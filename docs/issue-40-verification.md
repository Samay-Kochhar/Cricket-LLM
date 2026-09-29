# Issue 40 verification: batter dismissals by recorded dismissal type

Issue 40 adds `dismissal_type` as a registered categorical dimension and answers
one batter's dismissal counts (or shares) across recorded dismissal types. The
tracer "How often was Kohli dismissed caught versus bowled?" now returns caught
170 and bowled 34. This is a capability and evidence change only; the approved
UI is unchanged (existing summary and table blocks, no new chart or layout).

## Deterministic definitions

- **Registered dimension** (`dismissal_types.DISMISSAL_TYPE_REGISTRY`, listed in
  `ontology.DIMENSIONS`): the literal stored categories `caught`, `bowled`,
  `leg before wicket`, `run out`, `stumped`, `hit wicket`,
  `obstructing the field` and `handled the ball`, with public labels (`Caught`,
  `Bowled`, `Leg before wicket`, ...). Language aliases such as `lbw`,
  `leg-before` and `run-out` map to the stored value. A focused test asserts the
  registry equals the database's stored dismissal values minus the
  non-dismissal values below.
- **Dismissed-batter attribution**: a delivery row counts for a batter when
  `out = 'True'`, the stored category is registered, and `p_out` is one of the
  batter's own identifiers (`SELECT DISTINCT p_bat ... WHERE bat = ?`). A
  non-striker who is run out therefore counts for the dismissed batter, and a
  partner run out while the batter was on strike does not. No `ballfaced`
  condition is applied, so stumpings and run outs off wides count.
- **Not dismissals**: `retired not out (hurt)`, `not out` and null categories
  are excluded even when the source flags `out`.
- **Literal categories**: the source has no `caught and bowled` value (0 rows)
  and no catcher or fielding-position field. "Caught" means only the stored
  `caught` category (which already contains caught-and-bowled dismissals).
  "Caught and bowled", "caught behind"/"caught at slip"/"caught by the keeper",
  "timed out" and "retired" are targeted data limitations and are never merged
  silently. With explicit comparison wording ("Compare how often Kohli was
  caught and bowled") the phrase lists the two literal categories, and the
  answer shows each separately.
- **Metrics**: `dismissals` (count) and the new registered
  `dismissal_type_percentage` ("Share of Dismissals"): category count divided by
  all recorded dismissals of the same batter in the same scope, times 100. Only
  explicit percentage/share/proportion wording selects the share; "how often",
  "how many times" and "versus" produce counts.
- **Bowler wickets unchanged**: `BOWLER_WICKET_PREDICATE` and
  `is_bowler_credit_wicket` still exclude run outs; the dimension never converts
  dismissals into wickets.
- **Plan shape** (validated in `plan_validator._dismissal_type_errors`):
  `aggregate`, entity `batter`, metric `dismissals` or
  `dismissal_type_percentage`, `group_by: [dismissal_type]`, a named `batter`,
  an optional `dismissal_type` list of registered categories, and only
  delivery-context filters that also apply to a non-striker (bowler, years,
  venue, opposition, innings, phase, over range, competition, bowling style).
  Breakdown ("by dismissal type", "How was Kohli usually dismissed?"),
  filtered direct ("How many times was Kohli caught?") and requested-category
  ("caught versus bowled") forms all compile to this shape and execute through
  `query_builders/dismissal_type_builder.py`. Requested categories are
  enumerated, so a category with no dismissals returns 0 instead of vanishing.
- **Routing**: `canonical_dismissals.resolve_dismissal_types` runs before
  trend/split/comparison/matchup resolution, so a one-player categorical
  comparison never reaches the two-player comparison clarification. The named
  player is always the dismissed batter in any voice; a player after "by"
  ("bowled by Starc") becomes a bowler filter. Category words need dismissal
  context (a dismissal word, passive "was/got ... caught", frequency wording or
  two categories), so "overs bowled" is never a category. Fielding wording
  (catches, run outs effected) keeps the existing data limitation, while "was
  Kohli run out" is now a batter dismissal instead of a fielding limitation.
- **Completeness (#37)**: every extracted category value must be one the
  compiled meaning returns (`filter.dismissal_type`, or
  `dimension.dismissal_type` for an unrestricted breakdown); an extra or
  unregistered category blocks execution. The validator also rejects plans that
  drop the dimension or any requested category. Gemini's "comparison" family
  gloss is accounted for but cannot reroute the registered meaning.
- **Targeted limitations**: rankings of all batters by type, other statistics
  by type, striker-only filters (line, length, shot), ratios between types,
  single-match/stage lookups and chase-outcome/result conditions return a named
  unsupported capability.
- **Follow-ups**: a previous dismissal-type answer accepts scope changes
  ("And in 2019?"), category changes ("What about stumped?"), share/count
  switches ("As a percentage?", "counts instead") and "all dismissal types".

## Independent frozen-database check

Database: `data/odi_analytics.duckdb`

SHA-256: `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`

Read-only queries over `analytics.deliveries_v1`, separate from the application
builder (grouping `p_out` rows in Python), produced:

| Check | Value |
| --- | ---: |
| Virat Kohli caught / bowled | 170 / 34 |
| Kohli leg before wicket / run out / stumped / hit wicket | 19 / 12 / 5 / 1 |
| Kohli recorded dismissals (all registered types) | 241 |
| Kohli run outs as non-striker (included) | 4 |
| Partner run outs while Kohli on strike (excluded) | 11 |
| Legacy striker-attributed `dismissals` metric for Kohli | 248 (= 241 - 4 + 11) |
| Kohli caught share | 70.54% (170 / 241); bowled 14.11% (34 / 241) |
| Kohli 2019: caught / bowled / lbw / total | 18 / 3 / 2 / 23 |
| Kohli 2019 against Australia: caught / total | 7 / 9 |
| Kohli dismissals on Mitchell Starc deliveries: bowled / total | 0 / 1 (lbw) |
| Kohli caught batting first / chasing | 82 / 88 |
| Rohit Sharma lbw / registered total | 23 / 223 (one `retired not out (hurt)` row excluded) |
| Rows stored as `caught and bowled` | 0 |

## Verification

- Focused issue test: `tests/backend/test_issue_40_dismissal_types.py`
  (53 tests), plus the updated registry test.
- Related focused modules (canonical meaning, patches, response policy,
  breakdowns, matchups, comparisons, splits, issues 37–39, language meaning,
  structured planner, chat contract, trace suite, matchup executor): all pass.
- The saved 150-response capture was re-executed offline: 150/150.
- The saved priority-8 capture replays the dismissal tracer as a pass with the
  saved Flash extraction and no new model call (4/8 overall; the remaining four
  are issues #41–#44). No fresh Gemini evaluation was run.

## Limitations

- The existing `dismissals` metric and batting average remain striker-attributed
  (`ballfaced = 1 AND out`, 248 for Kohli). The dismissal-type path uses
  dismissed-batter attribution (241). Aligning the older metric changes existing
  answers and profile numbers and is left for a separate, reviewed change.
- Batter identity follows the existing name-based convention: a name with two
  source identifiers (Mohammad Shahzad) combines both, as `bat = ?` already does.
- Rankings of batters by dismissal type, bowler-perspective wicket types,
  fielder/catcher detail and chase-outcome filters are not supported.
