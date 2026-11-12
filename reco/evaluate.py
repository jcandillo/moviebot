#!/usr/bin/env python3
"""Offline evaluation harness.
  explicit LOO : each confirmed positive movie (taste 'up', any weight) is held out of the seeds and ranked against the eligible pool.
  implicit     : N_IMPLICIT sampled titles from imported (unconfirmed) provider history are held out of cf_imp and ranked against the pool.
Metrics per ranker: HR@10, NDCG@10, HR@50, MRR, median rank. Rankers: v3 (current live), reco (blend with given weights), quality_only, cf_only, random.
  evaluate.py [OUT.json] [--grid]   --grid: coarse weight search on the cached features; best config reported (selection metric: mean HR@50 + 10*MRR over both sets)."""
import itertools, json, math, os, random, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranker import *
import policy
N_IMPLICIT = 150
def build(c):
    S_all = TP.seeds(c, lambda t: None); D = TP.downs(c, lambda t: None); md = TP.metadata(c)
    c.row_factory = __import__("sqlite3").Row
    meta = {r["tmdb_id"]: meta_to_tp(dict(r)) for r in c.execute("SELECT * FROM reco_meta")}; c.row_factory = None
    ex, hist = exclusions(c); pos_ids = {u["tmdb_id"] for u in S_all if u.get("tmdb_id")}
    implicit = [r[0] for r in c.execute("SELECT tmdb_id FROM reco_implicit_history ORDER BY tmdb_id")]
    pool = [TP.enrich(m, md) for m in load_pool(c) if m["tmdb_id"] not in ex and m["tmdb_id"] not in pos_ids and m["title"].strip().lower() not in hist]
    cf = CF() if os.path.exists(ML_NPZ) else None; cases = []
    for h in [u for u in S_all if u.get("media_type") == "movie" and u["weight"] > 0 and u["tmdb_id"] in meta]:
        ctx = Ctx(c, [u for u in S_all if u.get("tmdb_id") != h["tmdb_id"]], D, policy.QUESTIONNAIRE_GENRES, implicit=[t for t in implicit if t != h["tmdb_id"]], cf=cf)
        cases.append(("explicit", h["title"], ctx, TP.enrich(meta[h["tmdb_id"]], md)))
    rnd = random.Random(11); imp = [t for t in implicit if t in meta and t not in pos_ids]; rnd.shuffle(imp)
    for t in imp[:N_IMPLICIT]:
        ctx = Ctx(c, S_all, D, policy.QUESTIONNAIRE_GENRES, implicit=[x for x in implicit if x != t], cf=cf)
        cases.append(("implicit", meta[t]["title"], ctx, TP.enrich(meta[t], md)))
    # features: pool features depend on ctx; cache per case
    data = []
    for kind, title, ctx, tgt in cases:
        P = [ctx.features(m) for m in pool]; data.append((kind, title, ctx.features(tgt), P))
    return data, len(pool)
SC = {"v3": 1 / 1.5, "cf_pos": 1 / 0.25, "cf_neg": 1 / 0.25, "cf_imp": 1 / 0.25, "quality": 1 / 0.6, "pop": 1.0}
def lin(W): return lambda f: sum(W.get(k, 0) * f[k] * SC[k] for k in FEATS)
def evaluate(data, keyf, k=10):
    out = {}
    for kind in ("explicit", "implicit"):
        ranks = []
        for kd, title, tf, P in data:
            if kd != kind: continue
            ts = keyf(tf); ranks.append(1 + sum(1 for f in P if keyf(f) > ts))
        n = max(1, len(ranks))
        out[kind] = dict(n=len(ranks), hr_at_10=round(sum(r <= k for r in ranks) / n, 3), ndcg_at_10=round(sum(1 / math.log2(r + 1) for r in ranks if r <= k) / n, 4),
                         hr_at_50=round(sum(r <= 50 for r in ranks) / n, 3), mrr=round(sum(1 / r for r in ranks) / n, 4), median_rank=statistics.median(ranks) if ranks else None)
    return out
def sel(m): return sum(m[k]["hr_at_50"] + 10 * m[k]["mrr"] for k in ("explicit", "implicit")) / 2
if __name__ == "__main__":
    c = connect(); ensure_schema(c); data, npool = build(c); W = load_weights(c)
    rnd = random.Random(3); rv = {}
    R = {"v3": lambda f: f["v3"], "reco_current_weights": lin(W), "quality_only": lambda f: f["quality"], "cf_only": lambda f: f["cf_pos"],
         "random": lambda f: rv.setdefault(id(f), rnd.random())}
    res = {name: evaluate(data, f) for name, f in R.items()}
    o = {"at": now(), "pool_size": npool, "weights_current": W, "results": res}
    if "--grid" in sys.argv:
        best = None
        for v3, cp, ci, q, cn in itertools.product([0.5, 1.0, 2.0], [0, 0.5, 1.0, 2.0], [0, 0.3, 1.0], [0, 0.25, 0.5, 1.0], [0, -0.4]):
            Wg = dict(v3=v3, cf_pos=cp, cf_imp=ci, quality=q, cf_neg=cn, pop=0.1); m = evaluate(data, lin(Wg)); s = sel(m)
            if not best or s > best[0]: best = (s, Wg, m)
        o["grid_best"] = {"weights": best[1], "results": best[2], "selection_score": round(best[0], 4), "v3_selection_score": round(sel(res["v3"]), 4)}
    p = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
    if p: json.dump(o, open(p, "w"), indent=1)
    print(json.dumps(o, indent=1))
