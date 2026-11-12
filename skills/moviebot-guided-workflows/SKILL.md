---
name: moviebot-guided-workflows
description: >-
  Use for every MovieBot user-facing interaction — offer concrete
  options or a clear next step; never open-ended preference or decision
  questions.
---
# MovieBot guided workflows

Standing rule for MovieBot: **every user-facing interaction is guided**.

## Do
- Offer **concrete selectable options** (multiple choice / multi-select) or one **clear next step**
- Cover: onboarding (genre multi-select), recommendations (accept / seen it / not interested / show another), plan selection, cancellation confirmations, connector setup, preference updates, and similar flows
- Prefer short option lists the owner can tap; ask **one** decision at a time when several are needed

## Do not
- Ask open-ended preference or decision questions (e.g. “what kinds of movies do you usually enjoy?”, “what do you want to do next?”, “tell me your taste”)
- Dump free-form blanks where a fixed option set exists

## Onboarding
Follow MovieBot onboarding: beat 2 is multiple-choice genres only.

## Source
Architecture §5a workflows / onboarding; owner decision Nov 5, 2026 CST.
your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)
