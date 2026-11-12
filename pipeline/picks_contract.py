"""Photo-frame picks slot contract (owner rule): EVERY slot must carry identity, a non-empty description and structured watch_availability.
Pure validation; no writes. Used by preflight (before native CAS), record-publish and record-backfill (own readback)."""
import json
STATUSES = ("verified_offers", "verified_no_home_offers", "unverified")
LISTS = ("subscription", "free", "rent", "buy")
DESC_MAX = 280
def watch_errors(w):
    if not isinstance(w, dict): return ["watch_availability_missing"]
    e = []
    st = w.get("status")
    if st not in STATUSES: e.append(f"watch_status_invalid:{st}")
    for k in LISTS:
        v = w.get(k)
        if not isinstance(v, list): e.append(f"watch_{k}_not_list"); continue
        for it in v:
            if k in ("subscription", "free"):
                if not (isinstance(it, dict) and isinstance(it.get("service"), str) and it["service"].strip()): e.append(f"watch_{k}_item_invalid")
            elif not (isinstance(it, str) and it.strip()): e.append(f"watch_{k}_item_invalid")
    for k in ("theaters_only", "home_offers"):
        if not isinstance(w.get(k), bool): e.append(f"watch_{k}_not_bool")
    if e: return e
    any_offer = any(w[k] for k in LISTS)
    if st == "verified_offers" and not any_offer: e.append("verified_offers_but_no_offers")
    if st == "verified_no_home_offers" and (any_offer or w["home_offers"]): e.append("no_home_offers_but_offers_listed")
    if st == "unverified" and (any_offer or w["home_offers"] or w["theaters_only"]): e.append("unverified_but_offers_asserted")
    if w["home_offers"] != bool(w["subscription"] or w["free"] or w["rent"] or w["buy"]): e.append("home_offers_inconsistent")
    if not (str(w.get("checked_at") or w.get("updated_at") or "").strip()): e.append("watch_no_check_time")
    if not str(w.get("source") or "").strip(): e.append("watch_no_source")
    return e
def slot_errors(s, slot_id=None):
    if not isinstance(s, dict): return ["slot_missing"]
    e = []
    for k in ("title", "tmdb_id", "year", "media_type", "poster"):
        if s.get(k) in (None, ""): e.append(f"identity_{k}_missing")
    if slot_id and s.get("slot_id") not in (None, slot_id): e.append("slot_id_mismatch")
    d = s.get("description")
    if not isinstance(d, str) or not d.strip(): e.append("description_missing")
    elif len(d) > DESC_MAX: e.append("description_too_long")
    e += watch_errors(s.get("watch_availability"))
    return e
def doc_errors(P):
    out = {}
    for sid in ("new", "classic"):
        er = slot_errors((P.get("slots") or {}).get(sid), sid)
        if er: out[sid] = er
    return out
