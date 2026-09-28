# Issue 38 verification: four and six counts

Issue 38 adds four and six counts as registered, batter-owned aggregate metrics.
This is a capability and evidence change only; the approved UI is unchanged.

## Deterministic definitions

- `four_count`: count rows where `TRY_CAST(ballfaced AS INTEGER) = 1` and
  `TRY_CAST(batruns AS INTEGER) = 4`.
- `six_count`: count rows where `TRY_CAST(ballfaced AS INTEGER) = 1` and
  `TRY_CAST(batruns AS INTEGER) = 6`.
- `boundary_ball_count`: count eligible rows with exactly four or six batter runs.
- `boundary_runs`: sum batter runs on those exact four- or six-run rows.
- `boundary_percentage`: boundary-ball count divided by the existing batter-ball
  sample. It remains a rate, not a count.
- `runs_scored`: all batter runs on eligible rows. It remains distinct from runs
  scored on boundary rows.

The `ballfaced = 1` predicate is the existing batter-delivery eligibility
convention used by batting aggregates. Null or non-numeric values do not satisfy
the cast comparisons. Wides are not given a separate exclusion: a row counts only
if the source marks it as a ball faced and records exactly four or six batter runs.
No-ball boundary rows therefore count when `ballfaced = 1`. Values such as five or
seven, including any unusual or overthrow-like source encoding, are not reclassified
as fours or sixes.

## Independent frozen-database check

Database: `data/odi_analytics.duckdb`

SHA-256: `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`

An independent read-only query over `analytics.deliveries_v1`, separate from the
application query builder, produced these Virat Kohli totals:

| Statistic | Value |
| --- | ---: |
| Fours | 1,309 |
| Sixes | 154 |
| Boundary balls | 1,463 |
| Boundary runs | 6,160 |
| Total batter runs | 13,950 |
| Balls faced | 14,918 |

The source audit found no null `batruns`, `ballfaced`, `wide`, or `noball` values.
For Kohli, one of the 154 sixes was recorded on a no-ball and none on a wide.
Across the full dataset, 116 exact-six rows were no-balls and none were wides.
The dataset also contains 24 unusual batter-run rows (`-4`, `-2`, `-1`, or `7`);
the exact-value boundary formulas exclude all of them.

## Verification

- Focused issue test: `tests/backend/test_issue_38_boundary_counts.py`
- Registry and boundary-rate compatibility tests remain green.
- The saved 150-response capture was re-executed through the application and
  database offline: 150/150, with no fresh Gemini evaluation.
