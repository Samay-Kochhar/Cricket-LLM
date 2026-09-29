# Issue 41 verification: typed required-run-rate predicates

Issue 41 adds typed numeric match-state predicates, starting with required run
rate. The tracer "Rohit's strike rate when required rate was above 8?" now returns
batting strike rate 118.79 from 354 runs and 298 balls. This is a capability and
evidence change only; the approved UI is unchanged (existing summary, table and
evidence-note blocks; no new layout, control or chart).

## Deterministic definitions

- **Registered field** (`match_state_filters.MATCH_STATE_FIELDS`): only
  `required_run_rate` is registered. It maps to the stored `inns_rrr` column,
  read as `TRY_CAST(inns_rrr AS DOUBLE)`, with thresholds bounded to 0–100.
  The registry lists it as an allowed filter for every delivery metric
  (`metric_registry.COMMON_FILTERS`) and in the validator vocabulary; it is not a
  grouping dimension. No other column or expression can compile.
- **Typed predicate**: the plan filter holds the field (the filter key), a
  comparison operator and numeric values separately:
  `{"operator": "gt" | "gte" | "lt" | "lte", "value": n}` or the inclusive range
  `{"operator": "between", "lower": a, "upper": b}` with `a < b`. Anything else
  (strings such as `">8"`, booleans, NaN, `eq`, extra keys, reversed or
  out-of-range bounds) is rejected by `plan_validator` and, defensively,
  compiles to `1 = 0` in the builder rather than widening the scope. Values are
  bound SQL parameters, never inlined.
- **Numbers**: parsed with `Decimal`; integral values stay integers (8) and
  decimals stay floats (8.5, 7.25). No string or integer coercion is applied.
- **Language** (deterministic): aliases `required rate`, `required run rate`,
  `RRR`, `asking rate`, `required RR`, `run rate required`. Operators:
  above/over/more than/exceeded/`>` → `gt`; at least/N or more/N+/`>=` → `gte`;
  below/under/less than/fewer than/`<` → `lt`; at most/N or less/up to/`<=` →
  `lte`; between A and B / A–B / from A to B → inclusive `between`. Rate units
  ("an over", "per over", "rpo") are accepted. Current run rate, run rate,
  target, runs needed, balls remaining, wickets in hand, win probability,
  predicted score and team score are recognised but unregistered.
- **Threshold wording stays with its predicate**: "at least 8" or "above 8" is
  removed before sample, ranking-direction, limit, over-range and metric
  detection, so it can never become a 8-ball minimum, an ascending sort, or the
  run-rate metric (`strip_match_state_phrases`, used by the canonical resolver,
  split metric detection, legacy fallback and the validator).
- **Gemini**: may extract the condition, but its reading is only accepted when
  its operator, values and evidence agree with the deterministic parse of the
  same words. The saved Flash extraction (`values: [">8"]`, no operator) parses
  to `gt 8`. If Flash and the question disagree (for example `gte` for "above
  8") the user is asked to choose; a Flash extraction that omits the condition
  cannot remove the deterministically parsed predicate.
- **Fail closed**: a required-rate mention without a threshold ("by required
  rate", "when the required rate was high"), an equality without a comparison
  ("was 8"), two thresholds or bands ("above 8 vs below 8", "above 8 and below
  12") and out-of-range values return a targeted clarification. Unregistered
  numeric fields return "Filtering by <concept> is not a registered match-state
  filter" with the exact concept. These outcomes are claimed by the canonical
  path before any legacy planner, and batting-profile shortcuts are skipped when
  a match-state condition is present.
- **Completeness (#37)**: each extracted required-rate filter records three
  kinds of fact — the field (`filter.required_run_rate`), the operator
  (`filter.required_run_rate.operator`) and every numeric value
  (`...value`, or `...lower`/`...upper` for ranges). Execution is blocked unless
  all three match the compiled predicate exactly. The validator also rejects any
  plan (canonical, legacy fallback or model-planned) that drops or changes a
  predicate stated in the question, or keeps one the question removes.
- **Composition**: the predicate is a delivery-context clause applied through
  the shared filter builder, so it composes with player, phase, over range,
  opposition, years, venue, innings and bowling-style filters, rankings,
  comparisons, matchups, splits, yearly trends and dismissal-type breakdowns.
- **Follow-ups** (`canonical_patches`): "What about above 10?" replaces the
  threshold, "And at least 9?" tightens it (not a sample), "What about when the
  RRR was below 6?" replaces it, "Without the required rate filter?" /
  "regardless of required rate" removes it, and "And in 2019?" keeps it. The
  player and metric are preserved. An unregistered follow-up condition asks
  instead of being ignored.

## Source audit: `inns_rrr` is the state after the delivery

Read-only queries over `analytics.deliveries_v1`:

| Check | Result |
| --- | ---: |
| First-innings rows / with a recorded `inns_rrr` | 739,775 / 0 |
| Second-innings rows | 625,076 |
| Rows equal to `ROUND(inns_runs_rem × 6 / inns_balls_rem, 2)` using the stored (after-ball) remaining values | 624,753 |
| Rows with no balls remaining (all store `inns_rrr = 0`) | 323 |
| Rows matching the before-ball formula (after-ball remaining + this ball's runs and legal ball) | 197,324 |

Example: the first ball of a 165 chase stores `inns_balls_rem = 299` and
`inns_rrr = 3.31` (165 × 6 / 299), not 3.30 (165 × 6 / 300).

So the stored value is the required rate after the recorded delivery. CricAtlas
uses the stored value as recorded and states this in every answer's evidence
note. Rows with no balls remaining have no defined required rate; their stored
0 is treated as unavailable, like first-innings rows. The predicate SQL is
`TRY_CAST(inns_rrr AS DOUBLE) IS NOT NULL AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0
AND TRY_CAST(inns_rrr AS DOUBLE) <op> ?`. For comparison only, a derived
before-ball rate above 8 would give Rohit 372 runs from 295 balls (126.10); that
reading is not used.

## Independent frozen-database check

Database: `data/odi_analytics.duckdb`

SHA-256: `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`

Read-only queries separate from the application builder:

| Question scope | Runs | Balls | Strike rate |
| --- | ---: | ---: | ---: |
| Rohit Sharma, required rate > 8 (tracer) | 354 | 298 | 118.79 |
| Rohit, required rate >= 8 | 354 | 301 | 117.61 |
| Rohit, required rate > 8.5 | 232 | 191 | 121.47 |
| Rohit, required rate between 6 and 8 (inclusive) | 1,588 | 1,783 | 89.06 |
| Rohit, required rate < 4 (unavailable excluded) | 1,441 | 1,474 | 97.76 |
| Rohit, `inns_rrr < 4` if the stored 0 were trusted | 1,441 | 1,475 | 97.69 |
| Rohit, required rate > 10 | 97 | 50 | 194.00 |
| Rohit, required rate > 8 in death overs | 126 | 67 | 188.06 |
| Rohit, required rate > 8 against Australia in 2019 | 60 | 46 | 130.43 |
| Virat Kohli, required rate > 8 | 580 | 514 | 112.84 |

Other checks: Rohit faced 11,841 balls in all; 5,260 had no recorded required
rate (5,259 first-innings balls and 1 ball with no balls remaining) and are
excluded and disclosed in the answer's evidence note. Rohit faced 3 balls with a
stored rate of exactly 8.00, which is why `> 8` and `>= 8` differ. Jasprit Bumrah
conceded 466 runs from 529 legal balls with required rate > 8 (economy 5.29).
Mahmudullah leads batter runs with required rate > 10 (563).

## Verification

- Focused issue test: `tests/backend/test_issue_41_required_run_rate.py`
  (59 tests): tracer from the saved Flash extraction and without a model,
  completeness accounting, source audit, every operator and range, decimals,
  `>` versus `>=`, aliases versus current run rate and strike rate, unavailable
  values, malformed predicates, model disagreement and omission, composition,
  follow-ups and unsupported fields, all checked against independent queries.
- Related focused modules (canonical meaning, patches, response policy,
  breakdowns, matchups, comparisons, splits, trends, issues 37–40, language
  meaning, structured planner, chat contract, trace suite, matchup and split
  executors, registry, sort thresholds): all pass.
- The saved 150-response capture was re-executed offline: 150/150.
- The saved priority-8 capture replays the required-rate tracer as a pass with
  the saved Flash extraction and no new model call (5/8 overall; the remaining
  three are issues #42–#44 and fail exactly as before). No fresh Gemini
  evaluation was run.

## Limitations

- Only required run rate is registered. Target, runs needed, balls remaining,
  wickets in hand, current run rate, win probability and predicted score fail
  closed until their before/after semantics are audited and registered.
- The stored rate is the post-delivery state; a before-ball required rate is
  not offered.
- One predicate per field: combined bounds such as "above 8 and below 12" and
  required-rate band comparisons ("above 8 versus below 8") ask the user to
  choose a single threshold or an inclusive range.
- Comparison, matchup and split narratives disclose the predicate in the
  evidence note rather than in their headline sentence.
