---
name: moviebot-continuous-improvement
description: >-
  Use whenever MovieBot decisions or workflows change, or on the
  Thursday architecture↔skills audit — keep the Architecture Page and the
  GitHub/shared skill collection in sync.
---
# MovieBot continuous improvement

Keep three surfaces aligned: Architecture Page (source of truth), GitHub skill collection, and the skill library your agent host loads (if separate).

## Source of truth
Architecture Page: your instance Architecture document (public reference: `docs/architecture.md`; keep your instance copy and its link private)

GitHub skills repo (private): https://github.com/your-github-user/moviebot under `skills/<id>/SKILL.md`
Local checkout: instance-local clone of this repository

## When to run (detect change)
1. **Event path (immediate):** After any locked owner decision or workflow change for MovieBot — onboarding, taste weights, watch-history interview, title metadata, why-line rules, cancellation, subscribe/trial, connectors, maintenance, recommendation card, refresh loop, Frame Movie Night publish, privacy phase, license/publication, reco experiment flags, ranker weights, pool sources, exploration share, or similar.
2. **Audit path (scheduled):** Thursday continuous-improvement audit (alongside Thursday maintenance intent).
3. **Drift signal:** Architecture Page text contradicts a MovieBot skill body, or a skill exists on only one of GitHub vs shared library.

## Propagate (always this order)
1. **Update the Architecture Page first** — lock the decision in the right section (§1 optional display, §5a workflows, §5b dashboard, §12 recommend, §12a taste profile, §16 tracker, etc.). Date the lock. Do not invent privacy policy (phase two).
2. **Mirror into skills**
   - Rewrite or add the matching `skills/<id>/SKILL.md` in the local checkout, commit, push to `your-github-user/moviebot`. If the repository is public, keep copies agent-neutral with no personal data, and run a secret scanner (for example gitleaks) before every push.
   - Update the matching skill in your agent host's skill library so every agent that runs MovieBot loads the same procedure.
3. **Point the MovieBot agent** — if new skills or new Architecture links matter, refresh the MovieBot agent's instructions so it still points at the Page and the skill set.
4. **Report** — one short note to the owner: what changed on the Page, which skill folders updated, and any conflict that needs a decision.

## Hard rules
- Experiments: before any change, snapshot the DB and flags, put the change behind a flag, and log date/time, what, why, metric before/after and rollback steps in the experiment changelog and the Architecture experiment log; tag the repository commit `exp-YYYYMMDD-<name>`. Third-party ratings datasets, learned weights and personal data never go in a public repository.
- Architecture Page wins on conflict unless the owner gave a newer explicit override in chat/voice — then update the Page to match that override, then skills.
- Do **not** auto-change runtime product behavior, billing, or send messages as the owner.
- Doc/skill sync is reversible documentation work; still ask before deleting a skill globally.
- Prefer fewer clearer skills over overlapping ones; rewrite in place when workflows evolve.
- When a decision is ambiguous (e.g. product sub vs streamer sub, agent-run cancel vs guide-only), stop and ask the owner once with a clear choice — do not guess into both surfaces.

## Thursday audit checklist
1. Read Architecture Page locked callouts and §5a / §5b / §12 / §12a / §16 rows dated recently.
2. List `skills/*/SKILL.md` in the repo and shared MovieBot skills.
3. Diff: missing skill, stale skill body, Page text without a skill, skill without Page backing.
4. Apply syncs automatically for clear doc drift; ask the owner only for real product ambiguities.
5. If nothing drifted, stay quiet (no “all clear” spam).
