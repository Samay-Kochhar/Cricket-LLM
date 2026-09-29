# Issue 39 verification: toss-winner match facts

Issue 39 answers database-identifiable toss facts through the registered
match-fact path. This is a capability and evidence change only; the approved UI
is unchanged.

## Deterministic definitions

- **Registered facts** (`MATCH_FACT_REGISTRY`): `toss` reads only the stored
  `toss` field, `winner` reads only the stored `winner` field, and `team_total`
  reads innings state. The three are separate fact types in extraction, canonical
  meaning, compiled plan (`filters.fact_type`), resolution, evidence and summary.
- **Match-level collapse**: `MATCH_METADATA_CANDIDATES_SQL` groups delivery rows by
  `p_match` and lists the distinct trimmed year, date, competition, ground, winner,
  toss and team values, plus counts of rows with a missing toss or winner. A value
  is used only when exactly one distinct value exists and no row is missing it;
  otherwise the request fails closed as a data limitation.
- **No recorded winner**: the source uses `-` when a match has no winner (tie or no
  result). `-` is never a team: a `winner` request returns a data limitation, a
  `-` toss value is treated as missing, and a toss value must be one of the
  match's two teams. Toss is never inferred from innings order or the winner.
- **Competition aliases** (`COMPETITION_REGISTRY`): each tournament family maps
  its aliases to the exact stored name per edition:

  | Family | Stored editions |
  | --- | --- |
  | ICC Cricket World Cup (`world cup`, `cricket world cup`, `icc world cup`, `cwc`) | 2007 `ICC World Cup`; 2011, 2015, 2019 `ICC Cricket World Cup`; 2023 `World Cup 2023` |
  | ICC Champions Trophy | 2006, 2009, 2013, 2017 |
  | Asia Cup | 2008, 2010, 2012, 2014, 2018, 2023 |

  An alias qualified as another event (T20, women's, U19, Afro-Asia, qualifiers,
  Super League, league) is a data limitation and never broadens to the ODI
  tournament. A year with no stored edition is a data limitation that lists the
  stored editions. A focused test asserts the registry equals the database's
  stored competition/year pairs.
- **Final selection rule**: the database has no stage field. A final is the sole
  match on the latest recorded date within the exact stored competition and year
  of a registered single-final tournament, and it must record exactly two teams.
  Two matches on that date is ambiguous. The rule is never applied to other
  competitions (bilateral series, tri-series with best-of-three finals,
  qualifiers, leagues) or to other stages: semi-final, quarter-final, group stage,
  super six/eight, opening match and eliminator requests are data limitations.
  "Who won the 2011 World Cup?" asks for the tournament winner and uses the same
  final rule; toss questions always need the stage.
- **Identity constraints**: named teams must have played the selected match and a
  named venue must equal its stored ground; otherwise the answer is a data
  limitation. A polar question naming one team ("Did India win the toss ...")
  answers Yes or No before the stored fact.
- **Completeness (#37)**: every registered match-fact meaning records a
  disposition for fact type, year, competition, stage, venue and named teams, with
  the exact question excerpt as evidence. Missing year, competition or stage asks
  a focused clarification; more than one year, stage, venue or competition, or a
  request for both toss and match winner, asks a clarification. Toss decisions
  (not stored) are a data limitation; toss counts/rates, toss-result filters,
  toss losers and players applied to a toss are unsupported with the reason named.
- **Precedence**: response capability policy (for example future prediction)
  runs before the match-fact path. Questions naming a player, ranking wording or
  "full toss" deliveries are not claimed by the match-fact path.

## Independent frozen-database check

Database: `data/odi_analytics.duckdb`

SHA-256: `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`

Independent read-only queries over `analytics.deliveries_v1`, separate from the
application SQL, produced:

| Check | Value |
| --- | --- |
| 2019 `ICC Cricket World Cup` matches / date range | 45 / 2019-05-30 to 2019-07-14 |
| Matches on the latest 2019 date | 1 (match 1144530) |
| Match 1144530 delivery rows | 622 |
| Distinct toss / winner / date / ground / competition / year values | 1 each |
| Toss | New Zealand (0 rows missing) |
| Stored winner | `-` |
| Ground | Lord's, London |
| Teams | England, New Zealand |
| Innings totals | New Zealand 241/8, England 241/10 (tied) |
| 2011 final (433606) | Sri Lanka won toss; India won; Sri Lanka 274/6, India 277/4 |

Across the dataset (2,567 matches), no match has inconsistent toss, winner,
date, ground, competition or year values across delivery rows, and no match has
a missing toss row. 122 matches store winner `-`. One match (66387, 2005) stores
toss `ICC World XI` while its teams are `Asia XI` and `World-XI`; the resolver
fails closed for such a match instead of guessing the name mapping.
The latest-date rule selects the known final of every registered edition:
World Cup 2007 247507, 2011 433606, 2015 656495, 2019 1144530, 2023 1384439;
Champions Trophy 2006 249759, 2009 415287, 2013 566948, 2017 1022375; Asia Cup
2008 335358, 2010 455237, 2012 535800, 2014 710311, 2018 1153255, 2023 1388414.

## Verification

- Focused issue test: `tests/backend/test_issue_39_toss_facts.py` (60 tests).
- Focused compatibility run (issue 37, 38 and 39 tests, grounded completion
  contract, golden factual chat): 256 passed.
- Full suite: 1,057 passed, 11 failed. The same 11 fail on the unchanged parent
  commit and at 54a1821, and pass at f90a5ac; they are the "minimum N balls"
  sort-direction regression described under limitations, not match facts.
- The saved 150-response capture
  (`tests/evals/results/releases/current-2026-09-27/fresh-150.jsonl`) was
  re-executed through the application and database offline: 145/150, identical to
  the unchanged baseline before this change. The five failures are pre-existing
  ranking sort-direction regressions unrelated to match facts (see limitations).
- The saved priority-8 capture replays the toss tracer as a pass with no model
  call; no fresh Gemini evaluation was run.

## Limitations

- Contextual follow-ups after a match-fact answer ("And in 2015?") are not yet
  patched from conversation state; they return planner uncertainty rather than a
  wrong match.
- Toss decision, toss loser and toss-conditioned statistics are not registered.
- Five saved-150 ranking cases (`unseen-rank-middle-dots-a`,
  `unseen-rank-yorker-rate-a`, `unseen-rank-worst-econ-a`, `unseen-rank-spin-sr-a`,
  `unseen-rank-pace-boundary-b`) fail offline replay at this change's baseline and
  at 54a1821; they pass at f90a5ac. All five use "minimum N legal balls" wording,
  and 54a1821 added "minimum" as an ascending-order word in
  `requested_sort_direction`. This is outside issue 39 and is left for a separate
  fix.
