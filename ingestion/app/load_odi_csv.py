from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import duckdb


EXPECTED_COLUMNS = [
    "p_match",
    "inns",
    "bat",
    "p_bat",
    "team_bat",
    "bowl",
    "p_bowl",
    "team_bowl",
    "ball",
    "ball_id",
    "outcome",
    "score",
    "out",
    "dismissal",
    "p_out",
    "over",
    "noball",
    "wide",
    "byes",
    "legbyes",
    "cur_bat_runs",
    "cur_bat_bf",
    "cur_bowl_ovr",
    "cur_bowl_wkts",
    "cur_bowl_runs",
    "inns_runs",
    "inns_wkts",
    "inns_balls",
    "inns_runs_rem",
    "inns_balls_rem",
    "inns_rr",
    "inns_rrr",
    "target",
    "max_balls",
    "date",
    "year",
    "ground",
    "country",
    "winner",
    "toss",
    "competition",
    "bat_hand",
    "bowl_style",
    "bowl_kind",
    "batruns",
    "ballfaced",
    "bowlruns",
    "bat_out",
    "rain",
    "daynight",
    "gmt_offset",
    "wagonX",
    "wagonY",
    "wagonZone",
    "line",
    "length",
    "shot",
    "control",
    "predscore",
    "wprob",
]


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def execute_sql_files(conn: duckdb.DuckDBPyConnection, paths: Iterable[Path]) -> None:
    for path in paths:
        conn.execute(read_sql(path))


def build_select_list(raw_columns: list[str]) -> str:
    actual = set(raw_columns)
    first_column = raw_columns[0] if raw_columns else ""
    dropped = {first_column} if first_column not in EXPECTED_COLUMNS else set()

    missing = [column for column in EXPECTED_COLUMNS if column not in actual]
    if missing:
        raise ValueError(f"CSV is missing expected columns: {missing}")

    select_lines = []
    for column in EXPECTED_COLUMNS:
        source = quote_ident(column)
        target = column
        select_lines.append(f"  {source} AS {target}")

    if dropped:
        dropped_list = ", ".join(sorted(dropped))
        print(f"Dropping non-domain columns: {dropped_list}")

    return ",\n".join(select_lines)


def create_normalized_table(conn: duckdb.DuckDBPyConnection) -> None:
    raw_columns = [row[1] for row in conn.execute("PRAGMA table_info('raw.odi_bbb_raw')").fetchall()]
    select_list = build_select_list(raw_columns)
    conn.execute("DROP TABLE IF EXISTS analytics.deliveries_v1")
    conn.execute(
        f"""
        CREATE TABLE analytics.deliveries_v1 AS
        SELECT
{select_list}
        FROM raw.odi_bbb_raw
        """
    )


def run(csv_path: Path, db_path: Path, base_sql: Path, derived_sql: Path) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    ensure_parent(db_path)
    conn = duckdb.connect(str(db_path))

    try:
        execute_sql_files(conn, [base_sql])
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE raw.odi_bbb_raw AS
            SELECT *
            FROM read_csv_auto(
                {sql_literal(str(csv_path))},
                header = true,
                delim = ',',
                quote = '"',
                escape = '"',
                sample_size = -1,
                strict_mode = false,
                null_padding = true,
                all_varchar = true
            )
            """
        )
        create_normalized_table(conn)
        execute_sql_files(conn, [derived_sql])
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    return argparse.ArgumentParser(description="Load the ODI CSV into a local DuckDB database").parse_args(
        []
    )


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Load the ODI CSV into a local DuckDB database")
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=root / "data" / "odi_bbb-25.csv",
        help="Path to the ODI CSV source file",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=root / "data" / "odi_analytics.duckdb",
        help="Path to the generated DuckDB file",
    )
    parser.add_argument(
        "--base-sql",
        type=Path,
        default=root / "ingestion" / "sql" / "base_schema.sql",
        help="SQL file with base schema setup statements",
    )
    parser.add_argument(
        "--derived-sql",
        type=Path,
        default=root / "ingestion" / "sql" / "derived_views.sql",
        help="SQL file with derived views and materializations",
    )
    args = parser.parse_args()
    run(args.csv_path, args.db_path, args.base_sql, args.derived_sql)
    print(f"Generated analytics database at {args.db_path}")


if __name__ == "__main__":
    main()
