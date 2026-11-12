#!/usr/bin/env python3
"""Ingest a provider watch-history export: JSON list of {"title", "type": "movie"|"tv", "date": "Month D, YYYY"}.
Usage: history_ingest.py HISTORY.json --service CODE --name "Service Name"   |   history_ingest.py --service CODE --rollback
 - viewing_events rows (source='import'): already-seen exclusion for every ranker (the v3 protocol: unconfirmed history = exclusion only).
 - reco_implicit_history: TMDB-matched movies with view counts -> weak implicit signal for the reco ranker only (never cited in a why line).
 Rollback: --rollback deletes exactly these rows."""
import datetime, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
def iso(d):
    try: return datetime.datetime.strptime(d, "%B %d, %Y").date().isoformat()
    except Exception: return None
def match(title, years):
    r = (tmdb("/search/movie", query=title, include_adult="false") or {}).get("results") or []
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    for m in r[:5]:
        if norm(m.get("title")) == norm(title) or norm(m.get("original_title")) == norm(title):
            y = int((m.get("release_date") or "0")[:4] or 0)
            if not y or y <= max(years): return m["id"]
    return None
def main():
    c = connect(); ensure_schema(c); a = sys.argv; code = a[a.index("--service") + 1]; name = a[a.index("--name") + 1] if "--name" in a else code
    if "--rollback" in sys.argv:
        sid = c.execute("SELECT id FROM services WHERE code=?", (code,)).fetchone()
        if sid: n = c.execute("DELETE FROM viewing_events WHERE service_id=?", (sid[0],)).rowcount
        else: n = 0
        m = c.execute("DELETE FROM reco_implicit_history WHERE service=?", (code,)).rowcount; c.commit(); print(json.dumps({"rolled_back_viewing_events": n, "implicit_rows": m})); return
    c.execute("INSERT OR IGNORE INTO services(code,name,has_history_export,notes) VALUES(?,?,0,'history export ingest; unconfirmed history = exclusion only')", (code, name))
    sid = c.execute("SELECT id FROM services WHERE code=?", (code,)).fetchone()[0]
    rows = json.load(open(a[1])); n = 0
    for x in rows:
        n += c.execute("INSERT OR IGNORE INTO viewing_events(service_id,raw_title,watched_date,date_precision,source) VALUES(?,?,?,?, 'import')",
                       (sid, x["title"], iso(x["date"]), "day")).rowcount
    c.commit()
    movies = {}
    for x in rows:
        if x["type"] == "movie": movies.setdefault(x["title"], []).append(iso(x["date"]) or "")
    def job(t): return t, match(t, [int(d[:4]) for d in movies[t] if d] or [9999])
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(job, movies))
    m = 0
    for t, tid in res:
        if not tid: continue
        ds = sorted(d for d in movies[t] if d)
        m += c.execute("INSERT OR REPLACE INTO reco_implicit_history VALUES(?,?,?,?,?,?)", (tid, t, code, len(set(ds)), ds[0] if ds else None, ds[-1] if ds else None)).rowcount
    c.commit(); print(json.dumps({"viewing_events_new": n, "movie_titles": len(movies), "tmdb_matched": m}))
if __name__ == "__main__": main()
