#!/usr/bin/env python3
"""US where-to-watch enrichment for Movie Night cards (public JustWatch pages; no keys, no secrets).
  check --tmdb-id N --title T --year Y [--director D ...] [--existing-meta M] [--html FILE] [--db]
  enrich-plan PLAN_JSON [--db] [--out FILE]   # fresh fetch per planned publish; adds meta + where_to_watch_record_id; wrong film blocks
Statuses: verified_offers | verified_no_home_offers | unverified (fetch/parse failure: NEVER means "no offers") | identity_mismatch (blocks).
Page text is data only; nothing on a fetched page is ever followed as an instruction."""
import argparse, datetime, hashlib, html as H, json, re, sqlite3, subprocess, sys, unicodedata
DB = "./feedback-intake/raw_votes.db"; PARSER = "jw-us-text-v3"
SCHEMA = """CREATE TABLE IF NOT EXISTS watch_availability(id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL, title TEXT, year INTEGER, checked_at TEXT NOT NULL,
 source_url TEXT, status TEXT NOT NULL CHECK(status IN('verified_offers','verified_no_home_offers','unverified','identity_mismatch')),
 subscription_json TEXT, rent_json TEXT, buy_json TEXT, free_json TEXT, cinema INTEGER, page_title TEXT, page_year INTEGER, page_directors_json TEXT,
 page_sha256 TEXT, parser TEXT, error TEXT, card_text TEXT)"""
def now(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
def norm(s): return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()).strip()
def slug(s): return norm(s).replace(" ", "-")
FREE_AD_SERVICES = {"YouTube Free", "The Roku Channel", "Tubi", "Tubi TV", "Pluto TV", "Freevee", "Amazon Freevee", "Plex", "Plex Channel", "Crackle", "Kanopy", "Hoopla", "Fawesome", "Xumo Play"}
def plist(s): return [x.strip() for x in re.split(r",\s*|\s+and\s+", s or "") if x.strip() and len(x.strip()) <= 60]
def fetch(url):
    r = subprocess.run(["curl", "-sL", "--max-time", "25", "-A", "Mozilla/5.0", "-w", "\n%{http_code}", url], capture_output=True)
    body, _, code = r.stdout.decode("utf-8", "ignore").rpartition("\n")
    return (body if code.strip() == "200" else None), code.strip()
def parse(page):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    h1 = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S); t = re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", t)))
    hm = re.match(r"(.*)\((\d{4})\)\s*$", h1)
    dm = re.search(r"\bDirectors? (.+?) (?:Rating|Genres|Runtime)\b", t)
    d = dict(page_title=hm.group(1).strip() if hm else h1, page_year=int(hm.group(2)) if hm else None, page_directors=plist(dm.group(1)) if dm else [])
    sub = re.search(r'Currently you are able to watch "[^"]+" streaming on (.+?)\.(?: |$)', t)
    subtxt, freetxt = (sub.group(1) if sub else ""), ""
    if " or for free with ads on " in subtxt: subtxt, freetxt = subtxt.split(" or for free with ads on ", 1)   # v3: split ad-supported free tier out of subscriptions
    elif subtxt.startswith("for free with ads on "): subtxt, freetxt = "", subtxt[len("for free with ads on "):]
    buy = re.search(r'buy "[^"]+" on (.+?) as download', t) or re.search(r'online and to download it on (.+?)\.(?: |$)', t)  # digital purchase only; DVD/Blu-ray ignored
    rent = re.search(r'rent (?:it|"[^"]+") on (.+?) online', t)
    free = re.search(r'watch "[^"]+" for free (?:with ads )?on ([^."]{1,200}?)\.(?: |$)', t)
    none = "couldn't find an offer" in t or "could not find an offer" in t
    subs, frees = [], plist(freetxt) + (plist(free.group(1)) if free else [])
    for x in plist(subtxt):
        (frees if x in FREE_AD_SERVICES else subs).append(x)
    d.update(subscription=subs, buy=plist(buy.group(1)) if buy else [], rent=plist(rent.group(1)) if rent else [],
             free=list(dict.fromkeys(frees)), cinema=bool(re.search(r"tickets to see .{0,80} in theaters", t)), no_offers_statement=none)
    return d
def merge_tiers(xs):  # "Netflix Standard with Ads" is a Netflix plan, not another service
    out = []
    for x in xs:
        base = re.sub(r"\s+(?:(?:Standard|Basic)\s+)?with\s+Ads$", "", x)
        if base not in out: out.append(base)
    return out
def card_text(rec, date):
    st = rec["status"]; src = f"JustWatch US {date}"
    if st == "unverified": return f"Where to watch: unverified ({date})"
    if st == "verified_no_home_offers": return ("In theaters · " if rec["cinema"] else "") + f"No streaming/rent/buy yet ({src})"
    parts = []
    if rec["subscription"]: parts.append("Stream: " + ", ".join(merge_tiers(rec["subscription"])))
    if rec["free"]: parts.append("Free: " + ", ".join(rec["free"]))
    if rec["rent"] and rec["rent"] == rec["buy"]: parts.append("Rent/Buy: " + ", ".join(rec["rent"]))
    else:
        if rec["rent"]: parts.append("Rent: " + ", ".join(rec["rent"]))
        if rec["buy"]: parts.append("Buy: " + ", ".join(rec["buy"]))
    if rec["cinema"]: parts.append("In theaters")
    return " · ".join(parts) + f" ({src})"
VIA = {"amazon channel": "Amazon Channel", "apple tv channel": "Apple TV Channel", "roku premium channel": "Roku Premium Channel"}
def svc(x):  # channel bundle = interface; service named separately
    m = re.match(r"(.+?)\s+(Amazon Channel|Apple TV Channel|Roku Premium Channel)$", x, re.I)
    return dict(service=m.group(1), via=VIA[m.group(2).lower()]) if m else dict(service=x, via=None)
WATCH_STATUSES = ("verified_offers", "verified_no_home_offers", "unverified")
WATCH_KEYS = ("status", "checked_at", "theaters_only", "home_offers", "subscription", "free", "rent", "buy")
def to_watch_json(rec):
    """--watch-json payload (display contract: status + free[{service,via}]). Always emitted, including explicit unverified.
    None only for identity_mismatch (publish blocked)."""
    st = rec["status"]
    if st not in WATCH_STATUSES: return None
    if st == "unverified":   # unknown is NOT 'no offers': no offer lists asserted
        return dict(status="unverified", checked_at=rec.get("checked_at"), theaters_only=False, home_offers=False, subscription=[], free=[], rent=[], buy=[])
    subs = merge_tiers(rec.get("subscription", [])); free = [svc(x) for x in merge_tiers(rec.get("free", []))]
    home = bool(subs or rec.get("rent") or rec.get("buy") or free)
    return dict(status=st, checked_at=rec.get("checked_at"), theaters_only=bool(rec.get("cinema")) and not home, home_offers=home, subscription=[svc(x) for x in subs], free=free,
                rent=list(rec.get("rent", [])), buy=list(rec.get("buy", [])))
def watch_source(rid, checked_at):  # helper --source label (<=120 chars): links readback to our record + check time
    return f"justwatch_us_public wtw#{rid} checked {checked_at}"
def base_meta(existing):  # strip any where-to-watch text (ours or helper's) so the helper's metadata op renders it once
    m = existing or ""
    for mk in (" · Where to watch:", " · Stream:", " · Free:", " · Rent", " · Buy:", " · In theaters", " · No streaming", " · Theaters only", " · Sub: "):
        i = m.find(mk); m = m[:i] if i >= 0 else m
    return m.rstrip(" ·")
def compose_meta(existing, text):
    ex = re.sub(r"\s*·\s*(Where to watch: unverified|Stream:|Free:|Rent|Buy:|In theaters|No streaming).*$", "", existing or "").strip()  # replace old where-to-watch, keep TMDB/year
    return (ex + " · " + text) if ex else text
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from policy import REPORTED_SUBSCRIPTIONS as USER_REPORTED_SUBS  # per-instance, from config/local.json
def migrate(c):
    c.execute(SCHEMA); cols = [r[1] for r in c.execute("PRAGMA table_info(watch_availability)")]
    for col, ddl in (("media_type", "TEXT DEFAULT 'movie'"), ("country", "TEXT DEFAULT 'US'"), ("source", "TEXT DEFAULT 'justwatch_public_page'"), ("superseded_reason", "TEXT")):
        if col not in cols: c.execute(f"ALTER TABLE watch_availability ADD COLUMN {col} {ddl}")
def your_services(subs):  # listing match only; never an entitlement claim
    return [k for k, names in USER_REPORTED_SUBS.items() if any(n.lower() == x.lower() for x in subs for n in names)]
def structured(rec):
    return dict(status=rec["status"], country="US", media_type=rec.get("media_type", "movie"), source="justwatch_public_page", source_url=rec.get("source_url"), checked_at=rec["checked_at"],
                subscription=merge_tiers(rec.get("subscription", [])), rent=rec.get("rent", []), buy=rec.get("buy", []), free=rec.get("free", []), cinema=bool(rec.get("cinema")),
                listed_on_user_reported_subscriptions=your_services(rec.get("subscription", [])), record_id=rec.get("record_id"), card_text=rec.get("card_text"),
                note=("availability unverified: fetch/parse failed; not evidence of no offers" if rec["status"] == "unverified" else None))
def check(tmdb_id, title, year, directors, existing_meta=None, html_file=None, db=DB, media_type="movie"):
    c = sqlite3.connect(db); migrate(c); at = now(); date = datetime.date.today().strftime("%m/%d")
    tried, rec = [], None
    kind = "movie" if media_type == "movie" else "tv-show"
    urls = [f"https://www.justwatch.com/us/{kind}/{slug(title)}", f"https://www.justwatch.com/us/{kind}/{slug(title)}-{year}"]
    for u in ([html_file] if html_file else urls):
        page, code = ((open(u, encoding="utf-8").read(), "200") if __import__("os").path.exists(u) else (None, "offline_fixture_missing")) if html_file else fetch(u)
        if page is None: tried.append(dict(url=u, http=code)); continue
        d = parse(page); idok = norm(d["page_title"]) == norm(title) and d["page_year"] == int(year)
        dirok = not directors or not d["page_directors"] or bool({norm(x) for x in directors} & {norm(x) for x in d["page_directors"]})
        base = dict(tmdb_id=tmdb_id, title=title, year=int(year), checked_at=at, source_url=(u if not html_file else "file:" + u), page_title=d["page_title"], page_year=d["page_year"],
                    page_directors=d["page_directors"], page_sha256=hashlib.sha256(page.encode()).hexdigest(), subscription=d["subscription"], rent=d["rent"], buy=d["buy"], free=d["free"], cinema=d["cinema"], error=None)
        if not (idok and dirok):
            tried.append(dict(url=u, mismatch=f"{d['page_title']} ({d['page_year']}) dirs={d['page_directors']}")); rec = rec or dict(base, status="identity_mismatch", error="page film differs: " + tried[-1]["mismatch"]); continue
        has = any([d["subscription"], d["rent"], d["buy"], d["free"]])
        if has: rec = dict(base, status="verified_offers")
        elif d["no_offers_statement"]: rec = dict(base, status="verified_no_home_offers")
        else: rec = dict(base, status="unverified", error="page matched film but no offer/no-offer statement parsed")
        break
    if rec is None: rec = dict(tmdb_id=tmdb_id, title=title, year=int(year), checked_at=at, source_url=None, status="unverified", subscription=[], rent=[], buy=[], free=[], cinema=False,
                               page_title=None, page_year=None, page_directors=[], page_sha256=None, error="fetch failed: " + json.dumps(tried))
    rec["card_text"] = card_text(rec, date) if rec["status"] != "identity_mismatch" else None
    with c:
        cur = c.execute("INSERT INTO watch_availability(media_type,country,source,tmdb_id,title,year,checked_at,source_url,status,subscription_json,rent_json,buy_json,free_json,cinema,page_title,page_year,page_directors_json,page_sha256,parser,error,card_text) VALUES(?,'US','justwatch_public_page',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (media_type, tmdb_id, title, int(year), at, rec["source_url"], rec["status"], json.dumps(rec["subscription"]), json.dumps(rec["rent"]), json.dumps(rec["buy"]), json.dumps(rec["free"]), int(rec["cinema"]),
                         rec["page_title"], rec["page_year"], json.dumps(rec["page_directors"]), rec["page_sha256"], PARSER, rec["error"], rec["card_text"]))
    rec["media_type"] = media_type; rec["record_id"] = cur.lastrowid; rec["where_to_watch"] = structured(rec); rec["meta"] = compose_meta(existing_meta, rec["card_text"]) if rec["card_text"] else None
    return rec
def enrich_plan(a):
    import lease as L
    plan = json.load(open(a.plan)); c = sqlite3.connect(a.db)
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_lease'").fetchone():
        try: L.guard(c, a.lease_token)
        except L.LeaseError as e: print(json.dumps(dict(ok=False, error=e.msg))); sys.exit(e.code)
    for o in plan:
        pp = o.get("publisher_plan")
        if not pp: continue
        ch = o.get("chosen") or {}
        dirs = [x.strip() for x in (ch.get("credits") or "").split(";")[0].split(",") if x.strip()] or ([ch["director"]] if ch.get("director") else [])
        base_meta_src = pp.get("meta") or ch.get("meta") or (f"TMDB {ch['tmdb_user_score_pct']}% · {pp['year']}" if ch.get("tmdb_user_score_pct") else str(pp["year"]))
        alerts = o.setdefault("alerts", [])
        d0 = (pp.get("description") or ch.get("description") or "").strip()
        if len(d0) > 280: d0 = d0[:277].rsplit(" ", 1)[0] + "…"
        pp["description"] = d0 or None; pp["description_source"] = (pp.get("description_source") or ch.get("description_source")) if d0 else None
        if not d0: alerts.append(f"ALERT owner: description missing for {pp['title']} ({pp['year']}, TMDB {pp['tmdb_id']}); publishing anyway (owner rule: no hold)")
        hf = f"{a.html_dir}/jw_{slug(pp['title'])}.html" if a.html_dir else None   # offline fixtures for tests only
        if hf and not __import__("os").path.exists(hf):   # offline mode never falls back to live fetch: explicit unverified
            r = check(pp["tmdb_id"], pp["title"], pp["year"], dirs, base_meta_src, html_file="/nonexistent-offline-fixture", db=a.db)
        else: r = check(pp["tmdb_id"], pp["title"], pp["year"], dirs, base_meta_src, html_file=hf, db=a.db)
        if r["status"] == "identity_mismatch":
            o["blocked"] = "where_to_watch_identity_mismatch: " + r["error"]; o.pop("publisher_plan"); continue
        wj = to_watch_json(r); bm = base_meta(base_meta_src)
        pp["meta"] = bm   # helper renders availability (incl. explicit unknown) from --watch-json in the same CAS revision
        pp["watch_source"] = watch_source(r["record_id"], r["checked_at"])
        pp["watch_json"] = wj; pp["where_to_watch_record_id"] = r["record_id"]; pp["where_to_watch_status"] = r["status"]; pp["where_to_watch"] = r["where_to_watch"]
        pp["replace_flags"] = ["--slot", pp["slot"], "--expected-revision", str(pp["expected_revision"]), "--source-event-id", o["source_event_id"], "--title", pp["title"], "--year", str(pp["year"]),
                               "--tmdb-id", str(pp["tmdb_id"]), "--why", pp.get("why") or "", "--meta", pp["meta"], "--credits", pp.get("credits") or "",
                               "--watch-json", json.dumps(wj, separators=(",", ":")), "--source", pp["watch_source"]] + (["--description", pp["description"]] if pp["description"] else [])  # + --poster-datauri (parent fetches poster)
    s = json.dumps(plan, indent=1); (open(a.out, "w").write(s) if a.out else print(s))
def annotate_recs(a):
    """Attach structured where_to_watch to EVERY recommendations.json item (movie and TV). Fresh cache (<= max-age h) reused; else fetch if --fetch; else explicit not_checked."""
    import os, shutil
    c = sqlite3.connect(a.db); migrate(c); R = json.load(open(a.recs)); n = dict(fresh_cache=0, fetched=0, not_checked=0, identity_mismatch=0)
    for row in R["rows"]:
        for it in row["items"]:
            mt, tid = it.get("media_type"), it.get("tmdb_id")
            if mt not in ("movie", "tv") or not tid or not it.get("year"):
                it["where_to_watch"] = dict(status="not_checked", reason="no TMDB identity/year (e.g. creator content)"); n["not_checked"] += 1; continue
            r = c.execute("SELECT id,checked_at FROM watch_availability WHERE tmdb_id=? AND media_type=? AND country='US' AND superseded_reason IS NULL AND status!='identity_mismatch' ORDER BY id DESC LIMIT 1", (tid, mt)).fetchone()
            fresh = r and (datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(r[1])).total_seconds() <= a.max_age_hours * 3600
            if fresh:
                row_ = c.execute("SELECT status,source_url,checked_at,subscription_json,rent_json,buy_json,free_json,cinema,card_text,id FROM watch_availability WHERE id=?", (r[0],)).fetchone()
                rec = dict(status=row_[0], source_url=row_[1], checked_at=row_[2], subscription=json.loads(row_[3]), rent=json.loads(row_[4]), buy=json.loads(row_[5]), free=json.loads(row_[6]), cinema=row_[7], card_text=row_[8], record_id=row_[9], media_type=mt)
                it["where_to_watch"] = structured(rec); n["fresh_cache"] += 1
            elif a.fetch and (a.rows is None or row["key"] in a.rows):
                dirs = [x.strip() for x in (it.get("director") or "").split(",") if x.strip()]
                rec = check(tid, it["title"], it["year"], dirs, db=a.db, media_type=mt); n["fetched"] += 1
                if rec["status"] == "identity_mismatch": it["where_to_watch"] = dict(status="identity_mismatch", checked_at=rec["checked_at"], note=rec["error"]); n["identity_mismatch"] += 1
                else: it["where_to_watch"] = rec["where_to_watch"]
            else: it["where_to_watch"] = dict(status="not_checked", reason=f"no US check within {a.max_age_hours}h"); n["not_checked"] += 1
    bk = a.recs + "." + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".wtw.bak"; shutil.copy(a.recs, bk)
    tmp = a.recs + ".tmp"; json.dump(R, open(tmp, "w"), indent=1); os.replace(tmp, a.recs); print(json.dumps(dict(backup=bk, **n)))
if __name__ == "__main__":
    p = argparse.ArgumentParser(); s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("check"); x.add_argument("--tmdb-id", type=int, required=True); x.add_argument("--title", required=True); x.add_argument("--year", type=int, required=True)
    x.add_argument("--director", action="append", default=[]); x.add_argument("--existing-meta"); x.add_argument("--html"); x.add_argument("--db", default=DB)
    y = s.add_parser("enrich-plan"); y.add_argument("plan"); y.add_argument("--db", default=DB); y.add_argument("--out"); y.add_argument("--html-dir"); y.add_argument("--lease-token")
    x.add_argument("--media-type", default="movie", choices=["movie", "tv"])
    z = s.add_parser("annotate-recs"); z.add_argument("--recs", default="./recommendations.json"); z.add_argument("--db", default=DB); z.add_argument("--fetch", action="store_true")
    z.add_argument("--max-age-hours", type=float, default=24); z.add_argument("--rows", nargs="*")
    a = p.parse_args()
    if a.cmd == "annotate-recs": annotate_recs(a)
    elif a.cmd == "check": print(json.dumps(check(a.tmdb_id, a.title, a.year, a.director, a.existing_meta, a.html, a.db, a.media_type), indent=1))
    else: enrich_plan(a)
