#!/usr/bin/env python3
"""Validate a titles-only in_theaters JSON shape (synthetic sample; no personal fixtures)."""
import json, re, sys, tempfile
from pathlib import Path

SAMPLE = {
  "status": "checked",
  "scope": "First-rate theaters near home area",
  "checked_at": "2026-11-07",
  "source": "https://us.showtimes.com/ theater pages",
  "note": "Playing at nearby first-rate theaters. Showtimes intentionally not shown.",
  "coverage": [],
  "dropped": [],
  "items": [
    {
      "slot_id": "theaters:1",
      "title": "Sample Theater Film",
      "tmdb_id": 1,
      "media_type": "movie",
      "year": 2026,
      "poster": None,
      "description": "A spoiler-free one-line overview for tests.",
      "description_source": "synthetic",
      "meta": "TMDB rating unavailable · 2026",
      "theater_status": "in_theaters_listed",
      "metadata_alerts": ["poster"],
      "showings": [
        {
          "theater": "AMC Example Branch",
          "city": "Example City",
          "source_url": "https://us.showtimes.com/movie-theaters/example-amc-branch-0000/",
          "listed_date": "Sat, Nov 7",
          "checked_date": "2026-11-07",
        },
        {
          "theater": "Cinemark Example Branch",
          "city": "Example City",
          "source_url": "https://us.showtimes.com/movie-theaters/example-cinemark-branch-0000/",
          "listed_date": "Sat, Nov 7",
          "checked_date": "2026-11-07",
        },
      ],
      "theater_source": {
        "source": "showtimes.com public theater pages",
        "checked_date": "2026-11-07",
        "checked_at": "2026-11-07",
        "identity": "TMDB exact title + runtime ±6 min",
      },
    }
  ],
}

if len(sys.argv) > 1:
    B = json.load(open(sys.argv[1]))
else:
    B = SAMPLE

res = []

def check(n, c):
    res.append(bool(c))
    print(("PASS " if c else "FAIL ") + n)

check("status checked", B.get("status") == "checked")
check("has items", isinstance(B.get("items"), list) and len(B["items"]) >= 1)
check(
    "no home/streaming fields",
    not re.search(r'"(watch_availability|home_watch_availability|subscription|rent|buy)"', json.dumps(B.get("items"))),
)
# Theater rule: any first-rate theater qualifies; discount/second-rate experiences are excluded.
# Public examples (the built-in SAMPLE) stay chain-only with national chains.
NATIONAL_CHAINS = r"(AMC|Cinemark|Regal|Alamo Drafthouse)\b"
DISCOUNT_MARKERS = r"(?i)(dollar|discount|bargain|\$\d|second[- ]run|budget)"
showings = [s for i in B["items"] for s in i["showings"]]
check("every showing names a theater", all(str(s.get("theater", "")).strip() for s in showings))
check("no discount/second-rate theaters", not any(re.search(DISCOUNT_MARKERS, s["theater"]) for s in showings))
if B is SAMPLE:
    check("public example uses national chains only", all(re.match(NATIONAL_CHAINS, s["theater"]) for s in showings))
check(
    "titles-only showing keys",
    all(set(x) <= {"theater", "city", "source_url", "listed_date", "checked_date"} for i in B["items"] for x in i["showings"]),
)
_t = json.dumps([i["showings"] for i in B["items"]]) + json.dumps([i.get("meta", "") for i in B["items"]])
check("no clock times in published showings/meta", not re.search(r"\d{1,2}:\d{2}", _t))
print(f"{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
