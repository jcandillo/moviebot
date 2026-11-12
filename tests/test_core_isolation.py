#!/usr/bin/env python3
"""Core Python packages must not import integrations/photo-frame."""
from __future__ import annotations
import ast, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_DIRS = [ROOT / "pipeline", ROOT / "theaters", ROOT / "tools"]
res = []

def check(n, c, detail=""):
    res.append(bool(c))
    print(("PASS " if c else "FAIL ") + n + (f" -> {detail}" if detail and not c else ""))

hits = []
for base in CORE_DIRS:
    if not base.exists():
        continue
    for path in base.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "integrations/photo-frame" in text or "integrations.photo_frame" in text:
            hits.append(f"{path.relative_to(ROOT)}:string-ref")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as e:
            check(f"parse {path.relative_to(ROOT)}", False, str(e))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if "integration" in a.name:
                        hits.append(f"{path.relative_to(ROOT)}:import {a.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if "integration" in node.module:
                    hits.append(f"{path.relative_to(ROOT)}:from {node.module}")

check("core Python has no integration imports/path refs", not hits, "; ".join(hits[:10]))

sys.path.insert(0, str(ROOT / "pipeline"))
import genre_cards, where_to_watch, amend_descriptions, genre_flow, lease, picks_contract  # noqa: F401
check("core pipeline modules import", True)

print(f"{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
