# Issue 42 verification: batter statistics in successful ODI chases

Issue 42 adds a registered, deterministic chase/result condition for batting
statistics. This is a capability and evidence change only; the approved UI is
unchanged.

## Deterministic definitions

A *successful chase* is not a stored column. It is two registered conditions,
compiled and accounted for separately:

- `innings = 2`: the existing second-innings (chasing) filter, `inns = 2`.
- `batting_result = "won"`: the delivery's batting team equals the stored match
  winner (`winner = team_bat`, winner present and not `-`).

An *unsuccessful chase* is `innings = 2` plus `batting_result = "lost"`, which
requires the stored winner to equal the **bowling** team (`winner = team_bowl`).
It is not merely "winner differs from the batting team".

| Wording | Canonical filters |
| --- | --- |
| "in successful chases", "successfully chasing", "chased down" | `innings: 2`, `batting_result: won` |
| "in unsuccessful / failed chases", "failed to chase" | `innings: 2`, `batting_result: lost` |
| "while chasing", "batting second" | `innings: 2` |
| "in India's wins", "when they won" | `batting_result: won` (no innings condition) |
| no chase or result wording | neither |

The condition is registered in `backend/app/cricket_analytics/match_result_conditions.py`.
It is parsed from the question's own wording, and the validator rejects plans
that drop it, change it, or keep it after the user removes it. A model reading
cannot add or contradict it; a disagreement produces a clarification. Gemini
never supplies its SQL.

The #37 completeness check records the chase innings and the winning outcome as
two separate items. A combined model fact such as `innings_outcome=win` plus
`innings_type=chase` is split into both, so neither can hide the other.

### Result policy

- **Ties, no-results, abandoned matches.** Stored winner `-` (122 matches in
  total, 60 of which have a second innings). These are neither wins nor losses.
  They are excluded from successful and unsuccessful chases, and included in
  plain "chasing" and unfiltered scopes.
- **Unmatched winner.** Match 66387 stores winner `ICC World XI`, but its teams
  are `Asia XI` and `World-XI`. It is neither a win nor a loss.
- **Rain-affected matches.** `rain` is 1 or 9 for 222 matches. These use the
  stored result as recorded, including revised targets; the result is not
  re-derived from scores. 127 of the 1,280 successful chases are rain-affected.
- **Nonstandard innings and super overs.** Only innings 1 and 2 exist in the
  delivery data (739,775 and 625,076 rows), and no super-over rows are stored.
  A chase always requires the literal second innings.
- **Unsupported, and failing closed with the condition named:** ties or
  no-results as a filter, successful and unsuccessful chases compared in one
  question, a chase-result condition combined with batting first, result
  conditions on bowling statistics, and unread result wording.

Every answer carries an evidence note titled "Successful chase condition" (or
the unsuccessful / match-result equivalent). It states the definition, the
policy, and the sample scope: qualifying chases out of in-scope chases, plus
the excluded no-winner, unmatched-winner and rain-affected counts.

### Team roles (composition)

Answering "for India in successful chases" correctly needed a registered
own-side team filter. The canonical path previously read every team mention as
the opposition, so "Most runs for India" answered *against* India. The fix adds
`player_team`, the subject's own side. It compiles to `team_bat` for batting
statistics and `team_bowl` for bowling statistics, mirroring `opposition`.

- "for India", "representing India", "India's batters" → `player_team`
- "against India", "vs India", or a bare team name → `opposition`, unchanged

## Independent frozen-database check

Database: `data/odi_analytics.duckdb`

SHA-256: `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`

These are independent read-only queries over `analytics.deliveries_v1` (plain
`inns = '2' AND winner = team_bat`), separate from the application query
builder.

| Check | Value |
| --- | ---: |
| Successful chases: Virat Kohli runs (rank 1) | 5,791 |
| Successful chases: Rohit Sharma runs (rank 2) | 4,415 |
| Successful chases: MS Dhoni runs (rank 3) | 2,877 |
| Kohli, all chases (`inns = 2`) | 7,844 |
| Kohli, unsuccessful chases | 2,008 |
| Second-innings matches | 2,505 |
| Successful / unsuccessful chases | 1,280 / 1,164 |
| Chases with no stored winner / unmatched winner | 60 / 1 |
| Most wickets for India (bowling side) | Ravindra Jadeja, 226 |
| Most successful-chase runs for Australia against India | Aaron Finch, 344 |

The tracer response ranks Kohli first with 5,791 runs from 5,963 balls across
97 matches, followed by Rohit Sharma (4,415) and MS Dhoni (2,877).

## Verification

- Focused issue test: `tests/backend/test_issue_42_successful_chases.py` (70 tests).
  It covers the saved Flash extraction and model-free tracer paths, the
  successful, unsuccessful, chasing and unfiltered distinctions, paraphrases,
  the result policy, parameterised SQL, and composition with player, own team,
  opposition, year, venue, competition and sample thresholds. It also covers
  ranking direction, limits and explicit thresholds; follow-ups that broaden to
  all chases by removing only the result condition; fail-closed requests; model
  disagreement; and validator rejection.
- Issue 40 and 41 suites remain green. One issue-40 expectation changed:
  "bowled in successful run chases" is now a registered condition rather than a
  limitation, and unread result wording is still a named limitation.
- The saved 150-response capture was re-executed offline through the
  application and database: 150/150. No fresh Gemini evaluation was run.
- The saved priority-8 capture was replayed offline: 6/8. The successful-chase
  tracer passes; the two remaining cases belong to issues 43 and 44.
- Full suite: 1,257 passed, 0 failed.

## Limitations

- Result conditions are registered for batting statistics only. The bowling
  side's result is not yet a registered condition, so those requests fail closed.
- Comparing successful and unsuccessful chases in one question is not supported yet.
- Summaries for plain "while chasing" answers do not repeat the innings wording.
  This predates issue 42; the plan and evidence still carry `innings = 2`.
- Year-range wording such as "since 2015" still reaches the legacy planner on
  some paths and returns planner uncertainty. This predates issue 42 and was
  noted in issue 41.
