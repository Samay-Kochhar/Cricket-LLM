# Issue 46 verification: Workbench routing through shared semantic meaning

Issue 46 changes how a Workbench search is routed. The approved player, squad,
year-choice and unsupported cards are unchanged.

## Defect

`WorkbenchService.search` ran repository token-overlap searches on the entire
raw sentence before deciding what the user asked:

- In "Show the best death-over bowlers with at least 300 balls", the word
  "best" matched the player Tino Best, so the question became a Tino Best
  profile.
- A player match with no team match always selected the first repository
  candidate. So "Sharma" silently became one Sharma, and "Kohli versus Starc
  head to head" became a Kohli profile.
- Questions naming no player or team, such as "Which bowling team has the lowest
  economy against India?", returned "Try a player name or a team and year."
- Natural-language questions went to the legacy query handler, so Chat and
  Workbench could interpret the same question differently.

## Routing seam

`backend/app/services/workbench_service.py` now makes one explicit choice:

1. **Structured lookup (exact input only).** The whole input, after removing
   years, must be one of the following:
   - an exact team name (optionally with `squad`, `team`, `side`, `odi`, `odis`
     or `in`);
   - an exact player name or a registered alias (`player_resolution.ALIASES`);
   - at most four whole words, all of which are whole words of one player's
     name, such as "Virat" or "Sharma".

   The results are:
   - Team with a year: `team_squad`.
   - Team without a year: `team_year_required`.
   - One player: the approved `player_result`, which uses the same profile
     handler and role summary as before.
   - Several players: a `clarification` listing every matching player.

   A sentence never reaches this lookup by partial token overlap.
2. **Natural-language analytics (everything else).** The question goes to the
   same `query_handler` object Atlas Chat uses (Semantic V2 when enabled), after
   the same pre-model metric clarifications as Chat. These now live in
   `chat_service.standalone_metric_clarification`; Chat's behavior is
   unchanged. Players and teams are resolved from the mentions that Semantic V2
   extracts. The response kinds are:
   - A Semantic V2 clarification becomes a `clarification` with the same option
     wording as Chat.
   - A refusal or data limitation becomes the existing `unsupported` card with
     the Semantic V2 reason.
   - An answer about exactly one player keeps the approved `player_result` card,
     carrying the Semantic V2 answer.
   - Every other answer becomes `analytics_result`.

The Gemini-based player/team tie-break in Workbench is removed. Structured
lookup is deterministic, and natural-language meaning comes only from the shared
Semantic V2 path. `bootstrap.py` wires `query_handler=query_handler` (shared with
Chat) and `profile_handler=legacy_query_handler`. The profile handler is only
for exact player lookups: it produces the approved pitch map, wagon wheel, shot
profile, field zones and radar visuals.

### Frontend

The Workbench page previously had no way to show a result that is not a player,
squad or refusal. Two render branches were added. They reuse only existing
components and classes, and no existing element changed.

- `analytics_result`: the same `workbench-grid` as the player result. It has a
  `workbench-card` headed "Resolved question" with the question and its answer
  sentence, then `ChatResponseSections` and the "Search trace" details.
- `clarification`: the same `panel result-panel` as the unsupported card, plus
  the `chip-row` / `suggestion-chip` buttons used by the year choice. Choosing
  an option searches that option.

`api-types.ts` gains the two response variants.

## Verification

### Independent database checks (read-only DuckDB)

| Check | Query result | Displayed |
| --- | --- | --- |
| Kohli v Starc, all ODI deliveries | 156 runs, 155 non-wide balls | "Virat Kohli scored 156 runs from 155 balls against Mitchell Starc" |
| Death overs (stored overs 41–50) | Kohli 1523 runs / 1016 balls (149.90); Rohit 1107 / 725 (152.69) | "Virat Kohli scored more runs than Rohit Sharma: 1523 vs 1107 … 152.69 vs 149.9" |
| Players whose surname is Sharma | Aryansh, Ishant, Joginder, Karn, Mohit, Rahul, Rohit, Sanchit | Same eight choices |
| Players whose surname is Best | Tino Best only | Never selected for the best-bowlers ranking |

### Focused backend tests

`tests/backend/test_workbench_service.py`: 28 passed. The tests cover:

- exact player, alias and unique-name-word lookups using the profile handler;
- team plus year, team with "squad", and team without a year;
- ambiguous surnames (Sharma, Pandya) returning targeted choices;
- "best death-over bowlers" reaching the analytics handler verbatim, with no
  Tino Best;
- ordinary words ("best economy", "most runs", team economy) never becoming
  players;
- two-player and single-player analytics;
- Semantic V2 and metric clarifications, refusals and empty input;
- on the real database with the real `SemanticAnalyticsService` (Gemini off):
  - Chat and Workbench produce identical entities and canonical filters for
    four questions;
  - the death comparison keeps both players and `phase=death`;
  - head to head compiles to a Kohli-batter/Starc-bowler `matchup`;
  - every Sharma is offered;
- `bootstrap` gives Workbench and Chat the same `query_handler` object.

### Real browser (Playwright `integration`, real backend, no interception)

`frontend/e2e/workbench.integration.spec.ts` (new, 6 tests):

- The best-bowlers ranking returns `analytics_result`. It shows no "Resolved
  player" card and no Tino Best.
- Kohli versus Starc head to head shows the matchup sentence above.
- The Kohli/Rohit death comparison shows 1523 vs 1107.
- "Virat Kohli" shows the approved player card and role summary.
- "Sharma" shows the choices. Choosing Rohit Sharma loads his player card.
- "India" asks for a year. Choosing 2019 loads the India 2019 squad.

Result: the whole integration project passed (17 tests: 6 new Workbench, 3
routing and 8 ODI smoke). The API ran on port 8765 with `GEMINI_API_KEY` empty,
so no model calls were made. The `mocked` project also passed (13 tests).

The issue 45 routing spec still searches "death over strike rate of Hardik
Pandya". That wording has no batting/bowling role for an all-rounder, so both
Chat and Workbench now ask "batting or bowling strike rate?", as the glossary
requires. The spec checks only same-origin routing and a 200 response, so it is
unaffected.

### Saved-response replays (offline, no model calls)

- Frozen 150 replay: 148/150 with no regressions. The two differences are the
  intended issue 44 team-economy cases (`unseen-unsupported-team-econ-a/-b`).
  The frozen 150 files are unchanged.
- Priority-8 replay: 8/8.

No fresh Gemini run was needed for this routing slice.

### Full suite

`python -m pytest tests -q`: 1342 passed (baseline 1316 at 697730d plus 26 net
new Workbench tests).

## Known limitations

- With Gemini disabled, the development fallback reads "best death-over bowlers
  with at least 300 balls" as a batter runs ranking. Chat does the same because
  the path is shared. Production extraction is unaffected, and the issue 47
  fresh runs cover the live model path.
- A single-word input that is a player's whole surname, such as "Best", is still
  treated as a player lookup, because the user typed only that name.
