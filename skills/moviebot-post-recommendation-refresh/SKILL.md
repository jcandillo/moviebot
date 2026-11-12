---
name: moviebot-post-recommendation-refresh
description: >-
  Use after a successful/accepted MovieBot movie recommendation to queue a
  light recommendation refresh (event-driven, in addition to Thursday), keeping
  required where-to-watch current.
---
# MovieBot post-recommendation refresh

## When
After each successful/accepted movie recommendation.

## What
Queue a light refresh of suggested and anti lists — don't wait for Thursday. No 1985 floor (onboarding-only).

Every suggestion and anti-recommendation follows MovieBot recommendation card, including required **where to watch**. Refresh expired provider observations in SQLite; distinguish flatrate/rent/buy; prefer confirmed subscriptions; distinct explicit statuses for empty vs failed lookups; never omit or invent.

Frame candidates must satisfy MovieBot frame Movie Night's where_to_watch contract (fill misses from movie data, else publish and alert the owner; never hold). Changes to what an optional display renders need the owner's explicit OK.

## Do not
- Silent-cancel anything
- Re-run new-service history review
- Put a title on both lists (suggested wins)
- Expose TMDB keys or commit instance DBs

Architecture §12 + §5a + §1:
your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)

## Reco logging (optional; see `docs/reco.md`)
- Every display wake logs the cards shown and the reactions (`reco/reco_log.py log-picks` / `ingest-reactions`) and refreshes `reco/precompute.py`; these run inside the wake pipeline.
- If you publish outside the wake pipeline, run `python3 reco/reco_log.py log-picks <readback.json>` after the readback.
- Ranking and why lines follow the instance flags file (copy of `config/reco_flags.example.json`: `live_ranker`, `live_pool_widen`, `explore_thompson`, `why_v3_frame`). Never edit flags without an experiment changelog entry.
