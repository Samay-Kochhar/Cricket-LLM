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
- [ ] An unqualified batter comparison shows runs, batting average, batting strike rate, boundary percentage, and batter dot-ball percentage.
- [ ] An unqualified bowler comparison shows wickets, bowling average, economy rate, bowling strike rate, bowler dot-ball percentage, and boundary percentage.
- [ ] Bowling strike rate is calculated as legal balls bowled divided by bowler-credit wickets and is labelled separately from batting strike rate.
- [ ] Every unqualified player strike-rate request asks the user to choose batting or bowling strike rate.
- [ ] Every strike-rate answer visibly says “Batting Strike Rate” or “Bowling Strike Rate.”
- [ ] The exact supported comparison prompts pass through the real chat API and UI, not only the executor.
- [ ] Comparison follow-ups preserve both compared players and any phase, venue, opposition, or bowling-style filter.
- [ ] A short comparison follow-up changes only its explicit filter; for example, “What about powerplay?” preserves both bowlers and the comparison metrics while replacing the death-over phase.
- [ ] No comparison prompt is shown as an example or suggestion until its complete user flow passes.
- [ ] The first verified suggested follow-up offers a phase-wise comparison of the same players.
- [ ] The phase-wise answer shows powerplay, middle overs, and death overs together for every compared player.
- [ ] Phase-wise comparison uses one combined table for all players and phases.
- [ ] Every phase row shows balls faced for batters or legal balls bowled for bowlers.
- [ ] Small samples remain visible in descriptive comparisons without an unnecessary warning; the displayed sample size provides the context.
- [ ] Team-wise comparison is added only after phase-wise comparison is product-ready.
- [ ] The exploratory team-wise comparison includes all opposition teams with available evidence.
- [ ] A directly named opposition filters the comparison to that team only.
- [ ] The all-oppositions view renders one team-wise table per compared player without an additional difference table.
- [ ] Each player table omits opposition teams for which that player has no recorded evidence.
- [ ] A short summary highlights only clear high or low differences using values calculated by deterministic code, not arithmetic performed by the LLM.
- [ ] The short summary contains no more than three standout differences.
- [ ] The highlights use different metrics where possible instead of repeating one metric.

## Blocked by

- #1
- #2
