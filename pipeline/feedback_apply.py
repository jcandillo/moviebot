#!/usr/bin/env python3
"""MovieBot feedback apply + regenerate (standalone, agent host only).
  run    [--moviebot-db] [--rawdb] [--recs] [--snapshots DIR] [--fetch]   # apply -> regenerate (one entrypoint)
  apply  ...        # thumbs -> taste_signals; Watched -> one suggestion_feedback viewing_event; Next -> nothing
  regenerate ...    # rescore New/Classic movie pools with accepted history + raw up/down; writes recommendations.json rows
Never: Mac writes, publish, secrets, numeric human ratings, history from thumbs/Next, button time as viewing time."""
import argparse, datetime, glob, hashlib, html, json, os, re, shutil, sqlite3, subprocess, uuid
HERE = "./feedback-intake"
def now(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
def sha(o): return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
FB_SERVICE = ("display_suggestion_feedback", "Suggestion feedback (Movie Night display)", 0,
              "Not a streaming connector. Rows here come only from explicit Watched presses on titles the product displayed (origin=suggestion_feedback).")
MIGRATION = """
CREATE TABLE IF NOT EXISTS taste_signals(
 event_id TEXT PRIMARY KEY, tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL CHECK(media_type IN('movie','tv')),
 signal TEXT NOT NULL CHECK(signal IN('up','down')),          -- raw categorical; never mapped to love it/nope or a number
 origin TEXT NOT NULL, title TEXT, slot_id TEXT, displayed_revision INTEGER, event_timestamp TEXT NOT NULL,
 supersedes TEXT, payload_sha256 TEXT NOT NULL, raw_json TEXT NOT NULL, applied_at TEXT NOT NULL, apply_receipt_id TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS taste_latest AS
 SELECT t.* FROM taste_signals t WHERE NOT EXISTS (SELECT 1 FROM taste_signals u WHERE u.tmdb_id=t.tmdb_id AND u.media_type=t.media_type
   AND (u.event_timestamp > t.event_timestamp OR (u.event_timestamp = t.event_timestamp AND u.event_id > t.event_id)));
CREATE TABLE IF NOT EXISTS feedback_history_receipts(
 action_event_id TEXT PRIMARY KEY, viewing_event_id INTEGER NOT NULL REFERENCES viewing_events(id), title_match_id INTEGER,
 tmdb_id INTEGER NOT NULL, media_type TEXT NOT NULL, evidence_json TEXT NOT NULL, applied_at TEXT NOT NULL, apply_receipt_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback_apply_receipts(receipt_id TEXT PRIMARY KEY, at TEXT, kind TEXT, counts_json TEXT, backup_path TEXT, inputs_json TEXT);
"""
def backup(tvdb):
    os.makedirs(f"{BK}", exist_ok=True)
    dst = f"{BK}/{os.path.basename(tvdb)}.{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.bak"
    s = sqlite3.connect(tvdb); d = sqlite3.connect(dst); s.backup(d); d.close(); s.close(); return dst

BK = os.environ.get("MOVIEBOT_BACKUP_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
def picks_evidence(snapdir, slot, rev, tmdb, title):
    """Product-displayed proof: a copied picks snapshot at the event's displayed_revision showing this film in that slot."""
    for p in sorted(glob.glob(f"{snapdir}/picks-*.json")):
        try: P = json.load(open(p))
        except Exception: continue
        s = (P.get("slots") or {}).get(slot) or {}
        if P.get("revision") == rev and s.get("tmdb_id") == tmdb and (s.get("title") or "").lower() == (title or "").lower() and s.get("media_type") == "movie":
            return dict(picks_snapshot=os.path.basename(p), picks_sha256=hashlib.sha256(open(p, "rb").read()).hexdigest(), revision=rev, slot=slot,
                        displayed_title=s["title"], displayed_tmdb_id=tmdb, displayed_why=s.get("why"), displayed_source_event_id=s.get("source_event_id"))
    return None

def lease_guard(a):
    c = lease.conn(a.rawdb); c.execute("BEGIN IMMEDIATE")
    try: lease.guard(c, a.lease_token)
    except lease.LeaseError as e: c.execute("ROLLBACK"); print(json.dumps(dict(ok=False, error=e.msg))); raise SystemExit(e.code)
    c.execute("COMMIT")
def apply(a):
    lease_guard(a)
    raw = sqlite3.connect(a.rawdb); tv = sqlite3.connect(a.tvdb); tv.execute("PRAGMA foreign_keys=ON")
    bk = backup(a.tvdb); rid = str(uuid.uuid4())
    n = dict(taste_new=0, taste_duplicate=0, taste_conflict=0, taste_skipped=0, watched_applied=0, watched_already=0, watched_marked_recovered=0, watched_blocked=[], next_neutral=0)
    with tv:
        tv.executescript(MIGRATION)
        tv.execute("INSERT OR IGNORE INTO services(code,name,has_history_export,notes) VALUES(?,?,?,?)", FB_SERVICE)
        svc = tv.execute("SELECT id FROM services WHERE code=?", (FB_SERVICE[0],)).fetchone()[0]
        for eid, rj, h in raw.execute("SELECT event_id, raw_json, payload_sha256 FROM raw_votes ORDER BY event_timestamp"):
            o = json.loads(rj)
            if o.get("test") is True or o.get("vote") not in ("up", "down") or not isinstance(o.get("tmdb_id"), int) or o.get("media_type") not in ("movie", "tv"):
                n["taste_skipped"] += 1; continue
            ex = tv.execute("SELECT payload_sha256 FROM taste_signals WHERE event_id=?", (eid,)).fetchone()
            if ex: n["taste_duplicate" if ex[0] == h else "taste_conflict"] += 1; continue
            tv.execute("INSERT INTO taste_signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (eid, o["tmdb_id"], o["media_type"], o["vote"], o.get("origin") or "unknown", o.get("title"),
                       o.get("slot_id"), o.get("displayed_revision"), o.get("timestamp") or o.get("ts_utc"), o.get("supersedes"), h, rj, now(), rid))
            n["taste_new"] += 1
        n["next_neutral"] = raw.execute("SELECT count(*) FROM raw_actions WHERE action='next'").fetchone()[0]
        todo = raw.execute("SELECT event_id,raw_json,slot_id,displayed_revision,title,tmdb_id,media_type,watch_history_status FROM raw_actions WHERE action='watched'").fetchall()
        mark = []
        for eid, rj, slot, rev, title, tmdb, mt, st in todo:
            if tv.execute("SELECT 1 FROM feedback_history_receipts WHERE action_event_id=?", (eid,)).fetchone():
                if st != "applied": mark.append(eid); n["watched_marked_recovered"] += 1
                else: n["watched_already"] += 1
                continue
            o = json.loads(rj)
            if o.get("signal") != "viewed_explicit" or o.get("test") is True or mt != "movie" or not isinstance(tmdb, int):
                n["watched_blocked"].append(dict(event_id=eid, reason="contract")); continue
            ev = picks_evidence(a.snapshots, slot, rev, tmdb, title)
            if not ev: n["watched_blocked"].append(dict(event_id=eid, reason="no picks snapshot proving the product displayed this film")); continue
            url = f"movie-night-display:action:{eid}"
            cur = tv.execute("INSERT INTO viewing_events(service_id,connector_id,raw_title,show_name,season,episode,watched_date,date_precision,channel,url,source) VALUES(?,NULL,?,NULL,NULL,NULL,NULL,'unknown',NULL,?,'suggestion_feedback')",
                             (svc, title, url))
            vid = cur.lastrowid
            tv.execute("INSERT OR IGNORE INTO title_matches(item_kind,service_id,match_key,tmdb_id,media_type,confidence,status,method,matched_at) VALUES('viewing',?,?,?,?,1.0,'matched','suggestion_feedback_picks_verified',?)",
                       (svc, title, tmdb, mt, now()))
            tm = tv.execute("SELECT id FROM title_matches WHERE service_id=? AND item_kind='viewing' AND match_key=?", (svc, title)).fetchone()[0]
            evid = dict(ev, action_event_id=eid, action_timestamp_is_not_viewing_time=o.get("timestamp"), viewing_time="unknown", idempotency_key=o.get("idempotency_key"))
            tv.execute("INSERT INTO feedback_history_receipts VALUES(?,?,?,?,?,?,?,?)", (eid, vid, tm, tmdb, mt, json.dumps(evid), now(), rid))
            mark.append(eid); n["watched_applied"] += 1
        tv.execute("INSERT INTO feedback_apply_receipts VALUES(?,?,?,?,?,?)", (rid, now(), "apply", json.dumps(n), bk, json.dumps(dict(rawdb=a.rawdb, snapshots=a.snapshots))))
    with raw:  # after tv commit; a crash here is recovered on rerun via feedback_history_receipts
        for eid in mark: raw.execute("UPDATE raw_actions SET watch_history_status='applied' WHERE event_id=?", (eid,))
    print(json.dumps(dict(apply_receipt_id=rid, backup=bk, **n)))

# ---------- public TMDB page metadata (no API key) ----------
def fetch_public(tmdb_id):
    r = subprocess.run(["curl", "-sL", "--max-time", "20", "-A", "Mozilla/5.0", f"https://www.themoviedb.org/movie/{tmdb_id}?language=en-US"], capture_output=True)
    s = r.stdout.decode("utf-8", "ignore")
    g = lambda p: (lambda m: html.unescape(m.group(1)).strip() if m else None)(re.search(p, s, re.S))
    title = g(r'<meta property="og:title" content="([^"]+)"')
    if not title: return None
    genres = [html.unescape(x) for x in re.findall(r'<a href="/genre/\d+[^"]*">([^<]+)</a>', g(r'<span class="genres">(.*?)</span>') or "")]
    dirs = [html.unescape(nm) for nm, role in re.findall(r'<li class="profile">\s*<p><a href="/person/[^"]+">([^<]+)</a></p>\s*<p class="character">([^<]+)</p>', s) if "Director" in role]
    cast = [html.unescape(x) for x in re.findall(r'<li class="card"[^>]*>.*?<p><a href="/person/[^"]+">([^<]+)</a></p>', s, re.S)[:5]]
    rt = g(r'<span class="runtime">\s*([^<]+)') or ""; mins = sum(int(v) * (60 if u == "h" else 1) for v, u in re.findall(r"(\d+)([hm])", rt)) or None
    rel = g(r'class="release">\s*([^<]+)'); yr = g(r'<span class="tag release_date">\(?(\d{4})') or (re.search(r"(\d{4})", rel or "") or [None, None])[1]
    img = g(r'<meta property="og:image" content="([^"]+)"')
    ov = g(r'<div class="overview"[^>]*>\s*<p>(.*?)</p>') or g(r'<meta property="og:description" content="([^"]*)"')
    return dict(tmdb_id=tmdb_id, title=title, year=int(yr) if yr else None, genres=genres, directors=dirs, cast=cast, runtime_min=mins,
                status=g(r'Status</bdi></strong>\s*([^<]+)'), release=rel, tmdb_user_score_pct=int(float(g(r'data-percent="([\d.]+)"') or 0)) or None,
                poster_url=("https://image.tmdb.org/t/p/w342/" + img.rsplit("/", 1)[1]) if img else None, source=f"https://www.themoviedb.org/movie/{tmdb_id}", fetched_at=now(), overview=re.sub(r"<[^>]+>", "", ov or "").strip() or None)

CLASSIC_SEEDS = [679, 782, 63, 105, 562, 861, 218, 5548, 106, 18, 926, 607, 2666, 563, 1637, 754, 949, 9802, 87, 85, 620, 813]
# Onboarding answers (chosen genres + seed ratings) come from config/local.json via policy.py; never hard-code them here.
import sys; sys.path.insert(0, HERE)
from policy import QUESTIONNAIRE_GENRES, SEED_NOPE, HARD_EXCLUDE
import lease
def meta_table(raw):
    raw.execute("CREATE TABLE IF NOT EXISTS tmdb_public_meta(tmdb_id INTEGER, media_type TEXT, payload_json TEXT, payload_sha256 TEXT, fetched_at TEXT, PRIMARY KEY(tmdb_id,media_type,payload_sha256))")
def meta_get(raw, tid, fetch):
    r = raw.execute("SELECT payload_json FROM tmdb_public_meta WHERE tmdb_id=? AND media_type='movie' ORDER BY fetched_at DESC LIMIT 1", (tid,)).fetchone()
    if r and ("overview" in json.loads(r[0]) or not fetch): return json.loads(r[0])  # refetch older cache rows that lack overview
    if not fetch: return None
    m = fetch_public(tid)
    if m:
        with raw: raw.execute("INSERT OR IGNORE INTO tmdb_public_meta VALUES(?,?,?,?,?)", (tid, "movie", json.dumps(m), sha(m), m["fetched_at"]))
    return m

def describe(overview):
    """Spoiler-free short description = first 1-2 sentences of the TMDB overview (verbatim, no generated plot)."""
    o = re.sub(r"\s+", " ", overview or "").strip()
    if not o: return None
    sents = re.split(r"(?<=[.!?])\s+", o); d = sents[0]
    if len(sents) > 1 and len(d) + 1 + len(sents[1]) <= 220: d += " " + sents[1]
    return d if len(d) <= 240 else d[:237].rsplit(" ", 1)[0] + "…"
def regenerate(a):
    lease_guard(a)
    raw = sqlite3.connect(a.rawdb); tv = sqlite3.connect(a.tvdb); meta_table(raw); year = datetime.date.today().year; cutoff = year - 25; today = datetime.date.today().isoformat()
    tv.executescript(MIGRATION)
    seen = {r[0] for r in tv.execute("SELECT DISTINCT tmdb_id FROM title_matches WHERE status IN('matched','needs_review') AND media_type='movie' AND item_kind='viewing' AND tmdb_id IS NOT NULL")}
    taste = tv.execute("SELECT tmdb_id, signal, title, event_id FROM taste_latest WHERE media_type='movie'").fetchall()
    ups = [t for t in taste if t[1] == "up"]; downs = [t for t in taste if t[1] == "down"]
    prof = {}
    for tid, sig, title, eid in taste:
        m = meta_get(raw, tid, a.fetch)
        if m: prof[tid] = dict(m, signal=sig, event_id=eid)
    # candidate pools
    cands = []
    for mt, x in json.load(open(a.newcands)):
        if mt != "movie" or not x.get("release_date") or x["release_date"] > today or (x.get("runtime") or 0) < 60 or x.get("status") != "Released" or not x.get("poster_path"): continue
        y = int(x["release_date"][:4])
        if y <= cutoff: continue
        crew = (x.get("credits") or {}); cands.append(dict(slot="new", tmdb_id=x["id"], title=x["title"], year=y, genres=[g["name"] for g in x.get("genres", [])],
              directors=[c["name"] for c in crew.get("crew", []) if c.get("job") == "Director"], cast=[c["name"] for c in crew.get("cast", [])[:5]], runtime_min=x.get("runtime"),
              tmdb_user_score_pct=round((x.get("vote_average") or 0) * 10) or None, poster_url="https://image.tmdb.org/t/p/w342" + x["poster_path"], release=x["release_date"],
              source="prototype/new_releases_candidates.json (cached TMDB detail)", overview=x.get("overview"), overview_source="TMDB overview via prototype/new_releases_candidates.json"))
    if a.fresh_ids:  # freshly fetched public TMDB pages (now playing / popular); fresh metadata wins over cached
        fresh = []
        for tid in [int(x) for x in open(a.fresh_ids).read().split() if x.strip().isdigit()]:
            m = meta_get(raw, tid, a.fetch)
            if not m or not m.get("year") or m["year"] <= cutoff or m.get("status") != "Released" or (m.get("runtime_min") or 0) < 60 or not m.get("poster_url"): continue
            fresh.append(dict(m, slot="new", source=m["source"] + " (fresh public page)", overview_source="TMDB overview via " + m["source"]))
        ids = {f["tmdb_id"] for f in fresh}; cands = [c for c in cands if c["tmdb_id"] not in ids] + fresh
    for tid in CLASSIC_SEEDS:
        m = meta_get(raw, tid, a.fetch)
        if m and m.get("year") and m["year"] <= cutoff and m.get("poster_url") and (m.get("runtime_min") or 0) >= 60 and m.get("status") == "Released":
            cands.append(dict(m, slot="classic", overview_source="TMDB overview via " + m["source"]))
    P = json.load(open(a.picks)) if a.picks else {"slots": {}}
    disp = {s.get("tmdb_id") for s in P.get("slots", {}).values()}
    published = {r[0] for r in raw.execute("SELECT tmdb_id FROM verified_publish_receipts")}
    acted = {r[0] for r in raw.execute("SELECT tmdb_id FROM raw_actions WHERE tmdb_id IS NOT NULL")}
    down_ids = {t[0] for t in downs}; up_ids = {t[0] for t in ups}
    out = {"new": [], "classic": []}; excluded = []
    for c in cands:
        why_ex = [k for k, s_ in (("seen/accepted history", seen), ("thumbs down", down_ids), ("thumbs up already (familiar)", up_ids), ("displayed now", disp), ("already published", published), ("acted on", acted), ("onboarding nope/rated seed (hard exclude)", HARD_EXCLUDE)) if c["tmdb_id"] in s_]
        if why_ex: excluded.append(dict(title=c["title"], tmdb_id=c["tmdb_id"], slot=c["slot"], reasons=why_ex)); continue
        score = (c.get("tmdb_user_score_pct") or 50) / 100.0; ev = []
        qg = sorted(set(c["genres"]) & QUESTIONNAIRE_GENRES)
        if qg: score += 0.5 * len(qg); ev.append(f"matches your chosen genres {', '.join(qg)} (onboarding)")
        for tid, p in prof.items():
            sg = sorted(set(c["genres"]) & set(p["genres"])); sd = sorted(set(c["directors"]) & set(p["directors"])); sc = sorted(set(c["cast"]) & set(p["cast"]))
            if not (sg or sd or sc): continue
            if p["signal"] == "up":
                gj = 2.0 * len(sg) / max(1, len(set(c["genres"]) | set(p["genres"])))  # Jaccard: no bonus for piling on genres
                score += gj + len(sd) * 2.0 + len(sc) * 1.0; ev.insert(0, f"shares {', '.join(sg + sd + sc)} with {p['title']} (thumbs up)")
            else:  # a single down is specific: penalise same director/cast fully, shared genres lightly
                w = len(sd) * 2.0 + len(sc) * 1.0 + len(sg) * 0.25
                score -= w; ev.append(f"shares {', '.join(sg + sd + sc)} with {p['title']} (thumbs down, -{w:g})")
        out[c["slot"]].append(dict(c, score=round(score, 3), evidence=ev or ["no overlap with explicit feedback; ranked by TMDB score only"],
              why=(ev[0][0].upper() + ev[0][1:] + ".") if ev and "thumbs down" not in ev[0] else "Well-rated pick in this slot's era.", services="unknown (not re-verified)"))
    held = []   # owner rule: no TMDB overview -> candidate held (not published), run continues
    for k in out:
        held += [dict(slot=k, tmdb_id=d["tmdb_id"], title=d["title"], reason="missing_tmdb_overview (kept, publish proceeds with alert)") for d in out[k] if not describe(d.get("overview"))]
    for k in out: out[k].sort(key=lambda d: (-d["score"], d["tmdb_id"]))
    R = json.load(open(a.recs)); os.makedirs(f"{BK}", exist_ok=True)
    bk = f"{BK}/recommendations.json.{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.bak"; shutil.copy(a.recs, bk)
    def card(d): return dict(title=d["title"], why=d["why"], description=describe(d.get("overview")), description_source=d.get("overview_source") if d.get("overview") else None, detail=(d.get("overview") or "")[:160] or None, cast=", ".join(d["cast"][:3]), director=", ".join(d["directors"]),
                             rating=(d.get("tmdb_user_score_pct") or 0) / 10 or None, year=d["year"], services=[], media_type="movie", tmdb_id=d["tmdb_id"], poster=d["poster_url"],
                             evidence=d["evidence"], score=d["score"], availability="unknown (not re-verified)", source=d["source"])
    rows = [r for r in R["rows"] if r["key"] not in ("movie_night_new_pool", "movie_night_classic_pool")]
    rows += [dict(key="movie_night_new_pool", label="Movie Night New pool (taste-ranked)", items=[card(d) for d in out["new"][:15]]),
             dict(key="movie_night_classic_pool", label="Movie Night Classic pool (taste-ranked)", items=[card(d) for d in out["classic"][:15]])]
    R["rows"] = rows; R["taste_applied"] = dict(at=now(), policy="raw categorical: +0.5 per onboarding-chosen genre (unchosen genres neutral); per thumbs-up film +2 x genre Jaccard overlap, +2 shared director, +1 shared top-5 cast; per thumbs-down film -2 shared director, -1 shared cast, -0.25 shared genre; base = TMDB user score/100; excluded: accepted history, thumbs-down, thumbs-up (already familiar), displayed, published, acted-on, onboarding seed titles. Weights are ranking heuristics, not human ratings.",
        signals=[dict(tmdb_id=t[0], signal=t[1], title=t[2], event_id=t[3]) for t in taste], excluded=excluded[:50], held_missing_description=held, backup=bk)
    tmp = a.recs + ".tmp"; json.dump(R, open(tmp, "w"), indent=1); os.replace(tmp, a.recs)
    # append verified pool versions for the planner (append-only)
    added = 0
    with raw:
        raw.execute("CREATE TABLE IF NOT EXISTS candidate_pool(id INTEGER PRIMARY KEY, slot_id TEXT NOT NULL, tmdb_id INTEGER NOT NULL, payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL, source TEXT NOT NULL, verified_at TEXT NOT NULL, loaded_at TEXT, UNIQUE(slot_id,tmdb_id,payload_sha256))")
        for k in out:
            for d in reversed(out[k][:15]):  # best loaded last => newest id => planner prefers by load order; keep order stable below
                pass
            for d in out[k][:15]:
                it = dict(slot_id=k, title=d["title"], tmdb_id=d["tmdb_id"], media_type="movie", year=d["year"], poster_url=d["poster_url"], why=d["why"],
                          credits="; ".join(filter(None, [", ".join(d["directors"]), ", ".join(d["cast"][:2])])), meta=f"TMDB {d.get('tmdb_user_score_pct')}% · {d['year']}",
                          score=d["score"], evidence=d["evidence"], source=d["source"], verified_at=d.get("fetched_at") or now(),
                          description=describe(d.get("overview")), description_source=d.get("overview_source") if d.get("overview") else None)
                cur = raw.execute("INSERT OR IGNORE INTO candidate_pool VALUES(NULL,?,?,?,?,?,?,?)", (k, d["tmdb_id"], sha(it), json.dumps(it), it["source"], it["verified_at"], now())); added += cur.rowcount
    print(json.dumps(dict(backup=bk, held_missing_description=len(held), signals=len(taste), new_top=[(d["title"], d["score"]) for d in out["new"][:5]], classic_top=[(d["title"], d["score"]) for d in out["classic"][:5]],
                          excluded=len(excluded), pool_rows_added=added)))

def run(a): apply(a); regenerate(a)
p = argparse.ArgumentParser(); s = p.add_subparsers(dest="cmd", required=True)
for name, f in (("apply", apply), ("regenerate", regenerate), ("run", run)):
    x = s.add_parser(name); x.set_defaults(f=f)
    x.add_argument("--moviebot-db", "--tvdb", dest="tvdb", default="./moviebot.db"); x.add_argument("--rawdb", default=f"{HERE}/raw_votes.db")
    x.add_argument("--recs", default="./recommendations.json"); x.add_argument("--newcands", default="./prototype/new_releases_candidates.json")
    x.add_argument("--snapshots", default=f"{HERE}/snapshots"); x.add_argument("--picks"); x.add_argument("--fetch", action="store_true"); x.add_argument("--lease-token"); x.add_argument("--fresh-ids")
a = p.parse_args(); a.f(a)
