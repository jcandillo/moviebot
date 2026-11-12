#!/usr/bin/env python3
"""P1 quality floor. Bayesian weighted rating (IMDb-style): WR = v/(v+m)*R + m/(v+m)*C.
TMDB: R=vote_average, v=vote_count, C=pool mean, m=M_CLASSIC (or M_NEW for titles from the last 2 years).
IMDb (non-commercial ratings file, local only): same formula with m=M_IMDB. quality = mean of available WRs (0-10).
Floor: vote_count >= VC_MIN (VC_MIN_NEW for recent) and quality >= Q_MIN. Store-only values from real sources; never invented."""
import csv, gzip, os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
YEAR = datetime.date.today().year
M_CLASSIC, M_NEW, M_IMDB = 500, 100, 5000; VC_MIN, VC_MIN_NEW, Q_MIN = 150, 40, 6.2
def load_imdb(c):
    need = {r[0] for r in c.execute("SELECT imdb_id FROM reco_meta WHERE imdb_id IS NOT NULL")}
    rows = []
    with gzip.open(IMDB_TSV, "rt") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["tconst"] in need: rows.append((row["tconst"], float(row["averageRating"]), int(row["numVotes"]), now()))
    c.executemany("INSERT OR REPLACE INTO reco_imdb_ratings VALUES(?,?,?,?)", rows); c.commit(); return len(rows)
def compute(c):
    rows = c.execute("SELECT m.tmdb_id, m.year, m.vote_average, m.vote_count, i.average_rating, i.num_votes FROM reco_meta m LEFT JOIN reco_imdb_ratings i ON i.imdb_id=m.imdb_id").fetchall()
    vs = [(r[2], r[3]) for r in rows if r[2] and r[3]]; C = sum(a * v for a, v in vs) / max(1, sum(v for a, v in vs))
    iv = [(r[4], r[5]) for r in rows if r[4]]; CI = sum(a * v for a, v in iv) / max(1, sum(v for a, v in iv)) if iv else 6.5
    out = []
    for tid, y, R, v, IR, IV in rows:
        recent = (y or 0) >= YEAR - 1; m = M_NEW if recent else M_CLASSIC
        wt = (v / (v + m) * R + m / (v + m) * C) if R and v else None
        wi = (IV / (IV + M_IMDB) * IR + M_IMDB / (IV + M_IMDB) * CI) if IR and IV else None
        q = [x for x in (wt, wi) if x is not None]; q = sum(q) / len(q) if q else None
        floor = (v or 0) >= (VC_MIN_NEW if recent else VC_MIN) and q is not None and q >= Q_MIN
        reason = "ok" if floor else ("low_votes" if (v or 0) < (VC_MIN_NEW if recent else VC_MIN) else "low_quality")
        out.append((tid, wt, wi, q, int(floor), reason, now()))
    c.executemany("INSERT OR REPLACE INTO reco_quality VALUES(?,?,?,?,?,?,?)", out); c.commit()
    return dict(n=len(out), passes=sum(o[4] for o in out), C_tmdb=round(C, 3), C_imdb=round(CI, 3))
if __name__ == "__main__":
    c = connect(); ensure_schema(c); print("imdb matched", load_imdb(c)); print(compute(c))
