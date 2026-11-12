---
name: moviebot-cancellation
description: >-
  Use when canceling MovieBot access — revoke, confirm, last prompt;
  require vocal confirmation before any automatic unsubscribe.
---
# MovieBot cancellation

## Flow
1. **Revoke access** (connectors / grants as appropriate)
2. **Confirm** intent with the human
3. **One last prompt** before they go

## Vocal confirmation (hard)
Before any **automatic unsubscribe**, get **vocal confirmation**. Nothing cancels silently.

Never auto-buy, auto-cancel a streamer’s billing, or change plans without explicit human decision.
Architecture: your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)
