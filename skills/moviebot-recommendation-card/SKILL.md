---
name: moviebot-recommendation-card
description: >-
  Use when formatting MovieBot movie/TV suggestions or anti-recommendations —
  title, one-line why, optional detail, cast/director, TMDB rating, year, and
  REQUIRED where to watch; never runtime. No recommendation year floor (1985 is
  onboarding-only).
---
# MovieBot recommendation card

Use for every suggested movie/TV title and every anti-recommendation, on every surface: chat, Frame Movie Night, dashboards, lists, and any other output.

## Display (required shape)
1. **Title** (short)
2. **One-line why** — evidence-backed reason
3. **Description (required)** — 1–2 sentence spoiler-free summary from the TMDB overview (cached in SQLite); never omit on any surface
4. **Key cast and director** — TMDB credits
5. **TMDB vote average**
6. **Year**
7. **Where to watch** — region, named provider(s), and subscription/flatrate, rent, or buy. Prefer the human's confirmed subscribed services; label other and paid access honestly.

## Where-to-watch data
- Required for EVERY suggestion and anti-recommendation; never silently omit it.
- Use TMDB `movie/{id}/watch/providers` or `tv/{id}/watch/providers` for the instance region (e.g. US).
- Cache per media type, TMDB id, region in instance SQLite with source, checked_at, expiry; refresh expired before reuse.
- Keep flatrate, rent, buy separate. Don't imply subscription availability without availability + subscription evidence.
- Include TMDB regional watch link and attribution where applicable; never invent deep links or prices.
- Successful empty lookup = **checked_unavailable**: "No listed US subscription/rental/purchase options found" with freshness.
- Failed/unverified lookup = **verification_unavailable**: "Where to watch could not be verified." Not proof of unavailability.
- Never show a bare guess; never treat stale data as current.
- Frame picks must also satisfy the data contract and publish gate in MovieBot frame Movie Night. Changes to what an optional display renders need the owner's explicit OK.

## Rent/Buy tab — owner decision 2026-11-08 (12:35 PM CT)
Supersedes the earlier allowance of rent/buy on the home view. The movies page has three views: Watch at Home (genre buttons), In Theaters, and Rent/Buy.
- Genre home views (Comedy, Action & Adventure, Sci-Fi, Drama, Thriller, Family) show only titles streamable via subscription or free, with no per-title payment.
- Rent/buy-only titles move to the Rent/Buy tab (description + provider + rent/buy labels; never invent prices).
- A title with qualifying subscription/free streaming plus optional rent/buy may stay on home: show the qualifying streaming provider as its where-to-watch line, and paid alternatives on a separate labeled line.
- `unverified` or `verified_no_home_offers` titles are not home-eligible. Wake planning/eligibility and guarded CAS publish enforce this; real feedback is preserved.
- In Theaters unchanged: titles, descriptions and chain names only; no showtimes.

## Hard rules
- No runtime.
- Clean and crisp.
- Same structure for anti-recommendations.
- A title never on both lists; suggested wins.
- No recommendation year floor (1985 is onboarding-only).
- Never expose TMDB keys anywhere; never commit the instance DB.

Architecture §1 / §12 / §12a:
your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)

### Rent/Buy view details and limits (rev18, 2026-11-08)
- The Rent/Buy view is read-only. Each card shows the TMDB description, the rent/buy providers, and a dated "checked" line (region and source). There are no prices, votes, Watched/Next or transaction controls.
- **Spec-only (not yet in this repository's `publish-picks.py`):** `publish-picks.py migrate-rent-buy --expected-revision N --spec FILE` makes one guarded compare-and-swap. It replaces each listed genre card (guarded by its expected outgoing tmdb_id), writes `rent_buy` {status, checked_at, note, items[]}, and is idempotent on `migration_id`. Slots, In Theaters and other cards stay untouched. Use it to move paid-only titles out of the home view.
- Known limitation: Rent/Buy is not auto-refreshed yet. If a later provider check finds that a home title lost its subscription/free offer, nothing migrates it automatically. The publisher rejects the ineligible update and requires an explicit repair or alert. It never claims eligibility was re-verified when it was not.

## Subscription-aware home gate — owner decision 2026-11-08 (1:44 PM CT)
Supersedes the earlier "any subscription/free provider" home gate.
- Watch at Home / genre views: eligible only with a US free/AVOD offer, or a US flatrate offer on a service in the human's fresh `verified_active` ServiceSubscription entitlements (verified tier; bundle/channel aliases mapped).
- `likely_active` and `unknown` never qualify. Provider availability, connector reachability, and library service lists are not proof of payment. Unknown stays unknown.
- No qualifying offer: Rent/Buy tab if paid options exist, else hold. Never say "your X" for an unverified service.
- ServiceSubscription rows: status, confidence, evidence_refs, as_of, tier, access_path (direct/bundle/channel_addon/free), host_service_id, renews_on, stale_after, known expiry.
- Keep current from receipt/renewal/cancel signals; a passed renewal date with no fresh evidence becomes `unknown`, never inactive. Reconstruct existing records before asking the human; never repeat onboarding; no account or billing changes.
- In Theaters (owner clarification 2026-11-08): any first-rate theater; exclude discount/second-rate experiences, not independents by category. Private surfaces may show specific cinema names; public docs/examples stay chain-only.
- An explicit, dated owner confirmation is a valid `verified_active` source (source=human); card statements and receipt/renewal email are supporting evidence and never block the gate.

## Unsubscribed tab
- One sub-tab per major US streaming service the owner does not have as `verified_active`. Live-TV bundles such as YouTube TV are excluded.
- Each sub-tab shows the **top 10** taste-matched movies on that service's flatrate offer, as standard cards (description, provider, dated check). Shows what each missing service would add.
- Services with unknown status are labeled "not confirmed"; once the owner explicitly confirms they do not subscribe, label the service **"not subscribed"**.
- Read-only: no prices, sign-up links or transaction controls; never implies the owner has the service; never counts toward Watch at Home eligibility. Hide empty sub-tabs.
- Precedence: a title also available on a `verified_active` subscription or free belongs to Watch at Home (if picked) and is excluded from every Unsubscribed sub-tab; the existing subscription wins.
- A rentable title that also streams on an unsubscribed service may appear in both Rent/Buy and Unsubscribed, with both access types labeled.

## Why lines and taste profile v3
- Pick the why line at publish time and cite the strongest real link: a loved / thumbs-up / "more like this" title, a person (director, writer/creator, lead) with verified credits, or an owner-stated signal.
- Diversity cap: any one seed title or person may be cited on at most 3 visible cards on a surface.
- Never cite unconfirmed watch history (weight 0) or a title the owner said they didn't watch.
- Taste weights: confirmed loves / thumbs up / "more like this" 1.0; ratings imported from a streaming service 0.7; "It was fine" 0.4; unconfirmed history 0 (used only to exclude already-seen titles); thumbs down and "Not for me" negative.
- People affinity by role: director 2, writer/creator 1.5, lead 1, other cast 0.6; plus keyword and genre affinity.
- Card facts come from `title_metadata` (directors, writers, cast, keywords, TMDB score and reviews). Never invent IMDb, Rotten Tomatoes or Metacritic scores.
- Owner-gated options: publishing attribute-level why lines to an optional display (flag `why_v3_frame`) and widening the candidate pool via TMDB person search (flag `pool_person_search`) each need the owner's explicit approval first. Once approved, run each as a tracked experiment (snapshot, flag, changelog entry, rollback steps).
- Attribute-level why lines: name a liked title only when it shares at least 2 concrete attributes with the pick (a director, writer, creator or lead, or a specific keyword theme such as heists or time travel) and the tone and era fit (for example, an animated family film never cites a live-action crime drama). Generic overlaps such as "lawmen and cops", "a true story" or "family ties" never carry a line alone. Otherwise use the attribute phrase alone, or the honest genre line. The diversity cap still applies.
- Picks may come from a widened candidate pool, but every card still needs verified where-to-watch at publish and never shows runtime.
