# Contextual Follow-Up Contract

Labels: `ready-for-agent`

## What to build

Make short follow-up questions reliably reuse the previous answer context. The follow-up should inherit the player, metric, and filters, then replace only the details the user explicitly changes.

For example, after asking for Maxwell’s strike rate against off-spin, “What about leg-spin?” should ask for Maxwell’s strike rate against leg-spin.

## Acceptance criteria

- [ ] Chat state keeps the resolved player, metric, comparison participants, and filters from the previous supported answer.
- [ ] A follow-up replaces only the context explicitly changed by the user.
- [ ] Short natural follow-ups work without requiring phrases such as “the player,” “his,” or “same player.”
- [ ] Materially ambiguous follow-ups ask one clear question instead of guessing.
- [ ] Clear follow-ups continue without unnecessary clarification; only multiple reasonable meanings trigger a question.
- [ ] A failed or unclear turn does not overwrite the last successful conversation context.
- [ ] A short follow-up after a failed turn clearly reuses the last successful context or asks for clarification.
- [ ] Chained chat tests cover direct statistics, filtered statistics, comparisons, and matchups separately.
- [ ] Comparison follow-ups preserve every compared player and metric while replacing only the explicitly changed filter.
- [ ] Suggested follow-ups remain hidden until their exact chained chat tests pass.

## Blocked by

- #2
- #4
- #5
- #6
