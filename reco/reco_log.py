#!/usr/bin/env python3
"""P0 impression + reaction log.
  reco_log.py log-picks PICKS.json [--model v3]     log every card on the Frame picks document (idempotent per revision/slot/title)
  reco_log.py ingest-reactions                      copy Frame votes/actions (raw_votes.db) + interview answers into reco_reactions, linked to impressions
  reco_log.py backfill                              log every picks readback under $MOVIEBOT_PICKS_ARCHIVE, then ingest reactions
Never blocks the Frame pipeline: callers should run it with `|| true`."""
import glob, hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from common import ROOT
def _id(*p): return hashlib.sha256("|".join(map(str, p)).encode()).hexdigest()[:24]
def why_type(w):
    w = w or ""
    if w.startswith(("Directed by", "Written by", "Stars", "Features", "From ")): return "person"
    if w.startswith("Shares"): return "genre_overlap_seed"
    if w.startswith("In the vein of"): return "affinity"
    if w.startswith("Well-reviewed"): return "genre_fallback"
    if "fans of" in w.lower(): return "collaborative"
    return "other" if w else "none"
def cards(P):
    for k, s in (P.get("slots") or {}).items():
        if s: yield "movie_night", s.get("slot_id") or k, 0, s
    for g in P.get("genres") or []:
        for e in ("new", "classic"):
            if g.get(e): yield "watch_at_home", f"genre:{g['genre_id']}:{e}", 0, g[e]
    for i, it in enumerate((P.get("rent_buy") or {}).get("items") or []): yield "rent_buy", it.get("slot_id") or f"rentbuy:{i}", i, it
    for sv in (P.get("unsubscribed") or {}).get("services") or []:
        for i, it in enumerate(sv.get("items") or []): yield "unsubscribed", f"unsub:{sv.get('service_id')}:{i}", i, it
    for i, it in enumerate((P.get("in_theaters") or {}).get("items") or []): yield "in_theaters", it.get("slot_id") or f"theaters:{i}", i, it
def log_picks(c, path, model=None):
    P = json.load(open(path)); rev = P.get("revision"); shown = P.get("updated_at") or now(); n = 0; f = flags()
    since = f.get("live_ranker_since") if f.get("live_ranker") == "reco_v1" else None
    try: explored = {(r[0], r[1]) for r in c.execute("SELECT slot_id, tmdb_id FROM reco_explore_choices")}
    except Exception: explored = set()
    for surface, slot, rank, x in cards(P):
        if not x.get("tmdb_id"): continue
        wa = x.get("watch_availability") or {}
        iid = _id(rev, slot, x["tmdb_id"])
        cur = c.execute("INSERT OR IGNORE INTO reco_impressions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (iid, rev, surface, slot, rank, x["tmdb_id"], x.get("media_type") or "movie", x.get("title"), x.get("year"), x.get("why"), why_type(x.get("why")),
                   x.get("reco_score"), json.dumps(x.get("reco_features")) if x.get("reco_features") else None, model or x.get("reco_model") or ("reco_v1" if since and shown >= since else "v3"), "explore" if (slot, x["tmdb_id"]) in explored else (x.get("reco_lane") or "exploit"),
                   wa.get("status"), shown, path, now()))
        n += cur.rowcount
    c.commit(); return n
def _link(c, tmdb_id, ts):
    r = c.execute("SELECT impression_id FROM reco_impressions WHERE tmdb_id=? AND shown_at<=? ORDER BY shown_at DESC LIMIT 1", (tmdb_id, ts or "9999")).fetchone()
    if not r: r = c.execute("SELECT impression_id FROM reco_impressions WHERE tmdb_id=? ORDER BY shown_at LIMIT 1", (tmdb_id,)).fetchone()
    return r[0] if r else None
def ingest_reactions(c):
    n = 0
    if os.path.exists(RAW_DB):
        r = connect(RAW_DB, ro=True)
        for eid, tid, vote, ts in r.execute("SELECT event_id, tmdb_id, vote, event_timestamp FROM raw_votes WHERE tmdb_id IS NOT NULL"):
            n += c.execute("INSERT OR IGNORE INTO reco_reactions VALUES(?,?,?,?,?,?,?,?,?)", (eid, _link(c, tid, ts), tid, vote, None, None, ts, "frame_vote", now())).rowcount
        for eid, act, tid, slot, rev, ts in r.execute("SELECT event_id, action, tmdb_id, slot_id, displayed_revision, event_timestamp FROM raw_actions WHERE tmdb_id IS NOT NULL"):
            if act not in ("next", "watched"): continue
            n += c.execute("INSERT OR IGNORE INTO reco_reactions VALUES(?,?,?,?,?,?,?,?,?)", (eid, _link(c, tid, ts), tid, act, slot, rev, ts, "frame_action", now())).rowcount
    try:
        for eid, tid, ans, ts in c.execute("SELECT x.event_id, s.tmdb_id, x.answer, x.recorded_at FROM taste_signal_context x JOIN taste_signals s USING(event_id) WHERE x.origin='interview' AND s.media_type='movie'").fetchall():
            m = {"loved": "interview_loved", "fine": "interview_fine", "not_for_me": "interview_not_for_me"}.get(ans)
            if m: n += c.execute("INSERT OR IGNORE INTO reco_reactions VALUES(?,?,?,?,?,?,?,?,?)", ("iv:" + eid, None, tid, m, None, None, ts, "interview", now())).rowcount
    except Exception: pass
    c.commit(); return n
def backfill(c):
    base = os.environ.get("MOVIEBOT_PICKS_ARCHIVE", os.path.join(ROOT, "data"))
    paths = sorted(set(glob.glob(os.path.join(base, "**", "picks*readback*.json"), recursive=True)))
    return sum(log_picks(c, p) for p in paths)
if __name__ == "__main__":
    c = connect(); ensure_schema(c); cmd = sys.argv[1]
    if not flags()["log_impressions"]: print(json.dumps({"ok": True, "skipped": "log_impressions flag off"})); sys.exit(0)
    if cmd == "log-picks": print(json.dumps({"ok": True, "impressions_new": log_picks(c, sys.argv[2], sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--model" else None)}))
    elif cmd == "ingest-reactions": print(json.dumps({"ok": True, "reactions_new": ingest_reactions(c)}))
    elif cmd == "backfill": print(json.dumps({"ok": True, "impressions_new": backfill(c), "reactions_new": ingest_reactions(c)}))
