"""Adapter exposing the taste-profile API the reco layer expects, backed by the generic content scorer (content.py).
An instance with its own private taste module can replace this file (same function names)."""
import content
def seeds(c, meta_fn=None): return content.seeds(c)
def downs(c, meta_fn=None): return content.downs(c)
def metadata(c): return {}
def enrich(m, md, media="movie"): return m
def score(m, S, D, qgenres):
    return content.score(m, S, D) + 0.5 * len(set(m.get("genres") or []) & set(qgenres or ()))
_score_v3 = score
person_affinity = content.person_affinity
_PA = {}
def neutralized_tmdb(c):
    try: return {r[0] for r in c.execute("SELECT DISTINCT tmdb_id FROM history_neutralized WHERE tmdb_id IS NOT NULL")}
    except Exception: return set()
def history_titles(c):
    try: return {r[0].strip().lower() for r in c.execute("SELECT raw_title FROM viewing_events WHERE raw_title IS NOT NULL")}
    except Exception: return set()
