"""HTTPS LAN frame server: static frame-live + flights proxy + Movie Night vote/picks/outbox.
Auth: cookie or ?k=. Never log tokens. Secrets never in responses.
"""
import hmac, json, os, ssl, uuid, urllib.parse, urllib.request, http.server, functools, threading, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOME = os.path.expanduser("~")
TLS = os.path.join(HOME, "frame-sync/tls")
ROOT = os.path.join(HOME, "Documents/frame-live")
VOTE_DIR = os.path.join(HOME, "frame-sync/movie-night-votes")
PICKS = os.path.join(VOTE_DIR, "picks", "picks.json")
PICKS_LAST = os.path.join(VOTE_DIR, "picks", "picks.last-good.json")
OUTBOX = os.path.join(VOTE_DIR, "outbox", "wake.jsonl")
SEND_WAKE = os.path.join(VOTE_DIR, "send-wake.py")
ACTIONS = os.path.join(VOTE_DIR, "actions.jsonl")
ACTIONS_TEST = os.path.join(VOTE_DIR, "actions-test.jsonl")
LATEST_ACTIONS = os.path.join(VOTE_DIR, "latest-actions.json")
LATEST_ACTIONS_TEST = os.path.join(VOTE_DIR, "latest-actions-test.json")
ACTION_BY_ID = os.path.join(VOTE_DIR, "actions-by-id.json")
ACTION_BY_ID_TEST = os.path.join(VOTE_DIR, "actions-by-id-test.json")
PORT = 8443
ORIGIN = "photo_frame_movie_night"
CLASSIC_MAX_YEAR = datetime.now().year - 25

with open(os.path.join(TLS, "token")) as f:
    TOKEN = f.read().strip()
COOKIE = "frame_auth"
os.makedirs(os.path.join(VOTE_DIR, "outbox"), exist_ok=True)
os.makedirs(os.path.join(VOTE_DIR, "picks"), exist_ok=True)


def _now_offset():
    try:
        from zoneinfo import ZoneInfo
        tz_name = os.environ.get("MOVIEBOT_TZ", "America/New_York")
        return datetime.now(ZoneInfo(tz_name)).isoformat(timespec="seconds")
    except Exception:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())


def _write_json_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_picks():
    p = _load_json(PICKS)
    if p and p.get("schema_version") == 1 and "slots" in p:
        return p
    return _load_json(PICKS_LAST)


# --- genres-v1 card identity (STAGED). Card ids: "new" | "classic" (v1 slots) | "genre:<genre_id>:<new|classic>".
import re as _re
GENRE_IDS = ("comedy", "action_adventure", "scifi", "drama", "thriller", "family")
_CARD_RE = _re.compile(r"genre:([a-z_]+):(new|classic)")
def _valid_card_id(cid):
    if cid in ("new", "classic"):
        return True
    m = _CARD_RE.fullmatch(cid or "") if isinstance(cid, str) else None
    return bool(m and m.group(1) in GENRE_IDS)
def _resolve_card(picks, cid):
    """Exact card lookup in the CURRENT picks; None if absent (empty genre card => 409 title_mismatch)."""
    if cid in ("new", "classic"):
        return (picks.get("slots") or {}).get(cid)
    m = _CARD_RE.fullmatch(cid or "")
    if not m or m.group(1) not in GENRE_IDS:
        return None
    for g in picks.get("genres") or []:
        if g.get("genre_id") == m.group(1):
            c = g.get(m.group(2))
            return c if isinstance(c, dict) and c.get("slot_id") == cid else None
    return None


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass

    def _authed(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        k = (q.get("k") or [""])[0]
        if k and hmac.compare_digest(k.encode(), TOKEN.encode()):
            return "param"
        for part in (self.headers.get("Cookie") or "").split(";"):
            n, _, v = part.strip().partition("=")
            if n == COOKIE and hmac.compare_digest(v.encode(), TOKEN.encode()):
                return "cookie"
        return None

    def end_headers(self):
        if getattr(self, "_setcookie", False):
            self.send_header("Set-Cookie", "%s=%s; Max-Age=315360000; Path=/; Secure; HttpOnly; SameSite=Strict" % (COOKIE, TOKEN))
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _deny(self):
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "10")
        self.end_headers()
        self.wfile.write(b"Forbidden\n")

    def _json(self, code, obj):
        body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self, max_n=16384):
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            return None, "bad_length"
        if n <= 0 or n > max_n:
            return None, "bad_length"
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8")), None
        except Exception:
            return None, "bad_json"

    def do_HEAD(self):
        self._deny()

    def do_GET(self):
        a = self._authed()
        if not a:
            return self._deny()
        self._setcookie = (a == "param")
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/api/movie-night/picks":
            return self._picks()
        if u.path == "/api/movie-night/pending":
            return self._pending()
        if u.path.startswith("/api/flights"):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8098" + u.path, timeout=25) as r:
                    body, ct, code = r.read(), r.headers.get("Content-Type", "application/json"), r.status
            except Exception:
                body, ct, code = b'{"error":"upstream"}', "application/json", 502
            self.send_response(code)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.path = u.path
        super().do_GET()

    def do_POST(self):
        a = self._authed()
        if not a:
            return self._deny()
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/api/movie-night/vote":
            return self._vote()
        if u.path == "/api/movie-night/action":
            return self._action()
        if u.path == "/api/movie-night/forwarded":
            return self._forwarded()
        return self._json(404, {"ok": False, "error": "not_found"})

    def _picks(self):
        p = _load_picks()
        if not p:
            return self._json(503, {"ok": False, "error": "picks_unavailable"})
        return self._json(200, p)

    def _vote(self):
        data, err = self._read_json_body()
        if err:
            return self._json(400, {"ok": False, "error": err})
        vote = data.get("vote")
        if vote not in ("up", "down"):
            return self._json(400, {"ok": False, "error": "bad_vote"})
        slot_id = data.get("slot_id")
        if not _valid_card_id(slot_id):
            return self._json(400, {"ok": False, "error": "bad_slot_id"})
        try:
            displayed_revision = int(data.get("displayed_revision"))
        except Exception:
            return self._json(400, {"ok": False, "error": "bad_displayed_revision"})
        title = (data.get("title") or "").strip()
        if not title or len(title) > 200:
            return self._json(400, {"ok": False, "error": "bad_title"})
        year = data.get("year")
        if year is not None:
            try:
                year = int(year)
            except Exception:
                return self._json(400, {"ok": False, "error": "bad_year"})
        tmdb_id = data.get("tmdb_id")
        if tmdb_id is not None:
            try:
                tmdb_id = int(tmdb_id)
                if tmdb_id <= 0:
                    tmdb_id = None
            except Exception:
                return self._json(400, {"ok": False, "error": "bad_tmdb_id"})
        test = bool(data.get("test"))
        media_type = (data.get("media_type") or "movie").strip()[:20]

        picks = _load_picks()
        if not picks:
            return self._json(503, {"ok": False, "error": "picks_unavailable"})
        if picks.get("revision") != displayed_revision:
            return self._json(409, {"ok": False, "error": "stale_revision", "current_revision": picks.get("revision")})
        slot = _resolve_card(picks, slot_id) or {}
        if (slot.get("title") or "").strip() != title:
            return self._json(409, {"ok": False, "error": "title_mismatch", "current_title": slot.get("title")})
        if tmdb_id is not None and slot.get("tmdb_id") is not None and int(slot["tmdb_id"]) != tmdb_id:
            return self._json(409, {"ok": False, "error": "tmdb_mismatch"})

        if tmdb_id is not None:
            idem = "%s:%s:%s:%s" % (ORIGIN, slot_id, media_type, tmdb_id)
        else:
            idem = "%s:%s:%s:%s:%s" % (ORIGIN, slot_id, media_type, title.lower(), year if year is not None else "")
        if test:
            idem = "test:" + idem

        event_id = str(uuid.uuid4())
        ts = _now_offset()
        latest_path = os.path.join(VOTE_DIR, "latest-test.json" if test else "latest.json")
        jsonl_path = os.path.join(VOTE_DIR, "votes-test.jsonl" if test else "votes.jsonl")
        latest = _load_json(latest_path, {}) or {}
        prev = latest.get(idem)
        event = {
            "event_id": event_id,
            "title": title,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "vote": vote,
            "timestamp": ts,
            "origin": ORIGIN,
            "year": year,
            "slot_id": slot_id,
            "displayed_revision": displayed_revision,
            "test": test,
            "idempotency_key": idem,
        }
        if prev:
            event["supersedes"] = prev.get("event_id")
        _append_jsonl(jsonl_path, event)
        latest[idem] = {
            "event_id": event_id,
            "vote": vote,
            "title": title,
            "year": year,
            "tmdb_id": tmdb_id,
            "slot_id": slot_id,
            "displayed_revision": displayed_revision,
            "timestamp": ts,
            "test": test,
        }
        _write_json_atomic(latest_path, latest)

        # Durable outbox AFTER vote persistence (non-test only)
        if not test:
            payload = {
                "type": "movie_night_vote",
                "event_id": event_id,
                "slot_id": slot_id,
                "vote": vote,
                "title": title,
                "tmdb_id": tmdb_id,
                "year": year,
                "displayed_revision": displayed_revision,
                "origin": ORIGIN,
                "timestamp": ts,
            }
            _append_jsonl(OUTBOX, {
                "status": "pending",
                "attempts": 0,
                "queued_at": ts,
                "event_id": event_id,
                "payload": payload,
            })
            # bounded background send — never blocks vote ack long
            def _bg():
                try:
                    subprocess.run(["/opt/homebrew/bin/python3", SEND_WAKE], timeout=30,
                                   capture_output=True, cwd=VOTE_DIR)
                except Exception:
                    pass
            threading.Thread(target=_bg, daemon=True).start()

        return self._json(200, {
            "ok": True,
            "event_id": event_id,
            "status": "queued_locally",
            "ui_message": "Saved locally",
            "vote": vote,
            "slot_id": slot_id,
            "displayed_revision": displayed_revision,
            "idempotency_key": idem,
            "supersedes": event.get("supersedes"),
            "wake": "outboxed" if not test else "skipped_test",
            "delivery": {"applied": False, "note": "raw_feedback_only; no watched inference"},
        })

    def _action(self):
        """POST /api/movie-night/action — interim Watched / Next.
        Distinct from votes: no rating inference, no pick auto-replace here.
        Outboxes wake payload type=movie_night_action (sender disabled until wake-webhook.env).
        Schema movie_night_action_v1 → actions.jsonl (actions-test.jsonl if test).
        """
        data, err = self._read_json_body()
        if err:
            return self._json(400, {"ok": False, "error": err})
        action = (data.get("action") or "").strip()
        if action not in ("watched", "next"):
            return self._json(400, {"ok": False, "error": "bad_action"})
        slot_id = data.get("slot_id")
        if not _valid_card_id(slot_id):
            return self._json(400, {"ok": False, "error": "bad_slot_id"})
        try:
            displayed_revision = int(data.get("displayed_revision"))
        except Exception:
            return self._json(400, {"ok": False, "error": "bad_displayed_revision"})
        title = (data.get("title") or "").strip()
        if not title or len(title) > 200:
            return self._json(400, {"ok": False, "error": "bad_title"})
        year = data.get("year")
        if year is not None:
            try:
                year = int(year)
            except Exception:
                return self._json(400, {"ok": False, "error": "bad_year"})
        tmdb_id = data.get("tmdb_id")
        if tmdb_id is not None:
            try:
                tmdb_id = int(tmdb_id)
                if tmdb_id <= 0:
                    tmdb_id = None
            except Exception:
                return self._json(400, {"ok": False, "error": "bad_tmdb_id"})
        test = bool(data.get("test"))
        media_type = (data.get("media_type") or "movie").strip()[:20]
        client_eid = (data.get("event_id") or "").strip()
        try:
            if client_eid:
                uuid.UUID(client_eid)
            else:
                client_eid = None
        except Exception:
            return self._json(400, {"ok": False, "error": "bad_event_id"})

        picks = _load_picks()
        if not picks:
            return self._json(503, {"ok": False, "error": "picks_unavailable"})
        if picks.get("revision") != displayed_revision:
            return self._json(409, {"ok": False, "error": "stale_revision", "current_revision": picks.get("revision")})
        slot = _resolve_card(picks, slot_id) or {}
        if (slot.get("title") or "").strip() != title:
            return self._json(409, {"ok": False, "error": "title_mismatch", "current_title": slot.get("title")})
        if tmdb_id is not None and slot.get("tmdb_id") is not None and int(slot["tmdb_id"]) != tmdb_id:
            return self._json(409, {"ok": False, "error": "tmdb_mismatch"})

        if tmdb_id is not None:
            film = "%s:%s" % (media_type, tmdb_id)
        else:
            film = "%s:%s:%s" % (media_type, title.lower(), year if year is not None else "")
        idem = "action:%s:%s:%s:%s:r%s" % (action, ORIGIN, slot_id, film, displayed_revision)
        if test:
            idem = "test:" + idem

        by_id_path = ACTION_BY_ID_TEST if test else ACTION_BY_ID
        latest_path = LATEST_ACTIONS_TEST if test else LATEST_ACTIONS
        jsonl_path = ACTIONS_TEST if test else ACTIONS
        by_id = _load_json(by_id_path, {}) or {}
        latest = _load_json(latest_path, {}) or {}

        def _ok_resp(eid, idempotent):
            ui = "Saved locally" if action == "watched" else "Queued"
            return self._json(200, {
                "ok": True,
                "idempotent": idempotent,
                "event_id": eid,
                "action": action,
                "slot_id": slot_id,
                "displayed_revision": displayed_revision,
                "status": "queued_locally" if action == "next" else "saved_locally",
                "ui_message": ui,
                "delivery": {"applied": False, "note": "local_action_only; same-slot replace needs MovieBot publish; wake sender may be disabled"},
                "wake": "skipped_test" if test else "outboxed",
            })

        if client_eid and client_eid in by_id:
            prev = by_id[client_eid]
            mismatch = (
                prev.get("action") != action
                or prev.get("slot_id") != slot_id
                or prev.get("displayed_revision") != displayed_revision
                or (prev.get("title") or "") != title
                or prev.get("tmdb_id") != tmdb_id
            )
            if mismatch:
                return self._json(409, {"ok": False, "error": "event_id_conflict", "event_id": client_eid})
            return _ok_resp(client_eid, True)

        prev_logical = latest.get(idem)
        if prev_logical and not client_eid:
            return _ok_resp(prev_logical.get("event_id"), True)

        event_id = client_eid or str(uuid.uuid4())
        ts = _now_offset()
        event = {
            "schema": "movie_night_action_v1",
            "event_id": event_id,
            "action": action,
            "slot_id": slot_id,
            "displayed_revision": displayed_revision,
            "title": title,
            "tmdb_id": tmdb_id,
            "year": year,
            "media_type": media_type,
            "origin": ORIGIN,
            "timestamp": ts,
            "test": test,
            "idempotency_key": idem,
            "signal": None if action == "next" else "viewed_explicit",
            "taste": None,
            "rating": None,
            "note": "interim_local_action; requests same-slot refresh; not a thumb vote",
        }
        _append_jsonl(jsonl_path, event)
        meta = {
            "event_id": event_id, "action": action, "slot_id": slot_id,
            "displayed_revision": displayed_revision, "title": title, "tmdb_id": tmdb_id,
            "timestamp": ts, "test": test, "idempotency_key": idem,
        }
        by_id[event_id] = meta
        _write_json_atomic(by_id_path, by_id)
        latest[idem] = meta
        _write_json_atomic(latest_path, latest)

        # Outbox for event-driven wake (sender no-ops without wake-webhook.env; never converts to vote)
        if not test:
            payload = {
                "type": "movie_night_action",
                "schema": "movie_night_action_v1",
                "event_id": event_id,
                "action": action,
                "slot_id": slot_id,
                "title": title,
                "tmdb_id": tmdb_id,
                "year": year,
                "displayed_revision": displayed_revision,
                "origin": ORIGIN,
                "timestamp": ts,
                "signal": event["signal"],
                "taste": None,
                "rating": None,
                "replace_requested": True,
            }
            _append_jsonl(OUTBOX, {
                "status": "pending", "attempts": 0, "queued_at": ts,
                "event_id": event_id, "payload": payload,
            })
            def _bg():
                try:
                    subprocess.run(["/opt/homebrew/bin/python3", SEND_WAKE], timeout=30,
                                   capture_output=True, cwd=VOTE_DIR)
                except Exception:
                    pass
            threading.Thread(target=_bg, daemon=True).start()

        return _ok_resp(event_id, False)

    def _pending(self):
        events = []
        path = os.path.join(VOTE_DIR, "votes.jsonl")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("test"):
                        continue
                    events.append(e)
        ledger = _load_json(os.path.join(VOTE_DIR, "forwarded-ledger.json"), {"forwarded": {}}) or {"forwarded": {}}
        forwarded = ledger.get("forwarded") or {}
        pending = [e for e in events if e.get("event_id") and e["event_id"] not in forwarded]
        return self._json(200, {"ok": True, "pending_count": len(pending), "pending": pending,
                                "note": "legacy_push_view; MovieBot prefers pull-votes.py / webhook wake"})

    def _forwarded(self):
        data, err = self._read_json_body()
        if err:
            return self._json(400, {"ok": False, "error": err})
        ids = data.get("event_ids") or []
        if not isinstance(ids, list) or not ids:
            return self._json(400, {"ok": False, "error": "bad_event_ids"})
        known = {}
        path = os.path.join(VOTE_DIR, "votes.jsonl")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if not e.get("test"):
                        known[e.get("event_id")] = e
        ledger_path = os.path.join(VOTE_DIR, "forwarded-ledger.json")
        ledger = _load_json(ledger_path, {"forwarded": {}, "history": []}) or {"forwarded": {}, "history": []}
        ts = _now_offset()
        marked, skipped, unknown = [], [], []
        for eid in ids:
            if eid not in known:
                unknown.append(eid); continue
            if eid in ledger["forwarded"]:
                skipped.append(eid); continue
            entry = {"event_id": eid, "transport_status": "forwarded_to_agent", "forwarded_at": ts,
                     "means": "messaging_transport_ack_only", "applied": False, "accepted": False}
            ledger["forwarded"][eid] = entry
            ledger["history"].append(entry)
            marked.append(eid)
            _append_jsonl(os.path.join(VOTE_DIR, "forwarded-ledger.jsonl"), entry)
        _write_json_atomic(ledger_path, ledger)
        return self._json(200, {"ok": True, "marked_forwarded": marked, "already_forwarded": skipped,
                                "unknown_event_ids": unknown, "applied": False})


if __name__ == "__main__":
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(os.path.join(TLS, "server.crt"), os.path.join(TLS, "server.key"))
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), functools.partial(H, directory=ROOT))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()
