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

## Compare modes and venue batting (#54, #55, #57)

`GET /api/compare` accepts two `player` values, `mode=batting|bowling`, a
mode-specific `metric`, `phase`, paired inclusive `year_start` / `year_end`, and
an optional canonical venue name, alias or ID in `venue`. Batting is the default;
its chart defaults to `batting_strike_rate`. Bowling defaults to `economy_rate`.
The shared service resolves player names and applies one identical context to
both players. Empty samples retain both player rows with zero counts and null
rates. Samples below 24 balls faced or legal balls are flagged; comparison does
not exclude players or assign an overall winner. Metric metadata explains higher
or lower preference; balls, runs conceded, and dismissal totals are descriptive.

`GET /api/venues/{venue}` adds `mode=batting` while preserving the existing
bowling default and `bowling_leaderboard` response field. `leaderboard` always
contains the active mode; `batting_leaderboard` contains batting rows only.
Both modes return canonical venue identity, filter metadata, metric options and
sample units through the same profile service used by Streamlit and Next.js.
Switching mode preserves the applied context and minimum, resets the metric to a
valid default, and maps the ball sample unit to balls faced or legal balls;
distinct-match units remain unchanged. Reset applies the current mode's defaults.

Batting metrics are `runs_scored`, `batting_average`, `batting_strike_rate`,
`control_percentage`, `batter_dot_percentage`, `boundary_percentage`,
`balls_faced` and `dismissals`. Dot percentage ranks ascending; the others rank
descending. Balls faced and dismissals are labelled descriptive totals.
Ties use player name ascending. The default minimum is 24 balls faced; callers
can select distinct matches or an explicit zero minimum. Venue aliases, phase
and inclusive years filter delivery rows before aggregation, sample eligibility,
selected-metric availability and top N.

Balls faced count recorded `ballfaced = 1` events. Batting runs sum all recorded
striker runs, including runs on events not counted as a ball faced; dismissals
count recorded striker `out` events. Average is runs / dismissals, and strike
rate is runs / balls faced × 100. Batter dots and boundaries count balls faced
with zero bat runs or four/six bat runs, divided by balls faced. Control percentage
uses the average recorded control value on balls faced × 100 and exposes
`control_balls`, the count of balls with usable control. Missing control is
excluded from that denominator. Zero denominators remain null, render as `—`,
and do not become zero-valued comparison bars. Venue rankings exclude null
values only for the chosen ranking metric, retaining nulls elsewhere in the table.
