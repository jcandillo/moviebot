"""[STAGED genres-v1/in_theaters-v1] Shared card identity + extension validation for publish-picks.py (and mirrored inline in https_server.py).
Card ids: "new" | "classic" (legacy v1 slots, unchanged) | "genre:<genre_id>:<new|classic>".
picks.json stays schema_version 1; extensions are additive top-level fields that v1 consumers ignore:
  extensions: ["genres-v1", "in_theaters-v1"]
  genres: [{genre_id, label, tmdb_genre_ids:[int], new: CARD|null, classic: CARD|null}]   (fixed order, all 6)
  in_theaters: {status, checked_at, note, items:[THEATER_ITEM]}   (never carries streaming offers)"""
import re
GENRES = [("comedy", "Comedy", (35,)), ("action_adventure", "Action & Adventure", (28, 12)), ("scifi", "Sci-Fi", (878,)),
          ("drama", "Drama", (18,)), ("thriller", "Thriller", (53,)), ("family", "Family", (10751,))]
GENRE_IDS = tuple(g[0] for g in GENRES); TMDB_IDS = {g[0]: set(g[2]) for g in GENRES}; LABELS = {g[0]: g[1] for g in GENRES}
TMDB_NAME = {35: "Comedy", 28: "Action", 12: "Adventure", 878: "Science Fiction", 18: "Drama", 53: "Thriller", 10751: "Family"}
CARD_RE = re.compile(r"genre:([a-z_]+):(new|classic)")
HOME_STATUSES = ("verified_offers", "unverified")   # main view may show verified home offers or an honest 'unverified'; never no-home/theaters-only
THEATER_STATUSES = ("in_theaters_listed", "special_screening_listed", "coming_soon", "unverified")

def parse(cid):
    if cid in ("new", "classic"): return ("legacy", None, cid)
    m = CARD_RE.fullmatch(cid) if isinstance(cid, str) else None
    return ("genre", m.group(1), m.group(2)) if m and m.group(1) in GENRE_IDS else None

def resolve(picks, cid):
    p = parse(cid)
    if not p: return None
    if p[0] == "legacy": return (picks.get("slots") or {}).get(cid)
    for g in picks.get("genres") or []:
        if g.get("genre_id") == p[1]:
            c = g.get(p[2]); return c if isinstance(c, dict) and c.get("slot_id") == cid else None
    return None

def all_cards(picks):
    for sid, s in (picks.get("slots") or {}).items(): yield sid, s
    for g in picks.get("genres") or []:
        for era in ("new", "classic"):
            if isinstance(g.get(era), dict): yield g[era]["slot_id"], g[era]

def in_genre(genre_id, tmdb_genre_ids): return bool(TMDB_IDS[genre_id] & set(int(x) for x in tmdb_genre_ids or []))

def era_ok(era, year, classic_max): return (year <= classic_max) if era == "classic" else (year > classic_max)

def validate_card(c, gid, era, classic_max):
    cid = f"genre:{gid}:{era}"
    for k in ("slot_id", "title", "tmdb_id", "media_type", "year", "poster", "why", "tmdb_genre_ids"):
        if c.get(k) in ("", None): raise ValueError(f"{cid}_missing_{k}")
    if c["slot_id"] != cid: raise ValueError(f"{cid}_slot_id_mismatch")
    if c["media_type"] != "movie": raise ValueError(f"{cid}_media_type")
    if not str(c["poster"]).startswith("data:image"): raise ValueError(f"{cid}_poster_must_be_datauri")
    if not era_ok(era, int(c["year"]), classic_max): raise ValueError(f"{cid}_era_boundary")
    if not in_genre(gid, c["tmdb_genre_ids"]): raise ValueError(f"{cid}_not_in_genre")
    d = c.get("description")   # no-hold: may be null only with an explicit alert naming the field
    if d is None:
        if "description" not in (c.get("metadata_alerts") or []): raise ValueError(f"{cid}_description_missing_without_alert")
    elif not isinstance(d, str) or not d.strip() or len(d) > 280: raise ValueError(f"{cid}_description_invalid")
    w = c.get("watch_availability")
    if not isinstance(w, dict) or w.get("status") not in HOME_STATUSES: raise ValueError(f"{cid}_watch_not_home_eligible")
    if w.get("theaters_only"): raise ValueError(f"{cid}_theaters_only_in_main")
    if not w.get("source") or not w.get("checked_at"): raise ValueError(f"{cid}_watch_provenance")

def validate_ext(p, classic_max):
    ext = p.get("extensions") or []
    if not isinstance(ext, list) or any(e not in ("genres-v1", "in_theaters-v1") for e in ext): raise ValueError("bad_extensions")
    if "genres" in p:
        if "genres-v1" not in ext: raise ValueError("genres_without_extension")
        G = p["genres"]
        if not isinstance(G, list) or [g.get("genre_id") for g in G] != list(GENRE_IDS): raise ValueError("genres_order_or_set")
        seen = {}
        for g in G:
            if g.get("label") != LABELS[g["genre_id"]] or sorted(g.get("tmdb_genre_ids") or []) != sorted(TMDB_IDS[g["genre_id"]]): raise ValueError("genre_definition_" + g["genre_id"])
            for era in ("new", "classic"):
                c = g.get(era)
                if c is None: continue
                validate_card(c, g["genre_id"], era, classic_max)
                if c["tmdb_id"] in seen: raise ValueError(f"duplicate_genre_card_tmdb_{c['tmdb_id']}")
                seen[c["tmdb_id"]] = c["slot_id"]
    if "in_theaters" in p:
        if "in_theaters-v1" not in ext: raise ValueError("in_theaters_without_extension")
        T = p["in_theaters"]
        if not isinstance(T, dict) or not isinstance(T.get("items"), list) or not T.get("checked_at"): raise ValueError("in_theaters_shape")
        for it in T["items"]:
            if it.get("theater_status") not in THEATER_STATUSES: raise ValueError("theater_status")
            if any(k in it for k in ("watch_availability", "home_watch_availability")): raise ValueError("theater_item_carries_streaming")
            if not (it.get("theater_source") or {}).get("checked_at"): raise ValueError("theater_provenance")
            if not str(it.get("slot_id", "")).startswith("theaters:"): raise ValueError("theater_slot_id")
