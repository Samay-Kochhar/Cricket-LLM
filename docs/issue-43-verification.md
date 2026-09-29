# Issue 43 verification: one-player splits by recorded match lighting

Issue 43 adds `match_lighting` as a registered split dimension and filter over
the database's recorded match-lighting category. This is a capability and
evidence change only. The approved UI is unchanged: answers use the existing
summary, table and evidence-note blocks.

## Deterministic definitions

`match_lighting` reads the stored `daynight` column, which holds one value per
match. Its registered values are the literal stored labels:

| Stored value | Matches | Delivery rows |
| --- | ---: | ---: |
| `day match` | 1,368 | 727,170 |
| `day/night match` | 1,178 | 626,104 |
| `night match` | 21 | 11,577 |

No match has a null or conflicting value. Any unknown, null or unexpected value
would be excluded and counted in the evidence note, never reassigned.

The registry lives in `backend/app/cricket_analytics/match_lighting.py`.

- **Split:** two categories. It is compiled in `canonical_splits.py`, and
  `split_compare_executor.py` buckets only the literal stored values.
- **Filter:** one category. It is compiled as `CAST(daynight AS VARCHAR) = ?`
  in the shared aggregate filter builder, so it works for aggregates, rankings,
  trends, matchups, player comparisons and dismissal-type counts.
- **Excluded:** a malformed value compiles to `1 = 0` and never widens scope.

Economy uses the existing definition: `bowlruns` over legal balls (no wides and
no no-balls), times 6.

### Language rules

| Wording | Category |
| --- | --- |
| "day", "daytime" (never "one-day") | `day match` |
| "day/night", "day-night", "d/n" | `day/night match` |
| "pure night", "night-only", "only night" | `night match` |
| casual "night" ("day versus night matches", "at night") | `day/night match`, with a disclosure |
| casual "night" alongside explicit "day/night" | `night match` (so the two never collapse) |
| "floodlit", "under lights", "evening", "twilight" | fails closed; not a recorded category |
| more than two categories | fails closed |

### Casual "night" and day/night disclosure

Casual night wording is read as the recorded `day/night match` category,
because ODIs called night games are recorded as day/night matches. The
**Match lighting** evidence note always shows:

- the literal categories used;
- that a `day/night match` is a scheduled match category, not evidence that
  every delivery was bowled at night;
- when casual wording was used, that pure `night match` is a separate
  category the user can ask for;
- the count of in-scope deliveries with no or unexpected lighting.

Explicit pure-night wording keeps the `night match` category. Bumrah has no
such rows, so the answer is an insufficient-evidence data limitation
("Night Match has 0 balls"). The day/night category is never substituted.

### Evidence

A named-player lighting split adds a **Recorded match-lighting evidence**
table. Each category gets its own row, with the metric's numerator,
denominator and match count, taken from the same registered aggregate builder
as a direct answer.

### Routing and completeness

Split resolution runs before the two-player comparison family. One named player
with two lighting categories therefore becomes `split_compare`, even when Flash
labels the question "comparison", and never asks for a second player. The #37
completeness check accounts for Flash's dimension (`day_night_condition`), its
filter and each value as `dimension.match_lighting`. The validator rejects
plans that:

- drop, change or reorder into different categories;
- split by another dimension;
- lose a single requested lighting filter;
- use an unregistered value.

### Follow-ups

`match_lighting` is a patchable filter:

- "What about day matches?" replaces it.
- "Remove the lighting filter" removes it.
- "Only in day/night matches" adds it to a previous phase split.

Metric follow-ups on a lighting split keep the categories.

## Independent frozen-database check

Database: `data/odi_analytics.duckdb`

SHA-256: `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`

These are independent read-only queries over `analytics.deliveries_v1`, written
separately from the application builders.

| Check | Value |
| --- | ---: |
| Bumrah, day match: runs / legal balls / economy | 1,055 / 1,487 / 4.26 |
| Bumrah, day/night match: runs / legal balls / economy | 2,454 / 3,093 / 4.76 |
| Bumrah, night match: rows | 0 |
| Bumrah, all matches: legal balls | 4,580 |
| Kohli, day match: runs / balls | 3,150 / 3,540 (SR 88.98) |
| Kohli, day/night match: runs / balls | 10,800 / 11,378 (SR 94.92) |
| Kohli v Starc, day/night match: runs / balls | 109 / 114 |
| Rohit, day/night match: strike rate | 96.34 |
| Kohli dismissed in day/night matches: caught / bowled | 124 / 28 |

## Verification

- Focused issue test: `tests/backend/test_issue_43_match_lighting.py` (34 tests).
  It covers:
  - the saved Flash extraction and model-free tracer, with completeness facts;
  - stored-label registry checks;
  - language parsing (including "one-day" exclusions);
  - five paraphrases and reversed order;
  - pure-night insufficient evidence;
  - disclosure presence and absence;
  - unrecorded categories failing closed;
  - malformed values;
  - composition with the filter form, batter metrics, matchups, comparisons,
    dismissal types and opposition;
  - follow-ups;
  - validator rejection;
  - unchanged phase splits.
- Saved 150-response capture replayed offline through the application and
  database: 150/150. No fresh Gemini evaluation was run.
- Saved priority-8 capture replayed offline: 7/8. The lighting tracer passes;
  the remaining case belongs to issue 44.
- Full suite: 1,291 passed, 0 failed.

## Limitations

- A `by match lighting` breakdown (all three categories as rows) is not
  registered yet. It is answered as a two-category split or a filter.
- Split table column headers use the identifier form ("Day Night Match Value").
  The summary, the evidence table and the note use the literal
  `day/night match` label.
