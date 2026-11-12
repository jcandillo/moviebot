"""Shared helpers for the MovieBot reco layer ."""
import json, os, sqlite3, time, urllib.parse, urllib.request, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TV_DB = os.environ.get("MOVIEBOT_DB", os.path.join(ROOT, "moviebot.db"))
RAW_DB = os.environ.get("MOVIEBOT_RAW_DB", os.path.join(ROOT, "raw_votes.db"))
FLAGS_PATH = os.environ.get("RECO_FLAGS", os.path.join(ROOT, "config", "reco_flags.json"))
ML_DIR = os.environ.get("MOVIEBOT_ML_DIR", os.path.join(ROOT, "ml-data"))
ML_NPZ = os.environ.get("ML_OUT", os.path.join(ML_DIR, "ml_item_factors.npz"))
IMDB_TSV = os.environ.get("IMDB_RATINGS", os.path.join(ML_DIR, "title.ratings.tsv.gz"))
DEFAULT_FLAGS = {"log_impressions": True, "quality_floor": True, "pool_tmdb_discover": True, "pool_tmdb_recs": True, "pool_person_search": False,
                 "ml_cf": True, "personal_model": True, "explore_thompson": True, "explore_share": 0.10, "live_ranker": "content", "why_v3_frame": False,
                 "implicit_history_exclusion": True}
def flags():
    f = dict(DEFAULT_FLAGS)
    if os.path.exists(FLAGS_PATH): f.update(json.load(open(FLAGS_PATH)))
    return f
def now(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
def connect(path=TV_DB, ro=False):
    c = sqlite3.connect(f"file:{path}?mode=ro" if ro else path, uri=ro, timeout=30); c.execute("PRAGMA busy_timeout=30000"); return c
SCHEMA = """
CREATE TABLE IF NOT EXISTS reco_impressions(impression_id TEXT PRIMARY KEY, picks_revision INTEGER, surface TEXT NOT NULL, slot_id TEXT NOT NULL, rank INTEGER,
 tmdb_id INTEGER NOT NULL, media_type TEXT DEFAULT 'movie', title TEXT, year INTEGER, why TEXT, why_type TEXT, score REAL, features_json TEXT, model_version TEXT,
 lane TEXT, where_to_watch_status TEXT, shown_at TEXT NOT NULL, source_path TEXT, logged_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reco_impr_tmdb ON reco_impressions(tmdb_id);
CREATE TABLE IF NOT EXISTS reco_reactions(reaction_id TEXT PRIMARY KEY, impression_id TEXT, tmdb_id INTEGER NOT NULL, reaction TEXT NOT NULL
 CHECK(reaction IN('up','down','next','watched','skip','interview_loved','interview_fine','interview_not_for_me')), slot_id TEXT, displayed_revision INTEGER,
 event_timestamp TEXT, source TEXT NOT NULL, logged_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reco_react_tmdb ON reco_reactions(tmdb_id);
CREATE TABLE IF NOT EXISTS reco_meta(tmdb_id INTEGER PRIMARY KEY, title TEXT, year INTEGER, release_date TEXT, original_language TEXT, genres_json TEXT, directors_json TEXT,
 writers_json TEXT, cast_json TEXT, keywords_json TEXT, overview TEXT, poster_path TEXT, vote_average REAL, vote_count INTEGER, popularity REAL, imdb_id TEXT,
 us_flatrate_json TEXT, us_free_json TEXT, us_rent_json TEXT, us_buy_json TEXT, providers_checked_at TEXT, status TEXT, fetched_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reco_candidates(tmdb_id INTEGER NOT NULL, source TEXT NOT NULL, detail TEXT, added_at TEXT NOT NULL, PRIMARY KEY(tmdb_id, source, detail));
CREATE TABLE IF NOT EXISTS reco_imdb_ratings(imdb_id TEXT PRIMARY KEY, average_rating REAL, num_votes INTEGER, loaded_at TEXT);
CREATE TABLE IF NOT EXISTS reco_quality(tmdb_id INTEGER PRIMARY KEY, wr_tmdb REAL, wr_imdb REAL, quality REAL, passes_floor INTEGER, reason TEXT, computed_at TEXT);
CREATE TABLE IF NOT EXISTS reco_model_versions(model_version TEXT PRIMARY KEY, kind TEXT, params_json TEXT, n_train INTEGER, metrics_json TEXT, created_at TEXT, active INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS reco_lane_stats(lane TEXT PRIMARY KEY, ups REAL DEFAULT 0, downs REAL DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS reco_implicit_history(tmdb_id INTEGER, title TEXT, service TEXT, n_views INTEGER, first_seen TEXT, last_seen TEXT, PRIMARY KEY(tmdb_id, service));
"""
def ensure_schema(c): c.executescript(SCHEMA); c.commit()
_KEY = os.environ.get("TMDB_API_KEY")
def tmdb(path, retries=4, **q):
    q["api_key"] = _KEY; u = "https://api.themoviedb.org/3" + path + "?" + urllib.parse.urlencode(q)
    for a in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"Accept": "application/json"}), timeout=20) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code == 429: time.sleep(2 + a * 2); continue
            if a == retries - 1: raise RuntimeError(f"TMDB HTTP {e.code} for {path}") from None
        except Exception as e:
            if a == retries - 1: raise RuntimeError(f"TMDB error for {path}: {type(e).__name__}") from None
        time.sleep(1 + a)
