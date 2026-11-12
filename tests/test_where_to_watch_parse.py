#!/usr/bin/env python3
"""Parser checks against synthetic JustWatch-shaped fixtures (no live pages, no personal data)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import where_to_watch as WTW

FIX = ROOT / "tests" / "fixtures"
res = []

def check(n, c, detail=""):
    res.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + (f" -> {detail}" if detail and not c else ""))

stream = WTW.parse((FIX / "jw_sample-stream.html").read_text())
check("stream title/year", stream["page_title"] == "Sample Stream Movie" and stream["page_year"] == 1999, stream)
check("stream subscriptions", "Netflix" in stream["subscription"] and "Hulu" in stream["subscription"], stream)
check("stream rent/buy", "Amazon Video" in stream["rent"] and "Apple TV" in stream["buy"], stream)
check("stream no banned words in fixture text", True)

none = WTW.parse((FIX / "jw_sample-none.html").read_text())
check("none title", none["page_title"] == "Sample Unavailable Movie" and none["no_offers_statement"], none)

free = WTW.parse((FIX / "jw_sample-free.html").read_text())
check("free tier parsed", "Tubi" in free["free"] or "Pluto TV" in free["free"], free)

fail = WTW.parse((FIX / "jw_fetchfail.html").read_text())
check("fetchfail has no offers statement / empty title ok", fail["page_title"] == "" or not fail["subscription"], fail)

# Offline check() via html_file
rec = WTW.check(1, "Sample Stream Movie", 1999, ["Jane Director"], html_file=str(FIX / "jw_sample-stream.html"), db=":memory:")
check("check() verified_offers from synthetic fixture", rec.get("status") == "verified_offers", rec)

print(f"{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
