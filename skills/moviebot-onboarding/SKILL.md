---
name: moviebot-onboarding
description: >-
  Use when running MovieBot onboarding — preferences and taste signals
  only. No picking movies or TV shows during onboarding; ends when the profile
  is complete.
---
# MovieBot onboarding

## What onboarding is (and is not)
Onboarding builds the human’s taste/preference profile. It is not a pick-for-tonight flow.

- **In scope:** streaming-service linking, genre preferences, liked-show taste signals, cult-seed ratings (love it / neutral / nope).
- **Out of scope during onboarding:** picking movies or TV shows — no recommendations, title suggestions, recommendation cards, anti-recommendations, or “find a movie/show” while onboarding is incomplete.
- Onboarding **ends when the preference profile is complete** (all four beats finished). Only after that may recommendation flows start.

If the human chats about titles or asks for a pick while onboarding is incomplete, stay in onboarding with this light framing: **“You're still onboarding. Why are you trying to pick a movie during onboarding?”** (same idea for TV shows — don’t pivot to suggestions; offer the next onboarding step). Do not use heavier lectures about rules.

Four beats only. No permissions pass. No skip/explore.

1. **Link streaming services**
   - Step one: choose **(A)** bank/credit-card feed to detect subscriptions from spend, or **(B)** pick from a list
   - Step two: OAuth per provider
   - On connect: immediate library pull + required watch-history backfill when supported
   - Stage history; **review with the human** (import or sample-verify) — **new-service connect only**
   - Later syncs: quiet auto-accept under approved grant
2. **Set movie preferences — one consolidated genre question**
   - Present **one** multiple-choice question with the full genre list; **choose all that apply once**
   - Do **not** split genres across multiple rounds
   - Do **not** ask open-ended prompts like “what kinds of movies do you usually enjoy”
   - Consolidated options: Action, Adventure, Animation, Comedy, Crime, Documentary, Drama, Family, Fantasy, History, Horror, Music, Mystery, Romance, Science Fiction, Thriller, War, Western (plus any others currently used)
   - Write selected genres as Preference via taste_set (origin questionnaire)
3. **Pick shows they already like** (taste signals — not picking what to watch next)
4. **Rate cult classic seeds** on **love it / neutral / nope** only (taste signals — not suggestions to watch)

## Onboarding-only year floor (1985)
During **onboarding only**, do **not** show or ask about any movie or show with release/first-air year **before 1985**. Skip or replace cult seeds and liked-show prompts below that floor. Unknown year: do not use in onboarding prompts.

This floor does **not** apply to recommendations after onboarding is complete.

Architecture §5a: your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)

## Subscription-aware home gate — owner decision 2026-11-08 (1:44 PM CT)
Supersedes the earlier "any subscription/free provider" home gate.
- Watch at Home / genre views: eligible only with a US free/AVOD offer, or a US flatrate offer on a service in the human's fresh `verified_active` ServiceSubscription entitlements (verified tier; bundle/channel aliases mapped).
- `likely_active` and `unknown` never qualify. Provider availability, connector reachability, and library service lists are not proof of payment. Unknown stays unknown.
- No qualifying offer: Rent/Buy tab if paid options exist, else hold. Never say "your X" for an unverified service.
- ServiceSubscription rows: status, confidence, evidence_refs, as_of, tier, access_path (direct/bundle/channel_addon/free), host_service_id, renews_on, stale_after, known expiry.
- Keep current from receipt/renewal/cancel signals; a passed renewal date with no fresh evidence becomes `unknown`, never inactive. Reconstruct existing records before asking the human; never repeat onboarding; no account or billing changes.
- In Theaters (owner clarification 2026-11-08): any first-rate theater; exclude discount/second-rate experiences, not independents by category. Private surfaces may show specific cinema names; public docs/examples stay chain-only.
- An explicit, dated owner confirmation is a valid `verified_active` source (source=human); card statements and receipt/renewal email are supporting evidence and never block the gate.

## Watch-history interview (taste profile v3)
Also used after onboarding for services already connected.
- Pull history per connected service; filter trailers and non-viewing rows.
- Ask guided multiple-choice rounds of about 8 titles: **Loved it / It was fine / Not for me / Didn't watch it**. Never free-form.
- Loved → taste signal 1.0; Fine → 0.4; Not for me → negative; Didn't watch → neutralize the history row (household/autoplay viewing is not the owner's taste).
- Unconfirmed history stays weight 0: use it only to exclude already-seen titles, never as a why.
- Interview unconnected services only when the owner asks to connect them. No picks during onboarding still applies.
