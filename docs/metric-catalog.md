# ODI Metric Catalog

This document describes the initial v1 metric set for CricAtlas.

## Supported Query Classes
- Role and position comparison
- Strengths and weaknesses
- Head-to-head matchup
- Venue and context leaderboard
- Trend and progression analysis

## Initial Metrics
- `runs_scored`
- `batting_strike_rate`
- `dismissals`
- `boundary_percentage`
- `control_percentage`
- `economy_rate`
- `wickets_taken`
- `shot_share_percentage`

These metrics are defined in code in `backend/app/services/metric_catalog.py`.

## Venue Explorer bowling (#56)

The explorer uses canonical physical venues and combined historical aliases. Its
shared API/Streamlit/Next.js contract includes `filters`, `ranking`, supported
options, `sample_policy`, and `bowling_leaderboard`. Phase uses the repository
helpers: first 6 overs <=6, powerplay <=10, middle >10 through 40, death >40.
`year_start` and `year_end` are inclusive and must both be supplied; equal endpoints
select one year. Disabling years preserves phase, metric and sample choices.

The default minimum remains **24 legal balls**, with an explicit alternative of
distinct ODI matches, or 0 for no minimum. This venue-specific policy does not
change the chat ranking default of 60. All context filters apply before per-bowler
aggregation, sample eligibility and top N (default 10, allowed 1–100). Match counts
are distinct across combined aliases. Table deliveries are legal balls; delivery
rows also include wides and no-balls. Runs conceded sum `bowlruns`, including
bowler-charged extras. Legal balls exclude wides and no-balls. Wicket credit uses
`BOWLER_WICKET_PREDICATE`, excluding run-outs and other non-bowler dismissals.

- Wickets and bowler dot percentage rank descending.
- Bowling average = runs conceded / bowler-credit wickets, ascending.
- Economy = runs conceded / (legal balls / 6), ascending.
- Bowling strike rate (`balls_per_wicket`) = legal balls / wickets, ascending.
- Bowler dot percentage = legal balls with `bowlruns = 0` / legal balls * 100.
  Zero batter runs alone do not define a bowling dot.
- Boundary percentage conceded = legal balls with `batruns IN (4, 6)` / legal
  balls * 100, ascending. This follows the catalog's legal-ball boundary definition.
- Legal deliveries and runs conceded are descriptive totals, highest first; the
  selector explicitly labels the runs order without calling more runs better.

Zero-denominator rates are null and displayed as unavailable, never zero.
Rows unavailable for the selected metric are excluded before top N. Other null
rates remain visible in the detailed table. Ties use bowling average ascending
(null last), legal deliveries descending, then bowler name ascending.
