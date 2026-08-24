# Product Readiness

This is the source of truth for what users can currently rely on in the CricAtlas chat interface. Backend handlers or isolated passing tests do not by themselves make a capability product-ready.

| Question family | Current state | Meaning |
|---|---|---|
| Standalone player statistics and filters | Partial | Canonical batting/bowling strike rate and ambiguity clarification are verified, but broader language reliability is still being evaluated. |
| Player comparisons | Partial | Basic batter/bowler, combined phase-wise, and exploratory team-wise flows pass backend contracts; complete integrated browser acceptance is still pending. |
| Matchups | Not verified | Backend matchup code exists, but the real product flow has not yet been accepted. |
| Contextual follow-ups | Partial | Structured state preserves successful direct-stat, comparison, and matchup context; broader paraphrase and integrated browser acceptance remain. |
| Suggested follow-ups | Verification pending | The phase-wise comparison suggestion passes its backend history chain and has a browser click-through test; final browser execution is still pending. All other suggestions remain hidden. |
| Analyst workups | Experimental | One narrow bowling-plan path exists, but it is not a comparison and is not yet a generally supported question family. |

## Readiness rule

A question family becomes **product-ready** only when:

1. Its exact prompt passes through the real chat API and user interface.
2. Important paraphrases pass through the same flow.
3. Every displayed suggested follow-up preserves the required conversation context and returns a valid answer.
4. The failure response is clear when the data or capability is unavailable.

Until those checks pass, the UI must not promise the capability through example prompts or suggested follow-ups.

## Agreed delivery order

1. Keep unverified example prompts and suggested follow-ups hidden.
2. Add canonical bowling strike rate and keep it separate from batting strike rate.
3. Make unqualified “strike rate” questions ask the user to choose batting or bowling.
4. Make basic batter and bowler comparisons reliable through the real chat interface.
5. Add conversation state so short follow-ups inherit the last successful player, metric, comparison participants, and filters.
6. Add one combined phase-wise comparison table for both players across powerplay, middle overs, and death overs.
7. Add exploratory team-wise comparison with one opposition table per player and a short summary of at most three calculated standout differences.
8. Add backend history-chain tests and browser click-through tests for each suggested follow-up.
9. Restore each suggested follow-up individually only after both tests pass.

Rate and percentage rankings use a default minimum of 60 balls unless the user supplies another threshold. Descriptive player and phase comparisons show the actual value and sample size without applying that ranking threshold.

## Current delivery verification

- Canonical bowling strike rate uses legal balls per bowler-credit wicket, excludes zero-wicket rows from rankings, and retains them as unavailable in descriptive comparisons.
- Unqualified strike-rate chat requests return separate batting and bowling clarification options before analytics execution.
- Structured conversation state is canonical; transcript inference remains a compatibility fallback.
- Phase-wise comparisons use one combined player/phase table. Team-wise comparisons use one opposition table per player and at most three deterministic standout differences.
- Backend and ingestion suite: 363 passing tests.
- Frontend production build: passing with webpack.
- Clarification browser click-through: passing.
- Phase-wise suggested-follow-up browser click-through: test added; execution pending local Chromium permission.
