# Issue 44 verification: bowling-team economy against a batting opposition

Issue 44 adds a registered team metric with explicit batting-team and
bowling-team roles. This is a capability and evidence change only. The approved
UI is unchanged: answers use the existing summary, table and evidence-note blocks.

## Deterministic definitions

The registry lives in `backend/app/cricket_analytics/team_metrics.py`.

| Role | Column | Meaning |
| --- | --- | --- |
| `bowling_team` | `team_bowl` | the team whose bowlers delivered the ball |
| `batting_team` | `team_bat` | the team batting on that ball |

The only registered team metric is `economy_rate`, grouped by `bowling_team`.

### Team economy

Team economy is bowler-attributed runs (`bowlruns`) per six legal balls. This
is the same convention as player economy.

- `bowlruns` includes wide and no-ball runs charged to the bowler, and excludes
  byes and leg-byes.
  - Wide rows: `bowlruns` equals the recorded score (37,294 runs).
  - Bye and leg-bye rows: the 22,757 recorded runs are not charged to the bowler.
- Legal balls exclude wides and no-balls.
- Team economy is **not** the opposition's innings run rate, which also counts
  byes and leg-byes. That is a different team metric, is not registered, and
  requests for it fail closed with this distinction stated.

### Language and roles

| Wording | Canonical meaning |
| --- | --- |
| "bowling team/side/attack/unit", or "team(s)" with economy | grouped subject `bowling_team` |
| "against / vs India", "when India bat" | filter `batting_team = India` |
| "India's bowling", "for India" | filter `bowling_team = India` |
| lowest / best / most economical | sort ascending |
| highest / worst / most expensive | sort descending |
| "top N" | limit N (default 10) |
| "at least N balls" | explicit legal-ball qualification |
| no threshold | documented default of 60 legal balls, shown as a default |

Team names are read as team roles and are never resolved as players. A question
that names a player is not a team question.

Other filters that compose:
- years
- phase
- over range
- venue
- competition
- innings
- match lighting

These fail closed with the reason named:
- other metrics (for example team run rate);
- batting-team economy (asks which role is meant);
- more than one opposition;
- a team bowling against itself;
- unregistered filters.

### Routing

The team-metric stage runs in the planner before any model call, like
registered match facts. It claims:
- questions the capability policy would otherwise refuse as team analysis;
- questions with explicit bowling-side or batting-side wording.

So a request such as "Which bowling side is most economical against India?" can
no longer become a player ranking. Other policy outcomes, such as future
prediction, keep precedence.

### Validation and completeness

A bowler-owned metric on a team entity is valid only through its registered
team role (`economy_rate` grouped by `bowling_team`). Team plans must use
explicit `batting_team` or `bowling_team` filters, never `opposition`, and must
carry a legal-ball qualification.

The #37 completeness record lists:
- the grouped team role;
- each team filter;
- sort direction and limit;
- the threshold, marked `compiled` when requested or `default_applied` when
  the default was used.

### Evidence

The summary names the batting opposition. It shows either "the default minimum
of 60 legal balls" or "a minimum sample of N legal balls", so a default never
masquerades as a user threshold.

The **Team metric definition** note states:
- the numerator, denominator and extras treatment;
- the difference from innings run rate;
- both team roles;
- the qualification and whether it was requested;
- the sort order.

The table lists economy, runs conceded, legal balls and matches per bowling
team, so the table, narrative and sort field use the same metric and role.

No-result matches contribute their recorded deliveries, as for player economy.
No delivery has a missing bowling team. A qualification that no team meets
returns the standard insufficient-evidence state.

## Independent frozen-database check

Database: `data/odi_analytics.duckdb`

SHA-256: `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`

These are independent read-only queries grouping by `team_bowl`, written
separately from the application builders.

| Check | Value |
| --- | ---: |
| Against India, ≥ 60 legal balls: rank 1 | Zimbabwe 5.19 (4,099 / 4,743) |
| Against India, ≥ 600 legal balls: rank 1 | Zimbabwe 5.19 (4,099 / 4,743) |
| Against India, ≥ 600: ranks 2–3 | Ireland 5.30 (624 / 706), South Africa 5.30 (10,752 / 12,175) |
| Against India, ≥ 60: highest economy | Bermuda 8.12 (300 legal balls) |
| Against India in 2019: lowest | Afghanistan 4.48 (300 legal balls) |
| All matches: highest economy | World-XI 5.72 (1,139 legal balls) |
| Bowling teams that have bowled to India | 17 |

## Verification

- Focused issue test: `tests/backend/test_issue_44_team_economy.py` (24 tests).
  It covers:
  - the tracer with no model call and the default qualification displayed;
  - the explicit 600-ball threshold;
  - completeness of role, opposition, direction and threshold;
  - six direction wordings;
  - the global form;
  - composition with year, phase and venue, and the limit;
  - team names read as roles;
  - fail-closed metrics, role mismatch and multiple oppositions;
  - insufficient sample;
  - policy precedence;
  - validator role enforcement;
  - unchanged player economy and team run-rate split answers.
- Full suite: 1,315 passed, 0 failed.
- Saved priority-8 capture replayed offline: 8/8. The team-economy tracer
  now passes with no model call.
- Saved 150-response capture replayed offline through the application and
  database: 148/150. The two differences are the intended capability change,
  not regressions:
  - `unseen-unsupported-team-econ-a`: "Which national side has the best bowling
    economy?"
  - `unseen-unsupported-team-econ-b`: "Rank teams by economy rate against India."

  Both were frozen as unsupported refusals. They now return the registered
  bowling-team economy ranking. As issue 47 directs, the frozen 150 is left
  unchanged as compatibility evidence, and the new behaviour is recorded here
  and in the new capability benchmark. No other saved case changed. No fresh
  Gemini evaluation was run.
- Earlier tests that encoded the refusal were updated with the database
  evidence above:
  - the `odi_correctness_v1` gate case, now a supported team-economy case plus
    a still-unsupported team run-rate case;
  - two golden factual cases;
  - the grounded failure-state contract, which now uses team run rate as its
    unsupported example.

  The golden contract also accepts the registered team-metric stage as a
  fail-closed source.

## Limitations

- Economy is the only registered team metric. Batting-team metrics such as
  team run rate, and opposition innings run rate conceded, fail closed.
- Contextual follow-ups after a team ranking ("What about against Australia?")
  are not patched yet. They return planner uncertainty rather than a wrong answer.
- Team summaries do not repeat year filters in the sentence. This predates
  issue 44 for aggregate summaries; the plan and evidence carry the filter.
