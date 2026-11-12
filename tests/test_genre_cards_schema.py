#!/usr/bin/env python3
"""Smoke-test core genre/in_theaters extension validation."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import genre_cards as GC

res = []
def check(n, c, d=""):
    res.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (f" -> {d}" if d and not c else ""))

# minimal valid doc without extensions
doc = {"schema_version": 1, "revision": 1, "updated_at": "2026-11-07T00:00:00-06:00",
       "slots": {"new": None, "classic": None}}
try:
    GC.validate_ext(doc, 2001)
    check("plain v1 validates", True)
except Exception as e:
    check("plain v1 validates", False, str(e))

print(f"{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
