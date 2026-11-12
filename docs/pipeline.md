# Pipeline overview

Agent-host wake flow (no publish until the frame host runs CAS):

1. Claim a lease (`pipeline/lease.py`)
2. Import votes / actions (`pipeline/intake.py`, `pipeline/movie_night.py`)
3. Apply feedback and regenerate pools (`pipeline/feedback_apply.py`)
4. Plan stable same-slot selections (`pipeline/movie_night.py plan`)
5. Enrich with where-to-watch + description (`pipeline/where_to_watch.py`)
6. (Optional photo-frame) On the frame host: `integrations/photo-frame/publish-picks.py replace` / `set-theaters` with expected revision
7. (Optional) Native readback; record publish; release lease

Core MovieBot stops after enrich-plan. The optional helper `integrations/photo-frame/wake_pipeline.sh` wraps the same stages for a frame host. Paths for databases and recommendations are supplied by environment variables — never hard-code personal machine paths in this repo.

## Default working layout

Scripts run from the repository root and use these default paths (override with flags/env):

| Path | Purpose |
|---|---|
| `./moviebot.db` (`MOVIEBOT_DB`, `--moviebot-db`) | personal store, created from `docs/schema.sql` |
| `./feedback-intake/raw_votes.db` | feedback/lease ledger, auto-created (create the `feedback-intake/` folder first) |
| `./recommendations.json` | current candidate list |
| `./prototype/new_releases_candidates.json` | cached TMDB details for new-release candidates (JSON list) |
| `./backups/` (`MOVIEBOT_BACKUP_DIR`) | automatic DB backups before feedback apply |
| `config/local.json` (`MOVIEBOT_CONFIG`) | onboarding answers, reported subscriptions, theaters, Unsubscribed settings |

All of these are gitignored or local-only; never commit them.
