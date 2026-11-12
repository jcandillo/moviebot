#!/usr/bin/env python3
"""P3 personal model: L2-regularised logistic regression (numpy) on the owner's logged reactions.
Labels: up / watched / interview_loved = 1 (weight 1); interview_fine = 1 (0.4); down / interview_not_for_me = 0 (1); next = 0 (0.5).
Features = ranker FEATS computed with the labelled title removed from the seeds (no self-leakage), scaled like the blend.
Stored as reco_model_versions kind='logistic'. Becomes active only when n >= MIN_LABELS (50); until then the blend weights are the fallback."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranker import *
import policy
LAB = {"up": (1, 1.0), "watched": (1, 1.0), "interview_loved": (1, 1.0), "interview_fine": (1, 0.4), "down": (0, 1.0), "interview_not_for_me": (0, 1.0), "next": (0, 0.5)}
SC = {"v3": 1 / 1.5, "cf_pos": 1 / 0.25, "cf_neg": 1 / 0.25, "cf_imp": 1 / 0.25, "quality": 1 / 0.6, "pop": 1.0}
def train(c, l2=1.0, iters=3000, lr=0.1):
    S_all = TP.seeds(c, lambda t: None); D_all = TP.downs(c, lambda t: None); md = TP.metadata(c); cf = CF()
    c.row_factory = __import__("sqlite3").Row; meta = {r["tmdb_id"]: meta_to_tp(dict(r)) for r in c.execute("SELECT * FROM reco_meta")}; c.row_factory = None
    latest = {}
    for tid, rx, ts in c.execute("SELECT tmdb_id, reaction, COALESCE(event_timestamp, logged_at) FROM reco_reactions ORDER BY 3"):
        if rx in LAB: latest[tid] = rx   # last reaction per title wins
    X, y, w, used = [], [], [], []
    for tid, rx in latest.items():
        if tid not in meta: continue
        ctx = Ctx(c, [u for u in S_all if u.get("tmdb_id") != tid], [d for d in D_all if d["tmdb_id"] != tid], policy.QUESTIONNAIRE_GENRES, cf=cf)
        f = ctx.features(TP.enrich(meta[tid], md)); X.append([f[k] * SC[k] for k in FEATS]); y.append(LAB[rx][0]); w.append(LAB[rx][1]); used.append((meta[tid]["title"], rx))
    if len(set(y)) < 2: return None
    X = np.array(X); y = np.array(y, float); w = np.array(w); b = 0.0; th = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ th + b))); g = X.T @ (w * (p - y)) / w.sum() + l2 * th / len(y); gb = (w * (p - y)).sum() / w.sum()
        th -= lr * g; b -= lr * gb
    p = 1 / (1 + np.exp(-(X @ th + b))); acc = float(((p > 0.5) == (y > 0.5)).mean())
    return dict(w={k: round(float(v), 4) for k, v in zip(FEATS, th)}, b=round(float(b), 4), l2=l2), len(y), dict(train_acc=round(acc, 3), positives=int(y.sum()), negatives=int(len(y) - y.sum())), used
if __name__ == "__main__":
    c = connect(); ensure_schema(c); r = train(c)
    if not r: print(json.dumps({"ok": False, "reason": "need both positive and negative labels"})); sys.exit(0)
    params, n, metrics, used = r; mv = "logistic-" + now()
    c.execute("UPDATE reco_model_versions SET active=0 WHERE kind='logistic'")
    c.execute("INSERT INTO reco_model_versions VALUES(?,?,?,?,?,?,?)", (mv, "logistic", json.dumps(params), n, json.dumps(metrics), now(), 1))
    c.commit(); print(json.dumps({"ok": True, "model_version": mv, "n_train": n, "in_use": n >= MIN_LABELS, "min_labels": MIN_LABELS, "params": params, "metrics": metrics}, indent=1))
