---
name: moviebot-connector-no-subscription
description: >-
  Use when MovieBot has no active subscription — disconnect connectors
  and skip maintenance; also the fixed Apple TV / Paramount+ connector-check
  plan (report status then stop).
---
# MovieBot connector no-subscription

## No product subscription
When there is **no active product subscription** for this human’s instance:

1. Disconnect / idle connectors appropriately
2. **Do not** spend Thursday maintenance or refresh cycles on non-paying users
3. Keep personal store intact unless they asked for purge; subscription drop does not delete the titles library

## Fixed plan — Apple TV & Paramount+ connector check
When asked to connect or check Apple TV and Paramount+, follow this plan exactly. Do **not** invent next steps.

1. Check Apple TV account-linking option (supported personal library/history connector: yes/no).
2. Report Apple TV status: **connected** | **not connected** | **error** — one line.
3. Check Paramount+ account-linking option (same).
4. Report Paramount+ status: **connected** | **not connected** | **error** — one line.
5. **Stop.** No recommendations. No further actions.

### Current status note (November 5, 2026 CST)
Neither **Apple TV** nor **Paramount+** has a supported personal library/history connector yet. Both report **not connected** unless a real connector is later added and successfully linked.

Architecture §5: your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)
