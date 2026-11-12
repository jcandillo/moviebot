#!/usr/bin/env python3
"""Download first (local only, never commit): https://files.grouplens.org/datasets/movielens/ml-32m.zip -> unzip into $MOVIEBOT_ML_DIR/ml-32m.
Build collaborative item embeddings from MovieLens 32M (local only; research/non-commercial license; never committed).
Positives = ratings >= 4.0. Users with >= MIN_U positives, items with >= MIN_I positives. Rows scaled 1/sqrt(n_u).
Truncated SVD (scipy.sparse.linalg.svds, k=K) -> item factors V*sqrt(s), L2-normalised. Item-item similarity = cosine of factors.
Output: ml-data/ml_item_factors.npz {tmdb_ids, factors, pos_count, mean_rating, n_ratings}. Mapping via links.csv (movieId -> tmdbId)."""
import csv, os, sys, time
import numpy as np, scipy.sparse as sp
from scipy.sparse.linalg import svds
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from common import ML_DIR, ML_NPZ
D = os.path.join(ML_DIR, "ml-32m"); OUT = ML_NPZ
K = int(os.environ.get("ML_K", 96)); MIN_U, MIN_I = 5, 20
t0 = time.time()
R = np.loadtxt(f"{D}/ratings.csv", delimiter=",", skiprows=1, usecols=(0, 1, 2), dtype=np.float32)
u = R[:, 0].astype(np.int32); i = R[:, 1].astype(np.int32); r = R[:, 2]; del R
print("loaded", len(r), round(time.time() - t0, 1), "s", flush=True)
# per-item stats over all ratings
ni = np.bincount(i); si = np.bincount(i, weights=r)
pos = r >= 4.0; u, i = u[pos], i[pos]
uc = np.bincount(u); ic = np.bincount(i)
keep = (uc[u] >= MIN_U) & (ic[i] >= MIN_I); u, i = u[keep], i[keep]
uu, ui = np.unique(u, return_inverse=True); iu, ii = np.unique(i, return_inverse=True)
w = 1.0 / np.sqrt(np.bincount(ui)[ui]).astype(np.float32)
X = sp.csr_matrix((w, (ui, ii)), shape=(len(uu), len(iu)), dtype=np.float32)
print("matrix", X.shape, X.nnz, flush=True)
U, s, Vt = svds(X, k=K); order = np.argsort(-s); s, Vt = s[order], Vt[order]
F = (Vt.T * np.sqrt(s)).astype(np.float32); F /= np.linalg.norm(F, axis=1, keepdims=True) + 1e-9
links = {}
with open(f"{D}/links.csv") as f:
    for row in csv.DictReader(f):
        if row["tmdbId"]: links[int(row["movieId"])] = int(row["tmdbId"])
tm = np.array([links.get(int(m), -1) for m in iu], dtype=np.int64); ok = tm > 0
np.savez_compressed(OUT, tmdb_ids=tm[ok], factors=F[ok], pos_count=np.bincount(ii)[ok].astype(np.int32),
                    mean_rating=(si[iu] / np.maximum(ni[iu], 1))[ok].astype(np.float32), n_ratings=ni[iu][ok].astype(np.int32), singular_values=s)
print("saved", OUT, int(ok.sum()), "items", round(time.time() - t0, 1), "s", flush=True)
