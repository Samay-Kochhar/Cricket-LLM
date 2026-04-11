from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(slots=True)
class CoverageStat:
    field_name: str
    non_null_rows: int
    total_rows: int

    @property
    def non_null_ratio(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return self.non_null_rows / self.total_rows


@dataclass(slots=True)
class DatasetProfile:
    total_rows: int
    min_year: int | None
    max_year: int | None
    distinct_competitions: int
    distinct_grounds: int
    distinct_batters: int
    distinct_bowlers: int
    coverage: list[CoverageStat]


PROFILE_FIELDS = ["shot", "line", "length", "wagonX", "wagonY", "control", "dismissal"]


def build_profile(conn: duckdb.DuckDBPyConnection) -> DatasetProfile:
    total_rows, min_year, max_year = conn.execute(
        """
        SELECT COUNT(*), MIN(TRY_CAST(year AS INTEGER)), MAX(TRY_CAST(year AS INTEGER))
        FROM analytics.deliveries_v1
        """
    ).fetchone()
    distinct_competitions, distinct_grounds, distinct_batters, distinct_bowlers = conn.execute(
        """
        SELECT
          COUNT(DISTINCT competition),
          COUNT(DISTINCT ground),
          COUNT(DISTINCT bat),
          COUNT(DISTINCT bowl)
        FROM analytics.deliveries_v1
        """
    ).fetchone()

    coverage = []
    for field_name in PROFILE_FIELDS:
        non_null_rows = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM analytics.deliveries_v1
            WHERE NULLIF(TRIM(CAST({field_name} AS VARCHAR)), '') IS NOT NULL
            """
        ).fetchone()[0]
        coverage.append(CoverageStat(field_name=field_name, non_null_rows=non_null_rows, total_rows=total_rows))

    return DatasetProfile(
        total_rows=total_rows,
        min_year=min_year,
        max_year=max_year,
        distinct_competitions=distinct_competitions,
        distinct_grounds=distinct_grounds,
        distinct_batters=distinct_batters,
        distinct_bowlers=distinct_bowlers,
        coverage=coverage,
    )


def render_profile_markdown(profile: DatasetProfile) -> str:
    lines = [
        "# ODI Data Profile",
        "",
        "## Overview",
        f"- Total rows: {profile.total_rows}",
        f"- Year range: {profile.min_year} to {profile.max_year}",
        f"- Distinct competitions: {profile.distinct_competitions}",
        f"- Distinct grounds: {profile.distinct_grounds}",
        f"- Distinct batters: {profile.distinct_batters}",
        f"- Distinct bowlers: {profile.distinct_bowlers}",
        "",
        "## Field Coverage",
        "| Field | Non-null rows | Coverage |",
        "|-------|---------------|----------|",
    ]

    for stat in profile.coverage:
        lines.append(
            f"| `{stat.field_name}` | {stat.non_null_rows} | {stat.non_null_ratio:.2%} |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "- This profile is generated from `analytics.deliveries_v1`.",
            "- Coverage gaps should inform insufficient-evidence handling in the application layer.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Profile the generated ODI analytics database")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=root / "data" / "odi_analytics.duckdb",
        help="Path to the generated DuckDB file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "docs" / "data-profile.md",
        help="Path to the markdown output",
    )
    args = parser.parse_args()

    conn = duckdb.connect(str(args.db_path), read_only=True)
    try:
        profile = build_profile(conn)
    finally:
        conn.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_profile_markdown(profile), encoding="utf-8")
    print(f"Wrote profile to {args.output}")


if __name__ == "__main__":
    main()
