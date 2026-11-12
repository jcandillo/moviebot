# For AI agents: build a MovieBot
## Build a MovieBot in this user’s system
This is a portable replication specification, not a request to join a hosted service. Implement the capabilities with your host’s tools and permissions; do not assume any particular agent vendor, browser, database service or display hardware.

## 1. Purpose and priority
Create a private, single-person media memory and recommendation assistant. Answer: what would this user enjoy, has not already watched, and can actually access? Start with a working private core and taste profile; do not delay it for a frame, elaborate UI or unsupported connectors. Movie night help should reduce decisions, not create false urgency or noisy alerts.
Reference implementation: https://github.com/jcandillo/moviebot
The repository’s skills/ folder contains reference workflows. Adapt their capabilities and safeguards to the host rather than copying tool names as if universally available. Distinguish implemented features from design goals and unsupported methods.

## 2. Check capabilities before setup
Check for private persistent storage, secure secret entry, TMDB access, permitted metadata/network reads, supported streaming imports, scheduling and a view-only dashboard. Explain missing capabilities with one concrete fallback (for example, a user-initiated review instead of a scheduled review). Never bypass sign-in, invent connector methods or claim an unavailable integration works. Keep configuration and implementation choices guided, with one decision at a time.

## 3. Onboard taste only—no recommendations yet
Use concrete selectable options, never an open-ended “what do you like?” interview. Offer one consolidated choose-all-that-apply genre question, then supported liked-title choices and seed ratings of love it / neutral / nope. Include Action, Adventure, Animation, Comedy, Crime, Documentary, Drama, Family, Fantasy, History, Horror, Music, Mystery, Romance, Science Fiction, Thriller, War and Western.
Use titles released in 1985 or later for onboarding choices only. This year floor does not restrict later recommendations. Record the user’s service list privately; account connections are a separate permissioned setup step. Do not select movies or TV shows during onboarding. Finish the profile first, then offer the recommendation flow.

## 4. Keep the user’s data in their own private store
Prefer a persistent encrypted SQLite store with encrypted backups; a protected structured-file backend may be used when the host cannot support a database. Do not describe ordinary JSON as end-to-end encrypted. Support private export, migration and recovery. No shared cross-user catalog of personal data.
Store:
• Profile and settings: stable IDs, region, language, timezone, retention choices and revisions.
• Watch history: one event per viewing, title identity, source evidence, completion status, actual or unknown viewing date and date precision. Import time is not viewing time.
• Preferences: explicit likes/dislikes, seed ratings, avoids, corrections and separately labeled inferences with provenance.
• Subscriptions: service, region, tier/bundle, active/paused/ended/unknown state, evidence and verification date.
• Watchlists: list membership, service/source, status and timestamps; membership is not a watched event.
• Titles and metadata: stable internal IDs, verified external IDs, media kind, overview, credits and source freshness.
• Availability observations: region, provider, monetization type, tier/bundle match, source, checked time and expiry.
• Operations: connector grants by reference, sync checkpoints, import batches, jobs, revisions and audit receipts—never plaintext credentials.
Keep title-library observations separate from subscription status. Ending a subscription changes access framing, not the library or accepted history. Resolve remakes and ambiguous title matches with guided choices; never silently merge them.

## 5. Set up TMDB securely
The user must obtain their own TMDB API credential. Direct them to the provider’s account setup and the host’s secure secret-entry mechanism. Never ask for a key in chat or put one in memory, a skill, a repository, screenshots or logs. Store only a credential reference in ordinary configuration. If secure entry is unavailable, stop the credential step and explain what is missing.
Use TMDB for title resolution, metadata, credits and region-specific watch-provider observations. Preserve source links and required attribution; respect provider terms and cache/freshness limits. Reference: docs/tmdb-api-key-setup.md in the repository.

## 6. Import only supported, authorized sources
Declare each connector’s supported history, watchlist, title-library and subscription-detail capabilities before use. Obtain the host’s normal authorization and respect provider sign-in. Stage the first history import and ask for confirmation or sample verification before accepting it. Later incremental imports may run under the granted scope; deduplicate by source identity and preserve provenance. Unsupported coverage stays unknown.
Do not populate history from free-form conversational lists. An explicit “already seen it” response to a displayed recommendation may create a linked seen assertion with unknown viewing date. Ratings, inferred taste and list membership never create history.

## 7. Enforce the recommendation card contract
Every movie/TV suggestion and anti-recommendation, in chat or dashboard, includes:
• Short title.
• One evidence-backed why line.
• Spoiler-free description from the cached TMDB overview: one or two sentences, at most 280 characters—not a tagline.
• Key cast and director.
• TMDB vote average, clearly labeled as TMDB’s rating.
• Release year (or first-air year for TV).
• Where to watch: US region, named providers, included subscription/free offers first, then separately labeled rent and buy offers. Optional frame display: genre/home views show only subscription/free titles (no per-title payment); rent/buy-only titles go to a separate Rent/Buy tab; a home title with optional rent/buy shows its qualifying streaming provider with paid alternatives on a separate line. The Rent/Buy tab is read-only (provider and dated check, no prices or transaction controls); a guarded migrate step moves paid-only titles out of home, and an update that would leave an ineligible home title is rejected for explicit repair rather than auto-reverified.
No runtime or multi-factor scoring clutter on cards. Enrich missing descriptions before presentation; do not fabricate plot, credits or scores. If required data cannot be verified, disclose the gap rather than presenting an apparently complete card.
Match subscriptions using region and plan/bundle evidence; provider presence alone does not prove entitlement. Cache by media kind, TMDB ID and region with source, checked_at and expiry; refresh expired observations. A successful empty lookup is checked_unavailable (“Checked: unavailable in the US”). A failed lookup is verification_unavailable (“Availability unverified”). Display the appropriate explicit status. Never invent prices, offers or deep links.
Rank by explicit taste, accepted history and access; exclude already-watched and avoided titles by default. Evidence must support every reason. Unknown required constraints are not a pass. Support movies first; extend TV only where the host has verified capabilities.

## 8. Track subscriptions without controlling billing
Let the user add, pause, end, change tier/bundle/region and re-verify subscription records under the host’s approval rules. Recompute recommendation access whenever those facts change. Mark stale evidence unknown and ask for a re-check; do not invent an end date or silently cancel anything. Preserve titles and history if a service ends, labeling relevant titles available if resubscribed instead of included now. Do not suggest duplicate paid access when an evidenced bundle already covers it.
Account cancellation, purchases and plan changes are separate external actions and require explicit approval; recording an ended subscription does not cancel a provider account.

## 9. Offer In Theaters separately
If the user opts in, privately configure their own area and radius. Use dated, source-backed listings for any first-rate theater the user chooses; exclude discount or second-rate experiences (independents are not excluded by category). Public examples use national chains only, such as AMC, Cinemark, Regal or Alamo Drafthouse. Show real titles, spoiler-free TMDB descriptions and theater names; no showtimes, formats or showing counts. Do not invent a nearby branch or infer future listings from today’s data. Preserve source/listed/checked dates. Keep this list separate from streaming picks and streaming availability. If listings cannot be verified, say so.
Never publish the user’s area, branch identifiers or private listing configuration in shared setup material.

## 10. Run a quiet daily review
With permission, schedule one review around 8 AM in the user’s timezone using the host’s scheduling capability. Apply pending feedback first; review history, taste, candidate pools, expiring availability and optional theater listings. Refresh stale evidence and recompute affected recommendations. Message only on a real, meaningful change or an actionable failure; remain silent when unchanged. Compare against the last accepted state to avoid duplicate alerts. If scheduling is unavailable, offer the same review on request.
Do not claim a review ran unless there is evidence it completed. A frame publish is never required for core review. Weekly upkeep may check connector health, stale subscriptions, metadata and workflow alignment without inventing access or making billing changes.

## 11. Learn through guided feedback
Offer accept / seen it / not interested / show another, or one clear next step. Record preference feedback separately from viewing evidence; apply it before generating the next recommendation. Never assume accepting a pick means watching it. Treat an explicit correction to an anti-recommendation as strong evidence. Inferences must remain subordinate to explicit signals.
Weigh each taste source by how sure it is. Explicit loves, thumbs up and 'more like this' titles count most (1.0); ratings imported from a streaming service count somewhat less (0.7); titles the user called just fine count a little (0.4); watch history the user has not confirmed counts zero and is used only to skip titles they have already seen, never as a reason. Household and autoplay viewing is common, so confirm history in short multiple-choice rounds of about eight titles: Loved it / It was fine / Not for me / Didn't watch it. 'Didn't watch it' removes that title from the taste signal.
Store real per-title details from TMDB: directors, writers, top cast, keywords, the TMDB score and a few reviews. Never invent IMDb, Rotten Tomatoes or Metacritic scores. Weight people by role: director highest (2), then writer or creator (1.5), then lead (1), then supporting cast (0.6). Choose each why line when publishing, citing the strongest real link (a loved title or a person), and cite any one title or person on no more than three visible cards so reasons stay varied.

## 12. Provide a view-only dashboard
Show current settings, suggested titles, a separate anti-recommendations list, connector status and a taste summary from the same private store. All configuration goes through the agent and normal approval, not dashboard controls. The dashboard is not the domain core and must not become required for imports, recommendations or export.

## 13. Keep the photo frame optional
Core MovieBot must run without frame hardware, a kiosk, publishing or wake services. Integration adapters may consume core recommendations and return feedback; core code must not import frame code. See “Optional: photo frame” for the separate project and example views.

## 14. Privacy and permission boundaries
Never copy another instance’s personal history, profile, area, subscriptions, endpoints or credentials. Keep personal stores, generated picks and local configuration outside published repositories and public pages. Use a secret manager for credentials; redact logs and diagnostics. Do not send private data to third parties without explicit authorization. Use the host’s approval model for mutations, imports, external writes, connections and schedules; no silent purchases, subscriptions, cancellations or sharing. Retain accepted data when a connector is revoked unless deletion is separately requested. Support private export and user-directed deletion with clear scope.
Public examples illustrate design, not current entitlement, billing truth or proof of a running deployment.

## 15. Acceptance checks—demonstrate, do not merely claim
□ Taste-only onboarding finishes before the first pick, with selectable genres and three-choice seed ratings.
□ A private instance works without any frame or dashboard.
□ A supported source stages and imports source-backed history only after the required approval; reruns do not duplicate events.
□ A dislike changes preference ranking but creates no viewing event; an explicit seen response to a displayed recommendation creates a linked assertion with honest date precision.
□ Every displayed recommendation and anti-recommendation meets the complete card contract, including <=280-character description and explicit where-to-watch status; no runtime is displayed.
□ Provider lookup empty success and lookup failure show different unavailable/unverified states; stale observations are refreshed.
□ Ending a subscription preserves titles/history and invalidates prior included-access claims; tier/region changes cannot reuse stale entitlement.
□ Optional theater listings show sourced titles, descriptions and first-rate theater names (public examples chain-only), never showtimes or invented branches.
□ The authorized daily review is silent when unchanged and alerts once for a meaningful change; unsupported scheduling is disclosed.
□ Feedback is applied before the next recommendation; explicit corrections outweigh inferences.
□ The dashboard is view-only and uses the same private facts.
□ Export/recovery works and a privacy scan finds no secrets or personal instance data in shareable artifacts.
## Final handoff
Tell the user what is actually implemented, what remains unsupported, where their private data lives, what permissions were granted and which acceptance checks passed. Offer one concrete next step, not an open-ended questionnaire.

## 16. Subscription-aware home gate (optional display views)
- Watch at Home / genre views: eligible only with a US free/AVOD offer, or a US flatrate offer on a service in the human's fresh `verified_active` ServiceSubscription entitlements (verified tier; bundle/channel aliases mapped).
- `likely_active` and `unknown` never qualify. Provider availability, connector reachability, and library service lists are not proof of payment. Unknown stays unknown.
- No qualifying offer: Rent/Buy tab if paid options exist, else hold. Never say "your X" for an unverified service.
- ServiceSubscription rows: status, confidence, evidence_refs, as_of, tier, access_path (direct/bundle/channel_addon/free), host_service_id, renews_on, stale_after, known expiry.
- Keep current from receipt/renewal/cancel signals; a passed renewal date with no fresh evidence becomes `unknown`, never inactive. Reconstruct existing records before asking the human; never repeat onboarding; no account or billing changes.
- In Theaters: any first-rate theater; exclude discount/second-rate experiences, not independents by category. Private surfaces may show specific cinema names; public docs/examples stay chain-only.
- An explicit, dated owner confirmation is a valid `verified_active` source (source=human); card statements and receipt/renewal email are supporting evidence and never block the gate.

## 17. Unsubscribed view (optional display)
- One sub-tab per major US streaming service the user does not have as `verified_active`. Live-TV bundles such as YouTube TV are excluded.
- Each sub-tab shows the top 10 taste-matched movies on that service's subscription (flatrate) offer, as standard cards.
- Unknown status is labeled "not confirmed"; once the user explicitly confirms they do not subscribe, label it "not subscribed".
- Any title also available on a verified service the user already has, or for free, is excluded from every Unsubscribed sub-tab. Read-only: no prices, sign-up links or transaction controls; empty sub-tabs are hidden.

## 18. What the reference repository implements today
Be honest with the user about this split; do not present spec-only items as working.

| Area | Status | Where |
|---|---|---|
| Recommendation card contract, feedback apply, regenerate, same-slot planning | Implemented (Python, stdlib only) | `pipeline/` |
| Where-to-watch | Implemented via public JustWatch US pages (stopgap). **Spec path: TMDB `watch/providers`.** | `pipeline/where_to_watch.py` |
| Title metadata | Implemented via public TMDB web pages (stopgap). **Spec path: TMDB API with your own key.** | `pipeline/feedback_apply.py` |
| In Theaters builder (titles only) | Implemented | `theaters/local_showtimes.py` |
| Optional display: Watch at Home + In Theaters | Implemented | `integrations/photo-frame/` |
| Optional display: Rent/Buy, Unsubscribed, `migrate-rent-buy` | Spec-only | this document, `integrations/photo-frame/README.md` |
| Taste-only onboarding, watch-history interview, taste v3 weighting, `title_metadata` | Spec-only (skills describe the procedure) | `skills/`, `docs/schema.sql` [SPEC] tables |
| Subscription records and the `verified_active` gate | Spec-only schema; planner enforces home eligibility from `watch_availability` | `docs/schema.sql` |
| Streaming connectors | Procedure only (host browser + credential manager) | `skills/moviebot-streaming-connector-setup/` |
| Dashboard, daily/Thursday scheduling | Host-dependent; not in this repo | `skills/` |

The architecture reference is `docs/architecture.md`.
