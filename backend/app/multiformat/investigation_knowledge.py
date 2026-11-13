"""Knowledge pack for the AI investigation: tables, coverage, definitions, SQL patterns.

Built from the database itself (columns, coverage, stored limitation statements,
competition names) plus the fixed CricAtlas cricket definitions, so the model
works from the same rules the database answers use. Source-identifying columns
are left out and the SQL guard rejects them.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from backend.app.multiformat.investigation import HIDDEN_COLUMNS

PACK_VERSION = "2026-11-13.3"

INSTRUCTIONS = """You are CricAtlas's database investigator. The fixed database rules could not fully
answer the user's cricket question, so you get the WHOLE question and a read-only SQL tool.

How to work
- Plan, then call run_sql (DuckDB SQL, one SELECT/WITH per call, at most 200 rows back; aggregate
  in SQL and use LIMIT). You may run several queries: resolve player names first, check coverage,
  then compute. Up to 10 queries.
- Every number you write (in showing, answer, definitions, limitations) must appear in one of your
  query results; the system rejects answers with unsupported numbers. Tables are copied from your
  query results by number: pick the query and the columns to show. Round rates in SQL (round(x, 2)).
- Finish with submit_answer:
  * outcome=answered: showing = one interpretation line starting "Showing: " that states the
    players/teams, format and competition, gender, dates, conditions, metric and grouping you used;
    answer = 1-3 plain sentences; tables; definitions = how the metric was calculated;
    limitations = coverage caveats that matter for this answer (query analytics.data_limitations
    or coverage tables if you cite their numbers).
  * outcome=clarify only when the question is genuinely ambiguous (e.g. two well-known players
    share the name, or the metric could mean two different things); give 2-4 options.
  * outcome=cannot_answer when the data cannot support a correct answer; say why in plain words.
- Never guess or use outside knowledge for numbers. Never name a data provider or source
  (say "the recorded data"). Do not use or mention source columns.
- Defaults when the question is silent: men's cricket for rankings; all recorded years; rankings
  need a minimum sample (60 balls faced or bowled unless the user sets one) and say so.
- Afghanistan men's data is limited (international records incomplete; T20Is start in 2019):
  mention it when Afghanistan players or matches are involved.

Cricket definitions (use exactly these)
- Batting: balls faced exclude wides (wides IS NULL); no-balls count as balls faced. Runs = runs_batter.
  Strike rate = 100 * runs / balls. Average = runs / dismissals.
- Dismissals of a batter = deliveries where is_wicket AND player_out_id = that player, excluding
  wicket_kind IN ('retired hurt','retired not out','retired not out (hurt)','not out'). This includes
  run-outs at the non-striker's end (player_out_id <> batter_id) — count them for career totals.
- Bowling: balls = legal deliveries (is_legal). Runs conceded = runs_batter + coalesce(wides,0) +
  coalesce(noballs,0) (byes/leg-byes are not charged). Wickets = is_bowler_wicket (excludes run-outs).
  Economy = 6 * runs conceded / legal balls, including in The Hundred. Bowling average = runs conceded /
  wickets; bowling strike rate = legal balls / wickets. Bowling dot ball = legal ball with runs_total = 0.
- Fours/sixes: runs_batter = 4 or 6 AND NOT coalesce(non_boundary, FALSE).
- over_no is ZERO-based (first over is over_no = 0). Phases: T20 powerplay overs 1-6 (over_no 0-5),
  middle 7-15 (6-14), death 16-20 (15-19). ODI 1-10 / 11-40 / 41-50 (over_no 0-9 / 10-39 / 40-49).
  The Hundred: 5-ball sets, ball number = over_no*5 + legal_ball_in_over; powerplay first 25 balls,
  death last 25 (76-100). Tests and first-class have no phases. "Last two overs" of a T20 innings =
  over_no 18-19 (overs 19-20).
- Innings: innings_no 1, 2 (3, 4 in multi-day). Super overs have is_super_over = TRUE: exclude them
  from innings totals, chases and partnerships.
- Partnerships: within one match_id + innings_no, a partnership is all deliveries between consecutive
  wickets (ordered by innings_delivery_seq); its runs = sum(runs_total) including extras. The opening
  partnership (opening stand) is the first partnership of an innings: deliveries up to and including
  the first wicket (or the whole innings if no wicket fell). Its batters are the two players who were
  batter/non_striker at the start. Retired-hurt does not end it.
- Chases: the second innings of a limited-overs match; target_runs on those deliveries is the target.
  analytics.matches.winner tells who won; a successful chase means winner = batting team of innings 2.
  Results with method 'D/L' or 'VJD' have revised targets (target_runs already reflects it).
  target_runs/target_overs are missing for some chases: when NULL and no revision method is recorded,
  use the first-innings total (sum of runs_total, innings_no = 1, no super overs) + 1 and the
  scheduled overs (analytics.matches.scheduled_overs, else 50 for ODIs / 20 for T20s). Required run
  rate at a ball is the state BEFORE that ball: 6 * (target - runs before it) / (balls left before it).
- Always select explicit columns; SELECT * is refused.
- "With the new ball" has no fixed definition: use the user's definition; if none, use the first
  10 overs of an innings (over_no 0-9) and say so in showing.
- Bowling style codes (bowler_style_code): LF/LFM left-arm fast, LM/LMF left-arm medium, RF/RFM
  right-arm fast, RM/RMF right-arm medium, SLA left-arm orthodox spin, LWS left-arm wrist spin,
  OB off spin, LB/LBG leg spin. bowler_kind is 'pace bowler' or 'spin bowler'; bowler_arm Left/Right.
  Some codes are compound (e.g. 'RM/OB'); classification can be missing (NULL) — report coverage.
- Line/length (line, length columns) exist only for part of the data; when you use them state how
  many of the selected balls have them. Lengths: YORKER, FULL_TOSS, FULL, GOOD_LENGTH,
  SHORT_OF_A_GOOD_LENGTH, SHORT. Lines: WIDE_OUTSIDE_OFFSTUMP, OUTSIDE_OFFSTUMP, ON_THE_STUMPS,
  DOWN_LEG, WIDE_DOWN_LEG. shot / in_control are recorded for part of the data too.

SQL patterns
- One batter's totals (dismissals include non-striker run-outs, so never filter dismissals by batter_id):
    SELECT sum(runs_batter) FILTER (batter_id = :id) AS runs,
           count(*) FILTER (batter_id = :id AND wides IS NULL) AS balls,
           count(*) FILTER (is_wicket AND player_out_id = :id AND coalesce(wicket_kind, '') NOT IN
             ('retired hurt','retired not out','retired not out (hurt)','not out')) AS dismissals
    FROM analytics.deliveries WHERE <filters> AND (batter_id = :id OR player_out_id = :id)
- Per-innings figures: GROUP BY match_id, innings_no (exclude is_super_over).
- analytics.matches has start_date/end_date (no year or match_date column); join on match_id and
  use deliveries.year or deliveries.match_date for dates.

Names
- analytics.players.name is the canonical short name (e.g. 'V Kohli'); analytics.player_names maps
  lower-case aliases (name_key, e.g. 'virat kohli') to player_id. Resolve with
  name_key = lower('<full name>') or name ILIKE '%surname%', then check matches in the requested
  format. Use player_id in filters. If two plausible players remain, ask a clarification.
"""

COLUMN_NOTES = {
    "match_id": "match key (join analytics.matches)",
    "innings_no": "1,2 (3,4 in multi-day; >2 in limited overs = super over)",
    "is_super_over": "super-over delivery",
    "over_no": "ZERO-based over number",
    "legal_ball_in_over": "legal-ball count within the over",
    "innings_delivery_seq": "delivery order within the innings",
    "is_legal": "not a wide or no-ball",
    "batter_id": "striker player_id",
    "non_striker_id": "non-striker player_id",
    "bowler_id": "bowler player_id",
    "runs_batter": "runs off the bat",
    "runs_total": "all runs on the delivery incl. extras",
    "non_boundary": "TRUE when 4/6 runs were run, not a boundary",
    "wides": "wide runs (NULL if not a wide)",
    "noballs": "no-ball runs (NULL if not a no-ball)",
    "player_out_id": "dismissed player's id (may be the non-striker)",
    "is_bowler_wicket": "wicket credited to the bowler",
    "target_runs": "chase target on 2nd-innings deliveries",
    "format": "Test, ODI, T20I, T20 domestic, The Hundred, List A domestic, First-class domestic, ...",
    "gender": "'male' or 'female'",
    "team_type": "'international' or 'club'",
    "competition": "canonical competition name",
    "year": "calendar year of the match",
    "batter_hand": "RHB/LHB",
    "in_control": "batter in control of the shot (partial coverage)",
    "wagon_zone": "1-8 scoring zone (mainly men's ODIs)",
}


def _rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    return conn.execute(sql).fetchall()


def build_knowledge_pack(multiformat_db: Path, odi_db: Path | None = None) -> str:
    hidden = set(HIDDEN_COLUMNS)
    lines = [INSTRUCTIONS, f"Knowledge pack version {PACK_VERSION}.", "", "Tables (schema analytics):"]
    with duckdb.connect(str(multiformat_db), read_only=True) as conn:
        tables = [
            "deliveries", "matches", "players", "player_names", "coverage", "coverage_summary",
            "coverage_by_year", "data_limitations",
        ]
        for table in tables:
            columns = [
                (name, kind) for name, kind, *_ in _rows(conn, f"DESCRIBE analytics.{table}")
                if name not in hidden
            ]
            described = ", ".join(
                f"{name} {kind}" + (f" ({COLUMN_NOTES[name]})" if table == "deliveries" and name in COLUMN_NOTES else "")
                for name, kind in columns
            )
            lines.append(f"- analytics.{table}: {described}")
        lines += ["", "Formats in the database (format, gender, matches, first, last):"]
        for row in _rows(conn, "SELECT format, gender, matches, ball_by_ball_from, ball_by_ball_to FROM analytics.coverage_summary ORDER BY gender DESC, matches DESC"):
            lines.append(f"- {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}")
        lines += ["", "Competitions with at least 20 matches (competition | format | gender | matches | years):"]
        for row in _rows(conn, """
            SELECT competition, format, gender, matches, year(first_match), year(last_match)
            FROM analytics.coverage WHERE matches >= 20 ORDER BY format, gender, matches DESC"""):
            lines.append(f"- {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}-{row[5]}")
        lines += ["", "Stored data limitations (cite by querying analytics.data_limitations):"]
        for statement, in _rows(conn, "SELECT statement FROM analytics.data_limitations"):
            lines.append("- " + statement)
    if odi_db is not None and Path(odi_db).exists():
        lines += [
            "",
            "Second database, attached as odi (men's ODIs Jan 2005 - Feb 2025 only, every column VARCHAR - cast with TRY_CAST):",
            "- odi.analytics.deliveries_v1: p_match (match id), inns, bat/p_bat (batter name/id), team_bat, "
            "bowl/p_bowl, team_bowl, over (1-based), ball_id, score (runs on the ball), out ('True'/'False'), "
            "dismissal, p_out, noball, wide, byes, legbyes, batruns, ballfaced, bowlruns, inns_runs, inns_wkts, "
            "inns_balls, target, date, year, ground, country, winner, toss, competition, bat_hand, bowl_style, "
            "bowl_kind, wagonX, wagonY, wagonZone, line, length, shot, control ('1' in control, '0' not), "
            "predscore, wprob (pre-ball win probability, -1 unknown), daynight ('day match', "
            "'day/night match', 'night match'), rain, inns_runs_rem/inns_balls_rem (state AFTER the ball).",
            "Use analytics.deliveries for ODI statistics; use odi only for what the main database does not "
            "record: control, wagon wheel, win probability, day/night and rain. Day/night and rain are "
            "recorded ONLY here, i.e. for men's ODIs Jan 2005 - Feb 2025; no other format, women's cricket "
            "or later match records them - say so when you use them.",
        ]
    return "\n".join(lines)
