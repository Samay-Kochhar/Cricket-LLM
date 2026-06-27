# Leaderboard And Sample-Size Reliability

Labels: `ready-for-agent`

## What to build

Make top, bottom, best, worst, highest, lowest, most, and fewest leaderboard questions reliable across supported ODI metrics. Leaderboards should respect explicit limits and minimum sample wording, especially for rates and percentages.

This slice should produce a complete user-visible leaderboard answer with validated plan, approved SQL, result columns, and sample-size context.

## Acceptance criteria

- [ ] Top-N and bottom-N wording normalize to the correct limit and sort direction.
- [ ] Best/worst/highest/lowest/most/fewest wording maps correctly for metrics where lower is better, such as economy rate.
- [ ] Explicit minimum sample wording is parsed into the semantic plan where supported.
- [ ] Rate and percentage leaderboards expose sample columns such as balls or legal balls.
- [ ] Low or insufficient sample cases return the appropriate limitation state.

## Blocked by

- #1
- #2
