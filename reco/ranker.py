#!/usr/bin/env python3
"""reco_v1 ranker (P2/P3). score = linear blend of standardised features:
  v3      current taste-profile v3 score (people/keyword/genre/seed overlap)          content signal
  cf_pos  MovieLens item-item cosine (SVD factors) to positive seeds, weight-averaged top-3
  cf_neg  max cosine to thumbs-down titles
  cf_imp  mean top-5 cosine to implicit (unconfirmed) watch history, weak
  quality Bayesian weighted rating (TMDB + IMDb), centred at 7
  pop     log10 TMDB vote count
Weights: hand-set prior HAND_W; once the personal logistic model (personal_model.py) has >= MIN_LABELS reactions its weights blend in
by n/(n+MIN_LABELS). Thompson-sampling lanes pick ~explore_share of slots (explore.py)."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from common import *
try:
    import numpy as np
except ImportError:   # live Frame pipeline runs on system python: CF features come from reco_cf_features (precompute.py)
    np = None
import tp_adapter as TP
FEATS = ["v3", "cf_pos", "cf_neg", "cf_imp", "quality", "pop"]
HAND_W = {"v3": 1.0, "cf_pos": 1.0, "cf_neg": -0.4, "cf_imp": 0.15, "quality": 0.5, "pop": 0.1}
MIN_LABELS = 50
# TP.person_affinity memoises on id(list(D)), which is a fresh list on every TP.score call -> unbounded cache growth and recomputation.
# Bounded memo keyed on the seed/down object identities (same semantics) for reco processes.
_orig_pa = TP.person_affinity; _PA2 = {}
def _pa(S, D):
    key = (id(S), tuple(id(d) for d in D))
    if key not in _PA2:
        if len(_PA2) > 64: _PA2.clear()
        TP._PA.clear(); _PA2[key] = _orig_pa(S, D)
    return _PA2[key]
TP.person_affinity = _pa
class CF:
    def __init__(self, path=ML_NPZ):
        z = np.load(path); self.ids = z["tmdb_ids"]; self.F = z["factors"]; self.ix = {int(t): k for k, t in enumerate(self.ids)}
    def vec(self, t): k = self.ix.get(int(t)); return None if k is None else self.F[k]
class Ctx:
    """Everything a score needs, built once per run. seeds/downs are TP seed dicts; implicit = [tmdb_id]."""
    def __init__(self, c, S, D, qgenres, implicit=None, weights=None, cf=None, use_table=False):
        self.S, self.D, self.qg = S, D, qgenres; self.table = None
        self.cf = cf or (CF() if np is not None and flags()["ml_cf"] and os.path.exists(ML_NPZ) and not use_table else None)
        if self.cf is None and flags()["ml_cf"]:
            try: self.table = {r[0]: r[1:] for r in c.execute("SELECT tmdb_id, cf_pos, cf_neg, cf_imp FROM reco_cf_features")}
            except Exception: self.table = {}
        self.q = {r[0]: (r[1], r[2]) for r in c.execute("SELECT tmdb_id, quality, passes_floor FROM reco_quality")}
        if implicit is None: implicit = [r[0] for r in c.execute("SELECT tmdb_id FROM reco_implicit_history")]
        self.weights = weights or load_weights(c)
        if self.cf:
            P = [(self.cf.vec(u["tmdb_id"]), u["weight"]) for u in S if u.get("tmdb_id") and u.get("media_type") == "movie" and u["weight"] > 0]
            P = [(v, w) for v, w in P if v is not None]
            self.PV = np.stack([v for v, w in P]) if P else None; self.PW = np.array([w for v, w in P]) if P else None
            N = [self.cf.vec(d["tmdb_id"]) for d in D]; N = [v for v in N if v is not None]; self.NV = np.stack(N) if N else None
            I = [self.cf.vec(t) for t in implicit]; I = [v for v in I if v is not None]; self.IV = np.stack(I) if I else None
    def features(self, m):
        f = dict(v3=getattr(TP, "_score_v3", TP.score)(m, self.S, self.D, self.qg), cf_pos=0.0, cf_neg=0.0, cf_imp=0.0, quality=0.0, pop=0.0)
        q = self.q.get(m.get("tmdb_id"))
        if q and q[0] is not None: f["quality"] = q[0] - 7.0
        else: f["quality"] = -0.3   # no vote-count-backed rating (legacy pool title): slightly below the prior, never the raw unshrunk score
        f["pop"] = math.log10(1 + (m.get("vote_count") or 0))
        if self.table is not None:
            t = self.table.get(m.get("tmdb_id"))
            if t: f["cf_pos"], f["cf_neg"], f["cf_imp"] = t
            return f
        v = self.cf.vec(m["tmdb_id"]) if self.cf else None
        if v is not None:
            if self.PV is not None:
                s = self.PV @ v; top = np.argsort(-s)[:3]; f["cf_pos"] = float((s[top] * self.PW[top]).sum() / max(1e-9, self.PW[top].sum()))
            if self.NV is not None: f["cf_neg"] = float((self.NV @ v).max())
            if self.IV is not None: s = np.sort(self.IV @ v)[-5:]; f["cf_imp"] = float(s.mean())
        return f
    def score(self, m, f=None):
        f = f or self.features(m); W = self.weights
        # feature scales (fixed, from the 2026-11-11 pool): v3 ~ 0-4, cf ~ 0-1, quality ~ -1..+1.5, pop ~ 1-5
        sc = {"v3": 1 / 1.5, "cf_pos": 1 / 0.25, "cf_neg": 1 / 0.25, "cf_imp": 1 / 0.25, "quality": 1 / 0.6, "pop": 1 / 1.0}
        return round(sum(W.get(k, 0) * f[k] * sc[k] for k in FEATS), 4), f
def load_weights(c):
    """Active blend weights (reco_model_versions kind='blend', set by the offline-eval winner) else HAND_W; the personal logistic model
    (kind='logistic') blends in by n/(n+MIN_LABELS) only once it has >= MIN_LABELS labelled reactions (fallback = blend weights)."""
    w = dict(HAND_W)
    if c is None: return w
    try:
        r = c.execute("SELECT params_json FROM reco_model_versions WHERE kind='blend' AND active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if r: w.update(json.loads(r[0])["w"])
        if flags()["personal_model"]:
            r = c.execute("SELECT params_json, n_train FROM reco_model_versions WHERE kind='logistic' AND active=1 ORDER BY created_at DESC LIMIT 1").fetchone()
            if r and r[1] >= MIN_LABELS:
                p = json.loads(r[0])["w"]; a = r[1] / (r[1] + MIN_LABELS)
                # rescale logistic coefficients to the blend's L1 norm so the mix is in comparable units
                l1b = sum(abs(w[k]) for k in FEATS) or 1.0; l1p = sum(abs(p.get(k, 0)) for k in FEATS) or 1.0
                w = {k: (1 - a) * w[k] + a * p.get(k, 0) * l1b / l1p for k in FEATS}
    except Exception: pass
    return w
def meta_to_tp(r):
    """reco_meta row (dict) -> TP candidate dict."""
    j = lambda s: json.loads(s or "[]")
    return dict(tmdb_id=r["tmdb_id"], media_type="movie", title=r["title"], year=r["year"], genres=j(r["genres_json"]), directors=j(r["directors_json"]),
                writers=j(r["writers_json"]), creators=[], cast=j(r["cast_json"]), keywords=j(r["keywords_json"]), overview=r["overview"],
                tmdb_user_score_pct=round(r["vote_average"] * 10) if r["vote_average"] and r["vote_count"] else None, vote_count=r["vote_count"],
                poster_url=("https://image.tmdb.org/t/p/w342" + r["poster_path"]) if r["poster_path"] else None, release=r["release_date"],
                source=f"https://www.themoviedb.org/movie/{r['tmdb_id']}", us_flatrate=j(r["us_flatrate_json"]), us_free=j(r["us_free_json"]))
def load_pool(c, floor=True):
    c.row_factory = __import__("sqlite3").Row
    q = "SELECT m.* FROM reco_meta m JOIN (SELECT DISTINCT tmdb_id FROM reco_candidates) k USING(tmdb_id) LEFT JOIN reco_quality q USING(tmdb_id) WHERE m.status='Released'"
    if floor and flags()["quality_floor"]: q += " AND q.passes_floor=1"
    rows = [meta_to_tp(dict(r)) for r in c.execute(q)]; c.row_factory = None; return rows
def exclusions(c):
    import policy
    ex = {r[0] for r in c.execute("SELECT tmdb_id FROM taste_latest")} | set(policy.HARD_EXCLUDE)
    ex |= {r[0] for r in c.execute("SELECT tmdb_id FROM reco_implicit_history")} if flags()["implicit_history_exclusion"] else set()
    ex |= {r[0] for r in c.execute("SELECT DISTINCT tmdb_id FROM title_matches WHERE media_type='movie' AND item_kind='viewing' AND tmdb_id IS NOT NULL")} - TP.neutralized_tmdb(c)
    ex |= {r[0] for r in c.execute("SELECT tmdb_id FROM reco_reactions WHERE reaction IN('down','watched','interview_not_for_me')")}
    return ex, TP.history_titles(c)
