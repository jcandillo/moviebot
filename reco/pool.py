#!/usr/bin/env python3
"""Candidate sourcing (P1/P2). Sources, each behind a flag in flags.json:
  tmdb_discover  genre x era, sorted by vote count, vote-count floor           (pool_tmdb_discover)
  tmdb_recs      /recommendations + /similar for each positive seed movie      (pool_tmdb_recs)
  ml_cf          MovieLens collaborative neighbours of positive seeds          (ml_cf)
  person         TMDB person search for top-affinity creators/leads            (pool_person_search)
Then fetches details (credits, keywords, external ids, US watch providers) into reco_meta. Usage: pool.py [--sources a,b] [--no-fetch]"""
import argparse, json, os, sys, datetime
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
YEAR = datetime.date.today().year
GENRES = {28: "Action", 12: "Adventure", 35: "Comedy", 18: "Drama", 878: "Science Fiction", 53: "Thriller", 10751: "Family", 80: "Crime", 37: "Western",
          10752: "War", 9648: "Mystery", 10749: "Romance", 16: "Animation", 14: "Fantasy", 36: "History", 27: "Horror"}
ERAS = [("1960-01-01", "1979-12-31", 2), ("1980-01-01", "1994-12-31", 3), ("1995-01-01", "2009-12-31", 3), ("2010-01-01", f"{YEAR-2}-12-31", 3), (f"{YEAR-1}-01-01", f"{YEAR}-12-31", 3)]
def pos_seeds(c):
    return [r[0] for r in c.execute("SELECT tmdb_id FROM taste_latest WHERE signal='up' AND media_type='movie'")]
def add(c, tid, src, detail=""):
    c.execute("INSERT OR IGNORE INTO reco_candidates VALUES(?,?,?,?)", (tid, src, str(detail), now()))
def src_discover(c):
    jobs = []
    for g in GENRES:
        for a, b, pages in ERAS:
            recent = a.startswith(str(YEAR - 1))
            for p in range(1, pages + 1):
                jobs.append((g, a, b, p, 40 if recent else 300))
    def run(j):
        g, a, b, p, vc = j
        d = tmdb("/discover/movie", sort_by="vote_count.desc", **{"primary_release_date.gte": a, "primary_release_date.lte": b, "vote_count.gte": vc,
                 "with_genres": g, "include_adult": "false", "page": p}) or {}
        return j, [m["id"] for m in d.get("results", [])]
    with ThreadPoolExecutor(8) as ex:
        for (g, a, b, p, vc), ids in ex.map(run, jobs):
            for t in ids: add(c, t, "tmdb_discover", f"{GENRES[g]}|{a[:4]}-{b[:4]}")
    c.commit()
def src_recs(c):
    S = pos_seeds(c); jobs = [(s, kind, p) for s in S for kind in ("recommendations", "similar") for p in (1, 2)]
    def run(j):
        s, kind, p = j; d = tmdb(f"/movie/{s}/{kind}", page=p) or {}; return j, [m["id"] for m in d.get("results", [])]
    with ThreadPoolExecutor(8) as ex:
        for (s, kind, p), ids in ex.map(run, jobs):
            for t in ids: add(c, t, "tmdb_" + kind, s)
    c.commit()
def src_ml(c, per_seed=60):
    import numpy as np
    z = np.load(ML_NPZ); ids = z["tmdb_ids"]; F = z["factors"]; ix = {int(t): k for k, t in enumerate(ids)}
    for s in pos_seeds(c):
        if s not in ix: continue
        sims = F @ F[ix[s]]; top = np.argsort(-sims)[1:per_seed + 1]
        for k in top: add(c, int(ids[k]), "ml_cf", s)
    c.commit()
def src_person(c, top_n=15):
    S = TP.seeds(c); D = TP.downs(c); P, _ = TP.person_affinity(S, D)
    people = sorted(((v, p) for p, v in P.items() if v >= 1.0), reverse=True)[:top_n]
    for sc, name in people:
        r = (tmdb("/search/person", query=name) or {}).get("results") or []
        if not r: continue
        cr = tmdb(f"/person/{r[0]['id']}/movie_credits") or {}
        for m in cr.get("crew", []):
            if m.get("job") in ("Director", "Screenplay", "Writer") and (m.get("vote_count") or 0) >= 50: add(c, m["id"], "person", name)
        for m in cr.get("cast", []):
            if (m.get("order") if m.get("order") is not None else 99) <= 2 and (m.get("vote_count") or 0) >= 50: add(c, m["id"], "person", name)
    c.commit()
def _names(lst): return json.dumps(lst)
def fetch_one(tid):
    d = tmdb(f"/movie/{tid}", append_to_response="credits,keywords,external_ids,watch/providers")
    if not d: return tid, None
    crew = d.get("credits", {}).get("crew", []); cast = d.get("credits", {}).get("cast", [])
    us = (d.get("watch/providers", {}).get("results") or {}).get("US") or {}
    names = lambda k: [p["provider_name"] for p in us.get(k, [])]
    return tid, (tid, d.get("title"), int((d.get("release_date") or "0")[:4] or 0) or None, d.get("release_date"), d.get("original_language"),
                 _names([g["name"] for g in d.get("genres", [])]), _names([x["name"] for x in crew if x.get("job") == "Director"]),
                 _names(list(dict.fromkeys(x["name"] for x in crew if x.get("department") == "Writing"))[:4]), _names([x["name"] for x in cast[:5]]),
                 _names([k["name"] for k in d.get("keywords", {}).get("keywords", [])]), d.get("overview"), d.get("poster_path"), d.get("vote_average"), d.get("vote_count"),
                 d.get("popularity"), (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id"), _names(names("flatrate")), _names(names("free") + names("ads")),
                 _names(names("rent")), _names(names("buy")), now(), d.get("status"), now())
def fetch_meta(c, refresh=False):
    have = set() if refresh else {r[0] for r in c.execute("SELECT tmdb_id FROM reco_meta")}
    ids = [t for (t,) in c.execute("SELECT DISTINCT tmdb_id FROM reco_candidates") if t not in have]
    ids += [t for (t,) in c.execute("SELECT tmdb_id FROM taste_latest WHERE media_type='movie'") if t not in have and t not in ids]
    n = 0
    with ThreadPoolExecutor(10) as ex:
        for tid, row in ex.map(fetch_one, ids):
            if row: c.execute(f"INSERT OR REPLACE INTO reco_meta VALUES({','.join('?' * len(row))})", row); n += 1; c.commit()   # short transactions: never hold the live DB lock
    c.commit(); return n
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--sources", default=""); ap.add_argument("--no-fetch", action="store_true"); a = ap.parse_args()
    f = flags(); c = connect(); ensure_schema(c)
    want = a.sources.split(",") if a.sources else [s for s, k in (("tmdb_discover", "pool_tmdb_discover"), ("tmdb_recs", "pool_tmdb_recs"), ("ml_cf", "ml_cf"), ("person", "pool_person_search")) if f[k]]
    for s in want:
        {"tmdb_discover": src_discover, "tmdb_recs": src_recs, "ml_cf": src_ml, "person": src_person}[s](c)
        print(s, c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM reco_candidates WHERE source LIKE ?", (s.replace("tmdb_recs", "tmdb_%") if s != "tmdb_discover" else s,)).fetchone()[0], flush=True)
    if not a.no_fetch: print("fetched", fetch_meta(c), flush=True)
    print("pool distinct", c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM reco_candidates").fetchone()[0])
