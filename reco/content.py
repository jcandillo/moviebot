"""Generic content-based taste score (stand-in for an instance's private taste profile).
Seeds = taste_latest rows with signal='up' (weight by origin, see WEIGHTS); downs = signal='down'. Title metadata from reco_meta.
score = TMDB score/100 + sum_seeds w * 2 * genre-Jaccard + people affinity (director 2, writer 1.5, lead 1, cast 0.6) + 0.15 * shared keywords - down overlap.
Instances can plug in their own scorer: ranker.Ctx(content_fn=...)."""
import json
WEIGHTS = {"frame_vote": 1.0, "owner_chat": 1.0, "interview_loved": 1.0, "provider_rating": 0.7, "interview_fine": 0.4}
ROLE_W = {"director": 2.0, "writer": 1.5, "lead": 1.0, "cast": 0.6}
def _meta(c, tid):
    r = c.execute("SELECT title, genres_json, directors_json, writers_json, cast_json, keywords_json FROM reco_meta WHERE tmdb_id=?", (tid,)).fetchone()
    if not r: return None
    j = lambda s: json.loads(s or "[]")
    return dict(tmdb_id=tid, media_type="movie", title=r[0], genres=j(r[1]), directors=j(r[2]), writers=j(r[3]), cast=j(r[4]), keywords=j(r[5]))
def seeds(c):
    out = []
    for tid, mt, origin, title in c.execute("SELECT tmdb_id, media_type, origin, title FROM taste_latest WHERE signal='up'").fetchall():
        m = _meta(c, tid) if mt == "movie" else None
        out.append(dict(m or dict(tmdb_id=tid, media_type=mt, title=title, genres=[], directors=[], writers=[], cast=[], keywords=[]),
                        media_type=mt, weight=WEIGHTS.get(origin, 1.0), has_meta=bool(m)))
    return out
def downs(c):
    return [m for (tid,) in c.execute("SELECT tmdb_id FROM taste_latest WHERE signal='down' AND media_type='movie'").fetchall() if (m := _meta(c, tid))]
def _roles(x):
    r = [(p, "director") for p in x.get("directors") or []] + [(p, "writer") for p in x.get("writers") or []]
    return r + [(p, "lead" if i < 2 else "cast") for i, p in enumerate((x.get("cast") or [])[:5])]
def person_affinity(S, D):
    P, KW = {}, {}
    for u in S:
        if not u.get("has_meta") or u["weight"] <= 0: continue
        for p, role in _roles(u): P[p] = P.get(p, 0.0) + u["weight"] * ROLE_W[role]
        for k in set(u.get("keywords") or []): KW[k] = KW.get(k, 0.0) + u["weight"]
    for d in D:
        for p, role in _roles(d): P[p] = P.get(p, 0.0) - ROLE_W[role]
        for k in set(d.get("keywords") or []): KW[k] = KW.get(k, 0.0) - 1.0
    return P, KW
def score(m, S, D, _cache={}):
    key = (id(S), id(D))
    if key not in _cache: _cache.clear(); _cache[key] = person_affinity(S, D)
    P, KW = _cache[key]; g = set(m.get("genres") or [])
    s = (m.get("tmdb_user_score_pct") or 50) / 100.0
    for u in S:
        if u.get("has_meta") and u["weight"] > 0 and u.get("tmdb_id") != m.get("tmdb_id"):
            ug = set(u["genres"]); s += u["weight"] * 2 * len(g & ug) / max(1, len(g | ug))
    s += sum(max(0.0, P.get(p, 0.0)) * ROLE_W[r] / 2.0 for p, r in _roles(m))
    s += max(-1.0, min(1.0, 0.15 * sum(KW.get(k, 0.0) for k in set(m.get("keywords") or []))))
    for d in D: s -= 2 * len(set(m.get("directors") or []) & set(d["directors"])) + len(set(m.get("cast") or []) & set(d["cast"]))
    return round(s, 4)
