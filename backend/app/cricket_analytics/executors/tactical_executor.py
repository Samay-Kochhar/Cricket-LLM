from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.cricket_analytics.cricket_definitions import BOWLER_WICKET_PREDICATE, LEGAL_BALL_PREDICATE
from backend.app.cricket_analytics.query_builders.aggregate_builder import DIMENSION_SQL, _clean_sql
from backend.app.cricket_analytics.schemas import CricketQueryPlan


@dataclass(frozen=True, slots=True)
class TacticalProbe:
    title: str
    description: str
    sql: str
    params: list[Any]
    columns: list[str]
    rows: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class TacticalWorkup:
    batter: str
    probes: list[TacticalProbe]
    limitations: list[str]


def execute_tactical_recommendation(plan: CricketQueryPlan, repository: Any) -> TacticalWorkup:
    batter = plan.filters.get("batter")
    if not isinstance(batter, str) or not batter:
        raise ValueError(unsupported_reason(plan))

    probes = [
        _dimension_probe(
            repository,
            batter=batter,
            dimension="bowling_style",
            title="Bowling style probe",
            description="Checks how the batter scores and makes mistakes against bowling styles.",
            minimum_balls=12,
            limit=8,
        ),
        _dimension_probe(
            repository,
            batter=batter,
            dimension="length",
            title="Length probe",
            description="Checks scoring, dots, false shots, and dismissals by length.",
            minimum_balls=12,
            limit=8,
        ),
        _dimension_probe(
            repository,
            batter=batter,
            dimension="line",
            title="Line probe",
            description="Checks scoring, dots, false shots, and dismissals by line.",
            minimum_balls=12,
            limit=8,
        ),
        _dimension_probe(
            repository,
            batter=batter,
            dimension="field_zone",
            title="Scoring zone probe",
            description="Checks where the batter scores most and where scoring is limited.",
            minimum_balls=12,
            limit=8,
        ),
    ]
    limitations = [
        "This starter workup checks bowling style, length, line, and scoring-zone evidence only.",
        "It does not model match conditions, field settings, player availability, or live form.",
    ]
    if any(not probe.rows for probe in probes):
        limitations.append("One or more probes had no rows after the minimum sample filter.")
    return TacticalWorkup(batter=batter, probes=probes, limitations=limitations)


def unsupported_reason(plan: CricketQueryPlan) -> str:
    return (
        "Tactical recommendation requires a named batter and is currently limited to starter "
        "bowling-plan evidence probes."
    )


def _dimension_probe(
    repository: Any,
    *,
    batter: str,
    dimension: str,
    title: str,
    description: str,
    minimum_balls: int,
    limit: int,
) -> TacticalProbe:
    definition = DIMENSION_SQL[dimension]
    sql = _clean_sql(
        f"""
        WITH probe AS (
          SELECT
            {definition.expression} AS bucket,
            COUNT(*) AS balls,
            SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
            SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
            SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
            SUM(CASE WHEN TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots,
            SUM(CASE WHEN {BOWLER_WICKET_PREDICATE} THEN 1 ELSE 0 END) AS dismissals,
            SUM(CASE WHEN {LEGAL_BALL_PREDICATE} THEN 1 ELSE 0 END) AS legal_balls
          FROM analytics.deliveries_v1
          WHERE bat = ?
            AND TRY_CAST(ballfaced AS INTEGER) = 1
            AND NULLIF(TRIM(CAST({definition.not_null_expression or definition.expression} AS VARCHAR)), '') IS NOT NULL
          GROUP BY {definition.expression}
        )
        SELECT
          bucket,
          balls,
          runs,
          dot_balls,
          boundary_balls,
          false_shots,
          dismissals,
          runs / NULLIF(balls, 0) * 100.0 AS strike_rate,
          dot_balls / NULLIF(balls, 0) * 100.0 AS dot_percentage,
          false_shots / NULLIF(balls, 0) * 100.0 AS false_shot_percentage,
          boundary_balls / NULLIF(balls, 0) * 100.0 AS boundary_percentage
        FROM probe
        WHERE balls >= ?
        ORDER BY dot_percentage DESC, false_shot_percentage DESC, strike_rate ASC, balls DESC
        LIMIT ?
        """
    )
    columns = [
        "bucket",
        "balls",
        "runs",
        "dot_balls",
        "boundary_balls",
        "false_shots",
        "dismissals",
        "strike_rate",
        "dot_percentage",
        "false_shot_percentage",
        "boundary_percentage",
    ]
    rows = repository._fetchall(sql, [batter, minimum_balls, limit])
    dict_rows = [dict(zip(columns, row)) for row in rows]
    return TacticalProbe(
        title=title,
        description=description,
        sql=sql,
        params=[batter, minimum_balls, limit],
        columns=columns,
        rows=dict_rows,
    )
