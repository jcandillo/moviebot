#!/usr/bin/env python3
"""[STAGED] Agent-host genre-card flow: plan -> enrich -> (native publish-picks.py replace-card, ONE CAS) -> record (strong readback receipt).
Runs after the existing import -> apply -> regenerate stages (same raw_votes.db, same lease). Never calls the publisher, never writes the Mac.
  plan    --picks FRESH --db RAW_DB --moviebot-db MOVIEBOT_DB --pool genre_pool.json --lease-token T
  enrich  PLAN --db RAW_DB --lease-token T --out ENRICHED [--html-dir D] [--poster-fixture F]
  record  --enriched E --card CID --helper-output JSON --pre PICKS_BEFORE --readback PICKS_AFTER --db RAW_DB --lease-token T
Policy (owner no-hold rule + main=home only):
  * an event on card genre:<g>:<era> can only ever replace THAT card; candidates must be TMDB-genre members of <g> and inside <era>'s year bound.
  * excluded: displayed in any genre card, any voted/acted title (any card), Watched history, thumbs-down, hard excludes, previously chosen for another selection.
  * fresh JustWatch US lookup at publish time: verified home offers -> publish; verified no-home / theaters-only -> skip to the next candidate (never main);
    unverified (lookup failed) -> skip while a later candidate verifies; if none verifies within the first 8, publish the best-ranked one with explicit
    status 'unverified' + alert naming watch_availability (card shows 'Where to watch: unverified'). No offers invented, never a wrong-genre film.
  * description: <=280 TMDB-overview 1-2 sentences (clause-shortened, never '…'); if impossible publish with description null + alert naming 'description'.
  * no eligible candidate in the pool -> blocked_no_candidate: card left as is, alert (the outgoing film stays; nothing fabricated)."""
import argparse, base64, datetime, hashlib, json, os, sqlite3, subprocess, sys, uuid
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import genre_cards as GC, lease as L, where_to_watch as WTW
from amend_descriptions import desc280
SCHEMA = """CREATE TABLE IF NOT EXISTS genre_selections(selection_id TEXT PRIMARY KEY, source_event_id TEXT UNIQUE NOT NULL, card_id TEXT NOT NULL, kind TEXT,
 outgoing_title TEXT, outgoing_tmdb_id INTEGER, displayed_revision INTEGER, status TEXT NOT NULL, reason TEXT, chosen_json TEXT, plan_revision INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS genre_publish_receipts(id INTEGER PRIMARY KEY, selection_id TEXT, source_event_id TEXT UNIQUE, card_id TEXT, expected_revision INTEGER,
 new_revision INTEGER, title TEXT, tmdb_id INTEGER, card_sha TEXT, pre_sha TEXT, post_sha TEXT, description TEXT, watch_status TEXT, watch_checked_at TEXT,
 watch_source TEXT, metadata_alerts TEXT, verified_at TEXT);"""
def now(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def sha(o): return hashlib.sha256(canon(o).encode()).hexdigest()
def conn(db): c = sqlite3.connect(db); c.executescript(SCHEMA); return c
def guard(db, tok):
    c = L.conn(db); c.execute("BEGIN IMMEDIATE")
    try: L.guard(c, tok)
    except L.LeaseError as e: c.execute("ROLLBACK"); print(json.dumps(dict(ok=False, error=e.msg))); sys.exit(e.code)
    c.execute("COMMIT")
def events(c):
    ev = []
    for tbl, kind in (("raw_votes", "vote"), ("raw_actions", "action")):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tbl,)).fetchone(): continue
        for (j,) in c.execute(f"SELECT raw_json FROM {tbl}"):
            o = json.loads(j); ev.append(dict(kind=kind, event_id=o["event_id"], slot_id=o.get("slot_id"), rev=o.get("displayed_revision"), title=o.get("title"),
                                             tmdb_id=o.get("tmdb_id"), ts=o.get("timestamp") or "", what=o.get("vote") or o.get("action")))
    return sorted(ev, key=lambda e: e["ts"])

def plan(a):
    guard(a.db, a.lease_token); c = conn(a.db); P = json.load(open(a.picks)); grev = P["revision"]; cut = a.year - 25
    pool = json.load(open(a.pool))["pools"]; tv = sqlite3.connect(f"file:{a.tvdb}?mode=ro", uri=True)
    hist = {r[0].strip().lower() for r in tv.execute("SELECT raw_title FROM viewing_events WHERE raw_title IS NOT NULL")}
    try: downs = {r[0] for r in tv.execute("SELECT tmdb_id FROM taste_latest WHERE signal='down'")}
    except sqlite3.OperationalError: downs = set()
    EV = events(c); acted = {e["tmdb_id"] for e in EV if e["tmdb_id"]} | {(e["title"] or "").lower() for e in EV}
    if "genres" not in P: print(json.dumps(dict(ok=False, error="genres_not_initialized_in_picks"))); sys.exit(2)
    gev = [e for e in EV if GC.parse(e["slot_id"]) and GC.parse(e["slot_id"])[0] == "genre"]
    latest = {}
    for e in gev: latest[(e["slot_id"], e["rev"])] = e["event_id"]
    def shown_except(sid):
        return {x for (j,) in c.execute("SELECT chosen_json FROM genre_selections WHERE chosen_json IS NOT NULL AND selection_id<>? AND status IN ('planned','published')", (sid,))
                for x in (json.loads(j)["tmdb_id"], json.loads(j)["title"].lower())}
    def eligible(m, cid, sid):
        _, g, era = GC.parse(cid)
        disp = {x for k, cc in GC.all_cards(P) if k.startswith("genre:") for x in (cc.get("tmdb_id"), (cc.get("title") or "").lower())}
        ex = disp | acted | downs | shown_except(sid)
        return GC.in_genre(g, m["tmdb_genre_ids"]) and GC.era_ok(era, int(m["year"]), cut) and m["tmdb_id"] not in ex and m["title"].lower() not in ex and m["title"].lower() not in hist
    out = []
    with c:
        for e in gev:
            eid, cid = e["event_id"], e["slot_id"]; card = GC.resolve(P, cid) or {}
            ex = c.execute("SELECT selection_id,status,chosen_json FROM genre_selections WHERE source_event_id=?", (eid,)).fetchone()
            sid = ex[0] if ex else str(uuid.uuid4())
            rec = c.execute("SELECT new_revision FROM genre_publish_receipts WHERE source_event_id=?", (eid,)).fetchone()
            final = None
            if rec or card.get("source_event_id") == eid: final = ("published", "verified receipt" if rec else "already applied in picks snapshot")
            elif e["rev"] is None: final = ("stale", "no_displayed_revision")
            elif latest[(cid, e["rev"])] != eid: final = ("superseded", "later press on same card+displayed_revision")
            elif e["rev"] > grev: final = ("stale", f"picks snapshot rev {grev} older than event rev {e['rev']}; re-copy picks")
            elif card.get("tmdb_id") != e["tmdb_id"] or (card.get("title") or "").lower() != (e["title"] or "").lower(): final = ("stale", "card no longer shows the event's film")
            if final:
                c.execute("INSERT OR REPLACE INTO genre_selections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (sid, eid, cid, e["kind"], e["title"], e["tmdb_id"], e["rev"], final[0], final[1], ex[2] if ex else None, grev, now()))
                out.append(dict(source_event_id=eid, selection_id=sid, card_id=cid, status=final[0], reason=final[1])); continue
            prev = json.loads(ex[2]) if ex and ex[2] else None
            ranked = [m for m in pool.get(cid, []) if eligible(m, cid, sid)]
            if prev and ex[1] == "planned" and any(m["tmdb_id"] == prev["tmdb_id"] for m in ranked):   # stable reuse, re-validated
                ranked = [m for m in ranked if m["tmdb_id"] == prev["tmdb_id"]] + [m for m in ranked if m["tmdb_id"] != prev["tmdb_id"]]
            if not ranked:
                c.execute("INSERT OR REPLACE INTO genre_selections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (sid, eid, cid, e["kind"], e["title"], e["tmdb_id"], e["rev"], "blocked_no_candidate", f"pool n={len(pool.get(cid, []))}, none eligible", None, grev, now()))
                out.append(dict(source_event_id=eid, selection_id=sid, card_id=cid, status="blocked_no_candidate", alerts=[f"ALERT owner: no eligible candidate for {cid}; card unchanged"]))
                continue
            c.execute("INSERT OR REPLACE INTO genre_selections VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (sid, eid, cid, e["kind"], e["title"], e["tmdb_id"], e["rev"], "planned", "ranked pool", canon(ranked[0]), grev, now()))
            out.append(dict(source_event_id=eid, selection_id=sid, card_id=cid, status="planned", expected_revision=grev, outgoing=dict(title=e["title"], tmdb_id=e["tmdb_id"]),
                            ranked=ranked[:int(os.environ.get("GENRE_LOOKUP_MAX", "8"))], note="one replace-card per run: publish, readback, record, re-copy picks, re-plan"))
    print(json.dumps(out, indent=1))

def poster_uri(url, fixture):
    if fixture: return open(fixture).read().strip()
    b = subprocess.run(["curl", "-sL", "--max-time", "20", url], capture_output=True).stdout
    return "data:image/jpeg;base64," + base64.b64encode(b).decode() if b[:3] == b"\xff\xd8\xff" else None

def enrich(a):
    guard(a.db, a.lease_token); c = conn(a.db); plan_ = json.load(open(a.plan)); first = True
    for o in plan_:
        if o["status"] != "planned": continue
        if not first: o["status"] = "deferred_one_publish_per_run"; continue
        tried, chosen, fallback = [], None, None
        for m in o["ranked"][:int(os.environ.get("GENRE_LOOKUP_MAX", "8"))]:
            hf = None
            if a.html_dir:
                hf = os.path.join(a.html_dir, f"jw_{WTW.slug(m['title'])}.html")
                if not os.path.exists(hf): hf = "/nonexistent-offline-fixture"   # offline never falls back to a live fetch
            r = WTW.check(m["tmdb_id"], m["title"], m["year"], m.get("directors") or [], None, html_file=hf, db=a.db)
            wj = WTW.to_watch_json(r) if r["status"] != "identity_mismatch" else None
            tried.append(dict(title=m["title"], tmdb_id=m["tmdb_id"], status=r["status"], theaters_only=bool(wj and wj.get("theaters_only")), record_id=r.get("record_id"), checked_at=r.get("checked_at")))
            if wj and r["status"] == "verified_offers" and wj.get("home_offers") and not wj.get("theaters_only"): chosen = (m, r, wj); break
            if wj and r["status"] == "unverified" and not wj.get("theaters_only") and fallback is None: fallback = (m, r, wj)
        o["lookups"] = tried; alerts = o.setdefault("alerts", [])
        if not chosen and fallback:
            chosen = fallback; alerts.append(f"ALERT owner: watch_availability unverified for {fallback[0]['title']} ({o['card_id']}); published with explicit 'unverified' (no hold)")
        if not chosen:
            o["status"] = "blocked_no_home_candidate"; alerts.append(f"ALERT owner: no home-eligible candidate for {o['card_id']} (all no-home/theaters-only/identity mismatch); card unchanged")
            c.execute("UPDATE genre_selections SET status=?, reason=?, updated_at=? WHERE selection_id=?", (o["status"], canon(tried), now(), o["selection_id"])); c.commit(); first = False; continue
        m, r, wj = chosen
        if m["tmdb_id"] != o["ranked"][0]["tmdb_id"]:
            c.execute("UPDATE genre_selections SET chosen_json=?, reason=?, updated_at=? WHERE selection_id=?", (canon(m), "enrich: earlier ranked candidates not home-verified", now(), o["selection_id"])); c.commit()
        d = desc280(m["overview"])
        if not d: alerts.append(f"ALERT owner: description missing for {m['title']} ({o['card_id']}); published without it (no hold)")
        poster = poster_uri(m["poster_url"], a.poster_fixture)
        if not poster: o["status"] = "blocked_poster_fetch"; alerts.append(f"ALERT: poster fetch failed for {m['title']}"); first = False; continue
        src = WTW.watch_source(r["record_id"], r["checked_at"]); credits = "; ".join(filter(None, [", ".join(m["directors"][:2]), ", ".join(m["cast"][:2])])) or ""
        meta = (f"TMDB {m['rating']}% · {m['year']}" if m.get("rating") else f"TMDB rating unavailable · {m['year']}")
        flags = ["replace-card", "--card", o["card_id"], "--expected-revision", str(o["expected_revision"]), "--source-event-id", o["source_event_id"], "--title", m["title"],
                 "--year", str(m["year"]), "--tmdb-id", str(m["tmdb_id"]), "--tmdb-genre-ids", ",".join(map(str, m["tmdb_genre_ids"])), "--why", m["why"], "--meta", meta,
                 "--credits", credits, "--watch-json", json.dumps(wj, separators=(",", ":")), "--source", src, "--description-source", "TMDB overview via " + m["meta_source"]]
        flags += (["--description", d] if d else ["--description-missing-alert"])
        if m.get("rating"): flags += ["--rating", str(m["rating"])]
        o.update(status="ready", chosen=dict(m, description=d), watch_json=wj, watch_source=src, poster_sha=sha(poster), publisher_flags=flags, poster_datauri=poster); first = False
    s = json.dumps(plan_, indent=1); open(a.out, "w").write(s) if a.out else print(s)

class Reject(Exception): pass
def record(a):
    guard(a.db, a.lease_token); c = conn(a.db)
    o = [x for x in json.load(open(a.enriched)) if x.get("status") == "ready" and x["card_id"] == a.card][0]
    try:
        h = json.loads(a.helper_output); pre = json.load(open(a.pre)); post = json.load(open(a.readback)); ch = o["chosen"]
        if h.get("ok") is not True: raise Reject("helper_not_ok")
        if h.get("idempotent"):
            card = GC.resolve(post, a.card) or {}
            if card.get("source_event_id") != o["source_event_id"]: raise Reject("idempotent_but_card_not_ours")
        elif h.get("revision") != o["expected_revision"] + 1 or post.get("revision") != h["revision"]: raise Reject("revision_mismatch")
        if pre.get("revision") != o["expected_revision"]: raise Reject("pre_snapshot_not_expected_revision")
        card = GC.resolve(post, a.card)
        if not card: raise Reject("card_absent_in_readback")
        for k, v in (("title", ch["title"]), ("tmdb_id", ch["tmdb_id"]), ("year", ch["year"]), ("source_event_id", o["source_event_id"]), ("description", ch["description"])):
            if card.get(k) != v: raise Reject(f"readback_{k}_mismatch")
        if sha(card["poster"]) != o["poster_sha"]: raise Reject("poster_mismatch")
        w = card.get("watch_availability") or {}
        for k in ("status", "theaters_only", "subscription", "free", "rent", "buy", "checked_at"):
            if w.get(k) != o["watch_json"].get(k): raise Reject(f"readback_watch_{k}_mismatch")
        if w.get("source") != o["watch_source"]: raise Reject("readback_watch_source_mismatch")
        if w["status"] not in GC.HOME_STATUSES or w.get("theaters_only"): raise Reject("non_home_card_in_main")
        if not h.get("idempotent"):   # every other field byte-identical to the pre snapshot (one card changed, nothing else)
            A, B = json.loads(json.dumps(pre)), json.loads(json.dumps(post))
            for X in (A, B):
                X.pop("revision"); X.pop("updated_at")
                for g in X["genres"]:
                    if g["genre_id"] == GC.parse(a.card)[1]: g.pop(GC.parse(a.card)[2])
            if canon(A) != canon(B): raise Reject("other_content_changed")
        if GC.resolve(pre, a.card).get("tmdb_id") != o["outgoing"]["tmdb_id"] and not h.get("idempotent"): raise Reject("pre_card_not_outgoing_film")
    except Reject as e:
        print(json.dumps(dict(ok=False, error=str(e)))); sys.exit(3)
    with c:
        c.execute("INSERT OR IGNORE INTO genre_publish_receipts VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (o["selection_id"], o["source_event_id"], a.card, o["expected_revision"], post["revision"],
                  ch["title"], ch["tmdb_id"], sha(card), sha(pre), sha(post), ch["description"], w["status"], w["checked_at"], w["source"], canon(card.get("metadata_alerts") or []), now()))
        c.execute("UPDATE genre_selections SET status='published', reason='verified readback', updated_at=? WHERE selection_id=?", (now(), o["selection_id"]))
    print(json.dumps(dict(ok=True, card=a.card, new_revision=post["revision"], title=ch["title"], watch_status=w["status"], alerts=o.get("alerts", []), card_sha=sha(card))))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("plan"); [p.add_argument(k, required=True) for k in ("--picks", "--db", "--pool")]; p.add_argument("--moviebot-db", "--tvdb", dest="tvdb", required=True); p.add_argument("--year", type=int, default=datetime.date.today().year)
    e = sp.add_parser("enrich"); e.add_argument("plan"); e.add_argument("--db", required=True); e.add_argument("--out"); e.add_argument("--html-dir"); e.add_argument("--poster-fixture")
    r = sp.add_parser("record"); [r.add_argument(k, required=True) for k in ("--enriched", "--card", "--helper-output", "--pre", "--readback", "--db")]
    for x in (p, e, r): x.add_argument("--lease-token", default=None)
    a = ap.parse_args(); dict(plan=plan, enrich=enrich, record=record)[a.cmd](a)
