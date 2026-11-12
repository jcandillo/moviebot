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
1. **Watch at Home** — genre buttons (Comedy, Action & Adventure, Sci-Fi, Drama, Thriller, Family; TMDB genres), each with a New and a Classic card. Subscription/free streaming only (see home gate).
2. **In Theaters** — separate view; titles, genre/type, description and cinema names; no showtimes.
3. **Rent/Buy** — read-only, rent/buy-only titles.
4. **Unsubscribed** — read-only, one sub-tab per major streaming service the owner does not have.

In Theaters and Rent/Buy show all movies side by side with the TMDB genre under each title. Every title keeps its TMDB-overview description and where-to-watch.

## Subscription-aware home gate
- Watch at Home is eligible only with a US free/AVOD offer, or a US flatrate offer on a service in the owner's fresh `verified_active` subscription records (verified tier; bundle/channel aliases mapped).
- `likely_active` and `unknown` never qualify. Provider availability, connector reachability and library lists are not proof of payment. Unknown stays unknown.
- No qualifying offer: Rent/Buy if paid options exist, else hold. Never say "your X" for an unverified service.
- An explicit, dated owner confirmation is a valid `verified_active` source (source=human). Receipts and renewal emails are supporting evidence and never block the gate.
- A passed renewal date with no fresh evidence becomes `unknown`, never inactive. No account or billing changes.

## Rent/Buy view
- Rent/buy-only titles move here (description + provider + rent/buy labels + dated check). No prices, votes, Watched/Next, sign-up links or transaction controls.
- A home title with qualifying subscription/free streaming plus optional rent/buy stays on home: the qualifying streaming provider is its where-to-watch line, and paid alternatives go on a separate labeled line.
- `unverified` or `verified_no_home_offers` titles are not home-eligible.
- **Spec-only (not in this repository yet):** a guarded `publish-picks.py migrate-rent-buy` step that moves paid-only titles out of home in one compare-and-swap and writes `rent_buy {status, checked_at, note, items[]}`. Known limitation of the reference design: Rent/Buy is not auto-refreshed; an update that would leave an ineligible home title must be rejected for explicit repair, never silently re-verified.

## Unsubscribed view
- One sub-tab per major US streaming service the owner does not have as `verified_active`. Live-TV bundles such as **YouTube TV are excluded**.
- Each sub-tab shows the **top 10** taste-matched movies on that service's flatrate offer, as standard cards (description, provider, dated check).
- Label services whose status is unknown "not confirmed". Once the owner explicitly confirms they do not subscribe, label it **"not subscribed"**.
- Read-only: no prices, sign-up links or transaction controls; never implies the owner has the service; never counts toward Watch at Home eligibility. Hide empty sub-tabs.
- Precedence: a title also available on a `verified_active` subscription or free belongs to Watch at Home (if picked) and is excluded from every Unsubscribed sub-tab.
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
2. **APPLY** (`pipeline/feedback_apply.py`): up/down → `taste_signals`; Watched → one `viewing_events` row; Next → neutral.
3. **REGENERATE** `recommendations.json` + pools.
4. **PLAN** stable same-slot selection; fetch current where-to-watch.
5. **VALIDATE + CAS publish** with `publish-picks.py replace`.
6. **Receipt** — record publish + readback; the frame polls every 15 s.

`integrations/photo-frame/wake_pipeline.sh VOTES ACTIONS PICKS` runs through plan (no publish). Env: `MOVIEBOT_DB`, `MOVIEBOT_BACKUP_DIR`, `RAW_DB`, `RECS`, `LEASE_TOKEN`.

## Feedback semantics
Thumbs → taste only. Next → same-slot replace, no taste/history. Watched → explicit viewing; never invent a watch time.

## Wake credentials
Use your host's scheduler/webhook feature for the vote wake. The owner pastes the wake URL/key into a gitignored env file (`wake-webhook.env`) or the host's secure secret entry themselves; the agent never sees or echoes it.

## Release checks
Before pushing a movies-page change to the display: genre feedback API, CAS publish, planner and fresh readback must pass. Offline renders are examples, not proof of the physical display. Never claim deployment without evidence.

## Hard rules
- Movies only on the frame. Never paste webhook or TMDB secrets anywhere; never commit `moviebot.db`, picks or `config/local.json`.
