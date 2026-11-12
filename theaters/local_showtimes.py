#!/usr/bin/env python3
"""MovieBot In Theaters builder.

Reads the owner's chosen first-rate theaters (any first-rate theater; exclude discount/second-rate)
from config/local.json (see config/local.example.json).
Fetches public showtimes.com theater pages, matches films on TMDB (exact title + runtime ±6 min),
and writes an in_theaters-v1 body for optional downstream publishers.

Default output is titles-only: no session times, formats, or showing counts.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from amend_descriptions import desc280  # noqa: E402


def load_config():
    path = ROOT / "config" / "local.json"
    if not path.exists():
        ex = ROOT / "config" / "local.example.json"
        raise SystemExit(
            f"Missing {path}. Copy {ex} to config/local.json and fill in your first-rate theaters."
        )
    cfg = json.loads(path.read_text())
    theaters = cfg.get("theaters") or []
    if not theaters:
        raise SystemExit("config/local.json has no theaters[] entries")
    return cfg, theaters


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def norm(s):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        unicodedata.normalize("NFKD", html.unescape(s or ""))
        .encode("ascii", "ignore")
        .decode()
        .lower(),
    ).strip()


def get(url):
    r = subprocess.run(
        ["curl", "-sL", "--max-time", "25", "-A", "Mozilla/5.0", "-w", "\n%{http_code}", url],
        capture_output=True,
    )
    b, _, c = r.stdout.decode("utf-8", "ignore").rpartition("\n")
    return b if c.strip() == "200" else None


def txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_theater(page):
    out = []
    for blk in page.split('<li class="movie-info-box">')[1:]:
        m = re.search(
            r'<h2 class="media-heading">\s*<a href="(/movies/[^"]+)"[^>]*>\s*(.*?)\s*</a>',
            blk,
            re.S,
        )
        if not m:
            continue
        info = re.search(r'<span class="mpaa">([^<]*)</span>\s*\|([^<]*)</p>', blk) or re.search(
            r'<div class="clearfix"></div>\s*<p>\s*(.*?)</p>', blk, re.S
        )
        line = txt(info.group(0)) if info else ""
        rt = re.search(r"(\d+)h\s*(\d+)m", line)
        fmts = []
        tick = blk.split('class="ticketicons"', 1)[1] if 'class="ticketicons"' in blk else ""
        for tb in re.findall(r"<h3>(.*?)</h3>(.*?)(?=<h3>|</div>)", tick, re.S):
            fmt = txt(tb[0])
            day = None
            times = []
            for b in re.finditer(
                r'(?:<a href="([^"]+)"[^>]*>\s*)?<button type="button" class="buttonticket ([^"]+)"(?: data-toggle="tooltip" title="([^"]*)")?>([^<]+)</button>',
                tb[1],
            ):
                label = b.group(4).strip()
                if label.endswith(":"):
                    day = label[:-1]
                    continue
                times.append(
                    dict(
                        date=day,
                        time=label,
                        status={"Expired": "ended", "Buy Now": "upcoming"}.get(
                            b.group(3), "listed_status_unknown"
                        ),
                        ticket_url=html.unescape(b.group(1)) if b.group(1) else None,
                    )
                )
            if times:
                fmts.append(dict(format=fmt, times=times))
        out.append(
            dict(
                title=txt(m.group(2)),
                source_movie_path=m.group(1),
                info=line,
                runtime_min=(int(rt.group(1)) * 60 + int(rt.group(2))) if rt else None,
                formats=fmts,
            )
        )
    return out


def tmdb_match(title, runtime, fa):
    q = subprocess.run(
        ["python3", "-c", "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))", title],
        capture_output=True,
        text=True,
    ).stdout.strip()
    s = get("https://www.themoviedb.org/search/movie?query=" + q) or ""
    ids = list(dict.fromkeys(int(x) for x in re.findall(r'href="/movie/(\d+)[^"]*"', s)))[:5]
    best = None
    for t in ids:
        m = fa["fetch_public"](t)
        if not m or norm(m["title"]) != norm(title):
            continue
        if runtime and (not m.get("runtime_min") or abs(m["runtime_min"] - runtime) > 6):
            continue
        if best is None or (m.get("year") or 0) > (best.get("year") or 0):
            best = m
    return best


def poster_uri(url):
    b = subprocess.run(["curl", "-sL", "--max-time", "20", url], capture_output=True).stdout
    return "data:image/jpeg;base64," + base64.b64encode(b).decode() if b[:3] == b"\xff\xd8\xff" else None


def DAY(e):
    return next(
        (t["date"] for s in e["showings"] for f in s["formats"] for t in f["times"] if t.get("date")),
        "the listed date",
    )


def build(a):
    cfg, theaters = load_config()
    base = cfg.get("showtimes_base") or "https://us.showtimes.com/movie-theaters/"
    home_label = cfg.get("home_area_label") or "home area"

    # Optional: reuse TMDB public fetch from pipeline feedback_apply if present
    fa_path = ROOT / "pipeline" / "feedback_apply.py"
    if not fa_path.exists():
        # fall back to theaters-local stub import path used in older layouts
        fa_path = ROOT / "pipeline" / "feedback_apply.py"
    src = fa_path.read_text()
    # feedback_apply may define CLASSIC_SEEDS; keep prior trim if present
    if "CLASSIC_SEEDS" in src:
        src = src[: src.index("CLASSIC_SEEDS")]
    fa = {"__file__": str(fa_path), "__name__": "fa"}
    exec(compile(src, "fa", "exec"), fa)

    films, coverage = {}, []
    for t in theaters:
        tid, name, city = t["id"], t["name"], t.get("city") or ""
        url = base.rstrip("/") + "/" + tid.strip("/") + "/"
        at = now()
        page = (
            open(os.path.join(a.html_dir, tid + ".html")).read()
            if a.html_dir
            else get(url)
        )
        if not page:
            coverage.append(dict(theater=name, url=url, checked_at=at, status="fetch_failed"))
            continue
        L = parse_theater(page)
        coverage.append(dict(theater=name, url=url, checked_at=at, status="ok", listings=len(L)))
        for f in L:
            k = norm(f["title"])
            e = films.setdefault(
                k, dict(title=f["title"], runtime_min=f["runtime_min"], info=f["info"], showings=[])
            )
            e["showings"].append(
                dict(
                    theater=name,
                    city=city,
                    source_url=url,
                    checked_at=at,
                    formats=f["formats"],
                )
            )

    items, dropped = [], []
    for e in films.values():
        e["upcoming"] = sum(
            t["status"] == "upcoming"
            for s in e["showings"]
            for f in s["formats"]
            for t in f["times"]
        )
    ranked = sorted(films.values(), key=lambda e: (-len(e["showings"]), e["title"]))
    for e in ranked:
        if len(items) >= a.max:
            break
        if re.search(
            r"(?i)live viewing|episodes? \d|metropolitan opera|secret movie|in cinemas|concert|fathom",
            e["title"],
        ):
            dropped.append(dict(title=e["title"], reason="event/episode/concert listing, not a film"))
            continue
        m = tmdb_match(e["title"], e["runtime_min"], fa)
        if not m:
            dropped.append(
                dict(title=e["title"], reason="no exact TMDB title+runtime match (event/episode/concert or ambiguous)")
            )
            continue
        p = poster_uri(m["poster_url"]) if m.get("poster_url") else None
        d = desc280(m.get("overview"))
        items.append(
            dict(
                slot_id=f"theaters:{m['tmdb_id']}",
                title=m["title"],
                tmdb_id=m["tmdb_id"],
                media_type="movie",
                year=m["year"],
                poster=p,
                description=d,
                description_source="TMDB overview via " + m["source"],
                rating=m.get("tmdb_user_score_pct"),
                meta=(
                    (f"TMDB {m['tmdb_user_score_pct']}%" if m.get("tmdb_user_score_pct") else "TMDB rating unavailable")
                    + f" · {m['year']}"
                    + (f" · {e['info']}" if e["info"] else "")
                ),
                theater_status="in_theaters_listed",
                metadata_alerts=[x for x, v in (("description", d), ("poster", p)) if not v],
                showings=e["showings"],
                theater_source=dict(
                    source="showtimes.com public theater pages",
                    checked_at=min(s["checked_at"] for s in e["showings"]),
                    identity="TMDB exact title + runtime ±6 min",
                ),
            )
        )

    body = dict(
        status="checked",
        scope=f"First-rate theaters near {home_label}",
        checked_at=now(),
        source="https://us.showtimes.com/ theater pages",
        note="Playing at nearby first-rate theaters (showtimes.com). Showtimes intentionally not shown.",
        coverage=coverage,
        dropped=dropped,
        items=items,
    )

    if a.provenance_full:
        json.dump(body, open(a.out + ".provenance-full.json", "w"), indent=1, ensure_ascii=False)

    if not a.full_schedule_unsafe:
        for i in body["items"]:
            i["showings"] = [
                dict(
                    theater=x["theater"],
                    city=x["city"],
                    source_url=x["source_url"],
                    listed_date=DAY(dict(showings=[x])),
                    checked_date=x["checked_at"][:10],
                )
                for x in i["showings"]
            ]
            i["theater_source"] = dict(
                source="showtimes.com public theater pages",
                checked_date=i["theater_source"]["checked_at"][:10],
                checked_at=i["theater_source"]["checked_at"][:10],
                identity=i["theater_source"]["identity"],
            )
            i["meta"] = re.sub(r" · [^·]*\d+h \d+m[^·]*$", "", i["meta"])
        body["checked_at"] = body["checked_at"][:10]
        for c in body["coverage"]:
            c["checked_at"] = c["checked_at"][:10]

    json.dump(body, open(a.out, "w"), indent=1, ensure_ascii=False)
    print(
        json.dumps(
            dict(
                items=[(i["title"], i["year"], len(i["showings"])) for i in items],
                dropped=len(dropped),
                coverage=[(c["theater"], c["status"], c.get("listings")) for c in coverage],
            )
        )
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    s = ap.add_subparsers(dest="c", required=True)
    b = s.add_parser("build")
    b.add_argument("--out", required=True)
    b.add_argument("--html-dir")
    b.add_argument("--max", type=int, default=16)
    b.add_argument("--titles-only", action="store_true", help="default; kept for compat")
    b.add_argument("--provenance-full", action="store_true", help="also write internal provenance with times; never publish")
    b.add_argument(
        "--full-schedule-unsafe",
        action="store_true",
        help="INTERNAL DEBUG: write times into --out; never publish",
    )
    a = ap.parse_args()
    build(a)
