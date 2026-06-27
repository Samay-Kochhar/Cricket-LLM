from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.cricket_analytics.cricket_definitions import (
    BOWLER_WICKET_PREDICATE,
    LEGAL_BALL_PREDICATE,
    phase_case_expression,
    phase_filter_clause,
)
from backend.app.cricket_analytics.metric_registry import metric_sql_expression
from backend.app.cricket_analytics.ontology import METRICS
from backend.app.cricket_analytics.schemas import CricketQueryPlan, QueryBuildResult


LEGAL_BALL = LEGAL_BALL_PREDICATE
BOWLER_WICKET = BOWLER_WICKET_PREDICATE


@dataclass(frozen=True, slots=True)
class DimensionSql:
    expression: str
    alias: str
    not_null_expression: str | None = None


DIMENSION_SQL: dict[str, DimensionSql] = {
    "batter": DimensionSql("bat", "batter", "bat"),
    "bowler": DimensionSql("bowl", "bowler", "bowl"),
    "team": DimensionSql("team_bat", "team", "team_bat"),
    "batting_team": DimensionSql("team_bat", "batting_team", "team_bat"),
    "bowling_team": DimensionSql("team_bowl", "bowling_team", "team_bowl"),
    "line": DimensionSql("line", "line", "line"),
    "length": DimensionSql("length", "length", "length"),
    "shot_type": DimensionSql("shot", "shot_type", "shot"),
    "bowling_style": DimensionSql("bowl_style", "bowling_style", "bowl_style"),
    "batter_hand": DimensionSql("bat_hand", "batter_hand", "bat_hand"),
    "venue": DimensionSql("ground", "venue", "ground"),
    "innings": DimensionSql("inns", "innings", "inns"),
    "phase": DimensionSql(
        phase_case_expression(),
        "phase",
        "over",
    ),
    "bowler_hand": DimensionSql(
        "CASE WHEN LOWER(CAST(bowl_style AS VARCHAR)) LIKE 'l%' THEN 'left' "
        "WHEN NULLIF(TRIM(CAST(bowl_style AS VARCHAR)), '') IS NOT NULL THEN 'right' ELSE NULL END",
        "bowler_hand",
        "bowl_style",
    ),
    "field_zone": DimensionSql(
        "CASE "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 1) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 4) THEN 'midwicket' "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 2) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 3) THEN 'long_on' "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 3) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 2) THEN 'long_off' "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 4) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 1) THEN 'cover' "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 5) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 8) THEN 'point' "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 6) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 7) THEN 'third_man' "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 7) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 6) THEN 'fine_leg' "
        "WHEN (bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = 8) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = 5) THEN 'square_leg' "
        "ELSE NULL END",
        "field_zone",
        "wagonZone",
    ),
    "matchup": DimensionSql("CAST(bat AS VARCHAR) || ' vs ' || CAST(bowl AS VARCHAR)", "matchup", "bat"),
}


NON_MIGRATED_METRIC_SQL = {
    "run_rate": "runs_scored / NULLIF(legal_balls / 6.0, 0)",
    "control_percentage": "controlled_balls / NULLIF(sample_balls, 0) * 100.0",
    "dismissal_rate": "dismissals / NULLIF(sample_balls, 0) * 100.0",
    "wicket_opportunity_rate": "(wickets + false_shots) / NULLIF(legal_balls, 0) * 100.0",
}


def build_aggregate_query(plan: CricketQueryPlan) -> QueryBuildResult:
    dimensions = plan.group_by or ([plan.entity] if plan.entity in DIMENSION_SQL else [])
    dimension_defs = [DIMENSION_SQL[dimension] for dimension in dimensions]
    select_dimensions = [f"{definition.expression} AS {definition.alias}" for definition in dimension_defs]
    group_expressions = [definition.expression for definition in dimension_defs]
    columns = [definition.alias for definition in dimension_defs]

    where_clauses = ["1 = 1"]
    params: list[Any] = []
    for clause, clause_params in _filter_clauses(plan.filters, entity=plan.entity):
        where_clauses.append(clause)
        params.extend(clause_params)
    for definition in dimension_defs:
        if definition.not_null_expression:
            where_clauses.append(f"NULLIF(TRIM(CAST({definition.not_null_expression} AS VARCHAR)), '') IS NOT NULL")

    metric_expression = NON_MIGRATED_METRIC_SQL.get(plan.metric) or metric_sql_expression(
        plan.metric,
        entity=plan.entity,
        filters=plan.filters,
    )
    sort = plan.sort
    direction = sort.direction.upper() if sort else METRICS[plan.metric].default_sort.upper()
    sort_expression = plan.metric if not sort or sort.by == plan.metric else sort.by
    limit = plan.limit or 10

    having_clauses = []
    if plan.minimum_sample:
        if plan.minimum_sample.balls:
            having_clauses.append("sample_balls >= ?")
            params.append(plan.minimum_sample.balls)
        if plan.minimum_sample.legal_balls:
            having_clauses.append("legal_balls >= ?")
            params.append(plan.minimum_sample.legal_balls)
        if plan.minimum_sample.innings:
            having_clauses.append("innings >= ?")
            params.append(plan.minimum_sample.innings)

    select_prefix = ",\n                ".join(select_dimensions) + "," if select_dimensions else ""
    group_by_sql = "GROUP BY " + ", ".join(group_expressions) if group_expressions else ""
    having_sql = "WHERE " + " AND ".join(having_clauses) if having_clauses else ""
    order_sql = f"ORDER BY {sort_expression} {direction}, sample_balls DESC"

    sql = f"""
            WITH aggregate_rows AS (
              SELECT
                {select_prefix}
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bat AS VARCHAR)) AS innings,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) AS balls_faced,
                SUM(CASE WHEN {LEGAL_BALL} THEN 1 ELSE 0 END) AS legal_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) AS sample_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END) AS runs_scored,
                SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
                SUM(CASE WHEN {BOWLER_WICKET} THEN 1 ELSE 0 END) AS wickets,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN {LEGAL_BALL} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS bowler_dot_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(control AS DOUBLE) = 1 THEN 1 ELSE 0 END) AS controlled_balls,
                SUM(CASE WHEN {LEGAL_BALL} AND length = 'YORKER' THEN 1 ELSE 0 END) AS yorker_balls
              FROM analytics.deliveries_v1
              WHERE {' AND '.join(where_clauses)}
              {group_by_sql}
            )
            SELECT
              {', '.join(columns) + ',' if columns else ''}
              matches,
              innings,
              balls_faced,
              legal_balls,
              sample_balls AS balls,
              runs_scored,
              runs_conceded,
              wickets,
              dismissals,
              dot_balls,
              bowler_dot_balls,
              boundary_balls,
              false_shots,
              yorker_balls,
              {metric_expression} AS {plan.metric}
            FROM aggregate_rows
            {having_sql}
            {order_sql}
            LIMIT ?
            """
    params.append(limit)
    output_columns = [
        *columns,
        "matches",
        "innings",
        "balls_faced",
        "legal_balls",
        "balls",
        "runs_scored",
        "runs_conceded",
        "wickets",
        "dismissals",
        "dot_balls",
        "bowler_dot_balls",
        "boundary_balls",
        "false_shots",
        "yorker_balls",
        plan.metric,
    ]
    sample_columns = ["balls", "legal_balls", "innings"]
    return QueryBuildResult(
        sql=_clean_sql(sql),
        params=params,
        columns=output_columns,
        metric_column=plan.metric,
        sample_columns=sample_columns,
        description="Generic aggregate operation over analytics.deliveries_v1",
    )


def _filter_clauses(filters: dict[str, object], entity: str | None = None) -> list[tuple[str, list[Any]]]:
    clauses: list[tuple[str, list[Any]]] = []
    for key, value in filters.items():
        if value is None:
            continue
        if key == "batter":
            clauses.append(("bat = ?", [value]))
        elif key == "bowler":
            clauses.append(("bowl = ?", [value]))
        elif key == "team":
            clauses.append(("(team_bat = ? OR team_bowl = ?)", [value, value]))
        elif key == "batting_team":
            clauses.append(("team_bat = ?", [value]))
        elif key == "bowling_team":
            clauses.append(("team_bowl = ?", [value]))
        elif key == "phase":
            clause, params = phase_filter_clause(str(value))
            if clause:
                clauses.append((clause, params))
        elif key == "over_range" and isinstance(value, list) and value:
            start = int(value[0])
            end = int(value[-1])
            clauses.append(("TRY_CAST(over AS DOUBLE) >= ? AND TRY_CAST(over AS DOUBLE) < ?", [float(start - 1), float(end)]))
        elif key == "line":
            clauses.append(("line = ?", [value]))
        elif key == "length":
            clauses.append(("length = ?", [value]))
        elif key == "shot_type":
            clauses.append(("shot = ?", [value]))
        elif key == "bowling_style":
            clauses.append(_bowling_style_clause(str(value)))
        elif key == "batter_hand":
            clauses.append(("bat_hand = ?", [value]))
        elif key == "venue":
            clauses.append(("ground = ?", [value]))
        elif key == "opposition":
            if entity == "bowler" or ("bowler" in filters and "batter" not in filters):
                clauses.append(("team_bat = ?", [value]))
            else:
                clauses.append(("team_bowl = ?", [value]))
        elif key == "innings":
            clauses.append(("inns = ?", [value]))
        elif key == "field_zone":
            clauses.append((_field_zone_clause(str(value)), []))
        elif key == "years" and isinstance(value, list) and value:
            year_mode = filters.get("year_mode")
            if year_mode == "after":
                clauses.append(("TRY_CAST(year AS INTEGER) >= ?", [min(int(year) for year in value)]))
            elif year_mode == "before":
                clauses.append(("TRY_CAST(year AS INTEGER) <= ?", [max(int(year) for year in value)]))
            else:
                placeholders = ", ".join("?" for _ in value)
                clauses.append((f"TRY_CAST(year AS INTEGER) IN ({placeholders})", list(value)))
        elif key == "competition":
            clauses.append(("competition = ?", [value]))
    return clauses


def _bowling_style_clause(value: str) -> tuple[str, list[Any]]:
    if value == "pace":
        return ("bowl_kind = ?", ["pace bowler"])
    if value == "spin":
        return ("bowl_kind = ?", ["spin bowler"])
    if value == "left_arm_pace":
        return ("bowl_style IN ('LF', 'LFM', 'LMF', 'LM')", [])
    if value == "left_arm_spin":
        return ("bowl_style IN ('SLA', 'LWS')", [])
    if value == "leg_spin" or value == "wrist_spin":
        return ("bowl_style IN ('LBG', 'LB', 'LWS')", [])
    if value == "finger_spin":
        return ("bowl_style IN ('OB', 'SLA', 'SLO', 'RMF')", [])
    if value == "off_spin":
        return ("bowl_style = 'OB'", [])
    return ("bowl_style = ?", [value])


def _field_zone_clause(field_zone: str) -> str:
    zone_pairs = {
        "midwicket": (1, 4),
        "cover": (4, 1),
        "point": (5, 8),
        "third_man": (6, 7),
        "fine_leg": (7, 6),
        "square_leg": (8, 5),
        "long_on": (2, 3),
        "long_off": (3, 2),
    }
    right_zone, left_zone = zone_pairs.get(field_zone, zone_pairs["midwicket"])
    return (
        "((bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = "
        f"{right_zone}) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = {left_zone}))"
    )


def _clean_sql(sql: str) -> str:
    return "\n".join(line.rstrip() for line in sql.strip().splitlines() if line.strip())
