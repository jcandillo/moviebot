---
name: moviebot-thursday-maintenance
description: >-
  Use for MovieBot's default Thursday weekly review — connector health,
  cleanup, stale subscriptions, TMDB metadata and watch-provider cache,
  recommendation refresh, and architecture↔skills continuous improvement.
---
# MovieBot Thursday maintenance

Every Thursday, run together:

1. **Connector health** — authenticates, returns data; flag breakage
2. **Data cleanup** — expired caches, duplicates, orphans
3. **Stale subscription detection** — re-check prompt
4. **TMDB cache refresh** — title metadata and regional watch-provider observations; never expose keys
5. **Recommendation refresh** — from current taste (no 1985 floor). Every suggestion/anti-rec follows recommendation card incl. where to watch: provider, region, flatrate vs rent/buy, or explicit checked-unavailable/verification-unavailable. Prefer confirmed subscriptions; never fabricate or reuse stale data as current. Frame slots meet frame Movie Night gates.
6. **Continuous improvement** — Architecture Page ↔ GitHub/shared skills sync

## Notes
- No active subscription → skip those stream connectors; still do docs sync.
- Don't re-run interactive new-service history review.
- Never commit the DB or reveal TMDB credentials.
- Changes to what an optional display renders need the owner's explicit OK.
- Align with Architecture §5a.

your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)

## Subscription-aware home gate — owner decision 2026-11-08 (1:44 PM CT)
Supersedes the earlier "any subscription/free provider" home gate.
- Watch at Home / genre views: eligible only with a US free/AVOD offer, or a US flatrate offer on a service in the human's fresh `verified_active` ServiceSubscription entitlements (verified tier; bundle/channel aliases mapped).
- `likely_active` and `unknown` never qualify. Provider availability, connector reachability, and library service lists are not proof of payment. Unknown stays unknown.
- No qualifying offer: Rent/Buy tab if paid options exist, else hold. Never say "your X" for an unverified service.
- ServiceSubscription rows: status, confidence, evidence_refs, as_of, tier, access_path (direct/bundle/channel_addon/free), host_service_id, renews_on, stale_after, known expiry.
- Keep current from receipt/renewal/cancel signals; a passed renewal date with no fresh evidence becomes `unknown`, never inactive. Reconstruct existing records before asking the human; never repeat onboarding; no account or billing changes.
- In Theaters (owner clarification 2026-11-08): any first-rate theater; exclude discount/second-rate experiences, not independents by category. Private surfaces may show specific cinema names; public docs/examples stay chain-only.
- An explicit, dated owner confirmation is a valid `verified_active` source (source=human); card statements and receipt/renewal email are supporting evidence and never block the gate.

## Taste profile v3 upkeep
- Refresh stale `title_metadata` rows (directors, writers, top 5 cast, keywords, TMDB score/count, up to 3 reviews, IMDb id) and retry failures; store only what a real source returns.
- Recompute people (director 2, writer/creator 1.5, lead 1, cast 0.6), keyword and genre affinity from current taste signals; unconfirmed history stays weight 0.
- Check visible cards respect the why-line diversity cap (one seed or person on at most 3 visible cards).
- Optional weekly preview-only improvement session (no display publish) whose notes feed the owner's review; schedule it only with the owner's approval.
