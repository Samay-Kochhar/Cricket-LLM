# Bowling Strike Rate Contract

Labels: `ready-for-agent`

## What to build

Add bowling strike rate as a canonical bowling metric, separate from batting strike rate. It is calculated as legal balls bowled divided by bowler-credit wickets, and lower is better.

Any question that says only “strike rate” must ask the user to choose batting or bowling before execution. Every completed answer must display the full metric label.

## Acceptance criteria

- [ ] The metric registry, ontology, planner, SQL builder, evidence table, and metric reference use the canonical bowling strike-rate metric.
- [ ] The formula uses legal balls and excludes non-bowler dismissals from wickets.
- [ ] Direct, filtered, ranked, comparison, and phase-wise comparison question shapes are covered.
- [ ] Zero-wicket samples display “N/A — no wickets taken,” never zero or infinity.
- [ ] Rankings exclude zero-wicket rows and explain the exclusion; descriptive comparisons retain them with N/A.
- [ ] Unqualified strike-rate questions ask the user to choose batting or bowling before execution.
- [ ] Completed answers visibly say “Batting Strike Rate” or “Bowling Strike Rate.”
- [ ] Rate rankings use the default minimum of 60 legal balls unless the user supplies another threshold.

## Blocked by

- #2
- #4
- #6
