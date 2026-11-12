#!/usr/bin/env python3
"""Precompute MovieLens CF features for every MovieLens-mapped TMDB title against the CURRENT taste signals -> reco_cf_features.
Needed because the live Frame pipeline runs on system python (no numpy). Run (venv) after taste changes; the wake pipeline calls it.
cf_pos = weight-averaged top-3 cosine to positive seeds; cf_neg = max cosine to thumbs-down; cf_imp = mean top-5 cosine to implicit history."""
import hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranker import *
def main():
    c = connect(); ensure_schema(c)
    c.execute("CREATE TABLE IF NOT EXISTS reco_cf_features(tmdb_id INTEGER PRIMARY KEY, cf_pos REAL, cf_neg REAL, cf_imp REAL, computed_at TEXT, taste_hash TEXT)")
    S = TP.seeds(c, lambda t: None); D = TP.downs(c, lambda t: None); cf = CF()
    implicit = [r[0] for r in c.execute("SELECT tmdb_id FROM reco_implicit_history")]
    th = hashlib.sha256(json.dumps([[u.get("tmdb_id"), u["weight"]] for u in S] + [d["tmdb_id"] for d in D] + [len(implicit)]).encode()).hexdigest()[:16]
    P = [(cf.vec(u["tmdb_id"]), u["weight"]) for u in S if u.get("media_type") == "movie" and u["weight"] > 0]; P = [(v, w) for v, w in P if v is not None]
    PV = np.stack([v for v, w in P]); PW = np.array([w for v, w in P])
    N = [v for v in (cf.vec(d["tmdb_id"]) for d in D) if v is not None]; I = [v for v in (cf.vec(t) for t in implicit) if v is not None]
    SP = cf.F @ PV.T; top = np.argsort(-SP, axis=1)[:, :3]; tw = PW[top]; cfp = (np.take_along_axis(SP, top, 1) * tw).sum(1) / tw.sum(1)
    cfn = (cf.F @ np.stack(N).T).max(1) if N else np.zeros(len(cf.ids))
    SI = cf.F @ np.stack(I).T if I else None; cfi = np.zeros(len(cf.ids))
    if SI is not None:
        srt = np.sort(SI, axis=1); imp_set = set(implicit); self_hit = np.array([int(t) in imp_set for t in cf.ids])
        cfi = np.where(self_hit, srt[:, -6:-1].mean(1), srt[:, -5:].mean(1))   # implicit titles: skip their own self-match
    t = now(); c.execute("DELETE FROM reco_cf_features")
    c.executemany("INSERT OR REPLACE INTO reco_cf_features VALUES(?,?,?,?,?,?)", [(int(i), float(a), float(b), float(d), t, th) for i, a, b, d in zip(cf.ids, cfp, cfn, cfi)]); c.commit()
    print(json.dumps({"ok": True, "rows": len(cf.ids), "taste_hash": th, "pos_seeds_with_cf": len(P), "downs_with_cf": len(N), "implicit_with_cf": len(I)}))
if __name__ == "__main__": main()
