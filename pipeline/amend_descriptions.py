#!/usr/bin/env python3
"""Full (<=280 char) 1-2 sentence descriptions from the cached TMDB overview; never ellipsis-truncated. Rewrites data/picks.staging.json in place."""
import json, re, sqlite3
def desc280(ov):
    o = re.sub(r"\s+", " ", ov or "").strip(); s = re.split(r"(?<=[.!?])\s+", o)
    if not o: return None
    d = s[0]
    if len(s) > 1 and len(d) + 1 + len(s[1]) <= 280: d += " " + s[1]
    if len(d) <= 280: return d
    # first sentence >280: faithful shortening = keep the leading clauses (overview words only, no invention), end cleanly; never '…'
    cut = d[:279]; k = max(cut.rfind(", "), cut.rfind("; "), cut.rfind(" — "))
    return (cut[:k].rstrip(" ,;—") + ".") if k > 80 else None   # None -> caller publishes with alert naming 'description' 
if __name__ == "__main__":
    D = json.load(open("data/picks.staging.json")); db = sqlite3.connect("data/staging.db")
    nc = {(x[1] if isinstance(x, list) else x)["id"]: (x[1] if isinstance(x, list) else x) for x in json.load(open("./prototype/new_releases_candidates.json"))}
    def ov(t):
        if t in nc and nc[t].get("overview"): return nc[t]["overview"]
        r = db.execute("SELECT payload_json FROM tmdb_public_meta WHERE tmdb_id=? ORDER BY fetched_at DESC", (t,)).fetchall()
        for (j,) in r:
            o = json.loads(j).get("overview")
            if o: return o
    cards = [g[e] for g in D["genres"] for e in ("new", "classic") if g.get(e)] + D["in_theaters"]["items"]
    for c in cards:
        d = desc280(ov(c["tmdb_id"]))
        c["description"] = d; c["description_missing_alert"] = None if d else "overview missing or first sentence >280 chars"
        print(c["title"], len(d or ""), (d or "")[-25:])
    json.dump(D, open("data/picks.staging.json", "w"), indent=1)
