#!/usr/bin/env python3
"""P3 Thompson-sampling exploration. Lanes = primary genre x era bucket (pre-1980, 1980s, 1990s, 2000s, 2010s, 2020s).
Each lane keeps Beta(ups+1, downs+1) from reactions on shown cards (up/watched/loved = success; down/next/not-for-me = failure; next counts 0.5).
For a ranked genre pool, with probability explore_share (seeded per day + slot so reruns are stable), sample theta for each lane present in the
pool's top 30, take the best lane, and promote that lane's highest-quality candidate (outside the current top 3) to the top. Choices are
recorded in reco_explore_choices so impressions can be labelled lane='explore'. Stdlib only."""
import datetime, json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
SUCC = {"up": 1.0, "watched": 1.0, "interview_loved": 1.0}; FAIL = {"down": 1.0, "interview_not_for_me": 1.0, "next": 0.5}
def era(y): y = y or 0; return "pre1980" if y < 1980 else f"{(y // 10) * 10}s"
def lane(m): return f"{(m.get('genres') or ['Unknown'])[0]}|{era(m.get('year'))}"
def lane_stats(c):
    st = {}
    c.row_factory = None
    rows = c.execute("SELECT r.reaction, m.genres_json, m.year FROM reco_reactions r JOIN reco_meta m USING(tmdb_id)").fetchall()
    for rx, g, y in rows:
        L = f"{(json.loads(g or '[]') or ['Unknown'])[0]}|{era(y)}"; a, b = st.get(L, (0.0, 0.0))
        st[L] = (a + SUCC.get(rx, 0), b + FAIL.get(rx, 0))
    return st
def apply(c, pools):
    f = flags()
    if not f["explore_thompson"]: return pools, []
    c.execute("CREATE TABLE IF NOT EXISTS reco_explore_choices(day TEXT, slot_id TEXT, tmdb_id INTEGER, lane TEXT, theta REAL, PRIMARY KEY(day, slot_id))"); c.commit()
    st = lane_stats(c); day = datetime.date.today().isoformat(); chosen = []
    for slot, pool in pools.items():
        rnd = random.Random(f"{day}|{slot}")
        if not pool or rnd.random() >= f["explore_share"]: continue
        lanes = {}
        for i, m in enumerate(pool[:30]):
            if i >= 3: lanes.setdefault(lane(m), []).append(i)
        if not lanes: continue
        th = {L: rnd.betavariate(st.get(L, (0, 0))[0] + 1, st.get(L, (0, 0))[1] + 1) for L in lanes}
        L = max(th, key=th.get); i = max(lanes[L], key=lambda k: (pool[k].get("rating") or pool[k].get("tmdb_user_score_pct") or 0))
        m = pool.pop(i); m["reco_lane"] = "explore"; pool.insert(0, m); chosen.append((slot, m["tmdb_id"], L, round(th[L], 3)))
        c.execute("INSERT OR REPLACE INTO reco_explore_choices VALUES(?,?,?,?,?)", (day, slot, m["tmdb_id"], L, th[L]))
    c.commit(); return pools, chosen
