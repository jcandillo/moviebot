#!/usr/bin/env python3
"""Weekly scorecard -> improvement-sessions/YYYY-MM-DD-scorecard.md (+ .json).
Online (from reco_impressions/reco_reactions, Frame reactions only): cards shown, reactions, acceptance = (up+watched)/(up+down+next+watched),
down rate, skip (Next) rate, hit rate = share of distinct home/movie-night titles shown in the window that earned up/watched within 7 days,
by model_version and lane. Offline: latest eval JSON in reco/ (HR@10, NDCG@10, HR@50, MRR). Usage: scorecard.py [--days 7]"""
import datetime, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from common import ROOT
OUT = os.environ.get("MOVIEBOT_SESSIONS_DIR", os.path.join(ROOT, "improvement-sessions"))
def window(c, days):
    since = (datetime.datetime.now().astimezone() - datetime.timedelta(days=days)).isoformat(timespec="seconds")
    R = c.execute("SELECT r.reaction, COALESCE(i.model_version,'unlinked'), COALESCE(i.lane,'unlinked') FROM reco_reactions r LEFT JOIN reco_impressions i USING(impression_id) "
                  "WHERE r.source IN('frame_vote','frame_action') AND COALESCE(r.event_timestamp, r.logged_at) >= ?", (since,)).fetchall()
    shown = c.execute("SELECT COUNT(*), COUNT(DISTINCT tmdb_id) FROM reco_impressions WHERE surface IN('watch_at_home','movie_night') AND shown_at >= ?", (since,)).fetchone()
    hits = c.execute("SELECT COUNT(DISTINCT i.tmdb_id) FROM reco_impressions i JOIN reco_reactions r ON r.tmdb_id=i.tmdb_id AND r.reaction IN('up','watched') "
                     "WHERE i.surface IN('watch_at_home','movie_night') AND i.shown_at >= ? AND COALESCE(r.event_timestamp, r.logged_at) <= datetime(i.shown_at, '+7 days')", (since,)).fetchone()[0]
    def agg(rows):
        n = {k: sum(1 for r in rows if r[0] == k) for k in ("up", "down", "next", "watched")}; acted = sum(n.values())
        return dict(n, acted=acted, acceptance=round((n["up"] + n["watched"]) / acted, 3) if acted else None, down_rate=round(n["down"] / acted, 3) if acted else None,
                    skip_rate=round(n["next"] / acted, 3) if acted else None)
    by_model = {m: agg([r for r in R if r[1] == m]) for m in sorted({r[1] for r in R})}; by_lane = {l: agg([r for r in R if r[2] == l]) for l in sorted({r[2] for r in R})}
    return dict(since=since, all=agg(R), by_model=by_model, by_lane=by_lane, home_cards_shown=shown[0], home_titles_shown=shown[1], home_titles_hit=hits,
                hit_rate=round(hits / shown[1], 3) if shown[1] else None)
def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    c = connect(); ensure_schema(c); w = window(c, days); allt = window(c, 3650)
    ev = sorted(glob.glob(os.path.join(HERE, "eval-*.json")), key=os.path.getmtime); e = json.load(open(ev[-1])) if ev else None
    pool = c.execute("SELECT COUNT(DISTINCT tmdb_id) FROM reco_candidates").fetchone()[0]
    floor = c.execute("SELECT COUNT(*) FROM reco_quality q JOIN (SELECT DISTINCT tmdb_id FROM reco_candidates) k USING(tmdb_id) WHERE passes_floor=1").fetchone()[0]
    f = flags(); day = datetime.date.today().isoformat(); os.makedirs(OUT, exist_ok=True)
    doc = dict(at=now(), window_days=days, window=w, all_time=allt, pool=pool, pool_passing_floor=floor, flags=f, offline_eval=e and {k: e[k] for k in ("at", "pool_size", "results") if k in e})
    json.dump(doc, open(f"{OUT}/{day}-scorecard.json", "w"), indent=1)
    L = [f"# MovieBot scorecard {day} (last {days} days)", "", f"Live ranker: {f['live_ranker']} · explore share {f['explore_share'] if f['explore_thompson'] else 'off'} · pool {pool} ({floor} pass quality floor)", ""]
    for name, x in (("Last %d days" % days, w), ("All time", allt)):
        a = x["all"]; L += [f"## {name}", f"- Reactions: {a['acted']} (up {a['up']}, watched {a['watched']}, down {a['down']}, next {a['next']})",
                            f"- Acceptance {a['acceptance']} · down rate {a['down_rate']} · skip rate {a['skip_rate']}",
                            f"- Hit rate (home + movie night titles with up/watched within 7 days): {x['hit_rate']} ({x['home_titles_hit']}/{x['home_titles_shown']})",
                            f"- By model: " + "; ".join(f"{m}: acc {v['acceptance']} (n={v['acted']})" for m, v in x["by_model"].items()), ""]
    if e:
        L += ["## Offline eval (" + e.get("at", "") + ")"]
        for r, v in e["results"].items():
            L.append(f"- {r}: explicit HR@10 {v['explicit']['hr_at_10']}, NDCG@10 {v['explicit']['ndcg_at_10']}, HR@50 {v['explicit']['hr_at_50']}, MRR {v['explicit']['mrr']} · implicit HR@50 {v['implicit']['hr_at_50']}, MRR {v['implicit']['mrr']}")
    open(f"{OUT}/{day}-scorecard.md", "w").write("\n".join(L) + "\n"); print("\n".join(L))
if __name__ == "__main__": main()
