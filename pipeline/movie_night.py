#!/usr/bin/env python3
"""Standalone Movie Night action intake + deterministic same-slot selection (agent host only).
No network, no Mac writes, never runs the publisher, never writes moviebot.db.
  import-actions SNAPSHOT [--db] [--source-path] [--machine]   # movie_night_action_v1 only
  plan --picks PICKS_SNAPSHOT [--db] [--recs] [--moviebot-db] [--year]   # records stable selection per trigger event
  record-publish --selection-id ID --output JSON [--db]          # store publisher stdout as receipt
  report [--db]"""
import re as _re_gc
import argparse, datetime, hashlib, json, sqlite3, sys, uuid
sys.path.insert(0, "./feedback-intake")
import lease
from policy import HARD_EXCLUDE
HERE = "./feedback-intake"
REAL_DB, RECS, TVDB = f"{HERE}/raw_votes.db", "./recommendations.json", "./moviebot.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_actions(event_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL, raw_json TEXT NOT NULL,
 action TEXT CHECK(action IN('watched','next')), signal TEXT, slot_id TEXT, displayed_revision INTEGER, title TEXT,
 tmdb_id INTEGER, year INTEGER, media_type TEXT, event_timestamp TEXT, idempotency_key TEXT,
 watch_history_status TEXT NOT NULL DEFAULT 'not_applied',  -- explicit view kept raw; viewing_events untouched pending review
 first_receipt_id TEXT NOT NULL, ingested_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_conflicts(id INTEGER PRIMARY KEY, receipt_id TEXT, event_id TEXT, existing_sha256 TEXT,
 incoming_sha256 TEXT, incoming_raw TEXT, line_no INTEGER, seen_at TEXT);
CREATE TABLE IF NOT EXISTS action_rejects(id INTEGER PRIMARY KEY, receipt_id TEXT, line_no INTEGER, reason TEXT, raw_line TEXT, seen_at TEXT);
CREATE TABLE IF NOT EXISTS action_excluded_test(receipt_id TEXT, line_no INTEGER, event_id TEXT, raw_line TEXT, PRIMARY KEY(receipt_id,line_no));
CREATE TABLE IF NOT EXISTS action_receipts(receipt_id TEXT PRIMARY KEY, at TEXT, snapshot_path TEXT, source_path TEXT, source_machine TEXT,
 snapshot_bytes INTEGER, snapshot_sha256 TEXT, complete_bytes INTEGER, partial_tail_bytes INTEGER, lines INTEGER, new INTEGER,
 duplicate INTEGER, test_excluded INTEGER, conflict INTEGER, rejected INTEGER);
CREATE TABLE IF NOT EXISTS selections(selection_id TEXT PRIMARY KEY, source_event_id TEXT UNIQUE NOT NULL, source_kind TEXT,
 slot_id TEXT, outgoing_title TEXT, outgoing_tmdb_id INTEGER, picks_revision_seen INTEGER, picks_sha256 TEXT,
 status TEXT NOT NULL,  -- planned | blocked_no_candidate | stale | superseded | published | publish_rejected
 chosen_json TEXT, pool_sha256 TEXT, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS selection_revisions(id INTEGER PRIMARY KEY, selection_id TEXT NOT NULL, rev_no INTEGER NOT NULL,
 status TEXT NOT NULL, chosen_json TEXT, evidence TEXT, reason TEXT, created_at TEXT, UNIQUE(selection_id,rev_no));
CREATE TABLE IF NOT EXISTS verified_publish_receipts(id INTEGER PRIMARY KEY, selection_id TEXT, selection_rev_no INTEGER,
 source_event_id TEXT, slot_id TEXT, expected_revision INTEGER, new_revision INTEGER, title TEXT, tmdb_id INTEGER,
 poster_sha256 TEXT, helper_sha256 TEXT, helper_stdout TEXT, readback_json TEXT, machine_id TEXT, at TEXT, UNIQUE(source_event_id));
CREATE TABLE IF NOT EXISTS candidate_pool(id INTEGER PRIMARY KEY, slot_id TEXT NOT NULL, tmdb_id INTEGER NOT NULL, payload_sha256 TEXT NOT NULL,
 payload_json TEXT NOT NULL, source TEXT NOT NULL, verified_at TEXT NOT NULL, loaded_at TEXT, UNIQUE(slot_id,tmdb_id,payload_sha256));
CREATE TABLE IF NOT EXISTS publish_receipts(id INTEGER PRIMARY KEY, selection_id TEXT REFERENCES selections, at TEXT,
 ok INTEGER, new_revision INTEGER, idempotent INTEGER, error TEXT, raw_output TEXT);
"""
def _card_ok(cid):  # [STAGED genres-v1] legacy slots + genre:<gid>:<new|classic>
    return cid in ("new", "classic") or bool(isinstance(cid, str) and _re_gc.fullmatch(r"genre:(comedy|action_adventure|scifi|drama|thriller|family):(new|classic)", cid))

def now(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def db(p): c = sqlite3.connect(p); c.executescript(SCHEMA); return c

def import_actions(a):
    c = db(a.db); data = open(a.snapshot, "rb").read(); cut = data.rfind(b"\n") + 1
    if cut == 0 and data.strip():
        try: json.loads(data); cut = len(data)
        except Exception: pass
    rid = str(uuid.uuid4()); n = dict(lines=0, new=0, duplicate=0, test_excluded=0, conflict=0, rejected=0)
    with c:
        for i, line in enumerate(data[:cut].decode("utf-8", "replace").splitlines(), 1):
            if not line.strip(): continue
            n["lines"] += 1
            rej = lambda why: (n.__setitem__("rejected", n["rejected"] + 1), c.execute("INSERT INTO action_rejects VALUES(NULL,?,?,?,?,?)", (rid, i, why, line, now())))
            try: o = json.loads(line); assert isinstance(o, dict)
            except Exception: rej("malformed_json"); continue
            if o.get("test") is True:
                n["test_excluded"] += 1; c.execute("INSERT INTO action_excluded_test VALUES(?,?,?,?)", (rid, i, o.get("event_id"), line)); continue
            if o.get("schema") != "movie_night_action_v1" or "vote" in o: rej("not_movie_night_action_v1"); continue
            miss = [k for k in ("event_id", "action", "slot_id", "displayed_revision", "title", "timestamp") if o.get(k) in (None, "")]
            if miss: rej("missing:" + ",".join(miss)); continue
            exp_sig = {"watched": "viewed_explicit", "next": None}
            if o["action"] not in exp_sig or o.get("signal") != exp_sig[o["action"]] or o.get("taste") is not None or o.get("rating") is not None \
               or not _card_ok(o["slot_id"]) or not isinstance(o["displayed_revision"], int):
                rej("contract_violation"); continue
            h = hashlib.sha256(canon(o).encode()).hexdigest()
            r = c.execute("SELECT payload_sha256 FROM raw_actions WHERE event_id=?", (o["event_id"],)).fetchone()
            if r is None:
                c.execute("INSERT INTO raw_actions(event_id,payload_sha256,raw_json,action,signal,slot_id,displayed_revision,title,tmdb_id,year,media_type,event_timestamp,idempotency_key,first_receipt_id,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (o["event_id"], h, line, o["action"], o.get("signal"), o["slot_id"], o["displayed_revision"], o["title"], o.get("tmdb_id"), o.get("year"), o.get("media_type"), o["timestamp"], o.get("idempotency_key"), rid, now())); n["new"] += 1
            elif r[0] == h: n["duplicate"] += 1
            else: n["conflict"] += 1; c.execute("INSERT INTO action_conflicts VALUES(NULL,?,?,?,?,?,?,?)", (rid, o["event_id"], r[0], h, line, i, now()))
        c.execute("INSERT INTO action_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (rid, now(), a.snapshot, a.source_path, a.machine, len(data), hashlib.sha256(data).hexdigest(), cut, len(data) - cut, *n.values()))
    print(json.dumps(dict(db=a.db, receipt_id=rid, partial_tail_bytes=len(data) - cut, **n)))

def current_choice(c, sid):
    r = c.execute("SELECT rev_no,status FROM selection_revisions WHERE selection_id=? ORDER BY rev_no DESC LIMIT 1", (sid,)).fetchone()
    if r:
        ch = c.execute("SELECT rev_no,chosen_json FROM selection_revisions WHERE selection_id=? AND chosen_json IS NOT NULL ORDER BY rev_no DESC LIMIT 1", (sid,)).fetchone()
        if r[1] in ("blocked_no_candidate", "stale", "superseded") and (not ch or ch[0] < r[0]) and r[1] != "published": return r[0], r[1], None
        return (ch[0] if ch else r[0]), r[1], (json.loads(ch[1]) if ch else None)
    r = c.execute("SELECT status,chosen_json FROM selections WHERE selection_id=?", (sid,)).fetchone()
    return 0, r[0], (json.loads(r[1]) if r[1] else None)

def add_rev(c, sid, status, chosen, evidence, reason):
    n = (c.execute("SELECT max(rev_no) FROM selection_revisions WHERE selection_id=?", (sid,)).fetchone()[0] or 0)
    if n == 0:  # snapshot the base row first so lineage is complete
        st, cj = c.execute("SELECT status,chosen_json FROM selections WHERE selection_id=?", (sid,)).fetchone()
        c.execute("INSERT INTO selection_revisions VALUES(NULL,?,?,?,?,?,?,?)", (sid, 1, st, cj, "base row", "original", now())); n = 1
    c.execute("INSERT INTO selection_revisions VALUES(NULL,?,?,?,?,?,?,?)", (sid, n + 1, status, json.dumps(chosen) if chosen else None, evidence, reason, now()))
    c.execute("UPDATE selections SET status='see_revisions' WHERE selection_id=?", (sid,))

POOL_REQ = ("title", "tmdb_id", "media_type", "year", "poster_url", "why", "source", "verified_at")
def load_pool(a):
    """Append-only load of freshly verified candidates: JSON list of {slot_id, title, tmdb_id, media_type, year, poster_url, why, director?, cast?, rating?, release?, source, verified_at}."""
    c = db(a.db); items = json.load(open(a.file)); n = dict(added=0, duplicate=0, rejected=[])
    with c:
        for it in items:
            miss = [k for k in POOL_REQ + ("slot_id",) if it.get(k) in (None, "")]
            if miss or it["media_type"] != "movie" or it["slot_id"] not in ("new", "classic") or not str(it["poster_url"]).startswith("https://image.tmdb.org/"):
                n["rejected"].append(dict(title=it.get("title"), why=miss or "media_type/slot/poster_url")); continue
            h = hashlib.sha256(canon(it).encode()).hexdigest()
            cur = c.execute("INSERT OR IGNORE INTO candidate_pool VALUES(NULL,?,?,?,?,?,?,?)", (it["slot_id"], it["tmdb_id"], h, canon(it), it["source"], it["verified_at"], now()))
            n["added" if cur.rowcount else "duplicate"] += 1
    print(json.dumps(n))

def current_pool_ids(recs, slot):
    """Authoritative current pool = the latest regenerated recommendations.json movie_night_<slot>_pool row (not older candidate_pool versions)."""
    try: R = json.load(open(recs))
    except Exception: return None
    for row in R.get("rows", []):
        if row.get("key") == f"movie_night_{slot}_pool": return {it.get("tmdb_id") for it in row.get("items", [])}
    return None
def pool_items(c, slot, cutoff, recs=None):
    out, seen_ids = [], set(); cur_ids = current_pool_ids(recs, slot) if recs else None
    for (j,) in c.execute("SELECT payload_json FROM candidate_pool WHERE slot_id=? ORDER BY id DESC", (slot,)):  # newest verified version wins
        d = json.loads(j)
        if d["tmdb_id"] in seen_ids: continue
        seen_ids.add(d["tmdb_id"])
        if cur_ids is not None and d["tmdb_id"] not in cur_ids: continue   # stale pool version from an older regenerate
        y = d["year"]
        if (slot == "classic" and y <= cutoff) or (slot == "new" and y > cutoff): out.append(dict(d, source_row="candidate_pool"))
    out = out[::-1]  # load order
    out.sort(key=lambda d: -(d.get('score') if isinstance(d.get('score'), (int, float)) else -1e9))  # taste-ranked first, stable
    return out

def candidates(slot, cutoff, recs, tvdb):
    """Only already-cached data. new: recommendations.json movie rows in order. classic: cached TMDB movies <= cutoff."""
    out = []
    if slot == "new":
        R = json.load(open(recs))
        for row in R["rows"]:
            if row["key"] not in ("new_on_your_services", "new_releases_elsewhere", "for_you"): continue
            for it in row["items"]:
                if it.get("media_type") == "movie" and it.get("tmdb_id") and isinstance(it.get("year"), int) and it["year"] > cutoff and it.get("poster"):
                    out.append(dict(title=it["title"], tmdb_id=it["tmdb_id"], year=it["year"], why=it.get("why"), poster_url=it["poster"],
                                    rating=it.get("rating"), director=it.get("director") or None, subscription=it.get("subscription"), source_row=row["key"]))
    else:
        c = sqlite3.connect(f"file:{tvdb}?mode=ro", uri=True)
        for t, n, y, j in c.execute("SELECT tmdb_id,name,year,cached_json FROM titles WHERE media_type='movie' AND year IS NOT NULL AND year<=? ORDER BY tmdb_id", (cutoff,)):
            d = json.loads(j or "{}")
            if d.get("poster_path"):
                out.append(dict(title=n, tmdb_id=t, year=y, why=None, poster_url="https://image.tmdb.org/t/p/w342" + d["poster_path"], rating=d.get("vote_average"), director=None, source_row="titles_cache"))
    return out

def lease_guard(a):
    c = lease.conn(a.db); c.execute("BEGIN IMMEDIATE")
    try: lease.guard(c, a.lease_token)
    except lease.LeaseError as e: c.execute("ROLLBACK"); print(json.dumps(dict(ok=False, error=e.msg))); raise SystemExit(e.code)
    c.execute("COMMIT")

def plan(a):
    lease_guard(a)
    c = db(a.db); picks_raw = open(a.picks, "rb").read(); P = json.loads(picks_raw); cutoff = a.year - 25; grev = P["revision"]
    tv = sqlite3.connect(f"file:{a.tvdb}?mode=ro", uri=True)
    seen = {r[0] for r in tv.execute("SELECT tmdb_id FROM title_matches WHERE status='matched' AND item_kind='viewing' AND media_type='movie'")}
    voted = {r[0] for r in c.execute("SELECT tmdb_id FROM raw_votes WHERE tmdb_id IS NOT NULL")} | {r[0].lower() for r in c.execute("SELECT title FROM raw_votes")}
    acted = {r[0] for r in c.execute("SELECT tmdb_id FROM raw_actions WHERE tmdb_id IS NOT NULL")} | {r[0].lower() for r in c.execute("SELECT title FROM raw_actions")}
    try: downs = {r[0] for r in tv.execute("SELECT tmdb_id FROM taste_latest WHERE signal='down'")}
    except sqlite3.OperationalError: downs = set()
    published = downs | set(HARD_EXCLUDE) | {r[0] for r in c.execute("SELECT tmdb_id FROM verified_publish_receipts")} | {r[0].lower() for r in c.execute("SELECT title FROM verified_publish_receipts")}
    disp = {x for s_ in P["slots"].values() for x in (s_.get("tmdb_id"), (s_.get("title") or "").lower())}
    def shown_except(sid):
        out = set()
        for (j,) in c.execute("SELECT chosen_json FROM selection_revisions WHERE chosen_json IS NOT NULL AND selection_id<>? UNION ALL SELECT chosen_json FROM selections WHERE chosen_json IS NOT NULL AND selection_id<>?", (sid, sid)):
            d = json.loads(j); out |= {d["tmdb_id"], d["title"].lower()}
        return out
    def eligible(ch, slot, sid):
        excl = disp | voted | acted | seen | published | shown_except(sid)
        y = ch.get("year")
        return isinstance(y, int) and ((slot == "classic" and y <= cutoff) or (slot == "new" and y > cutoff)) and ch["tmdb_id"] not in excl and ch["title"].lower() not in excl and ch.get("media_type", "movie") == "movie"
    def pick(slot, sid):
        pool = pool_items(c, slot, cutoff, a.recs if a.current_pool_only else None) + (candidates(slot, cutoff, a.recs, a.tvdb) if a.allow_unverified else [])
        ok = [p_ for p_ in pool if eligible(p_, slot, sid)]
        return (ok[0] if ok else None), hashlib.sha256(canon(pool).encode()).hexdigest(), len(pool)
    events = [("vote", *r) for r in c.execute("SELECT event_id, json_extract(raw_json,'$.slot_id'), json_extract(raw_json,'$.displayed_revision'), title, tmdb_id, event_timestamp FROM raw_votes")]
    events += [("action", *r) for r in c.execute("SELECT event_id,slot_id,displayed_revision,title,tmdb_id,event_timestamp FROM raw_actions")]
    events.sort(key=lambda e: e[6] or "")
    latest = {}
    for e in events:
        if e[2] in ("new", "classic"): latest[(e[2], e[3])] = e
    out = []
    with c:
        for kind, eid, slot, rev, title, tmdb, ts in events:
            ex = c.execute("SELECT selection_id FROM selections WHERE source_event_id=?", (eid,)).fetchone()
            sid = ex[0] if ex else str(uuid.uuid4())
            cur = P["slots"].get(slot or "", {})
            rec = c.execute("SELECT new_revision FROM verified_publish_receipts WHERE source_event_id=?", (eid,)).fetchone()
            final = None
            if rec or cur.get("source_event_id") == eid: final = ("published", "verified receipt" if rec else "already applied in picks snapshot")
            elif slot not in ("new", "classic") or rev is None: final = ("stale", "no_slot_or_revision")
            elif latest[(slot, rev)][1] != eid: final = ("superseded", "later press on same slot+displayed_revision")
            elif rev > grev: final = ("stale", f"picks snapshot revision {grev} older than event displayed_revision {rev}; re-copy picks")
            elif cur.get("tmdb_id") != tmdb or (cur.get("title") or "").lower() != (title or "").lower():
                final = ("stale", "slot no longer shows the event's film (newer pick present)")
            if not ex:
                c.execute("INSERT INTO selections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid, eid, kind, slot, title, tmdb, grev, hashlib.sha256(picks_raw).hexdigest(), final[0] if final else "pending", None, None, final[1] if final else None, now()))
            rn, st, ch = current_choice(c, sid)
            if final:
                if st != final[0] and not (st == "published"): add_rev(c, sid, final[0], ch, f"picks rev {grev}", final[1])
                out.append(dict(source_event_id=eid, selection_id=sid, status=final[0], reason=final[1], chosen=ch)); continue
            # valid trigger: slot identity matches the event's film -> rebase to current global revision is safe
            top = pick(slot, sid)[0] if st == "planned" and ch else None
            attempted = c.execute("SELECT 1 FROM publish_receipts WHERE selection_id=?", (sid,)).fetchone()
            if st == "planned" and ch and eligible(ch, slot, sid) and (attempted or not top or top["tmdb_id"] == ch["tmdb_id"]):
                status, reason = "planned", "reused stable choice (revalidated)"
            elif st == "planned" and ch and eligible(ch, slot, sid):  # never attempted; pool re-ranked since -> replan with lineage
                add_rev(c, sid, "invalidated", ch, "pool top now tmdb %s" % top["tmdb_id"], "superseded by taste-regenerated pool before any publish attempt")
                add_rev(c, sid, "planned", top, "taste-ranked pool", "replan after regenerate"); ch, status, reason = top, "planned", "replanned from regenerated pool"
            else:
                if st == "planned" and ch: add_rev(c, sid, "invalidated", ch, f"picks rev {grev}", "revalidation failed (displayed/voted/acted/seen/published/year/pool)")
                nc, ph, n = pick(slot, sid)
                if nc: add_rev(c, sid, "planned", nc, f"pool sha {ph}", "new choice from verified pool"); ch, status, reason = nc, "planned", "new choice"
                else:
                    if st != "blocked_no_candidate": add_rev(c, sid, "blocked_no_candidate", None, f"pool sha {ph} n={n}", "no eligible verified candidate")
                    ch, status, reason = None, "blocked_no_candidate", f"verified pool n={n}, none eligible"
            o = dict(source_event_id=eid, selection_id=sid, status=status, reason=reason, chosen=ch, rebased=(rev != grev))
            if status == "planned":
                o["publisher_plan"] = dict(slot=slot, expected_revision=grev, source_event_id=eid, title=ch["title"], year=ch["year"], tmdb_id=ch["tmdb_id"],
                                           why=ch["why"], poster_url=ch["poster_url"], meta=ch.get("meta"), credits=ch.get("credits"),
                                           description=ch.get("description"), description_source=ch.get("description_source"),
                                           note="one replace per run; re-copy picks and re-plan before the next slot")
            out.append(o)
    print(json.dumps(out, indent=1))

class Reject(Exception): pass
def record_publish(a):
    lease_guard(a)
    c = db(a.db)
    try:
        try: o = json.loads(a.helper_output)
        except Exception: raise Reject("helper_output_not_json")
        if o.get("ok") is not True: raise Reject("helper_not_ok:" + str(o.get("error")))
        row = c.execute("SELECT source_event_id, slot_id FROM selections WHERE selection_id=?", (a.selection_id,)).fetchone()
        if not row: raise Reject("unknown_selection")
        eid, slot = row; rn, st, ch = current_choice(c, a.selection_id)
        if not ch: raise Reject("selection_has_no_choice")
        if o.get("slot_id") != slot: raise Reject("slot_mismatch")
        idem = o.get("idempotent") is True
        if not idem:
            if o.get("source_event_id") != eid: raise Reject("event_mismatch")
            if o.get("title") != ch["title"]: raise Reject("title_mismatch")
            if o.get("revision") != a.expected_revision + 1: raise Reject("revision_not_expected_plus_one")
        if not a.readback: raise Reject("missing_readback")
        R = json.load(open(a.readback)); rs = (R.get("slots") or {}).get(slot) or {}
        if R.get("revision") != o.get("revision") and not idem and not a.metadata_output: raise Reject("readback_revision_mismatch")
        if a.metadata_output and R.get("revision") not in (o.get("revision"), (o.get("revision") or 0) + 1) and not idem: raise Reject("readback_revision_mismatch")
        if rs.get("source_event_id") != eid or rs.get("tmdb_id") != ch["tmdb_id"] or rs.get("title") != ch["title"]: raise Reject("readback_slot_mismatch")
        poster = str(rs.get("poster") or "")
        if not poster.startswith("data:image/") or ";base64," not in poster: raise Reject("readback_poster_not_datauri")
        import base64
        try: pb = base64.b64decode(poster.split(",", 1)[1], validate=True)
        except Exception: raise Reject("poster_base64_invalid")
        if not (pb[:3] == b"\xff\xd8\xff" or pb[:8] == b"\x89PNG\r\n\x1a\n"): raise Reject("poster_not_jpeg_png")
        psha = hashlib.sha256(pb).hexdigest()
        if not a.poster_sha256: raise Reject("missing_expected_poster_sha256")
        if psha != a.poster_sha256: raise Reject("poster_sha256_mismatch")
        if a.wtw_record_id is None: raise Reject("missing_where_to_watch_provenance")
        import where_to_watch as WTW
        try: w = c.execute("SELECT tmdb_id,status,card_text,checked_at,subscription_json,rent_json,buy_json,free_json,cinema FROM watch_availability WHERE id=?", (a.wtw_record_id,)).fetchone()
        except sqlite3.OperationalError: w = None
        if not w: raise Reject("unknown_where_to_watch_record")
        if w[0] != ch["tmdb_id"] or w[1] == "identity_mismatch": raise Reject("where_to_watch_record_wrong_film")
        if (datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(w[3])).total_seconds() > 6 * 3600: raise Reject("where_to_watch_record_stale_refetch")
        wj = WTW.to_watch_json(dict(status=w[1], checked_at=w[3], subscription=json.loads(w[4] or "[]"), rent=json.loads(w[5] or "[]"), buy=json.loads(w[6] or "[]"), free=json.loads(w[7] or "[]"), cinema=w[8]))
        meta_rev = None; keys = WTW.WATCH_KEYS
        want_src = WTW.watch_source(a.wtw_record_id, w[3])
        alerts = []
        if ch.get("description"):   # supplied -> must land exactly; missing -> publish anyway + named alert (owner 2393/2396)
            if rs.get("description") != ch["description"]: raise Reject("readback_description_differs_from_plan")
            if not idem and o.get("description") != ch["description"]: raise Reject("helper_output_description_differs")
        else: alerts.append(f"description missing for {ch['title']} (TMDB {ch['tmdb_id']})")
        import picks_contract as PC
        for sid, er in PC.doc_errors(R).items(): alerts.append(f"slot {sid} metadata gaps: {','.join(er)}")
        if wj is None: raise Reject("where_to_watch_record_not_publishable")
        mode = "atomic_replace" if not a.metadata_output else "fallback_replace_then_metadata"
        if a.metadata_output:
            try: mo = json.loads(a.metadata_output)
            except Exception: raise Reject("metadata_output_not_json")
            if mo.get("ok") is not True or mo.get("slot_id") != slot or mo.get("title") != ch["title"] or mo.get("tmdb_id") != ch["tmdb_id"]: raise Reject("metadata_output_mismatch")
            meta_rev = mo.get("revision")
            if not mo.get("idempotent") and meta_rev != o.get("revision", 0) + 1 and not idem: raise Reject("metadata_revision_not_replace_plus_one")
            if R.get("revision") != meta_rev: raise Reject("readback_revision_not_metadata_revision")
        else:
            ow = o.get("watch_availability")
            if not idem and (not isinstance(ow, dict) or {k: ow.get(k) for k in keys} != {k: wj[k] for k in keys}): raise Reject("helper_output_watch_missing_or_differs")
            if R.get("revision") != o.get("revision") and not idem: raise Reject("readback_revision_not_replace_revision")
        sw = rs.get("watch_availability")   # structured availability is REQUIRED for every status, incl. unverified
        if not isinstance(sw, dict): raise Reject("readback_missing_structured_watch_availability")
        if any(k not in sw for k in keys): raise Reject("readback_watch_missing_fields:" + ",".join(k for k in keys if k not in sw))
        if {k: sw[k] for k in keys} != {k: wj[k] for k in keys}: raise Reject("readback_watch_availability_differs_from_record")
        if sw.get("source") != want_src: raise Reject("readback_watch_source_not_record_provenance")
        prev = c.execute("SELECT tmdb_id, poster_sha256 FROM verified_publish_receipts WHERE source_event_id=?", (eid,)).fetchone()
        if prev:
            if prev[0] == ch["tmdb_id"]: print(json.dumps(dict(recorded=False, already_recorded=True))); return
            raise Reject("receipt_conflict_existing_different_film")
        rb = dict(revision=R.get("revision"), updated_at=R.get("updated_at"), slot={k: v for k, v in rs.items() if k != "poster"}, poster_sha256=psha,
                  readback_file_sha256=hashlib.sha256(open(a.readback, "rb").read()).hexdigest(), where_to_watch_record_id=a.wtw_record_id, where_to_watch_status=w[1], replace_revision=o.get("revision"), metadata_revision=meta_rev, publish_mode=mode, description=ch.get("description"), description_source=ch.get("description_source"),
                       where_to_watch_checked_at=w[3], watch_source=want_src if wj is not None else None, watch_status=wj["status"], watch_availability=rs.get("watch_availability"), metadata_alerts=alerts, metadata_output=a.metadata_output)
        with c:
            c.execute("INSERT INTO verified_publish_receipts VALUES(NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (a.selection_id, rn, eid, slot, a.expected_revision, R.get("revision"), ch["title"], ch["tmdb_id"], psha, a.helper_sha256, a.helper_output, json.dumps(rb), a.machine, now()))
            add_rev(c, a.selection_id, "published", None, f"verified_publish_receipts event={eid} rev={R.get('revision')}", "strong record-publish")
            try: c.execute("UPDATE publish_intents SET state='confirmed', resolved_at=?, evidence=? WHERE source_event_id=? AND state IN('pending','uncertain')", (now(), json.dumps(dict(receipt="verified_publish_receipts", revision=R.get("revision"))), eid))
            except sqlite3.OperationalError: pass
        print(json.dumps(dict(recorded=True, revision=R.get("revision"), metadata_alerts=alerts)))
    except Reject as e:
        with c: c.execute("INSERT INTO publish_receipts VALUES(NULL,?,?,?,?,?,?,?)", (a.selection_id, now(), 0, None, 0, "rejected:" + str(e), a.helper_output))
        print(json.dumps(dict(recorded=False, rejected=str(e)))); raise SystemExit(1)

def report(a):
    c = db(a.db)
    for t in ("candidate_pool", "selection_revisions", "verified_publish_receipts", "raw_votes", "raw_actions", "action_conflicts", "action_rejects", "action_excluded_test", "action_receipts", "selections", "publish_receipts"):
        try: print(t, c.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
        except sqlite3.OperationalError: print(t, "n/a")
p = argparse.ArgumentParser(); s = p.add_subparsers(dest="cmd", required=True)
x = s.add_parser("import-actions"); x.add_argument("snapshot"); x.add_argument("--source-path"); x.add_argument("--machine"); x.set_defaults(f=import_actions)
x = s.add_parser("plan"); x.add_argument("--picks", required=True); x.add_argument("--recs", default=RECS); x.add_argument("--moviebot-db", "--tvdb", dest="tvdb", default=TVDB); x.add_argument("--year", type=int, default=datetime.date.today().year); x.add_argument("--allow-unverified", action="store_true"); x.add_argument("--current-pool-only", action="store_true", help="only the latest regenerated movie_night_<slot>_pool in --recs; holds candidates without description"); x.set_defaults(f=plan)
x = s.add_parser("record-publish"); x.add_argument("--selection-id", required=True); x.add_argument("--helper-output", required=True); x.add_argument("--readback")
x.add_argument("--expected-revision", type=int, required=True); x.add_argument("--poster-sha256"); x.add_argument("--helper-sha256", required=True); x.add_argument("--machine", required=True); x.add_argument("--wtw-record-id", type=int); x.add_argument("--metadata-output"); x.set_defaults(f=record_publish)
x = s.add_parser("load-pool"); x.add_argument("file"); x.set_defaults(f=load_pool)
x = s.add_parser("report"); x.set_defaults(f=report)
for sp in s.choices.values(): sp.add_argument("--db", default=REAL_DB); sp.add_argument("--lease-token")
a = p.parse_args(); a.f(a)
