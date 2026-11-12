#!/usr/bin/env python3
"""STAGING server (agent host only). Serves app/index.html and data/picks.staging.json at the production API paths; vote/action POSTs are
validated and logged to data/staging-events.jsonl ONLY (never forwarded to the Mac). Usage: python3 app/server.py [port]"""
import http.server, json, os, sys, datetime
ST = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); PICKS = os.environ.get("STAGING_PICKS", f"{ST}/data/picks.staging.json"); EV = f"{ST}/data/staging-events.jsonl"
def cards(d):
    out = {}
    for s in (d.get("slots") or {}).values(): out[s["slot_id"]] = s
    for g in d.get("genres", []):
        for e in ("new", "classic"):
            if g.get(e): out[g[e]["slot_id"]] = g[e]
    return out
class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ct="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/movies-tv/", "/index.html"): return self._send(200, open(f"{ST}/app/index.html", "rb").read(), "text/html; charset=utf-8")
        if self.path.split("?")[0] == "/preview.html":   # static render for screenshots (data inlined, no polling)
            h = open(f"{ST}/app/index.html").read().replace("<script>", "<script>window.__DOC=" + open(PICKS).read().replace("</", "<\\/") + ";</script><script>", 1)
            return self._send(200, h.encode(), "text/html; charset=utf-8")
        if self.path.startswith("/api/movie-night/picks"): return self._send(200, open(PICKS, "rb").read())
        self._send(404, {"ok": False, "error": "not_found"})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: b = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return self._send(400, {"ok": False, "error": "bad_json"})
        d = json.load(open(PICKS)); c = cards(d).get(b.get("slot_id"))
        if not c: return self._send(409, {"ok": False, "error": "unknown_slot"})
        if b.get("displayed_revision") != d["revision"] or b.get("title") != c["title"] or b.get("tmdb_id") != c["tmdb_id"]: return self._send(409, {"ok": False, "error": "stale_or_mismatch"})
        kind = "vote" if self.path.endswith("/vote") else "action" if self.path.endswith("/action") else None
        if not kind: return self._send(404, {"ok": False, "error": "not_found"})
        if kind == "vote" and b.get("vote") not in ("up", "down"): return self._send(400, {"ok": False, "error": "bad_vote"})
        if kind == "action" and (b.get("action") not in ("watched", "next") or not b.get("event_id")): return self._send(400, {"ok": False, "error": "bad_action"})
        b.update(staging=True, received_at=datetime.datetime.now().astimezone().isoformat()); open(EV, "a").write(json.dumps(dict(kind=kind, **b)) + "\n")
        self._send(200, {"ok": True, "staging": True, "event_id": b.get("event_id"), "ui_message": "Saved (staging only — not sent to Frame)"})
    def log_message(self, *a): pass
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
http.server.ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
