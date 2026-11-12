-- MovieBot data layer (single human, per-instance SQLite).
-- Two databases in the reference implementation:
--   moviebot.db   : personal store (this file). Create with: sqlite3 moviebot.db < docs/schema.sql
--   raw_votes.db  : optional display feedback/lease ledger; its tables (raw_votes, raw_actions, selections,
--                   workflow_lease, publish_intents, receipts, tmdb_public_meta, watch_availability cache ...)
--                   are created automatically by pipeline/*.py on first run.
-- Sections: [CORE-IMPLEMENTED] used by code in this repo; [SPEC] defined by docs/architecture.md and
-- docs/REPLICATE.md but not yet read/written by this repo's code.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS services (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  has_history_export INTEGER NOT NULL DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS connectors (
  id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id),
  account_name TEXT, account_email TEXT, account_verified INTEGER NOT NULL DEFAULT 0,
  profile TEXT, auth_path TEXT, auth_state TEXT, last_sync TEXT, notes TEXT,
  UNIQUE(service_id, account_name, profile));
CREATE TABLE IF NOT EXISTS viewing_events (
  id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id),
  connector_id INTEGER REFERENCES connectors(id),
  raw_title TEXT NOT NULL, show_name TEXT, season TEXT, episode TEXT,
  watched_date TEXT, date_precision TEXT, channel TEXT, url TEXT,
  source TEXT NOT NULL DEFAULT 'connector' CHECK (source IN ('connector','import','suggestion_feedback')),
  imported_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(service_id, raw_title, watched_date, url));
CREATE TABLE IF NOT EXISTS watchlist_items (
  id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id),
  connector_id INTEGER REFERENCES connectors(id),
  list_type TEXT NOT NULL,  -- my_list, continue_watching, watch_later, ...
  raw_title TEXT NOT NULL, show_name TEXT, season TEXT, episode TEXT, episode_title TEXT,
  progress TEXT, is_taste_signal INTEGER NOT NULL DEFAULT 1,  -- taste signal, NOT "seen"
  observed_at TEXT NOT NULL DEFAULT (datetime('now')), notes TEXT,
  UNIQUE(service_id, list_type, raw_title));
CREATE TABLE IF NOT EXISTS titles (
  tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL CHECK (media_type IN ('movie','tv')),
  name TEXT, year INTEGER, cached_json TEXT, fetched_at TEXT,
  PRIMARY KEY (tmdb_id, media_type));
CREATE TABLE IF NOT EXISTS title_matches (
  id INTEGER PRIMARY KEY, item_kind TEXT NOT NULL CHECK (item_kind IN ('viewing','watchlist')),
  service_id INTEGER NOT NULL REFERENCES services(id),
  match_key TEXT NOT NULL,           -- distinct show/movie name being matched
  tmdb_id INTEGER, media_type TEXT, confidence REAL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','matched','unmatched','creator_content','needs_review')),
  method TEXT, matched_at TEXT,
  UNIQUE(service_id, item_kind, match_key));
CREATE TABLE IF NOT EXISTS title_availability (
  tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL, service_id INTEGER NOT NULL REFERENCES services(id),
  source TEXT, observed_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tmdb_id, media_type, service_id));

-- ===================================================================================
-- [CORE-IMPLEMENTED] Feedback and taste (also created idempotently by pipeline/feedback_apply.py)
-- ===================================================================================
CREATE TABLE IF NOT EXISTS taste_signals(
  event_id TEXT PRIMARY KEY, tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL CHECK(media_type IN('movie','tv')),
  signal TEXT NOT NULL CHECK(signal IN('up','down')),          -- raw categorical; never mapped to a number
  origin TEXT NOT NULL, title TEXT, slot_id TEXT, displayed_revision INTEGER, event_timestamp TEXT NOT NULL,
  supersedes TEXT, payload_sha256 TEXT NOT NULL, raw_json TEXT NOT NULL, applied_at TEXT NOT NULL, apply_receipt_id TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS taste_latest AS
  SELECT t.* FROM taste_signals t WHERE NOT EXISTS (SELECT 1 FROM taste_signals u WHERE u.tmdb_id=t.tmdb_id AND u.media_type=t.media_type
    AND (u.event_timestamp > t.event_timestamp OR (u.event_timestamp = t.event_timestamp AND u.event_id > t.event_id)));
CREATE TABLE IF NOT EXISTS feedback_history_receipts(
  action_event_id TEXT PRIMARY KEY, viewing_event_id INTEGER NOT NULL REFERENCES viewing_events(id), title_match_id INTEGER,
  tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL, evidence_json TEXT NOT NULL, applied_at TEXT NOT NULL, apply_receipt_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback_apply_receipts(receipt_id TEXT PRIMARY KEY, at TEXT, kind TEXT, counts_json TEXT, backup_path TEXT, inputs_json TEXT);

-- [CORE-IMPLEMENTED] Where-to-watch observation cache (pipeline/where_to_watch.py creates it in the --db it is given).
-- Reference implementation parses public JustWatch US pages (source='justwatch_public_page').
-- Spec path: TMDB movie/{id}/watch/providers (source='tmdb_watch_providers') with the same status semantics.
CREATE TABLE IF NOT EXISTS watch_availability(
  id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL, title TEXT, year INTEGER, checked_at TEXT NOT NULL,
  source_url TEXT, status TEXT NOT NULL CHECK(status IN('verified_offers','verified_no_home_offers','unverified','identity_mismatch')),
  subscription_json TEXT, rent_json TEXT, buy_json TEXT, free_json TEXT, cinema INTEGER, page_title TEXT, page_year INTEGER,
  page_directors_json TEXT, page_sha256 TEXT, parser TEXT, error TEXT, card_text TEXT,
  media_type TEXT DEFAULT 'movie', country TEXT DEFAULT 'US', source TEXT DEFAULT 'justwatch_public_page', superseded_reason TEXT);

-- ===================================================================================
-- [SPEC] Subscriptions (ServiceSubscription). Drives the Watch at Home gate: only fresh verified_active rows qualify.
-- ===================================================================================
CREATE TABLE IF NOT EXISTS service_subscriptions(
  id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id),
  status TEXT NOT NULL CHECK(status IN('verified_active','likely_active','paused','ended','not_subscribed','unknown')),
  confidence REAL, source TEXT NOT NULL,                        -- e.g. human (dated owner confirmation), receipt, connector
  evidence_refs TEXT, as_of TEXT NOT NULL, tier TEXT, region TEXT NOT NULL DEFAULT 'US',
  access_path TEXT CHECK(access_path IN('direct','bundle','channel_addon','free')),
  host_service_id INTEGER REFERENCES services(id),              -- for bundles/channels carried by another service
  renews_on TEXT, stale_after TEXT, known_expiry TEXT, notes TEXT,
  UNIQUE(service_id, tier, region));

-- [SPEC] Explicit preferences (genres, seed ratings love/neutral/nope, avoids, corrections, labeled inferences)
CREATE TABLE IF NOT EXISTS preferences(
  id INTEGER PRIMARY KEY, subject_type TEXT NOT NULL CHECK(subject_type IN('genre','title','person','keyword','service','other')),
  subject_value TEXT NOT NULL, tmdb_id INTEGER, media_type TEXT,
  value TEXT NOT NULL,                  -- love | neutral | nope | like | dislike | avoid | loved | fine | not_for_me | didnt_watch
  weight REAL,                          -- taste v3: 1.0 explicit love/up, 0.7 imported rating, 0.4 fine, 0 unconfirmed, <0 negative
  origin TEXT NOT NULL,                 -- questionnaire | feedback | interview | import | inference
  is_inference INTEGER NOT NULL DEFAULT 0, provenance TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')), revision INTEGER NOT NULL DEFAULT 1);

-- [SPEC] Watch-history interview confirmations (taste v3): Loved it / It was fine / Not for me / Didn't watch it
CREATE TABLE IF NOT EXISTS history_confirmations(
  viewing_event_id INTEGER PRIMARY KEY REFERENCES viewing_events(id),
  answer TEXT NOT NULL CHECK(answer IN('loved','fine','not_for_me','didnt_watch')), answered_at TEXT NOT NULL);

-- [SPEC] Rich per-title metadata (taste v3). Store only what a real source (TMDB) returns.
CREATE TABLE IF NOT EXISTS title_metadata(
  tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL CHECK(media_type IN('movie','tv')),
  directors_json TEXT, writers_json TEXT, top_cast_json TEXT, keywords_json TEXT, genres_json TEXT,
  tmdb_vote_average REAL, tmdb_vote_count INTEGER, reviews_json TEXT, imdb_id TEXT, overview TEXT,
  source TEXT NOT NULL DEFAULT 'tmdb_api', fetched_at TEXT NOT NULL, expires_at TEXT,
  PRIMARY KEY (tmdb_id, media_type));
CREATE TABLE IF NOT EXISTS title_metadata_failures(
  tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL, error TEXT, failed_at TEXT NOT NULL, retries INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (tmdb_id, media_type));

-- [SPEC] Optional theater listings (also emitted as JSON by theaters/local_showtimes.py)
CREATE TABLE IF NOT EXISTS in_theaters_listings(
  id INTEGER PRIMARY KEY, tmdb_id INTEGER, title TEXT NOT NULL, theater_label TEXT NOT NULL, source_url TEXT,
  listed_date TEXT, checked_at TEXT NOT NULL);

-- [SPEC] Operations: audit receipts (never plaintext credentials; connector grants by reference only)
CREATE TABLE IF NOT EXISTS audit_receipts(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL DEFAULT (datetime('now')), actor TEXT NOT NULL, action TEXT NOT NULL,
  target TEXT, approval_ref TEXT, details_json TEXT);
