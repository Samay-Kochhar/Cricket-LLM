"""Independent read-only reference checks for the eight priority ODI questions.

The SQL here is written separately from the application query builders so a
release can compare CricAtlas answers against the frozen database without any
model call. Run:

    PYTHONPATH=. python -m scripts.verify_release_references --output <file.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

DEFAULT_DATABASE = Path("data/odi_analytics.duckdb")
LEGAL = "wide = '0' AND noball = '0'"

# Each check: SQL, then the frozen expectation from issue 47.
CHECKS: dict[str, tuple[str, object]] = {
    "kohli_sixes": (
        "SELECT COUNT(*) FROM analytics.deliveries_v1 "
        "WHERE bat = 'Virat Kohli' AND batruns = '6'",
        [[154]],
    ),
    "world_cup_2019_final_toss": (
        "WITH wc AS (SELECT * FROM analytics.deliveries_v1 "
        "WHERE competition = 'ICC Cricket World Cup' AND year = '2019'), "
        "final AS (SELECT DISTINCT p_match FROM wc WHERE date = (SELECT MAX(date) FROM wc)) "
        "SELECT DISTINCT toss, winner FROM wc WHERE p_match IN (SELECT p_match FROM final)",
        [["New Zealand", "-"]],
    ),
    "kohli_caught_bowled": (
        "SELECT dismissal, COUNT(*) FROM analytics.deliveries_v1 "
        "WHERE out = 'True' AND dismissal IN ('caught', 'bowled') "
        "AND p_out IN (SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat = 'Virat Kohli') "
        "GROUP BY dismissal ORDER BY dismissal",
        [["bowled", 34], ["caught", 170]],
    ),
    "rohit_required_rate_above_8": (
        "SELECT SUM(CAST(batruns AS INTEGER)), SUM(CAST(ballfaced AS INTEGER)), "
        "ROUND(100.0 * SUM(CAST(batruns AS INTEGER)) / SUM(CAST(ballfaced AS INTEGER)), 2) "
        "FROM analytics.deliveries_v1 "
        "WHERE bat = 'Rohit Sharma' AND TRY_CAST(inns_rrr AS DOUBLE) > 8",
        [[354, 298, 118.79]],
    ),
    "successful_chase_top_run_scorer": (
        "SELECT bat, SUM(CAST(batruns AS INTEGER)) AS runs FROM analytics.deliveries_v1 "
        "WHERE inns = '2' AND winner = team_bat GROUP BY bat ORDER BY runs DESC LIMIT 1",
        [["Virat Kohli", 5791]],
    ),
    "bumrah_economy_by_lighting": (
        "SELECT daynight, SUM(CAST(bowlruns AS INTEGER)), "
        f"SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END), "
        f"ROUND(6.0 * SUM(CAST(bowlruns AS INTEGER)) / SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END), 2) "
        "FROM analytics.deliveries_v1 WHERE bowl = 'Jasprit Bumrah' GROUP BY daynight ORDER BY daynight",
        [["day match", 1055, 1487, 4.26], ["day/night match", 2454, 3093, 4.76]],
    ),
    "lowest_team_economy_against_india": (
        "SELECT team_bowl, SUM(CAST(bowlruns AS INTEGER)) AS runs, "
        f"SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) AS legal, "
        f"ROUND(6.0 * SUM(CAST(bowlruns AS INTEGER)) / SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END), 2) AS economy "
        "FROM analytics.deliveries_v1 WHERE team_bat = 'India' GROUP BY team_bowl "
        "HAVING legal >= 600 ORDER BY economy, team_bowl LIMIT 1",
        [["Zimbabwe", 4099, 4743, 5.19]],
    ),
    # Stored `over` is the 1-based over number (over 1 holds innings balls 1-6),
    # so human overs 41-50 are stored overs 41..50 inclusive. The 2026-09-27
    # audit's 1,035 / 1,103 / 5.63 came from the off-by-one stored overs 40..49.
    "bumrah_overs_41_to_50_economy": (
        "SELECT SUM(CAST(bowlruns AS INTEGER)), "
        f"SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END), "
        f"ROUND(6.0 * SUM(CAST(bowlruns AS INTEGER)) / SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END), 2) "
        "FROM analytics.deliveries_v1 WHERE bowl = 'Jasprit Bumrah' "
        "AND CAST(over AS INTEGER) BETWEEN 41 AND 50",
        [[1081, 1123, 5.78]],
    ),
    "stored_over_is_one_based": (
        "SELECT COUNT(*), SUM(CASE WHEN CAST(over AS INTEGER) = "
        "CAST(CEIL(CAST(inns_balls AS INTEGER) / 6.0) AS INTEGER) THEN 1 ELSE 0 END) "
        f"FROM analytics.deliveries_v1 WHERE {LEGAL} AND CAST(inns_balls AS INTEGER) > 0",
        None,
    ),
}


def _normalize(rows: list[tuple[object, ...]]) -> list[list[object]]:
    return [[float(value) if hasattr(value, "as_tuple") else value for value in row] for row in rows]


def _one_based_over(actual: list[list[object]]) -> bool:
    """Legal ball n of an innings lies in stored over ceil(n / 6) for >= 99.9% of rows."""
    legal_balls, one_based = actual[0]
    return one_based / legal_balls >= 0.999


def run(database: Path) -> dict[str, object]:
    connection = duckdb.connect(str(database), read_only=True)
    results: dict[str, object] = {}
    for name, (sql, expected) in CHECKS.items():
        actual = _normalize(connection.execute(sql).fetchall())
        passed = actual == expected if expected is not None else _one_based_over(actual)
        results[name] = {"sql": sql, "expected": expected, "actual": actual, "passed": passed}
    connection.close()
    return {
        "database": str(database),
        "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        "passed": sum(1 for item in results.values() if item["passed"]),
        "total": len(results),
        "checks": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.database)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    for name, item in report["checks"].items():
        print(f"{'PASS' if item['passed'] else 'FAIL'} {name}: {item['actual']}")
    print(f"{report['passed']}/{report['total']} reference checks passed; database sha256 {report['database_sha256']}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
