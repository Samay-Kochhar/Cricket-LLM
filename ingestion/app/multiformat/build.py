"""Build the multi-format CricAtlas database.

Usage (from the repo root):
    python -m ingestion.app.multiformat.build                 # every step
    python -m ingestion.app.multiformat.build --steps align   # one step

Steps run in order and each one reads what the previous step left in the work
database (data/build/work.duckdb):

  cricsheet  parse data/sources/cricsheet/all_json.zip into Parquet
  raw        convert the AUCB CSV exports to Parquet
  enrich     normalize both AUCB exports into enrich.balls
  map        candidate Cricsheet matches per AUCB fixture
  align      ball-level alignment, choose and accept a match per fixture
  publish    write data/cricket_all.duckdb (see publish_sql.py)
  validate   run the validation battery and write the coverage/validation docs
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / "data" / "sources"
BUILD = ROOT / "data" / "build"
WORK_DB = BUILD / "work.duckdb"
OUTPUT_DB = ROOT / "data" / "cricket_all.duckdb"
ESPN_DB = ROOT / "data" / "odi_analytics.duckdb"

STEPS = ["cricsheet", "raw", "enrich", "map", "align", "publish", "validate"]


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def step_cricsheet() -> None:
    from ingestion.app.multiformat.cricsheet import convert_archive

    counts = convert_archive(SOURCES / "cricsheet" / "all_json.zip", BUILD)
    _log(f"cricsheet parsed: {counts}")


def step_raw() -> None:
    conn = duckdb.connect()
    for name in ["aucb_bbb", "odata_full"]:
        source = SOURCES / f"{name}.csv"
        target = BUILD / f"raw_{name}.parquet"
        conn.execute(
            f"COPY (SELECT * FROM read_csv('{source}', sample_size=-1, all_varchar=true)) "
            f"TO '{target}' (FORMAT parquet, COMPRESSION zstd)"
        )
        rows = conn.execute(f"SELECT count(*) FROM '{target}'").fetchone()[0]
        _log(f"{name}: {rows:,} rows")


def _work() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(WORK_DB))
    for schema in ["cs", "enrich"]:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    return conn


def step_enrich(conn: duckdb.DuckDBPyConnection) -> None:
    from ingestion.app.multiformat.enrichment_sql import ENRICHMENT_SQL

    for table in ["matches", "players", "deliveries"]:
        conn.execute(f"CREATE OR REPLACE TABLE cs.{table} AS SELECT * FROM '{BUILD / f'cs_{table}.parquet'}'")
    conn.execute(
        ENRICHMENT_SQL.format(
            aucb=BUILD / "raw_aucb_bbb.parquet",
            odata=BUILD / "raw_odata_full.parquet",
            espn=ESPN_DB,
        )
    )
    _log(f"enrich.balls: {conn.execute('SELECT count(*) FROM enrich.balls').fetchone()[0]:,} rows")
    from ingestion.app.multiformat import commentary_fill

    _log(f"rows filled from commentary: {commentary_fill.run(conn):,}")


def step_map(conn: duckdb.DuckDBPyConnection) -> None:
    from ingestion.app.multiformat.match_mapping_sql import MATCH_MAPPING_SQL

    conn.execute(MATCH_MAPPING_SQL)
    conn.execute("CREATE OR REPLACE TABLE enrich.map_candidates AS SELECT * FROM map_candidates")
    _log(f"candidates: {conn.execute('SELECT count(*) FROM enrich.map_candidates').fetchone()[0]:,}")


def step_align(conn: duckdb.DuckDBPyConnection) -> None:
    from ingestion.app.multiformat import alignment_step

    _log(f"alignment: {alignment_step.run(conn, SOURCES / 'cricsheet' / 'names.csv')}")


def step_publish(conn: duckdb.DuckDBPyConnection) -> None:
    from ingestion.app.multiformat import publish

    publish.run(conn, OUTPUT_DB, SOURCES)
    _log(f"published {OUTPUT_DB}")


def step_validate() -> int:
    """Runs on its own connection after the work database is closed."""
    from ingestion.app.multiformat import validate

    failures = validate.run(OUTPUT_DB, ROOT / "docs")
    _log(f"validation finished with {failures} failing check(s)")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", nargs="+", choices=STEPS, default=STEPS)
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    selected = [s for s in STEPS if s in args.steps]
    if "cricsheet" in selected:
        step_cricsheet()
    if "raw" in selected:
        step_raw()
    conn = _work()
    try:
        for name in selected:
            if name in {"cricsheet", "raw", "validate"}:
                continue
            _log(f"step {name}")
            globals()[f"step_{name}"](conn)
    finally:
        conn.close()
    if "validate" in selected and step_validate():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
