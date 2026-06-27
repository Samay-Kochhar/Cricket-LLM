# Player Comparison Contract

Labels: `ready-for-agent`

## What to build

Harden player comparison questions for batter-vs-batter and bowler-vs-bowler comparisons. Users should be able to compare two supported players on supported metrics with optional filters such as phase, venue, opposition, or bowling style.

Mixed batter-vs-bowler comparisons should be rejected clearly when the requested metric cannot be applied safely.

## Acceptance criteria

- [ ] Batter-vs-batter comparison paraphrases normalize to the same player comparison plan.
- [ ] Bowler-vs-bowler comparison paraphrases normalize to the same player comparison plan.
- [ ] Optional supported filters are preserved in the comparison evidence.
- [ ] Mixed-role comparisons return a clear unsupported-capability response.
- [ ] Comparison tables show each player, metric values, and relevant sample context.

## Blocked by

- #1
- #2
