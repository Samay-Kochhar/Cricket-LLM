# Database Table Schemas (v1)
For IPL analytics system built from raw JSON files.

We use **two main tables**:

- `matches`   – one row per match (match-level info)
- `deliveries` – one row per ball (ball-by-ball info)

These tables are populated from the raw JSON structure described in `ipl_match_schema.json`.


---

## 1. `matches` table (v1)

**Purpose:**  
Store one row per match with all important match-level metadata:
- teams
- date, season, venue
- result
- officials
- playing XIs

**Primary key:**  
- `match_id` (taken from the JSON filename, e.g. `238195.json` → `match_id = 238195`)

### Columns

| Column name         | Type      | Source in raw JSON                       | Notes |
|---------------------|-----------|------------------------------------------|-------|
| `match_id`          | INTEGER   | Filename (e.g. `238195.json`)            | Primary key |
| `season`            | TEXT      | `info.season`                            | Season/year label |
| `match_date`        | DATE      | `info.dates[0]`                          | First date string parsed as date |
| `city`              | TEXT      | `info.city`                              | Can be NULL if missing |
| `venue`             | TEXT      | `info.venue`                             | Stadium / ground |
| `event_name`        | TEXT      | `info.event.name`                        | Optional (tournament/league name) |
| `match_number`      | INTEGER   | `info.event.match_number`                | Optional |
| `team1`             | TEXT      | `info.teams[0]`                          | First team listed |
| `team2`             | TEXT      | `info.teams[1]`                          | Second team listed |
| `toss_winner`       | TEXT      | `info.toss.winner`                       | Team that won the toss |
| `toss_decision`     | TEXT      | `info.toss.decision`                     | `"bat"` or `"field"` |
| `winner`            | TEXT      | `info.outcome.winner`                    | Winning team; NULL if tie/NR |
| `result_margin`     | INTEGER   | `info.outcome.by.runs` or `.wickets`     | Numeric margin (runs or wickets) |
| `result_margin_type`| TEXT      | `"runs"` or `"wickets"`                  | Which margin was used in `by` |
| `balls_per_over`    | INTEGER   | `info.balls_per_over`                    | Usually 6 |
| `overs_scheduled`   | INTEGER   | `info.overs`                             | Scheduled overs per innings (e.g., 20) |
| `match_type`        | TEXT      | `info.match_type`                        | e.g. `"T20"` |
| `gender`            | TEXT      | `info.gender`                            | e.g. `"male"` |
| `team_type`         | TEXT      | `info.team_type`                         | e.g. `"club"` |

### Officials and player-of-match

| Column name        | Type    | Source in raw JSON                     | Notes |
|--------------------|---------|----------------------------------------|-------|
| `player_of_match`  | TEXT[]  | `info.player_of_match`                 | List of names; may contain 1+ players |
| `umpires`          | TEXT[]  | `info.officials.umpires`               | On-field umpires |
| `tv_umpires`       | TEXT[]  | `info.officials.tv_umpires`            | TV/third umpire(s) |
| `reserve_umpires`  | TEXT[]  | `info.officials.reserve_umpires`       | Optional |
| `match_referees`   | TEXT[]  | `info.officials.match_referees`        | Match referee(s) |

### Playing XIs

| Column name        | Type   | Source in raw JSON                      | Notes |
|--------------------|--------|-----------------------------------------|-------|
| `players_team1`    | TEXT[] | `info.players[team1]`                   | Full XI for team1 |
| `players_team2`    | TEXT[] | `info.players[team2]`                   | Full XI for team2 |


---

## 2. `deliveries` table (v1)

**Purpose:**  
Store one row per ball (delivery) with:

- who bowled to whom
- runs / extras on that ball
- dismissal information
- derived flags for phases, dots, boundaries, etc.

**Primary key:**  
- For now we can use a composite key: `(match_id, innings_number, over_number, ball_in_over)`  
  Later we may add a surrogate `delivery_id` if needed.

**Foreign key:**

- `match_id` → `matches.match_id`


### Columns

| Column name                | Type    | Source / Logic                                                                 |
|----------------------------|---------|-------------------------------------------------------------------------------|
| `match_id`                 | INTEGER | From filename (e.g. `238195.json` → 238195)                                   |
| `innings_number`           | INTEGER | Index in `innings[]` + 1 (1 for first innings, 2 for second, etc.)           |
| `batting_team`             | TEXT    | `innings[i].team`                                                             |
| `bowling_team`             | TEXT    | The other team from `info.teams` (team not equal to `batting_team`)          |
| `over_number`              | INTEGER | `innings[i].overs[j].over` (0-based over index from JSON)                    |
| `ball_in_over`             | INTEGER | Position in `overs[j].deliveries` list (1–6)                                  |
| `ball_number_absolute`     | INTEGER | Sequential **legal** ball count in this innings (1,2,3,...)                   |
| `phase`                    | TEXT    | `"powerplay (file)"`, `"middle (derived)"`, or `"death (derived)"`           |
| `batter`                   | TEXT    | `delivery.batter`                                                             |
| `bowler`                   | TEXT    | `delivery.bowler`                                                             |
| `non_striker`              | TEXT    | `delivery.non_striker`                                                        |
| `runs_batter`              | INTEGER | `delivery.runs.batter`                                                        |
| `runs_extras_total`        | INTEGER | `delivery.runs.extras`                                                        |
| `runs_total`               | INTEGER | `delivery.runs.total`                                                         |
| `extras_wides`             | INTEGER | `delivery.extras.wides` if present, else 0                                    |
| `extras_noballs`           | INTEGER | `delivery.extras.noballs` if present, else 0                                  |
| `extras_byes`              | INTEGER | `delivery.extras.byes` if present, else 0                                     |
| `extras_legbyes`           | INTEGER | `delivery.extras.legbyes` if present, else 0                                  |
| `runs_conceded_bowler`     | INTEGER | `runs_batter + extras_wides + extras_noballs` (byes/legbyes excluded)         |
| `is_legal_delivery`        | BOOLEAN | `FALSE` for wides and (depending on convention) no-balls without legal ball; `TRUE` otherwise |
| `is_boundary_4`            | BOOLEAN | `runs_batter == 4`                                                            |
| `is_boundary_6`            | BOOLEAN | `runs_batter == 6`                                                            |
| `is_dot_ball_bowler_view`  | BOOLEAN | `runs_conceded_bowler == 0`                                                   |
| `is_dot_ball_batter_view`  | BOOLEAN | `runs_batter == 0`                                                             |
| `dismissal_kind`           | TEXT    | From first `delivery.wickets[0].kind` if any wicket on this ball; else NULL  |
| `dismissal_player_out`     | TEXT    | `delivery.wickets[0].player_out` if present; else NULL                        |
| `dismissal_bowler_credit`  | BOOLEAN | TRUE if `dismissal_kind` is one where bowler gets credit (bowled, lbw, caught, stumped, etc.); FALSE/NULL otherwise |
| `fielder_1`                | TEXT    | `delivery.wickets[0].fielders[0].name` if present; else NULL                  |


---

## Notes and Assumptions (v1)

1. **match_id**
   - Derived from filename: `<match_id>.json`.
   - Used as the primary key in `matches` and foreign key in `deliveries`.

2. **innings_number**
   - 1-based index of the innings in the `innings` array in the JSON.

3. **bowling_team**
   - Determined by taking the team from `info.teams` that is **not** equal to `batting_team`.

4. **ball_number_absolute**
   - Counts only **legal** balls in the innings.
   - Wides and no-balls may not increment this count depending on how we decide to treat them (to be consistently implemented in code).

5. **phase**
   - `powerplay (file)` – deliveries whose ball index is within the `powerplays` range given in the JSON (`from`–`to`).
   - `middle (derived)` – deliveries after powerplay ends up to over 15.6.
   - `death (derived)` – deliveries from over 16.0 to the end of innings.

6. **runs_conceded_bowler**
   - Defined as: `runs_batter + wides + no-balls`.
   - Byes and leg byes **do not** count towards bowler’s runs conceded.

7. **dismissal_bowler_credit**
   - TRUE if `dismissal_kind` is in the set of bowler-credit dismissals: typically `"bowled"`, `"lbw"`, `"caught"`, `"stumped"` (and similar).
   - FALSE/NULL for dismissals like `"run out"`.


---

_End of v1 schema for `matches` and `deliveries`._
