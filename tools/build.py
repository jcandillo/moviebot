#!/usr/bin/env python3
from amend_descriptions import desc280
"""STAGING builder for the optional photo-frame Movies page (agent host only). Reads your own movie data (read-only), writes ONLY under staging-movies/.
Output: data/picks.staging.json = proposed schema v2: existing slots (verbatim from prod copy) + genres[] (New/Classic per genre, home-only)
+ in_theaters (separate top-level field). No Mac writes; no prod DB writes (lookups cached in data/staging.db, a copy)."""
import base64, datetime, json, os, re, sqlite3, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(ROOT, "pipeline"))
src = open(f"{FI}/feedback_apply.py").read(); exec(compile(src[:src.index("def regenerate(a):")], "feedback_apply_funcs", "exec"))  # fetch_public, meta_get, describe, policy
import where_to_watch as WTW
YEAR = datetime.date.today().year; CUT = YEAR - 25
GENRES = [("comedy", "Comedy", {"Comedy"}), ("action_adventure", "Action & Adventure", {"Action", "Adventure"}), ("scifi", "Sci-Fi", {"Science Fiction"}),
          ("drama", "Drama", {"Drama"}), ("thriller", "Thriller", {"Thriller"}), ("family", "Family", {"Family"})]
GID = {28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror",
       10402: "Music", 9648: "Mystery", 10749: "Romance", 878: "Science Fiction", 10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western"}
# curated classic seeds (real TMDB ids; identity re-read from TMDB public page) to cover thin genres
EXTRA_CLASSIC = [601, 771, 862, 10386, 9598, 11528, 8587, 812, 10020, 238, 489, 207, 568, 235, 13, 9377, 2108, 8467, 274, 807, 629, 348, 1891, 11, 85, 1366, 10681]
DB = os.environ.get("STAGING_DB", f"{ST}/data/staging.db"); raw = sqlite3.connect(DB); meta_table(raw)
tv = sqlite3.connect("file:" + os.environ.get("MOVIEBOT_DB", "./moviebot.db") + "?mode=ro", uri=True)
def log(*a): print(*a, file=sys.stderr, flush=True)
# ---- exclusions: history, explicit feedback, onboarding seeds, policy
hist = {r[0].strip().lower() for r in tv.execute("SELECT raw_title FROM viewing_events WHERE raw_title IS NOT NULL")}
taste = {r[0]: r[1] for r in tv.execute("SELECT tmdb_id, signal FROM taste_latest")}
excl_ids = set(taste) | set(SEED_NOPE) | set(HARD_EXCLUDE) | set(json.loads(os.environ.get("FRAME_ACTED_IDS", "[]")))  # Frame votes/actions (any card)
try:
    from policy import SEED_FAMILIAR; excl_ids |= set(SEED_FAMILIAR)
except Exception: pass
# ---- candidates
C = {}
def add(m, src_label):
    if not m or not m.get("tmdb_id") or not m.get("year") or not m.get("overview") or not m.get("poster_url"): return
    C.setdefault(m["tmdb_id"], dict(m, meta_source=src_label))
for x in json.load(open("./prototype/new_releases_candidates.json")):
    d = x[1] if isinstance(x, list) else x
    if (x[0] if isinstance(x, list) else "movie") != "movie" or d.get("status") not in (None, "Released"): continue
    crew = (d.get("credits") or {}).get("crew", []); cast = (d.get("credits") or {}).get("cast", [])
    y = int((d.get("release_date") or "0")[:4] or 0)
    add(dict(tmdb_id=d["id"], title=d["title"], year=y, genres=[g["name"] for g in d.get("genres", [])], directors=[c["name"] for c in crew if c.get("job") == "Director"],
             cast=[c["name"] for c in cast[:5]], tmdb_user_score_pct=round(d["vote_average"] * 10) if d.get("vote_average") and d.get("vote_count", 1) else None,
             poster_url="https://image.tmdb.org/t/p/w342" + d["poster_path"] if d.get("poster_path") else None, overview=d.get("overview"), release=d.get("release_date"),
             source=f"https://www.themoviedb.org/movie/{d['id']}"), "prototype/new_releases_candidates.json (cached TMDB detail)")
ids = [r[0] for r in raw.execute("SELECT DISTINCT tmdb_id FROM tmdb_public_meta WHERE media_type='movie'")] + CLASSIC_SEEDS + EXTRA_CLASSIC
for t in dict.fromkeys(ids):
    if t in C: continue
    m = meta_get(raw, t, True)
    if m and m.get("status") in (None, "Released"): add(m, "TMDB public page " + m["source"] + " fetched " + m.get("fetched_at", ""))
log("candidates", len(C))
ups = [C.get(t) or meta_get(raw, t, True) for t, s in taste.items() if s == "up"]; ups = [u for u in ups if u]
def score(m):
    s = (m.get("tmdb_user_score_pct") or 50) / 100 + 0.5 * len(set(m["genres"]) & set(QUESTIONNAIRE_GENRES)); why = None
    for u in ups:
        sg = set(m["genres"]) & set(u["genres"]); sd = set(m.get("directors", [])) & set(u.get("directors", [])); sc = set(m.get("cast", [])) & set(u.get("cast", []))
        s += 2 * len(sg) / max(1, len(set(m["genres"]) | set(u["genres"]))) + 2 * len(sd) + len(sc)
        if (sd or sc) and not why: why = f"Shares {', '.join(sorted(sd | sc))} with {u['title']} (thumbs up)."
        elif sg and not why: why = f"Shares {', '.join(sorted(sg))} with {u['title']} (thumbs up)."
    if not why and set(m["genres"]) & set(QUESTIONNAIRE_GENRES): why = f"Matches your {', '.join(sorted(set(m['genres']) & set(QUESTIONNAIRE_GENRES)))} picks from onboarding."
    return s, why or "Well-rated pick in this genre and era."
def eligible(m): return m["tmdb_id"] not in excl_ids and m["title"].strip().lower() not in hist
if os.environ.get("POOL_OUT"):   # genre pool regenerate (no lookups, no posters): ranked eligible candidates per genre/era
    NAME2ID = {v: k for k, v in GID.items()}; pools = {}
    for gid, label, gset in GENRES:
        for era in ("new", "classic"):
            pool = [m for m in C.values() if gset & set(m["genres"]) and eligible(m) and ((m["year"] <= CUT) if era == "classic" else (m["year"] > CUT))]
            pool.sort(key=lambda m: (-score(m)[0], m["tmdb_id"]))
            pools[f"genre:{gid}:{era}"] = [dict(title=m["title"], tmdb_id=m["tmdb_id"], year=m["year"], tmdb_genre_ids=[NAME2ID[n] for n in m["genres"] if n in NAME2ID],
                genres=m["genres"], overview=m["overview"], poster_url=m["poster_url"], directors=m.get("directors", []), cast=m.get("cast", []),
                rating=m.get("tmdb_user_score_pct"), score=round(score(m)[0], 4), why=score(m)[1], meta_source=m["meta_source"]) for m in pool[:30]]
    json.dump(dict(generated_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), moviebot_db=os.environ.get("MOVIEBOT_DB", "./moviebot.db"),
                   exclusions=dict(history=len(hist), taste=len(taste), ids=len(excl_ids)), pools=pools), open(os.environ["POOL_OUT"], "w"), indent=1)
    log("pool written", os.environ["POOL_OUT"], {k: len(v) for k, v in pools.items()}); sys.exit(0)
# ---- where to watch (fresh public JustWatch US, cached in STAGING db only)
WCACHE = {}
def wtw(m):
    if m["tmdb_id"] in WCACHE: return WCACHE[m["tmdb_id"]]
    r = WTW.check(m["tmdb_id"], m["title"], m["year"], m.get("directors") or [], None, db=DB); WCACHE[m["tmdb_id"]] = r; return r
def poster_uri(url):
    b = subprocess.run(["curl", "-sL", "--max-time", "20", url], capture_output=True).stdout
    return "data:image/jpeg;base64," + base64.b64encode(b).decode() if b[:3] == b"\xff\xd8\xff" else None
def rating_text(m): return f"TMDB {m['tmdb_user_score_pct']}%" if m.get("tmdb_user_score_pct") else "TMDB rating unavailable"
def card(m, slot_id, why, r):
    return dict(slot_id=slot_id, title=m["title"], tmdb_id=m["tmdb_id"], media_type="movie", year=m["year"], poster=poster_uri(m["poster_url"]), why=why,
                description=desc280(m["overview"]), description_source="TMDB overview via " + m["meta_source"],
                rating=m.get("tmdb_user_score_pct"), meta=f"{rating_text(m)} · {m['year']}",
                credits="; ".join(filter(None, [", ".join(m.get("directors", [])[:2]), ", ".join(m.get("cast", [])[:2])])) or None,
                genres=m["genres"], watch_availability=dict(WTW.to_watch_json(r), source=WTW.watch_source(r["record_id"], r["checked_at"])), source_event_id=None)
used, out_genres, theaters, checks = set(), [], {}, 0
for gid, label, gset in GENRES:
    entry = dict(genre_id=gid, label=label, tmdb_genres=sorted(gset))
    for era in ("new", "classic"):
        pool = [m for m in C.values() if gset & set(m["genres"]) and eligible(m) and m["tmdb_id"] not in used and ((m["year"] <= CUT) if era == "classic" else (m["year"] > CUT))]
        pool.sort(key=lambda m: (-score(m)[0], m["tmdb_id"])); pick = None; skipped = []
        for m in pool[:14]:
            r = wtw(m); checks += 1
            if r.get("cinema") and r["status"] != "identity_mismatch": theaters[m["tmdb_id"]] = (m, r)
            if r["status"] == "verified_offers" and WTW.to_watch_json(r)["home_offers"]: pick = (m, r); break
            skipped.append(dict(title=m["title"], year=m["year"], reason=r["status"] + ("+theaters" if r.get("cinema") else "")))
        if pick:
            used.add(pick[0]["tmdb_id"]); entry[era] = card(pick[0], f"genre:{gid}:{era}", score(pick[0])[1], pick[1])
        else: entry[era] = None
        entry[f"{era}_skipped"] = skipped
        log(label, era, entry[era] and entry[era]["title"], "skipped", len(skipped))
    out_genres.append(entry)
# theaters: also check top recent new releases not yet checked
recent = sorted([m for m in C.values() if m["year"] >= YEAR - 1 and eligible(m) and m["tmdb_id"] not in WCACHE], key=lambda m: m.get("release") or "", reverse=True)[:12]
for m in recent:
    r = wtw(m); checks += 1
    if r.get("cinema") and r["status"] != "identity_mismatch": theaters[m["tmdb_id"]] = (m, r)
th_items = []
for t, (m, r) in theaters.items():
    th_items.append(dict(slot_id=f"theaters:{t}", title=m["title"], tmdb_id=t, media_type="movie", year=m["year"], poster=poster_uri(m["poster_url"]), description=desc280(m["overview"]),
                         description_source="TMDB overview via " + m["meta_source"], rating=m.get("tmdb_user_score_pct"), meta=f"{rating_text(m)} · {m['year']}",
                         theater_status="in_theaters_listed", theater_source=dict(source="justwatch_us_public", record_id=r["record_id"], checked_at=r["checked_at"], url=r.get("source_url"))))
prod = json.load(open(f"{ST}/source/picks.rev12.json"))
doc = dict(schema_version=1, extensions=["genres-v1", "in_theaters-v1"], revision=prod["revision"], updated_at=prod["updated_at"],
           staging_built_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), slots=prod["slots"], genres=out_genres,
           in_theaters=dict(status="checked" if checks else "unverified", note="Separate from streaming; listed = JustWatch US public page shows theater tickets. Showtimes not checked.",
                            checked_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), items=th_items),
           provenance=dict(candidates=len(C), wtw_checks=checks, exclusions=dict(history=len(hist), taste=len(taste)), staging_db=DB))
json.dump(doc, open(f"{ST}/data/picks.staging.json", "w"), indent=1); log("done", checks, "checks;", len(th_items), "theater items")
