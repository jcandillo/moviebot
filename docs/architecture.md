# MovieBot — Architecture (public reference)

Cleaned public copy of the MovieBot architecture. It contains no personal data, accounts, locations or instance links. Keep **your own** instance Architecture document private and treat it as the source of truth for your instance; use this file as the starting template. Section numbers match the ones the skills cite.

Status legend used below: **[implemented]** = code exists in this repository · **[spec]** = requirement/design only · **[host]** = depends on your agent host's capabilities.

## 1. Optional integration: photo-frame dashboard
MovieBot runs without a photo frame, dashboard app, picks publisher, wake watcher or kiosk. The separate display project is <https://github.com/jcandillo/photo-frame-dashboard-android>; the movies page itself lives in `integrations/photo-frame/`. Neither project requires the other. Core code never imports display code; integration adapters consume core contracts.

- MovieBot owns movie data, selection, publishing and page layout; the display is a sink, never the recommender. Changes to what the display renders need the owner's explicit OK.
- **Watch at Home** [implemented]: six TMDB genre buttons — Comedy, Action & Adventure, Sci-Fi, Drama, Thriller, Family — each with New and Classic cards using the §12 card contract. Subscription/free streaming only.
- **Subscription-aware home gate**: a title qualifies only with a US free/AVOD offer, or a US flatrate offer on a service in the owner's fresh `verified_active` subscription records (verified tier; bundle/channel aliases mapped). `likely_active` and `unknown` never qualify; provider availability, connector reachability and library lists are not entitlement evidence. No qualifying offer → Rent/Buy if paid options exist, else hold. A dated owner confirmation is a valid `verified_active` source (source=human). A passed renewal date with no fresh evidence becomes `unknown`, never inactive.
- **Rent/Buy** [spec]: read-only rent/buy-only titles; description, providers, dated check; no prices, votes or transaction controls. A guarded `migrate-rent-buy` publisher step (one compare-and-swap, idempotent on `migration_id`) moves paid-only titles out of home. Known limitation: not auto-refreshed; ineligible updates are rejected for explicit repair.
- **Unsubscribed** [spec]: one sub-tab per major US streaming service the owner does not have as `verified_active`; **top 10** taste-matched movies on that service's flatrate offer; YouTube TV and other live-TV bundles excluded; unknown status labeled "not confirmed", and "not subscribed" once the owner confirms. Read-only; never counts toward home eligibility; empty sub-tabs hidden. A title also on a verified subscription or free is excluded from every Unsubscribed tab. A rentable title that also streams on an unsubscribed service may appear in both Rent/Buy and Unsubscribed with both access types labeled.
- **In Theaters** [implemented]: dated local showtimes-source pages (currently showtimes.com) for the owner's configured area/radius. **Any first-rate theater qualifies; exclude discount or second-rate experiences** (not independents by category). Titles, genre/type, §12 descriptions and theater names; never showtimes, formats or showing counts. Preserve source/listed/checked dates; never infer future listings. Stored in `in_theaters`, separate from streaming data. Locations, distances and branch IDs live only in gitignored `config/local.json`; public docs and examples stay chain-only.
- In Theaters and Rent/Buy lay out all movies side by side with the TMDB genre under each title.
- Before publishing, fill missing description or access data from cached records or an explicit `unverified` status; if still unresolved, publish and alert the owner naming the field. Read back every slot after publishing. Display mapping: `watch_availability` {status: verified_offers | verified_no_home_offers | unverified, checked_at, theaters_only, home_offers, subscription, free, rent, buy}. A failed lookup is not evidence of no offers.
- Release checks before a movies-page change: genre feedback API, compare-and-swap publish, planner and fresh readback. Offline renders are not proof of the physical display.

## 2. Recommendation and positioning
Build persistent media memory, not another streaming dashboard. MovieBot answers: "What would I enjoy this evening that I have not watched and can actually access?" The value is a trustworthy intersection of personal history, explicit taste, subscriptions, personal libraries and region-specific availability. This document specifies requirements, not deployment completion.

## 2a. Product architecture
Each user's agent runs an instance for exactly one human, with a personal catalog — no shared/global catalog, cross-user enrichment store or hosted multi-tenant product. The domain core owns accepted facts; connectors supply observations. Onboarding, catalog, recommendations, descriptions, where-to-watch, connectors and maintenance work without any display.

## 2b. Agent configuration
A maintainer role (a person or a separate agent) owns this architecture document, the skills and continuous improvement; the MovieBot agent operates the workflows. Chat relays cannot invent product rules. The MovieBot agent's instructions point at this document and load the matching skill when a workflow runs.

## 3. Goals and boundaries
Authorized reads need no fresh confirmation. Writes follow §9; subscription authority follows §5. No consumer UI beyond the view-only dashboard (§5b) and the optional display (§1).

## 4. Runtime architecture
- [spec] Modular core with a thin agent tool boundary, a storage repository interface and explicit SQLite migrations. Tool names and versioned JSON schemas define the product contract. One process plus a worker loop; no message bus, vector database, microservices or model service.
- [implemented] The reference implementation is a set of Python standard-library scripts (`pipeline/`, `theaters/`, `tools/`) over SQLite. The original design suggested a TypeScript modular monolith; any language is fine if the contracts hold.
- Commit a personal mutation, its audit receipt and any outbox entry in one transaction. Provider network calls run outside that transaction.
- The database is authoritative for accepted facts, not for a provider's current catalog. Availability is a dated observation. A metadata outage must not block reading history, changing a preference, marking a title seen or exporting data.

## 5. Streaming subscription workflow and maintenance [spec]
Subscription records are owner/agent-reported access, not provider billing truth (`service_subscriptions` in `docs/schema.sql`). Maintenance lists status/freshness, prompts on stale/unknown/suspected plan changes, commits the exact confirmed update, then recomputes access and invalidates dependent recommendation caches. Ending a subscription keeps titles and history and reframes them as "available if you resubscribe". Never cancel, buy or change plans without explicit approval.

## 5a. Workflows
- **Onboarding** [spec, skill `moviebot-onboarding`]: (1) record the service list privately and connect providers via the Connectors workflow; (2) one consolidated choose-all-that-apply genre question (Action, Adventure, Animation, Comedy, Crime, Documentary, Drama, Family, Fantasy, History, Horror, Music, Mystery, Romance, Science Fiction, Thriller, War, Western); (3) liked titles; (4) seed ratings on a three-point scale: love it / neutral / nope. Titles from 1985 or later during onboarding only. No picks during onboarding; if asked mid-onboarding, use a light reminder and continue. Answers are stored in the private store / `config/local.json` (`onboarding`), never in code.
- **Guided everywhere** [skill `moviebot-guided-workflows`]: every interaction offers concrete options or one clear next step; one decision at a time.
- **Streaming subscription**: help choose a plan (month-to-month / free trial where offered); the human decides and pays. Record tier/bundle and verified date; alert before known renewals; never auto-buy.
- **Cancellation** [skill `moviebot-cancellation`]: revoke the connector grant; get the owner's explicit confirmation before any unsubscribe step; one last check (watchlist titles on that service, renewal date); mark ended.
- **Connectors** [host, skill `moviebot-streaming-connector-setup`]: declare each service's supported capabilities; obtain the host's normal authorization (credential-manager approval first, then sign-in, then two-factor); pull supported watchlist, library and history. First connection only: stage history and ask for confirmation or sample verification. Later pulls merge quietly under the grant. Detect bundled services read-only and dedupe across catalogs. Verify the signed-in account is the right household member before reading anything. One service per run; never use payment options or change account settings.
- **Maintenance** [host, skill `moviebot-thursday-maintenance`]: a quiet daily review around 8 AM user-local; weekly connector health, subscription re-checks, cache cleanup, TMDB metadata refresh, recommendation recompute and documentation/skill audit. Each accepted recommendation queues a light refresh.
- **Continuous improvement** [skill `moviebot-continuous-improvement`]: update the architecture document first, then mirror `skills/<id>/SKILL.md` in your repository and your host's skill library. Weekly drift audit; stay quiet when unchanged.

## 5b. Dashboard [host]
A single view-only page: current settings, suggested titles, a separate anti-recommendations list, connector status and a taste summary, read from the same private store. All configuration happens through the agent under normal approval.

## 6. Concrete data model
See `docs/schema.sql` ([CORE-IMPLEMENTED] vs [SPEC] tables). Rules:
- One viewing event per viewing with source evidence, completion status and actual-or-unknown date with precision. Import time is not viewing time.
- Ratings, list membership, library inventory and dislikes never create viewing events. An explicit "seen it" response to a displayed recommendation may create a linked seen assertion with unknown date.
- Supporting records (provider connection by credential reference, event provenance, sync checkpoints, import batches, outbox jobs, approval grants, audit receipts) are part of the design. Raw provider payloads are short-lived staging data.
- Protect mutations with expected-revision compare-and-swap; paginate by stable cursor.

## 7. Identity and title resolution
Internal stable IDs with verified external aliases (TMDB id + media type). Resolve remakes and ambiguous matches with guided choices; never silently merge. A search may use connector title details but must not create personal history.

## 8. Agent tools [spec]
Product contracts, not pass-through wrappers. Reads need authentication only; writes are planned, then applied once after host approval. Every result includes schema_version, request_id, data, warnings, provenance and freshness. Stable error codes: AUTH_REQUIRED, FORBIDDEN, NEEDS_DISAMBIGUATION, APPROVAL_REQUIRED, STALE_PLAN, CONFLICT, PROVIDER_UNAVAILABLE, RATE_LIMITED. No generic HTTP proxy, SQL, shell, raw-token or arbitrary provider-method tool.

## 9. Write permission and confirmation
Use the host's normal approval protocol; nothing MovieBot-specific is required. Validate ownership server-side; a model-supplied `confirmed=true` is never sufficient. Skill sequence: read, resolve IDs, preserve uncertainty, propose exact writes, obtain consent, apply once, report.

## 10. Provider adapters
- TMDB supplies title metadata under its non-commercial terms with your own key (`docs/tmdb-api-key-setup.md`). No IMDb scraping. Cache with fetched_at/expires_at.
- **Where-to-watch spec path:** TMDB `movie/{id}/watch/providers` / `tv/{id}/watch/providers` for the instance region, with TMDB/JustWatch attribution. **Reference implementation today:** public JustWatch US pages parsed by `pipeline/where_to_watch.py` and public TMDB web pages for metadata — stopgaps that need no key; check provider terms and prefer the API path.
- Adapter interface: capabilities, search, getTitle, resolveIds, getAvailability, pullChanges, pushBatch — implement only supported methods; return normalized records with provenance and completeness.
- Normalize service aliases; channels, direct subscriptions and ad-supported tiers are not interchangeable. Keep rent and buy separate and never rank them as included.
- Freshness defaults: refresh active offers after 24 h; cache negative results briefly; show old observations as stale when refresh fails. Never invent leaving dates, prices, free status or deep links. If a connector is blocked, disable it; never scrape undocumented endpoints or swap credentials.

## 11. Sync and conflict resolution
Accepted local state wins without overwriting provider accounts. Start inbound-only; stage history and watchlists separately. Claim external delivery only after acknowledgment. Outbox: pending → leased → succeeded / retryable_failed / delivery_unknown / dead_letter, with backoff and per-connection locks.

## 12. Recommendation engine
Card contract for every suggestion and anti-recommendation: (1) short title; (2) one evidence-backed why line; (3) spoiler-free description from the cached TMDB overview, 1–2 sentences, ≤280 characters; (4) key cast and director; (5) TMDB vote average, labeled as TMDB's; (6) release year / first-air year; (7) where to watch — region, named providers, subscription/free first, rent and buy labeled separately, or an explicit checked-unavailable / unverified status. No runtime. A title is never on both lists (suggested wins). Explicit corrections to anti-recommendations are strong signals. Reasons must be reconstructible from stored evidence; never invent a personality.

## 12a. Preference and curation protocol (taste profile v3) [spec]
- Weights: confirmed loves / thumbs up / "more like this" 1.0; imported service ratings 0.7; "It was fine" 0.4; unconfirmed history 0 (exclusion only); thumbs down / "Not for me" negative.
- Watch-history interview: guided rounds of ~8 titles — Loved it / It was fine / Not for me / Didn't watch it.
- `title_metadata`: directors, writers, top cast, keywords, TMDB score/count, a few reviews, IMDb id — only what a real source returns.
- People affinity by role: director 2, writer/creator 1.5, lead 1, other cast 0.6; plus keyword and genre affinity.
- Why lines chosen at publish time; one seed title or person cited on at most 3 visible cards.
- Owner-gated options: publishing v3 why lines to a display; widening the candidate pool via TMDB person search.
- Instance-specific taste exceptions belong in the owner's private profile, never in shared docs or code.

## 13. Authentication and tenant isolation [spec]
Minimum scopes (catalog:read, history:read, taste:read, local:write, connections:manage, sync:pull, data:export, data:purge, ...). Agent identity and human identity are separate audit fields. Never reuse one person's token for another. Household sharing requires explicit grants.

## 14. Deployment and distribution
Default storage: SQLite on a persistent encrypted volume with encrypted backups. Optional vault for end-to-end encryption of history/preferences; protected JSON files as a last-resort backend (not E2E). One active writer. MIT license; publish only code, docs, skills, templates and synthetic fixtures.

## 15. Security, privacy and operations
Credentials live in a secret store, referenced by name only (`TMDB_API_KEY`). Never show keys, passwords or webhook URLs in chat, docs, skills, logs or Git. Never commit personal databases, picks, exports or `config/local.json`. Retention proposals: raw import payloads ≤7 days, operational logs 14 days, audit receipts 90 days, encrypted backups 30 days. Deletion covers rows, derived preferences, caches, staging, jobs and credentials as selected. Observe counts and timing, not titles.

## 16. Feature and function tracker
See the implemented-vs-spec table in `docs/REPLICATE.md` §18.

## 17. Streaming services library [spec]
Capability inventory per service (history pull, watchlist pull, title details, subscription details) with versioned methods; unsupported capabilities are marked unsupported, never improvised. Most streamers lack public consumer APIs; prefer Plex, Trakt and real APIs, and verified browser methods with provenance. "Major US streaming services" for the Unsubscribed view come from this inventory, excluding live-TV bundles.

## 18. Roadmap and acceptance tests
First end-to-end demonstration: an authorized connector stages two source-backed movie viewings and commits them; the human gives one dislike, asks for an unseen accessible movie, sees evidence-backed cards, marks one recommended title as already seen, approves a correction and exports the memory — all without a dashboard or display. Full acceptance checks: `docs/REPLICATE.md` §15.
