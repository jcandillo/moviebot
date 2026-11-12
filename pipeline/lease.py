#!/usr/bin/env python3
"""Workflow lease + publish-intent ledger for the Movie Night pipeline (agent-host raw_votes.db). Native publish-picks.py CAS stays the final arbiter.
  claim   [--ttl 900] [--note N]            -> {ok, token, expires_at, must_reconcile:[...]} | exit 75 {busy, holder_expires_at}
  renew   --token T [--ttl 900]             -> {ok, expires_at} | exit 76 token_mismatch/expired
  release --token T                         -> {ok, dirty: events imported since claim -> rerun pipeline}
  status
  intent-open  --token T --selection-id S --expected-revision N   (before native replace)
  intent-close --token T --intent-id I --state confirmed|failed --evidence JSON
  reconcile    --token T --picks READBACK   (resolve other owners' pending/uncertain intents from live picks; never guesses)
Exit codes: 0 ok, 75 busy (another live owner: leave events, exit), 76 lease invalid, 77 reconcile required."""
import argparse, datetime, json, secrets, sqlite3, sys
DB = "./feedback-intake/raw_votes.db"; NAME = "movie_night_pipeline"
SCHEMA = """CREATE TABLE IF NOT EXISTS workflow_lease(name TEXT PRIMARY KEY, owner_token TEXT, acquired_at TEXT, expires_at TEXT, renewed_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS lease_log(id INTEGER PRIMARY KEY, at TEXT, op TEXT, token_hint TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS publish_intents(intent_id INTEGER PRIMARY KEY, selection_id TEXT NOT NULL, source_event_id TEXT NOT NULL, slot_id TEXT NOT NULL,
 expected_revision INTEGER NOT NULL, owner_token_hint TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN('pending','confirmed','failed','uncertain')),
 created_at TEXT, resolved_at TEXT, evidence TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_intent_per_slot ON publish_intents(slot_id) WHERE state IN('pending','uncertain');"""
def now(): return datetime.datetime.now().astimezone()
def iso(t): return t.isoformat(timespec="seconds")
def hint(tok): return tok[:8] if tok else None
def conn(db):
    c = sqlite3.connect(db, isolation_level=None, timeout=30); c.executescript(SCHEMA); return c
def tx(c): c.execute("BEGIN IMMEDIATE")
class LeaseError(Exception):
    def __init__(s, code, msg): s.code, s.msg = code, msg
def check(c, token):
    """Call inside a transaction: valid unexpired lease owned by token."""
    r = c.execute("SELECT owner_token, expires_at FROM workflow_lease WHERE name=?", (NAME,)).fetchone()
    if not r or not r[0]: raise LeaseError(76, "no_lease_held")
    if r[0] != token: raise LeaseError(76, "token_mismatch")
    if datetime.datetime.fromisoformat(r[1]) <= now(): raise LeaseError(76, "lease_expired")
def guard(c, token):
    """For writers (plan/record-publish): with token -> must own; without token -> refuse if someone else holds a live lease."""
    r = c.execute("SELECT owner_token, expires_at FROM workflow_lease WHERE name=?", (NAME,)).fetchone()
    if token: return check(c, token)
    if r and r[0] and datetime.datetime.fromisoformat(r[1]) > now(): raise LeaseError(75, "busy_lease_held_by_other_run")
def log(c, op, tok, d): c.execute("INSERT INTO lease_log VALUES(NULL,?,?,?,?)", (iso(now()), op, hint(tok), json.dumps(d)))
def open_intents(c): return [dict(zip(("intent_id", "selection_id", "source_event_id", "slot_id", "expected_revision", "owner", "state"), r))
                             for r in c.execute("SELECT intent_id,selection_id,source_event_id,slot_id,expected_revision,owner_token_hint,state FROM publish_intents WHERE state IN('pending','uncertain')")]
def out(d, code=0): print(json.dumps(d)); sys.exit(code)
def claim(a, c):
    tx(c); r = c.execute("SELECT owner_token, expires_at FROM workflow_lease WHERE name=?", (NAME,)).fetchone(); t = now()
    if r and r[0] and datetime.datetime.fromisoformat(r[1]) > t:
        c.execute("ROLLBACK"); out(dict(ok=False, busy=True, holder=hint(r[0]), holder_expires_at=r[1], action="events are durable in votes/actions; exit and let the holder (or next wake) process them"), 75)
    tok = secrets.token_hex(24); exp = iso(t + datetime.timedelta(seconds=a.ttl)); prev = hint(r[0]) if r else None
    c.execute("INSERT INTO workflow_lease VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET owner_token=excluded.owner_token, acquired_at=excluded.acquired_at, expires_at=excluded.expires_at, renewed_at=excluded.renewed_at, note=excluded.note",
              (NAME, tok, iso(t), exp, iso(t), a.note))
    oi = open_intents(c)
    for i in oi:  # an expired owner's pending publish is not ours to retry blindly: mark uncertain until reconciled from live picks
        if i["state"] == "pending" and i["owner"] != hint(tok): c.execute("UPDATE publish_intents SET state='uncertain' WHERE intent_id=?", (i["intent_id"],)); i["state"] = "uncertain"
    log(c, "claim", tok, dict(expired_previous=prev, open_intents=len(oi))); c.execute("COMMIT")
    out(dict(ok=True, token=tok, expires_at=exp, took_over_expired=bool(prev), must_reconcile=oi))
def renew(a, c):
    tx(c)
    try: check(c, a.token)
    except LeaseError as e: c.execute("ROLLBACK"); out(dict(ok=False, error=e.msg), e.code)
    exp = iso(now() + datetime.timedelta(seconds=a.ttl)); c.execute("UPDATE workflow_lease SET expires_at=?, renewed_at=? WHERE name=?", (exp, iso(now()), NAME)); log(c, "renew", a.token, {}); c.execute("COMMIT")
    out(dict(ok=True, expires_at=exp))
def release(a, c):
    tx(c); r = c.execute("SELECT owner_token, acquired_at FROM workflow_lease WHERE name=?", (NAME,)).fetchone()
    if not r or r[0] != a.token: c.execute("ROLLBACK"); out(dict(ok=False, error="token_mismatch"), 76)
    pend = [i for i in open_intents(c) if i["owner"] == hint(a.token)]
    if pend: c.execute("ROLLBACK"); out(dict(ok=False, error="close_or_reconcile_own_intents_first", intents=pend), 77)
    dirty = 0
    for q in ("SELECT count(*) FROM receipts WHERE finished_at>? AND new>0", "SELECT count(*) FROM action_receipts WHERE at>? AND new>0"):
        try: dirty += c.execute(q, (r[1],)).fetchone()[0]
        except sqlite3.OperationalError: pass
    c.execute("UPDATE workflow_lease SET owner_token=NULL, expires_at=? WHERE name=?", (iso(now()), NAME)); log(c, "release", a.token, dict(dirty=dirty)); c.execute("COMMIT")
    out(dict(ok=True, dirty=bool(dirty), next="rerun pipeline: new events arrived during this run" if dirty else "done"))
def status(a, c):
    r = c.execute("SELECT owner_token, acquired_at, expires_at, note FROM workflow_lease WHERE name=?", (NAME,)).fetchone()
    live = bool(r and r[0] and datetime.datetime.fromisoformat(r[2]) > now())
    out(dict(held=live, holder=hint(r[0]) if r else None, acquired_at=r[1] if r else None, expires_at=r[2] if r else None, open_intents=open_intents(c)))
def intent_open(a, c):
    tx(c)
    try:
        check(c, a.token)
        if open_intents(c): raise LeaseError(77, "open_intent_exists_reconcile_first")
        s = c.execute("SELECT source_event_id, slot_id FROM selections WHERE selection_id=?", (a.selection_id,)).fetchone()
        if not s: raise LeaseError(76, "unknown_selection")
        if c.execute("SELECT 1 FROM verified_publish_receipts WHERE source_event_id=?", (s[0],)).fetchone(): raise LeaseError(77, "already_published_receipt_exists")
    except LeaseError as e: c.execute("ROLLBACK"); out(dict(ok=False, error=e.msg), e.code)
    cur = c.execute("INSERT INTO publish_intents(selection_id,source_event_id,slot_id,expected_revision,owner_token_hint,state,created_at) VALUES(?,?,?,?,?,'pending',?)", (a.selection_id, s[0], s[1], a.expected_revision, hint(a.token), iso(now())))
    log(c, "intent-open", a.token, dict(intent=cur.lastrowid)); c.execute("COMMIT"); out(dict(ok=True, intent_id=cur.lastrowid))
def intent_close(a, c):
    tx(c)
    try:
        check(c, a.token)
        r = c.execute("SELECT owner_token_hint, state FROM publish_intents WHERE intent_id=?", (a.intent_id,)).fetchone()
        if not r or r[0] != hint(a.token) or r[1] != "pending": raise LeaseError(76, "intent_not_owned_or_not_pending")
    except LeaseError as e: c.execute("ROLLBACK"); out(dict(ok=False, error=e.msg), e.code)
    c.execute("UPDATE publish_intents SET state=?, resolved_at=?, evidence=? WHERE intent_id=?", (a.state, iso(now()), a.evidence, a.intent_id)); log(c, "intent-close", a.token, dict(intent=a.intent_id, state=a.state)); c.execute("COMMIT")
    out(dict(ok=True))
def reconcile(a, c):
    P = json.load(open(a.picks)); tx(c)
    try: check(c, a.token)
    except LeaseError as e: c.execute("ROLLBACK"); out(dict(ok=False, error=e.msg), e.code)
    res = []
    for i in open_intents(c):
        s = P["slots"].get(i["slot_id"], {})
        if s.get("source_event_id") == i["source_event_id"]: st, why = "confirmed", "live picks show this event applied (record strong receipt next)"
        elif P["revision"] <= i["expected_revision"]: st, why = "failed", "live revision not advanced past expected; replace did not land"
        else: st, why = "uncertain", "revision advanced by another change; slot does not carry this event"
        if st != i["state"]: c.execute("UPDATE publish_intents SET state=?, resolved_at=?, evidence=? WHERE intent_id=?", (st, iso(now()) if st != "uncertain" else None, json.dumps(dict(why=why, picks_revision=P["revision"])), i["intent_id"]))
        res.append(dict(i, state=st, why=why))
    log(c, "reconcile", a.token, res); c.execute("COMMIT"); out(dict(ok=True, resolved=res, still_open=[r for r in res if r["state"] == "uncertain"]))
if __name__ == "__main__":
    p = argparse.ArgumentParser(); s = p.add_subparsers(dest="cmd", required=True)
    for n, f in (("claim", claim), ("renew", renew), ("release", release), ("status", status), ("intent-open", intent_open), ("intent-close", intent_close), ("reconcile", reconcile)):
        x = s.add_parser(n); x.set_defaults(f=f); x.add_argument("--db", default=DB)
        if n in ("claim", "renew"): x.add_argument("--ttl", type=int, default=900)
        if n == "claim": x.add_argument("--note")
        if n not in ("claim", "status"): x.add_argument("--token", required=True)
        if n == "intent-open": x.add_argument("--selection-id", required=True); x.add_argument("--expected-revision", type=int, required=True)
        if n == "intent-close": x.add_argument("--intent-id", type=int, required=True); x.add_argument("--state", choices=["confirmed", "failed"], required=True); x.add_argument("--evidence", default="{}")
        if n == "reconcile": x.add_argument("--picks", required=True)
    a = p.parse_args(); a.f(a, conn(a.db))
