from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.cricket_analytics.query_builders.aggregate_builder import (
    BOWLER_WICKET,
    LEGAL_BALL,
    _clean_sql,
    _filter_clauses,
)
from backend.app.cricket_analytics.metric_registry import (
    matchup_projection_sql,
    matchup_sort_expression,
    one_sided_matchup_score_expression,
)
from backend.app.cricket_analytics.schemas import CricketQueryPlan, QueryBuildResult


SUPPORTED_METRICS = {
    "runs_scored",
    "balls_faced",
    "dismissals",
    "batting_strike_rate",
    "dot_ball_percentage",
    "batter_dot_ball_percentage",
    "bowler_dot_ball_percentage",
    "boundary_percentage",
    "false_shot_percentage",
    "dismissal_rate",
    "wickets",
    "wickets_taken",
}


@dataclass(frozen=True, slots=True)
class MatchupDimension:
    alias: str
    expression: str
    group: bool = True


@dataclass(frozen=True, slots=True)
class MatchupBuild:
    query: QueryBuildResult
    dimension_columns: list[str]
    soft_minimum_sample: int
    ranking_note: str | None = None


def build_matchup_query(plan: CricketQueryPlan) -> MatchupBuild:
    if plan.metric not in SUPPORTED_METRICS:
        raise ValueError(unsupported_reason(plan))

    dimensions = _dimensions_for_plan(plan)
    select_dimensions = [f"{dimension.expression} AS {dimension.alias}" for dimension in dimensions]
    group_expressions = [dimension.expression for dimension in dimensions if dimension.group]
    dimension_columns = [dimension.alias for dimension in dimensions]

    where_clauses = ["1 = 1"]
    params: list[Any] = []
    for clause, clause_params in _filter_clauses(plan.filters, entity=plan.entity):
        where_clauses.append(clause)
        params.extend(clause_params)
    for dimension in dimensions:
        if dimension.group:
            where_clauses.append(f"NULLIF(TRIM(CAST({dimension.expression} AS VARCHAR)), '') IS NOT NULL")

    soft_minimum = _soft_minimum_sample(plan)
    limit = plan.limit or 10
    sort_expression, sort_direction, ranking_note = _sort_expression(plan)
    group_by_sql = "GROUP BY " + ", ".join(group_expressions) if group_expressions else ""
    select_dimension_sql = ",\n                ".join(select_dimensions) + "," if select_dimensions else ""
    metric_projection_sql = ",\n              ".join(matchup_projection_sql())

    sql = f"""
            WITH aggregate_rows AS (
              SELECT
                {select_dimension_sql}
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bat AS VARCHAR)) AS innings,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) AS balls,
                SUM(CASE WHEN {LEGAL_BALL} THEN 1 ELSE 0 END) AS legal_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END) AS runs,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
                SUM(CASE WHEN {BOWLER_WICKET} THEN 1 ELSE 0 END) AS wickets,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND COALESCE(TRY_CAST(batruns AS INTEGER), 0) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN {LEGAL_BALL} AND COALESCE(TRY_CAST(bowlruns AS INTEGER), 0) = 0 THEN 1 ELSE 0 END) AS bowler_dot_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
              FROM analytics.deliveries_v1
              WHERE {' AND '.join(where_clauses)}
              {group_by_sql}
            )
            SELECT
              {', '.join(dimension_columns) + ',' if dimension_columns else ''}
              balls,
              legal_balls,
              runs,
              dismissals,
              wickets,
              {metric_projection_sql},
              balls AS sample_size,
              balls < ? AS low_sample,
              {sort_expression} AS rank_value
            FROM aggregate_rows
            ORDER BY rank_value {sort_direction}, sample_size DESC
            LIMIT ?
            """
    params.extend([soft_minimum, limit])
    columns = [
        *dimension_columns,
        "balls",
        "legal_balls",
        "runs",
        "dismissals",
        "wickets",
        "strike_rate",
        "dot_percentage",
        "bowler_dot_percentage",
        "boundary_percentage",
        "false_shot_percentage",
        "dismissal_rate",
        "sample_size",
        "low_sample",
        "rank_value",
    ]
    return MatchupBuild(
        query=QueryBuildResult(
            sql=_clean_sql(sql),
            params=params,
            columns=columns,
            metric_column="rank_value",
            sample_columns=["sample_size", "low_sample"],
            description="Semantic V2 matchup analysis over analytics.deliveries_v1",
        ),
        dimension_columns=dimension_columns,
        soft_minimum_sample=soft_minimum,
        ranking_note=ranking_note,
    )


def unsupported_reason(plan: CricketQueryPlan) -> str:
    return (
        f"Matchup analysis for metric '{plan.metric}' was understood, "
        "but that metric or matchup shape is not implemented yet."
    )


def _dimensions_for_plan(plan: CricketQueryPlan) -> list[MatchupDimension]:
    dimensions: list[MatchupDimension] = []

    def add(alias: str, expression: str, group: bool = True) -> None:
        if alias not in {dimension.alias for dimension in dimensions}:
            dimensions.append(MatchupDimension(alias=alias, expression=expression, group=group))

    if "batter" in plan.filters:
        add("batter", "MIN(bat)", group=False)
    if "bowler" in plan.filters:
        add("bowler", "MIN(bowl)", group=False)

    group_by = set(plan.group_by)
    if "matchup" in group_by or plan.entity == "matchup":
        add("batter", "bat")
        add("bowler", "bowl")
        return dimensions

    if "batter" in group_by or plan.entity == "batter":
        add("batter", "bat")
    if "bowler" in group_by or plan.entity == "bowler":
        add("bowler", "bowl")
    if "bowling_style" in group_by or "bowling_style" in plan.filters:
        add("bowling_style", _bowling_style_group_expression())
    if "batter_hand" in group_by or "batter_hand" in plan.filters:
        add("batter_hand", "bat_hand")

    if not dimensions:
        add("batter", "bat")
        add("bowler", "bowl")
    return dimensions


def _bowling_style_group_expression() -> str:
    return (
        "CASE "
        "WHEN bowl_style IN ('LF', 'LFM', 'LMF', 'LM') THEN 'left_arm_pace' "
        "WHEN bowl_style IN ('LBG', 'LB', 'LWS') THEN 'wrist_spin' "
        "WHEN bowl_style IN ('OB', 'SLA', 'SLO', 'RMF') THEN 'finger_spin' "
        "WHEN bowl_kind = 'pace bowler' THEN 'pace' "
        "WHEN bowl_kind = 'spin bowler' THEN 'spin' "
        "ELSE bowl_style END"
    )


def _soft_minimum_sample(plan: CricketQueryPlan) -> int:
    if plan.minimum_sample:
        return plan.minimum_sample.balls or plan.minimum_sample.legal_balls or 20
    if plan.filters.get("batter") and plan.filters.get("bowler"):
        return 12
    if "matchup" in plan.group_by or plan.entity == "matchup":
        return 20
    return 24


def _sort_expression(plan: CricketQueryPlan) -> tuple[str, str, str | None]:
    if plan.question_subject == "one_sided_matchup":
        expression, note = one_sided_matchup_score_expression()
        return expression, "DESC", note
    return matchup_sort_expression(plan.metric, filters=plan.filters)
