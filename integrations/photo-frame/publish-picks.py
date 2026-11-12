#!/usr/bin/env python3
"""[STAGED genres-v1/in_theaters-v1 patch of publish-picks.py sha256 5c8bdd15; NOT deployed. Adds: set-genres, set-theaters, replace-card; extension validation.]
Atomic Movie Night picks publisher (fixed paths only).

Usage:
  publish-picks.py replace --slot new|classic --expected-revision N --source-event-id UUID \
      --title T --year Y [--tmdb-id ID] --why W --poster-datauri DATAURI [--meta M] [--credits C] \
      [--description D] [--watch-json JSON] [--source PROVENANCE] [--fixture-only]
  publish-picks.py metadata --slot new|classic --expected-revision N --title T --tmdb-id ID \
      [--watch-json JSON] [--description D] [--source PROVENANCE] [--fixture-only]
  publish-picks.py show

replace CAS: expected revision must match current; event_id must exist in votes.jsonl (non-test);
slot must match vote's slot_id; replacement must be classic/new eligible; cannot equal either
current title/tmdb or previously voted titles for that slot in queue (simple blocklist).
Idempotent if source_event_id already applied.
Optional --watch-json (same schema as metadata): atomically sets watch_availability + human meta
in the same revision as the film replace. Omitted --watch-json never inherits prior film offers/meta/provenance.
Optional --description: short bounded plain string from supplied source only (never invented); omitted
never inherits prior film description. metadata preserves description unchanged.

metadata: metadata-only same-slot update (where-to-watch and/or description). Guards revision +
slot_id + title + tmdb_id. Preserves title/poster/why/credits/source_event_id/media_type/year.
Optional --watch-json updates watch_availability + human meta suffix; omitted preserves watch object
exactly (incl. status/source/checked_at/updated_at). Optional --description sets short plain plot text
(supplied only; never invented); omitted leaves description untouched. At least one of --watch-json or
--description required. Idempotent if nothing changes (no revision bump).
"""
from __future__ import annotations
import argparse, fcntl, json, os, sys, tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
PICKS = HERE / "picks" / "picks.json"
LAST = HERE / "picks" / "picks.last-good.json"
LOCK = HERE / "picks" / "picks.lock"
VOTES = HERE / "votes.jsonl"
ACTIONS = HERE / "actions.jsonl"
LIVE = Path.home() / "Documents/frame-live/movies-tv/data/picks.json"
PUB = Path.home() / "Documents/photo-frame-dashboard/dashboard/public/movies-tv/data/picks.json"
CLASSIC_MAX_YEAR = datetime.now().year - 25  # 2026 -> 2001
import sys as _sys
_CORE = Path(__file__).resolve().parents[2] / "pipeline"
_sys.path.insert(0, str(_CORE))
import genre_cards as GC  # noqa: E402  # core schema; integration may import core


def now_iso() -> str:
    try:
        from zoneinfo import ZoneInfo
        tz_name = os.environ.get("MOVIEBOT_TZ", "America/New_York")
        return datetime.now(ZoneInfo(tz_name)).isoformat(timespec="seconds")
    except Exception:
        return datetime.utcnow().isoformat() + "Z"


def load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def validate_picks(p: Dict[str, Any]) -> None:
    if p.get("schema_version") != 1:
        raise ValueError("bad_schema_version")
    if not isinstance(p.get("revision"), int) or p["revision"] < 1:
        raise ValueError("bad_revision")
    slots = p.get("slots") or {}
    for sid in ("new", "classic"):
        if sid not in slots:
            raise ValueError("missing_slot_" + sid)
        s = slots[sid]
        for k in ("slot_id", "title", "media_type", "year", "poster", "why"):
            if k not in s or s[k] in ("", None):
                raise ValueError("slot_missing_" + k)
        if s["slot_id"] != sid:
            raise ValueError("slot_id_mismatch")
        if s["media_type"] != "movie":
            raise ValueError("media_type")
        if not str(s["poster"]).startswith("data:image"):
            raise ValueError("poster_must_be_datauri")
        year = int(s["year"])
        if sid == "classic" and year > CLASSIC_MAX_YEAR:
            raise ValueError("classic_too_new")
        if sid == "new" and year <= CLASSIC_MAX_YEAR:
            raise ValueError("new_too_old")
    GC.validate_ext(p, CLASSIC_MAX_YEAR)  # no-op for plain v1 docs (no extensions/genres/in_theaters)


def atomic_write(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".picks-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            f.write("\n")
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def find_event(event_id: str, votes_path: Path, actions_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Locate source event in votes.jsonl OR actions.jsonl (watched/next).
    Action events are valid replace triggers (same-slot refresh) but carry no taste/rating.
    """
    for path in (votes_path, actions_path or ACTIONS):
        if not path or not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("event_id") == event_id:
                    return e
    return None


def previously_voted_ids(votes_path: Path, slot_id: str) -> set:
    out = set()
    if not votes_path.exists():
        return out
    with votes_path.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("test"):
                continue
            if e.get("slot_id") != slot_id:
                continue
            if e.get("tmdb_id") is not None:
                out.add(("tmdb", int(e["tmdb_id"])))
            out.add(("title", (e.get("title") or "").lower()))
    return out


def cmd_replace(args: argparse.Namespace) -> int:
    votes_path = Path(args.votes) if args.votes else VOTES
    picks_path = Path(args.picks) if args.picks else PICKS
    last_path = Path(args.last_good) if args.last_good else LAST
    live_path = Path(args.live) if args.live else LIVE
    lock_path = picks_path.parent / "picks.lock"

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        cur = load(picks_path) or load(last_path)
        if not cur:
            print(json.dumps({"ok": False, "error": "no_current_picks"}))
            return 1
        try:
            validate_picks(cur)
        except ValueError as e:
            # fall back to last-good
            lg = load(last_path)
            if not lg:
                print(json.dumps({"ok": False, "error": "corrupt_and_no_last_good", "detail": str(e)}))
                return 1
            cur = lg
            validate_picks(cur)

        # idempotent: already applied this event
        for sid, s in cur["slots"].items():
            if s.get("source_event_id") == args.source_event_id:
                print(json.dumps({"ok": True, "idempotent": True, "revision": cur["revision"], "slot_id": sid}))
                return 0

        if cur["revision"] != args.expected_revision:
            print(json.dumps({"ok": False, "error": "cas_revision_mismatch", "current": cur["revision"], "expected": args.expected_revision}))
            return 1

        ev = find_event(args.source_event_id, votes_path, ACTIONS)
        if not ev:
            print(json.dumps({"ok": False, "error": "event_not_found"}))
            return 1
        if ev.get("test"):
            print(json.dumps({"ok": False, "error": "test_event_not_allowed"}))
            return 1
        if ev.get("slot_id") != args.slot:
            print(json.dumps({"ok": False, "error": "event_slot_mismatch", "event_slot": ev.get("slot_id"), "requested": args.slot}))
            return 1
        # Source may be a thumb vote OR an explicit action (watched/next). Never treat action as rating.
        is_action = ev.get("schema") == "movie_night_action_v1" or ev.get("action") in ("watched", "next")
        if is_action:
            if ev.get("action") not in ("watched", "next"):
                print(json.dumps({"ok": False, "error": "bad_action_source"}))
                return 1
        else:
            if ev.get("vote") not in ("up", "down"):
                print(json.dumps({"ok": False, "error": "bad_vote_source"}))
                return 1

        year = int(args.year)
        if args.slot == "classic" and year > CLASSIC_MAX_YEAR:
            print(json.dumps({"ok": False, "error": "classic_ineligible", "max_year": CLASSIC_MAX_YEAR}))
            return 1
        if args.slot == "new" and year <= CLASSIC_MAX_YEAR:
            print(json.dumps({"ok": False, "error": "new_ineligible", "min_year": CLASSIC_MAX_YEAR + 1}))
            return 1

        # reject both-current titles/ids
        for sid, s in cur["slots"].items():
            if args.tmdb_id is not None and s.get("tmdb_id") == args.tmdb_id:
                print(json.dumps({"ok": False, "error": "already_displayed_tmdb", "slot": sid}))
                return 1
            if (s.get("title") or "").lower() == args.title.lower():
                print(json.dumps({"ok": False, "error": "already_displayed_title", "slot": sid}))
                return 1

        # reject previously voted for this slot
        prev = previously_voted_ids(votes_path, args.slot)
        if args.tmdb_id is not None and ("tmdb", int(args.tmdb_id)) in prev:
            print(json.dumps({"ok": False, "error": "previously_voted_tmdb"}))
            return 1
        if ("title", args.title.lower()) in prev:
            # the vote that triggered replacement is for the OLD title — that's fine;
            # block if trying to put back a previously voted title as the NEW pick
            # The voted title is the one leaving; replacement title shouldn't be in prev as a different vote's title
            # Actually prev includes the current vote's title — we must allow that the event title != replacement title
            pass
        # Block replacement title if it appears as a voted title for this slot EXCEPT we need:
        # previously voted means user voted on it when it was displayed — those titles shouldn't return.
        # The current vote's title IS being replaced and is in prev — replacement is args.title which should be NEW film.
        if ("title", args.title.lower()) in prev:
            print(json.dumps({"ok": False, "error": "previously_voted_title"}))
            return 1

        if not args.poster_datauri.startswith("data:image"):
            print(json.dumps({"ok": False, "error": "bad_poster"}))
            return 1

        # Optional where-to-watch (exact same schema as metadata). Never inherit prior film.
        watch_store = None
        meta_out = args.meta
        stamp = now_iso()
        raw_watch = getattr(args, "watch_json", None)
        if raw_watch is not None:
            if len(raw_watch.encode("utf-8")) > WATCH_JSON_MAX:
                print(json.dumps({"ok": False, "error": "watch_json_too_large", "max": WATCH_JSON_MAX}))
                return 1
            try:
                watch_in = json.loads(raw_watch)
            except Exception:
                print(json.dumps({"ok": False, "error": "watch_json_invalid"}))
                return 1
            try:
                watch_norm = _norm_watch(watch_in)
            except ValueError as e:
                print(json.dumps({"ok": False, "error": "watch_invalid", "detail": str(e)}))
                return 1
            source = (getattr(args, "source", None) or "publish-picks-replace").strip()
            if not source or len(source) > WATCH_SOURCE_MAX:
                print(json.dumps({"ok": False, "error": "bad_source"}))
                return 1
            meta_out = merge_meta_watch(args.meta, watch_norm)
            if len(meta_out) > META_MAX:
                print(json.dumps({"ok": False, "error": "meta_too_large", "max": META_MAX, "len": len(meta_out)}))
                return 1
            watch_store = dict(watch_norm)
            watch_store["updated_at"] = stamp
            watch_store["source"] = source
            checked = watch_in.get("checked_at")
            if checked is not None and str(checked).strip():
                watch_store["checked_at"] = str(checked).strip()[:80]

        # Optional description — supplied source text only; never invent; never inherit.
        desc_out = None
        raw_desc = getattr(args, "description", None)
        if raw_desc is not None:
            desc = str(raw_desc).strip()
            if not desc:
                print(json.dumps({"ok": False, "error": "description_empty"}))
                return 1
            if len(desc) > DESCRIPTION_MAX:
                print(json.dumps({"ok": False, "error": "description_too_large", "max": DESCRIPTION_MAX, "len": len(desc)}))
                return 1
            if "\x00" in desc or any(ord(ch) < 9 for ch in desc):
                print(json.dumps({"ok": False, "error": "description_invalid"}))
                return 1
            desc_out = desc

        # Fresh slot object — omit watch_availability/description unless this replace supplied them
        # (prevents inheriting previous film offers / provenance / description).
        new_slot = {
            "slot_id": args.slot,
            "title": args.title,
            "tmdb_id": args.tmdb_id,
            "media_type": "movie",
            "year": year,
            "poster": args.poster_datauri,
            "why": args.why,
            "meta": meta_out,
            "credits": args.credits,
            "source_event_id": args.source_event_id,
        }
        if desc_out is not None:
            new_slot["description"] = desc_out
        if watch_store is not None:
            new_slot["watch_availability"] = watch_store
        nxt = json.loads(json.dumps(cur))  # deep copy
        nxt["slots"][args.slot] = new_slot
        nxt["revision"] = cur["revision"] + 1
        nxt["updated_at"] = stamp
        try:
            validate_picks(nxt)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": "validation_failed", "detail": str(e)}))
            return 1

        atomic_write(picks_path, nxt)
        atomic_write(last_path, nxt)
        # mirror to served paths (unless fixture-only)
        if not args.fixture_only:
            atomic_write(live_path, nxt)
            try:
                atomic_write(PUB, nxt)
            except Exception:
                pass
        receipt = {
            "ok": True,
            "revision": nxt["revision"],
            "slot_id": args.slot,
            "source_event_id": args.source_event_id,
            "title": args.title,
            "tmdb_id": args.tmdb_id,
            "meta": meta_out,
            "description": desc_out,
            "watch_availability": watch_store,
            "updated_at": stamp,
        }
        print(json.dumps(receipt))
        return 0


META_MAX = 500
WATCH_JSON_MAX = 4096
WATCH_SOURCE_MAX = 120
DESCRIPTION_MAX = 280


WATCH_STATUSES = ("verified_offers", "verified_no_home_offers", "unverified")


def _offer_bits(items) -> list:
    bits = []
    for s in items or []:
        if isinstance(s, dict):
            name = str(s.get("service") or s.get("name") or "").strip()
            via = str(s.get("via") or "").strip()
            bits.append((name + (" (" + via + ")" if via else "")).strip())
        else:
            bits.append(str(s).strip())
    return [b for b in bits if b]


def _has_home_offers(watch: Dict[str, Any]) -> bool:
    return bool(
        (watch.get("subscription") or [])
        or (watch.get("rent") or [])
        or (watch.get("buy") or [])
        or (watch.get("free") or [])
    )


def _infer_watch_status(watch: Dict[str, Any]) -> str:
    """Backcompat when status omitted. Empty lists alone are NEVER verified_no_home_offers."""
    has = _has_home_offers(watch)
    if watch.get("theaters_only") and not has:
        return "verified_no_home_offers"
    if has:
        return "verified_offers"
    return "unverified"


def _norm_watch(watch: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize watch payload for compare/store (no provenance fields).

    status: verified_offers | verified_no_home_offers | unverified
    free: optional [{service, via}] for free/ad-supported tiers.
    Missing status inferred conservatively (empty != verified no-offers).
    """
    if not isinstance(watch, dict):
        raise ValueError("watch_not_object")
    out: Dict[str, Any] = {}
    theaters = bool(watch.get("theaters_only"))
    out["theaters_only"] = theaters
    out["home_offers"] = bool(watch.get("home_offers", not theaters))

    def _list(key):
        v = watch.get(key) if key in watch else []
        if v is None:
            v = []
        if not isinstance(v, list):
            raise ValueError("watch_" + key + "_not_list")
        return v

    out["subscription"] = _list("subscription")
    out["rent"] = _list("rent")
    out["buy"] = _list("buy")
    out["free"] = _list("free")

    raw_status = watch.get("status")
    if raw_status is None or raw_status == "":
        status = _infer_watch_status(out)
    else:
        if not isinstance(raw_status, str):
            raise ValueError("watch_status_not_string")
        status = raw_status.strip()
        if status not in WATCH_STATUSES:
            # Unknown/legacy labels: fail closed — never relabel to verified_*
            raise ValueError("watch_status_invalid")

    has = _has_home_offers(out)
    if status == "verified_offers" and not has:
        raise ValueError("watch_status_contradiction_verified_offers_empty")
    if status == "verified_no_home_offers" and has:
        raise ValueError("watch_status_contradiction_no_home_with_offers")

    out["status"] = status
    if status == "verified_no_home_offers":
        out["home_offers"] = False
    elif status == "verified_offers":
        out["home_offers"] = True
    return out


def format_watch_suffix(watch: Dict[str, Any]) -> str:
    status = watch.get("status") or _infer_watch_status(watch)
    if status == "unverified":
        return "Availability unverified"
    if status == "verified_no_home_offers":
        return "Theaters only" if watch.get("theaters_only") else "No home offers"
    parts = []
    bits = _offer_bits(watch.get("subscription") or [])
    if bits:
        parts.append("Sub: " + ", ".join(bits))
    bits = _offer_bits(watch.get("free") or [])
    if bits:
        parts.append("Free: " + ", ".join(bits))
    for key, label in (("rent", "Rent"), ("buy", "Buy")):
        vals = []
        for x in (watch.get(key) or []):
            if isinstance(x, dict):
                name = str(x.get("service") or x.get("name") or "").strip()
                via = str(x.get("via") or "").strip()
                val = (name + (" (" + via + ")" if via else "")).strip()
            else:
                val = str(x).strip()
            if val:
                vals.append(val)
        if vals:
            parts.append(label + ": " + ", ".join(vals))
    if not parts:
        return "Availability unverified"
    return " · ".join(parts)


def strip_watch_suffix(meta: Optional[str]) -> str:
    """Remove a previously appended where-to-watch suffix so re-apply is stable."""
    if not meta:
        return ""
    base = str(meta)
    markers = (
        " · Availability unverified",
        " · Theaters only",
        " · No home offers",
        " · Sub: ",
        " · Free: ",
        " · Rent: ",
        " · Buy: ",
    )
    cut = len(base)
    for m in markers:
        i = base.find(m)
        if i >= 0:
            cut = min(cut, i)
    return base[:cut].rstrip(" ·")


def merge_meta_watch(existing_meta: Optional[str], watch: Dict[str, Any]) -> str:
    base = strip_watch_suffix(existing_meta)
    suffix = format_watch_suffix(watch)
    if not suffix:
        return base
    return (base + " · " + suffix) if base else suffix


def cmd_metadata(args: argparse.Namespace) -> int:
    """Metadata-only update for an existing displayed card (where-to-watch)."""
    picks_path = Path(args.picks) if args.picks else PICKS
    last_path = Path(args.last_good) if args.last_good else LAST
    live_path = Path(args.live) if args.live else LIVE
    lock_path = picks_path.parent / "picks.lock"

    raw_watch = args.watch_json
    raw_desc = getattr(args, "description", None)
    if raw_watch is None and raw_desc is None:
        print(json.dumps({"ok": False, "error": "missing_watch_json_or_description"}))
        return 1

    watch_in = None
    watch_norm = None
    if raw_watch is not None:
        if len(raw_watch.encode("utf-8")) > WATCH_JSON_MAX:
            print(json.dumps({"ok": False, "error": "watch_json_too_large", "max": WATCH_JSON_MAX}))
            return 1
        try:
            watch_in = json.loads(raw_watch)
        except Exception:
            print(json.dumps({"ok": False, "error": "watch_json_invalid"}))
            return 1
        try:
            watch_norm = _norm_watch(watch_in)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": "watch_invalid", "detail": str(e)}))
            return 1

    desc_out = None
    desc_provided = raw_desc is not None
    if desc_provided:
        desc = str(raw_desc).strip()
        if not desc:
            print(json.dumps({"ok": False, "error": "description_empty"}))
            return 1
        if len(desc) > DESCRIPTION_MAX:
            print(json.dumps({"ok": False, "error": "description_too_large", "max": DESCRIPTION_MAX, "len": len(desc)}))
            return 1
        if "\x00" in desc or any(ord(ch) < 9 for ch in desc):
            print(json.dumps({"ok": False, "error": "description_invalid"}))
            return 1
        desc_out = desc

    source = (args.source or "publish-picks-metadata").strip()
    if not source or len(source) > WATCH_SOURCE_MAX:
        print(json.dumps({"ok": False, "error": "bad_source"}))
        return 1

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        cur = load(picks_path) or load(last_path)
        if not cur:
            print(json.dumps({"ok": False, "error": "no_current_picks"}))
            return 1
        try:
            validate_picks(cur)
        except ValueError as e:
            lg = load(last_path)
            if not lg:
                print(json.dumps({"ok": False, "error": "corrupt_and_no_last_good", "detail": str(e)}))
                return 1
            cur = lg
            validate_picks(cur)

        if cur["revision"] != args.expected_revision:
            print(json.dumps({
                "ok": False, "error": "cas_revision_mismatch",
                "current": cur["revision"], "expected": args.expected_revision
            }))
            return 1

        slot = cur["slots"].get(args.slot)
        if not slot:
            print(json.dumps({"ok": False, "error": "missing_slot"}))
            return 1
        if (slot.get("title") or "") != args.title:
            print(json.dumps({
                "ok": False, "error": "title_mismatch",
                "current": slot.get("title"), "expected": args.title
            }))
            return 1
        if slot.get("tmdb_id") != args.tmdb_id:
            print(json.dumps({
                "ok": False, "error": "tmdb_mismatch",
                "current": slot.get("tmdb_id"), "expected": args.tmdb_id
            }))
            return 1

        stamp = now_iso()

        # Watch: update from --watch-json, else preserve existing object byte-for-byte (provenance exact)
        prev_w = slot.get("watch_availability")
        if watch_norm is not None:
            new_meta = merge_meta_watch(slot.get("meta"), watch_norm)
            if len(new_meta) > META_MAX:
                print(json.dumps({"ok": False, "error": "meta_too_large", "max": META_MAX, "len": len(new_meta)}))
                return 1
            watch_store = dict(watch_norm)
            watch_store["updated_at"] = stamp
            watch_store["source"] = source
            checked = (watch_in or {}).get("checked_at")
            if checked is not None and str(checked).strip():
                watch_store["checked_at"] = str(checked).strip()[:80]
            elif isinstance(prev_w, dict) and prev_w.get("checked_at"):
                watch_store["checked_at"] = prev_w.get("checked_at")
        else:
            new_meta = slot.get("meta")
            watch_store = json.loads(json.dumps(prev_w)) if isinstance(prev_w, dict) else None

        # Description: set if provided; else preserve existing (including absence)
        if desc_provided:
            final_desc = desc_out
        else:
            final_desc = slot["description"] if "description" in slot else None

        # Idempotency
        prev_cmp = None
        if isinstance(prev_w, dict):
            try:
                prev_cmp = _norm_watch(prev_w)
            except ValueError:
                prev_cmp = None
        watch_unchanged = True
        if watch_norm is not None:
            watch_unchanged = (prev_cmp == watch_norm and (slot.get("meta") or "") == (new_meta or ""))
        desc_unchanged = True
        if desc_provided:
            desc_unchanged = (slot.get("description") == final_desc)
        if watch_unchanged and desc_unchanged:
            print(json.dumps({
                "ok": True, "idempotent": True, "revision": cur["revision"],
                "slot_id": args.slot, "title": args.title, "tmdb_id": args.tmdb_id,
                "description": slot.get("description"),
                "watch_availability": prev_w,
            }))
            return 0

        nxt = json.loads(json.dumps(cur))
        s2 = nxt["slots"][args.slot]
        for k in ("slot_id", "title", "tmdb_id", "media_type", "year", "poster", "why", "credits", "source_event_id"):
            s2[k] = slot.get(k)
        s2["meta"] = new_meta
        if watch_store is not None:
            s2["watch_availability"] = watch_store
        elif "watch_availability" in s2:
            del s2["watch_availability"]
        if final_desc is not None:
            s2["description"] = final_desc
        elif "description" in s2:
            del s2["description"]
        nxt["revision"] = cur["revision"] + 1
        nxt["updated_at"] = stamp
        try:
            validate_picks(nxt)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": "validation_failed", "detail": str(e)}))
            return 1

        atomic_write(picks_path, nxt)
        atomic_write(last_path, nxt)
        if not args.fixture_only:
            atomic_write(live_path, nxt)
            try:
                atomic_write(PUB, nxt)
            except Exception:
                pass
        print(json.dumps({
            "ok": True,
            "revision": nxt["revision"],
            "slot_id": args.slot,
            "title": args.title,
            "tmdb_id": args.tmdb_id,
            "meta": new_meta,
            "description": final_desc,
            "watch_availability": watch_store,
            "updated_at": stamp,
        }))
        return 0



# ---------------- STAGED genres-v1 commands ----------------
def _canon_sha(o) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _paths(args):
    return (Path(args.picks) if args.picks else PICKS, Path(args.last_good) if args.last_good else LAST, Path(args.live) if args.live else LIVE)


def _load_current(picks_path, last_path):
    cur = load(picks_path) or load(last_path)
    if not cur:
        return None, "no_current_picks"
    try:
        validate_picks(cur)
    except ValueError:
        cur = load(last_path)
        if not cur:
            return None, "corrupt_and_no_last_good"
        validate_picks(cur)
    return cur, None


def _commit(args, cur, nxt):
    picks_path, last_path, live_path = _paths(args)
    try:
        validate_picks(nxt)
    except ValueError as e:
        return {"ok": False, "error": "validation_failed", "detail": str(e)}
    atomic_write(picks_path, nxt)
    atomic_write(last_path, nxt)
    if not args.fixture_only:
        atomic_write(live_path, nxt)
        try:
            atomic_write(PUB, nxt)
        except Exception:
            pass
    return None


def _out(d, code):
    print(json.dumps(d)); return code


def _events(path):
    out = []
    if path and path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return [e for e in out if not e.get("test")]


def cmd_set_genres(args) -> int:
    """One-time (or full re-seed) write of genres[] (+ optional in_theaters) under ONE CAS. Legacy slots preserved verbatim."""
    picks_path, last_path, _ = _paths(args)
    body = json.loads(Path(args.genres_file).read_text(encoding="utf-8"))
    lock_path = picks_path.parent / "picks.lock"; lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        cur, err = _load_current(picks_path, last_path)
        if err:
            return _out({"ok": False, "error": err}, 1)
        if cur.get("genres_setup_id") == args.setup_id:
            return _out({"ok": True, "idempotent": True, "revision": cur["revision"]}, 0)
        if cur["revision"] != args.expected_revision:
            return _out({"ok": False, "error": "cas_revision_mismatch", "current": cur["revision"], "expected": args.expected_revision}, 1)
        voted = {int(e["tmdb_id"]) for e in _events(Path(args.votes) if args.votes else VOTES) + _events(Path(args.actions) if args.actions else ACTIONS) if e.get("tmdb_id")}
        for g in body.get("genres") or []:
            for era in ("new", "classic"):
                c = g.get(era)
                if isinstance(c, dict):
                    if c.get("tmdb_id") in voted:
                        return _out({"ok": False, "error": "previously_voted_tmdb", "card": c.get("slot_id")}, 1)
                    if c.get("source_event_id") is not None:
                        return _out({"ok": False, "error": "seed_card_must_not_claim_event", "card": c.get("slot_id")}, 1)
        nxt = json.loads(json.dumps(cur)); stamp = now_iso()
        nxt["extensions"] = sorted(set(nxt.get("extensions") or []) | {"genres-v1"} | ({"in_theaters-v1"} if "in_theaters" in body else set()))
        nxt["genres"] = body["genres"]
        if "in_theaters" in body:
            nxt["in_theaters"] = body["in_theaters"]
        nxt["genres_setup_id"] = args.setup_id; nxt["revision"] = cur["revision"] + 1; nxt["updated_at"] = stamp
        if nxt["slots"] != cur["slots"]:
            return _out({"ok": False, "error": "internal_slots_changed"}, 1)
        e = _commit(args, cur, nxt)
        if e:
            return _out(e, 1)
        return _out({"ok": True, "revision": nxt["revision"], "setup_id": args.setup_id, "updated_at": stamp, "slots_sha": _canon_sha(nxt["slots"]),
                     "genres_sha": _canon_sha(nxt["genres"]), "in_theaters_sha": _canon_sha(nxt.get("in_theaters"))}, 0)


def cmd_set_theaters(args) -> int:
    """Replace ONLY in_theaters (separate field; never touches slots/genres)."""
    picks_path, last_path, _ = _paths(args)
    body = json.loads(Path(args.theaters_file).read_text(encoding="utf-8"))
    lock_path = picks_path.parent / "picks.lock"; lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        cur, err = _load_current(picks_path, last_path)
        if err:
            return _out({"ok": False, "error": err}, 1)
        if cur["revision"] != args.expected_revision:
            return _out({"ok": False, "error": "cas_revision_mismatch", "current": cur["revision"], "expected": args.expected_revision}, 1)
        nxt = json.loads(json.dumps(cur)); stamp = now_iso()
        nxt["extensions"] = sorted(set(nxt.get("extensions") or []) | {"in_theaters-v1"})
        nxt["in_theaters"] = body; nxt["revision"] = cur["revision"] + 1; nxt["updated_at"] = stamp
        e = _commit(args, cur, nxt)
        if e:
            return _out(e, 1)
        return _out({"ok": True, "revision": nxt["revision"], "in_theaters_sha": _canon_sha(body), "updated_at": stamp}, 0)


def cmd_replace_card(args) -> int:
    """Replace exactly ONE genre card (genre:<gid>:<era>) from a real Frame event on that card. ONE CAS carries identity + description + watch_availability."""
    p = GC.parse(args.card)
    if not p or p[0] != "genre":
        return _out({"ok": False, "error": "bad_card_id"}, 1)
    _, gid, era = p
    picks_path, last_path, _ = _paths(args)
    lock_path = picks_path.parent / "picks.lock"; lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        cur, err = _load_current(picks_path, last_path)
        if err:
            return _out({"ok": False, "error": err}, 1)
        if "genres" not in cur:
            return _out({"ok": False, "error": "genres_not_initialized"}, 1)
        for cid, c in GC.all_cards(cur):
            if c.get("source_event_id") == args.source_event_id:
                return _out({"ok": True, "idempotent": True, "revision": cur["revision"], "slot_id": cid}, 0)
        if cur["revision"] != args.expected_revision:
            return _out({"ok": False, "error": "cas_revision_mismatch", "current": cur["revision"], "expected": args.expected_revision}, 1)
        votes_path = Path(args.votes) if args.votes else VOTES; actions_path = Path(args.actions) if args.actions else ACTIONS
        ev = find_event(args.source_event_id, votes_path, actions_path)
        if not ev:
            return _out({"ok": False, "error": "event_not_found"}, 1)
        if ev.get("test"):
            return _out({"ok": False, "error": "test_event_not_allowed"}, 1)
        if ev.get("slot_id") != args.card:
            return _out({"ok": False, "error": "event_slot_mismatch", "event_slot": ev.get("slot_id"), "requested": args.card}, 1)
        is_action = ev.get("schema") == "movie_night_action_v1" or ev.get("action") in ("watched", "next")
        if (is_action and ev.get("action") not in ("watched", "next")) or (not is_action and ev.get("vote") not in ("up", "down")):
            return _out({"ok": False, "error": "bad_event_kind"}, 1)
        shown = GC.resolve(cur, args.card)
        if not shown or (shown.get("title") or "").strip().lower() != (ev.get("title") or "").strip().lower() or \
                (ev.get("tmdb_id") is not None and shown.get("tmdb_id") != int(ev["tmdb_id"])):
            return _out({"ok": False, "error": "event_not_for_current_card", "current_title": (shown or {}).get("title")}, 1)
        year = int(args.year)
        if not GC.era_ok(era, year, CLASSIC_MAX_YEAR):
            return _out({"ok": False, "error": era + "_ineligible", "classic_max_year": CLASSIC_MAX_YEAR}, 1)
        gids = [int(x) for x in args.tmdb_genre_ids.split(",") if x.strip()]
        if not GC.in_genre(gid, gids):
            return _out({"ok": False, "error": "not_in_genre", "genre": gid, "tmdb_genre_ids": gids}, 1)
        for cid, c in GC.all_cards(cur):
            if cid.startswith("genre:") and cid != args.card and (c.get("tmdb_id") == args.tmdb_id or (c.get("title") or "").lower() == args.title.lower()):
                return _out({"ok": False, "error": "already_displayed", "card": cid}, 1)
        if args.tmdb_id == shown.get("tmdb_id"):
            return _out({"ok": False, "error": "same_film_as_outgoing"}, 1)
        for e in _events(votes_path) + _events(actions_path):
            if (e.get("tmdb_id") is not None and int(e["tmdb_id"]) == args.tmdb_id) or (e.get("title") or "").lower() == args.title.lower():
                return _out({"ok": False, "error": "previously_voted_or_acted", "event_slot": e.get("slot_id")}, 1)
        if not args.poster_datauri.startswith("data:image"):
            return _out({"ok": False, "error": "bad_poster"}, 1)
        if len(args.watch_json.encode("utf-8")) > WATCH_JSON_MAX:
            return _out({"ok": False, "error": "watch_json_too_large"}, 1)
        try:
            win = json.loads(args.watch_json); wn = _norm_watch(win)
        except Exception as e:
            return _out({"ok": False, "error": "watch_invalid", "detail": str(e)}, 1)
        if wn["status"] not in GC.HOME_STATUSES or wn["theaters_only"]:
            return _out({"ok": False, "error": "not_home_eligible", "status": wn["status"]}, 1)
        src = (args.source or "").strip()
        if not src or len(src) > WATCH_SOURCE_MAX or not str(win.get("checked_at") or "").strip():
            return _out({"ok": False, "error": "watch_provenance_required"}, 1)
        stamp = now_iso()
        watch = dict(wn, source=src, checked_at=str(win["checked_at"]).strip()[:80], updated_at=stamp)
        alerts = []
        if args.description is not None:
            d = args.description.strip()
            if not d or len(d) > DESCRIPTION_MAX or any(ord(ch) < 9 for ch in d):
                return _out({"ok": False, "error": "description_invalid"}, 1)
        elif args.description_missing_alert:
            d = None; alerts.append("description")
        else:
            return _out({"ok": False, "error": "description_or_missing_alert_required"}, 1)
        card = {"slot_id": args.card, "title": args.title, "tmdb_id": args.tmdb_id, "media_type": "movie", "year": year, "poster": args.poster_datauri,
                "why": args.why, "description": d, "description_source": args.description_source, "meta": args.meta, "rating": args.rating,
                "credits": args.credits, "tmdb_genre_ids": gids, "genres": [GC.TMDB_NAME.get(x, str(x)) for x in gids if x in GC.TMDB_NAME],
                "watch_availability": watch, "source_event_id": args.source_event_id, "replaced": {"title": shown.get("title"), "tmdb_id": shown.get("tmdb_id")}}
        if wn["status"] == "unverified":
            alerts.append("watch_availability")
        if alerts:
            card["metadata_alerts"] = alerts
        nxt = json.loads(json.dumps(cur))
        for g in nxt["genres"]:
            if g["genre_id"] == gid:
                g[era] = card
        nxt["revision"] = cur["revision"] + 1; nxt["updated_at"] = stamp
        e = _commit(args, cur, nxt)
        if e:
            return _out(e, 1)
        return _out({"ok": True, "revision": nxt["revision"], "slot_id": args.card, "source_event_id": args.source_event_id, "title": args.title,
                     "tmdb_id": args.tmdb_id, "description": d, "watch_availability": watch, "metadata_alerts": alerts, "updated_at": stamp,
                     "card_sha": _canon_sha(card), "poster_sha": _canon_sha(args.poster_datauri)}, 0)


def cmd_show(_: argparse.Namespace) -> int:
    p = load(PICKS) or load(LAST)
    if not p:
        print(json.dumps({"ok": False, "error": "missing"})); return 1
    # omit huge posters in show
    slim = json.loads(json.dumps(p))
    for s in slim.get("slots", {}).values():
        if s.get("poster"):
            s["poster"] = "<datauri %d chars>" % len(s["poster"])
    print(json.dumps({"ok": True, "picks": slim}, indent=2)); return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replace")
    r.add_argument("--slot", required=True, choices=["new", "classic"])
    r.add_argument("--expected-revision", type=int, required=True)
    r.add_argument("--source-event-id", required=True)
    r.add_argument("--title", required=True)
    r.add_argument("--year", type=int, required=True)
    r.add_argument("--tmdb-id", type=int, default=None)
    r.add_argument("--why", required=True)
    r.add_argument("--poster-datauri", required=True)
    r.add_argument("--meta", default=None)
    r.add_argument("--credits", default=None)
    r.add_argument("--description", default=None,
                   help="optional short plain-text movie description (supplied source only; never invented)")
    r.add_argument("--watch-json", default=None,
                   help="optional JSON (same schema as metadata): status, theaters_only, subscription/free/rent/buy, checked_at")
    r.add_argument("--source", default="publish-picks-replace",
                   help="watch provenance label when --watch-json set (no secrets)")
    r.add_argument("--votes", default=None)
    r.add_argument("--picks", default=None)
    r.add_argument("--last-good", default=None)
    r.add_argument("--live", default=None)
    r.add_argument("--fixture-only", action="store_true")
    r.set_defaults(func=cmd_replace)
    m = sub.add_parser("metadata", help="metadata-only where-to-watch update for a currently displayed card")
    m.add_argument("--slot", required=True, choices=["new", "classic"])
    m.add_argument("--expected-revision", type=int, required=True)
    m.add_argument("--title", required=True)
    m.add_argument("--tmdb-id", type=int, required=True)
    m.add_argument("--watch-json", default=None, help="optional JSON: status, theaters_only, subscription/free/rent/buy, checked_at (omit to preserve watch exactly)")
    m.add_argument("--description", default=None, help="optional short plain-text plot (supplied source only; omit leaves unchanged)")
    m.add_argument("--source", default="publish-picks-metadata", help="provenance label when --watch-json set (no secrets)")
    m.add_argument("--picks", default=None)
    m.add_argument("--last-good", default=None)
    m.add_argument("--live", default=None)
    m.add_argument("--fixture-only", action="store_true")
    m.set_defaults(func=cmd_metadata)
    for name, fn in (("set-genres", cmd_set_genres), ("set-theaters", cmd_set_theaters), ("replace-card", cmd_replace_card)):
        g = sub.add_parser(name); g.set_defaults(func=fn)
        g.add_argument("--expected-revision", type=int, required=True)
        for k in ("--picks", "--last-good", "--live", "--votes", "--actions"):
            g.add_argument(k, default=None)
        g.add_argument("--fixture-only", action="store_true")
        if name == "set-genres":
            g.add_argument("--genres-file", required=True); g.add_argument("--setup-id", required=True)
        if name == "set-theaters":
            g.add_argument("--theaters-file", required=True)
        if name == "replace-card":
            g.add_argument("--card", required=True); g.add_argument("--source-event-id", required=True); g.add_argument("--title", required=True)
            g.add_argument("--year", type=int, required=True); g.add_argument("--tmdb-id", type=int, required=True); g.add_argument("--tmdb-genre-ids", required=True)
            g.add_argument("--why", required=True); g.add_argument("--poster-datauri", required=True); g.add_argument("--meta", default=None)
            g.add_argument("--rating", type=int, default=None); g.add_argument("--credits", default=None)
            g.add_argument("--description", default=None); g.add_argument("--description-source", default=None); g.add_argument("--description-missing-alert", action="store_true")
            g.add_argument("--watch-json", required=True); g.add_argument("--source", required=True)
    s = sub.add_parser("show"); s.set_defaults(func=cmd_show)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
