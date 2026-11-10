"""Write data/cricket_all.duckdb from the work database."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from ingestion.app.multiformat import orphan_alignment
from ingestion.app.multiformat.publish_sql import BACKBONE_SQL, FINAL_SQL, PLAYERS_SQL

COVERAGE_SQL = """
-- A delivery "has line/length" when either canonical field is present.
CREATE OR REPLACE TABLE out.analytics.coverage AS
SELECT format, gender, competition,
       count(DISTINCT match_id) AS matches,
       min(match_date) AS first_match, max(match_date) AS last_match,
       count(*) AS deliveries,
       count(*) FILTER (length IS NOT NULL OR line IS NOT NULL) AS ll_deliveries,
       round(100.0 * count(*) FILTER (length IS NOT NULL OR line IS NOT NULL) / count(*), 1) AS ll_pct,
       min(match_date) FILTER (length IS NOT NULL OR line IS NOT NULL) AS ll_first_match,
       max(match_date) FILTER (length IS NOT NULL OR line IS NOT NULL) AS ll_last_match,
       count(*) FILTER (line IS NOT NULL) AS line_deliveries,
       count(*) FILTER (shot IS NOT NULL) AS shot_deliveries,
       list(DISTINCT score_source ORDER BY score_source) AS score_sources
FROM out.analytics.deliveries
GROUP BY ALL;

CREATE OR REPLACE TABLE out.analytics.coverage_by_year AS
SELECT format, gender, year,
       count(DISTINCT match_id) AS matches,
       count(*) AS deliveries,
       round(100.0 * count(*) FILTER (length IS NOT NULL) / count(*), 1) AS length_pct,
       round(100.0 * count(*) FILTER (line IS NOT NULL) / count(*), 1) AS line_pct,
       round(100.0 * count(*) FILTER (shot IS NOT NULL) / count(*), 1) AS shot_pct,
       round(100.0 * count(*) FILTER (ll_source = 'espn') / count(*), 1) AS ll_from_espn_pct,
       round(100.0 * count(*) FILTER (ll_source IN ('aucb', 'odata')) / count(*), 1) AS ll_from_aucb_pct
FROM out.analytics.deliveries
GROUP BY ALL;

-- "Regular" coverage of a field starts in the first year where at least 25%
-- of that format's deliveries carry it; isolated earlier balls are ignored.
CREATE OR REPLACE TABLE out.analytics.coverage_summary AS
WITH regular AS (
  SELECT format, gender,
         min(year) FILTER (length_pct >= 25) AS length_regular_from_year,
         max(year) FILTER (length_pct >= 25) AS length_regular_to_year,
         min(year) FILTER (line_pct >= 25) AS line_regular_from_year,
         max(year) FILTER (line_pct >= 25) AS line_regular_to_year
  FROM out.analytics.coverage_by_year GROUP BY ALL
),
base AS (
  SELECT format, gender,
         count(DISTINCT match_id) AS matches,
         min(match_date) AS ball_by_ball_from, max(match_date) AS ball_by_ball_to,
         count(*) AS deliveries,
         min(match_date) FILTER (length IS NOT NULL) AS length_from,
         max(match_date) FILTER (length IS NOT NULL) AS length_to,
         min(match_date) FILTER (line IS NOT NULL) AS line_from,
         max(match_date) FILTER (line IS NOT NULL) AS line_to,
         count(DISTINCT match_id) FILTER (length IS NOT NULL OR line IS NOT NULL) AS matches_with_line_length,
         round(100.0 * count(*) FILTER (length IS NOT NULL OR line IS NOT NULL) / count(*), 1) AS line_length_pct_all_years
  FROM out.analytics.deliveries GROUP BY ALL
)
SELECT b.*, r.length_regular_from_year, r.length_regular_to_year, r.line_regular_from_year, r.line_regular_to_year,
       (SELECT round(100.0 * count(*) FILTER (d.length IS NOT NULL) / count(*), 1) FROM out.analytics.deliveries d
         WHERE d.format = b.format AND d.gender = b.gender
           AND d.year BETWEEN r.length_regular_from_year AND r.length_regular_to_year) AS length_pct_in_period,
       (SELECT round(100.0 * count(*) FILTER (d.line IS NOT NULL) / count(*), 1) FROM out.analytics.deliveries d
         WHERE d.format = b.format AND d.gender = b.gender
           AND d.year BETWEEN r.line_regular_from_year AND r.line_regular_to_year) AS line_pct_in_period
FROM base b LEFT JOIN regular r USING (format, gender);

-- Every way a player is named (Cricsheet register name, unique name, and the
-- alternative names in names.csv such as "Virat Kohli" for "V Kohli"), so
-- questions can use the names people actually type.
CREATE OR REPLACE TABLE out.analytics.player_names AS
SELECT DISTINCT lower(name) AS name_key, name, player_id FROM (
  SELECT name, player_id FROM out.analytics.players
  UNION ALL SELECT unique_name, player_id FROM out.analytics.players
  UNION ALL SELECT name, identifier FROM read_csv('{names}', all_varchar = true, header = true)
) WHERE name IS NOT NULL;

CREATE OR REPLACE TABLE out.analytics.build_info AS
SELECT current_timestamp::TIMESTAMP AS built_at,
       (SELECT max(start_date) FROM cs.matches) AS cricsheet_latest_match,
       (SELECT max(match_date) FROM enrich.balls WHERE src = 'aucb') AS aucb_latest_match,
       (SELECT max(match_date) FROM enrich.balls WHERE src = 'espn') AS espn_latest_match,
       (SELECT count(*) FROM out.analytics.matches) AS matches,
       (SELECT count(*) FROM out.analytics.deliveries) AS deliveries;
"""

VIEWS = {
    "deliveries_test_men": "format = 'Test' AND gender = 'male'",
    "deliveries_odi_men": "format = 'ODI' AND gender = 'male'",
    "deliveries_t20i_men": "format = 'T20I' AND gender = 'male'",
    "deliveries_ipl": "competition = 'Indian Premier League'",
    "deliveries_t20_leagues_men": "format IN ('T20 domestic', 'The Hundred') AND gender = 'male'",
    "deliveries_test_women": "format = 'Test' AND gender = 'female'",
    "deliveries_odi_women": "format = 'ODI' AND gender = 'female'",
    "deliveries_t20i_women": "format = 'T20I' AND gender = 'female'",
    "deliveries_with_line_length": "length IS NOT NULL OR line IS NOT NULL",
}


def run(conn: duckdb.DuckDBPyConnection, output: Path, sources: Path) -> None:
    staging = output.with_suffix(".staging.duckdb")
    for path in (staging, Path(str(staging) + ".wal")):
        if path.exists():
            path.unlink()
    # Row order of the published tables does not matter; keeping insertion order
    # forces the 12M-row delivery join to materialize and spill to disk.
    conn.execute("SET preserve_insertion_order = false")
    conn.execute("SET memory_limit = '8GB'")
    conn.execute(f"ATTACH '{staging}' AS out")
    conn.execute("CREATE SCHEMA IF NOT EXISTS out.analytics")
    conn.execute(f"ATTACH IF NOT EXISTS '{output.parent / 'odi_analytics.duckdb'}' AS espn_db (READ_ONLY)")
    try:
        conn.execute(PLAYERS_SQL.format(people=sources / "cricsheet" / "people.csv"))
        orphan_alignment.run(conn)
        conn.execute(BACKBONE_SQL.format(names=sources / "cricsheet" / "names.csv"))
        conn.execute(FINAL_SQL)
        conn.execute(COVERAGE_SQL.format(names=sources / "cricsheet" / "names.csv"))
        conn.execute(
            "CREATE OR REPLACE TABLE out.analytics.source_fixture_map AS "
            "SELECT * FROM enrich.fixture_match"
        )
    finally:
        conn.execute("DETACH out")
    # Views are created on a direct connection so they reference the file's
    # own catalog rather than the build-time alias.
    published = duckdb.connect(str(staging))
    try:
        for name, where in VIEWS.items():
            published.execute(f"CREATE OR REPLACE VIEW analytics.{name} AS SELECT * FROM analytics.deliveries WHERE {where}")
    finally:
        published.close()
    os.replace(staging, output)
