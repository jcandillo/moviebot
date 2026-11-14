---
name: moviebot-frame-movie-night
description: >-
  Use when selecting, publishing, or verifying MovieBot Movie Night picks on an
  optional photo-frame display — Watch at Home genre cards (New/Classic) with
  required description and where-to-watch, In Theaters, Rent/Buy and
  Unsubscribed views, votes/Watched/Next feedback, guarded compare-and-swap
  publish, and wake intake/apply/regenerate. The frame is a display sink only.
---
# MovieBot frame Movie Night (optional integration)

This skill applies only when you use `integrations/photo-frame/` with a photo-frame dashboard or compatible kiosk. MovieBot core runs without it. Your instance's Architecture document is the source of truth (see `docs/architecture.md`; keep your own instance copy private).

## Mission
Recommend **quality, curated movies** from the owner's preferences and confirmed watch history. Feedback is **urgent** — apply it every wake before the next pick. **Where to watch is required for every pick on every surface.**

## Roles
- **MovieBot (the agent)** owns the movies page: data, layout, selection and the publish step into `picks.json`. It also owns the vote wake and the daily ~8 AM user-local review.
- **Display host** (the machine serving the frame) only serves files and records votes/actions. It never selects titles.
- **Other helper agents** may assist with display plumbing only when the owner asks; they never own the movies page.
- **Owner approval:** changes to what the frame renders need the owner's explicit OK through your host's normal approval flow.

## Views on the movies page
1. **Watch at Home** — genre buttons (Comedy, Action & Adventure, Sci-Fi, Drama, Thriller, Family; TMDB genres), each with a New and a Classic card. Ad-free subscription streaming only (see home gate; no ad-supported services).
2. **In Theaters** — separate view; titles, genre/type, description and cinema names; no showtimes.
3. **Rent/Buy** — read-only, rent/buy-only titles.
4. **Unsubscribed** — read-only, one sub-tab per major streaming service the owner does not have.

In Theaters and Rent/Buy show all movies side by side with the TMDB genre under each title. Every title keeps its TMDB-overview description and where-to-watch.

## Subscription-aware home gate
- Watch at Home is eligible only with a US flatrate offer on a service in the owner's fresh `verified_active` subscription records (verified tier; bundle/channel aliases mapped). Free/AVOD and other ad-supported offers never qualify (owner 2026-11-13).
- `likely_active` and `unknown` never qualify. Provider availability, connector reachability and library lists are not proof of payment. Unknown stays unknown.
- No qualifying offer: Rent/Buy if paid options exist, else hold. Never say "your X" for an unverified service.
- An explicit, dated owner confirmation is a valid `verified_active` source (source=human). Receipts and renewal emails are supporting evidence and never block the gate.
- A passed renewal date with no fresh evidence becomes `unknown`, never inactive. No account or billing changes.
- **No ad-supported services (owner 2026-11-13):** Flag `exclude_ad_supported_services` (true) plus `ad_policy.json` next to entitlements. Blocked: FAST/AVOD (Tubi, Pluto, Roku Channel, free ad-supported Plex, Freevee and similar), live TV / cable apps with ads (Philo, Fubo, YouTube TV, Sling and similar), and named ad tiers (Essential, with Ads). Paramount+ matches only through a YouTube Primetime Channels-style channel path when that is how the owner has it. Rollback: set the flag false and republish through CAS.

## Rent/Buy view
- Rent/buy-only titles move here (description + provider + rent/buy labels + dated check). No prices, votes, Watched/Next, sign-up links or transaction controls.
- A home title with qualifying ad-free subscription streaming plus optional rent/buy stays on home: the qualifying streaming provider is its where-to-watch line, and paid alternatives go on a separate labeled line.
- `unverified` or `verified_no_home_offers` titles are not home-eligible.
- **Spec-only (not in this repository yet):** a guarded `publish-picks.py migrate-rent-buy` step that moves paid-only titles out of home in one compare-and-swap and writes `rent_buy {status, checked_at, note, items[]}`. Known limitation of the reference design: Rent/Buy is not auto-refreshed; an update that would leave an ineligible home title must be rejected for explicit repair, never silently re-verified.

## Unsubscribed view
- One sub-tab per major US streaming service the owner does not have as `verified_active`. Ad-supported live-TV / FAST services (YouTube TV, Philo, Fubo, Sling and similar) are excluded as tabs.
- Each sub-tab shows the **top 10** taste-matched movies on that service's **no-ads** flatrate offer only (owner 2026-11-13 NA2). Ad-tier plan names never qualify a title for a tab.
- Label services whose status is unknown "not confirmed". Once the owner explicitly confirms they do not subscribe, label it **"not subscribed"**.
- Read-only: no prices, sign-up links or transaction controls; never implies the owner has the service; never counts toward Watch at Home eligibility. Hide empty sub-tabs.
- Precedence: a title also available on a `verified_active` ad-free subscription belongs to Watch at Home (if picked) and is excluded from every Unsubscribed sub-tab. Free/ads offers do not win Watch at Home precedence.
- A rentable title that also streams on an unsubscribed service may appear in both Rent/Buy and Unsubscribed, with both access types labeled in its where-to-watch note.
- **Spec-only:** the reference `index.html` currently renders Watch at Home and In Theaters; Rent/Buy and Unsubscribed views are specified here but not yet implemented in this repository.

## In Theaters — titles-only contract
- Use dated local showtimes-source pages (currently public showtimes.com theater pages) for the owner's configured home area and radius; never national-release guesses.
- **Any first-rate theater qualifies; exclude discount or second-rate experiences** (independents are not excluded by category).
- Public docs, examples and screenshots stay chain-only (national chains such as AMC, Cinemark, Regal, Alamo Drafthouse) with no branch, city or area. Specific cinemas, locations and radius live only in gitignored `config/local.json`.
- Show titles, genre/type, spoiler-free descriptions and cinema names; never session times, formats or showing counts. Preserve source URLs and listed/checked dates. Never infer tomorrow from today.
- Keep `in_theaters` isolated from streaming genres and provider data.
- Daily ~8 AM user-local refresh: `python3 theaters/local_showtimes.py build --out FILE`, then guarded `integrations/photo-frame/publish-picks.py set-theaters --expected-revision R --theaters-file FILE` and readback. Report real failures; stay silent on normal success.

## Authoritative data
- Picks: `picks.json` on the display host (+ last-good). Schema v1; integer `revision` for compare-and-swap; movies only; Classic year ≤ now−25.
- Each populated card must carry `description` (1–2 sentences, ≤280 chars, TMDB overview) and `watch_availability`.
- Optional `reported_subscriptions` in the picks doc lists owner-reported services first in where-to-watch lines; never an entitlement claim.
- Candidates: `./recommendations.json`. Taste: `moviebot.db` (`taste_signals`, `taste_latest`). Never commit databases or picks.

## Where-to-watch contract
`watch_availability` = {status: verified_offers | verified_no_home_offers | unverified, checked_at, theaters_only, home_offers, subscription, free, rent, buy}.
- **Spec path:** TMDB `movie/{id}/watch/providers` for the instance region, cached by id + region with checked_at and expiry; keep TMDB/JustWatch attribution.
- **Reference implementation today:** `pipeline/where_to_watch.py` parses public JustWatch US title pages (no keys). Check JustWatch's terms before relying on it; prefer the TMDB endpoint.
- Empty successful lookup = checked unavailable; failed lookup = unverified. Never invent offers, prices or links.
- No hold-back: if description or where-to-watch is missing, fill it from movie data or an explicit `unverified` status; if still unresolved, publish and alert the owner naming the missing field. Verify both fields in readback.

## Wake checklist
1. **IMPORT** votes/actions into `raw_votes.db` (event_id dedupe).
2. **APPLY** (`pipeline/feedback_apply.py`): up/down → `taste_signals`; Watched → one `viewing_events` row when evidence resolves (legacy new/classic or genre-card slots when `watched_genre_slot_evidence` is true); Next → neutral.
3. **REGENERATE** `recommendations.json` + pools.
4. **PLAN** stable same-slot selection; fetch current where-to-watch.
5. **VALIDATE + CAS publish** with `publish-picks.py replace`.
6. **Receipt** — record publish + readback; the frame polls every 15 s.

`integrations/photo-frame/wake_pipeline.sh VOTES ACTIONS PICKS` runs through plan (no publish). Env: `MOVIEBOT_DB`, `MOVIEBOT_BACKUP_DIR`, `RAW_DB`, `RECS`, `LEASE_TOKEN`.

## Feedback semantics
Thumbs → taste only. Next → same-slot replace, no taste/history. Watched → explicit viewing with displayed-title evidence; never invent a watch time. Genre-card slots (`genre:<genre>:new|classic`) are accepted by `picks_evidence()` when flag `reco/flags.json` `watched_genre_slot_evidence` is true (same revision/tmdb_id/title/media_type checks as legacy slots); set the flag false to restore prior behavior.

## Nov 12–13, 2026: genre-slot Watched evidence, published picks archive, change governance, no ad-supported services
- **Genre-slot Watched evidence:** `picks_evidence()` accepts genre-card slots by exact `slot_id`. Flag: `watched_genre_slot_evidence` (true; false restores previous behavior).
- **Published picks archive:** When `archive_published_picks` is true, `picks_archive.py` runs after each verified publish readback (hooked in `genre_flow.py` and `movie_night.py`, before feedback apply; not in legacy `wake_pipeline.sh`). It copies the readback file byte-for-byte to `feedback-intake/snapshots/picks-<YYYYMMDD-HHMM>-rev<N>.json`, verifies sha256, never overwrites (same sha = no-op; different sha kept with a suffix and logged in `archive_log.jsonl`), and writes only when `--db` is the production `raw_votes.db`. Rollback: set the flag false; for a full rollback restore the matching `.bak-archive-picks-*` files and remove `picks_archive.py`.
- **Governance:** Design, architecture, pipeline-behavior or code changes go to the architecture owner as a proposal first (what, why, risk, rollback). Owner approval lands on the Architecture Page and skills before runtime change. The vote-wake routine never edits code or flags; it reports blocking bugs instead of patching them.
- **No ad-supported services (NA1 / NA2):** `exclude_ad_supported_services` plus `ad_policy.json`. Free/ads never qualify for Watch at Home; ad services never appear in recommendations or as Unsubscribed tabs; Unsubscribed offers must be no-ads plans only. Instance CHANGELOG entries NA1 and NA2; rollback is the flag (and optional `ad_tier_names` key for NA2 alone).

## Wake credentials
Use your host's scheduler/webhook feature for the vote wake. The owner pastes the wake URL/key into a gitignored env file (`wake-webhook.env`) or the host's secure secret entry themselves; the agent never sees or echoes it.

## Release checks
Before pushing a movies-page change to the display: genre feedback API, CAS publish, planner and fresh readback must pass. Offline renders are examples, not proof of the physical display. Never claim deployment without evidence.

## Hard rules
- Movies only on the frame. Never paste webhook or TMDB secrets anywhere; never commit `moviebot.db`, picks or `config/local.json`.
