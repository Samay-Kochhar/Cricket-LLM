from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.cricket_analytics.ontology import METRICS
from backend.app.cricket_analytics.metric_registry import split_metric_expression
from backend.app.cricket_analytics.query_builders.aggregate_builder import (
    BOWLER_WICKET,
    LEGAL_BALL,
    _clean_sql,
    _filter_clauses,
)
from backend.app.cricket_analytics.schemas import CricketQueryPlan, QueryBuildResult


SUPPORTED_SPLITS = {"phase", "batter_hand", "bowling_style_group", "balls_faced_window", "over_range"}
SUPPORTED_METRICS = {
    "batting_strike_rate",
    "economy_rate",
    "runs_scored",
    "run_rate",
    "dot_ball_percentage",
    "batter_dot_ball_percentage",
    "bowler_dot_ball_percentage",
    "boundary_percentage",
    "wickets",
    "wickets_taken",
    "dismissal_rate",
}


@dataclass(frozen=True, slots=True)
class SplitCompareBuild:
    query: QueryBuildResult
    value_a_column: str
    value_b_column: str
    sample_a_column: str
    sample_b_column: str
    split_a_label: str
    split_b_label: str


def build_split_compare_query(plan: CricketQueryPlan) -> SplitCompareBuild:
    if plan.split_by not in SUPPORTED_SPLITS:
        raise ValueError(unsupported_reason(plan))
    if plan.metric not in SUPPORTED_METRICS:
        raise ValueError(unsupported_reason(plan))

    entity_expression, entity_alias = _entity_sql(plan.entity)
    split_case, split_a, split_b, split_a_label, split_b_label, split_params = _split_sql(plan)
    value_a_column = f"{_safe_identifier(split_a_label)}_value"
    value_b_column = f"{_safe_identifier(split_b_label)}_value"
    sample_a_column = f"{_safe_identifier(split_a_label)}_sample"
    sample_b_column = f"{_safe_identifier(split_b_label)}_sample"
    sample_expression = _sample_expression(plan)
    metric_expression = _metric_expression(plan)
    difference_expression = _difference_expression(plan, value_a_column, value_b_column)
    rank_expression = _rank_expression(plan, difference_expression)
    minimum_sample = _minimum_sample(plan)
    limit = plan.limit or 10

    where_clauses = ["1 = 1"]
    filter_params: list[Any] = []
    skip_filters = _split_filter_keys(plan)
    for clause, clause_params in _filter_clauses({key: value for key, value in plan.filters.items() if key not in skip_filters}, entity=plan.entity):
        where_clauses.append(clause)
        filter_params.extend(clause_params)

    params = [*split_params, *filter_params, minimum_sample, minimum_sample, limit]

    sql = f"""
            WITH bucketed AS (
              SELECT
                {entity_expression} AS entity,
                {split_case} AS split_value,
                p_match,
                inns,
                team_bat,
                CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END AS balls_faced,
                CASE WHEN {LEGAL_BALL} THEN 1 ELSE 0 END AS legal_balls,
                CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END AS runs_scored,
                TRY_CAST(bowlruns AS INTEGER) AS runs_conceded,
                CASE WHEN {BOWLER_WICKET} THEN 1 ELSE 0 END AS wickets,
                CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END AS dismissals,
                CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND COALESCE(TRY_CAST(batruns AS INTEGER), 0) = 0 THEN 1 ELSE 0 END AS dot_balls,
                CASE WHEN {LEGAL_BALL} AND COALESCE(TRY_CAST(bowlruns AS INTEGER), 0) = 0 THEN 1 ELSE 0 END AS bowler_dot_balls,
                CASE WHEN {_boundary_condition(plan)} THEN 1 ELSE 0 END AS boundary_balls
              FROM analytics.deliveries_v1
              WHERE {' AND '.join(where_clauses)}
                AND NULLIF(TRIM(CAST({entity_expression} AS VARCHAR)), '') IS NOT NULL
            ),
            split_rows AS (
              SELECT
                entity,
                split_value,
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bat AS VARCHAR)) AS innings,
                SUM(balls_faced) AS balls_faced,
                SUM(legal_balls) AS legal_balls,
                SUM(runs_scored) AS runs_scored,
                SUM(runs_conceded) AS runs_conceded,
                SUM(wickets) AS wickets,
                SUM(dismissals) AS dismissals,
                SUM(dot_balls) AS dot_balls,
                SUM(bowler_dot_balls) AS bowler_dot_balls,
                SUM(boundary_balls) AS boundary_balls,
                {sample_expression} AS sample_size,
                {metric_expression} AS metric_value
              FROM bucketed
              WHERE split_value IN ('{split_a}', '{split_b}')
              GROUP BY entity, split_value
            ),
            pivoted AS (
              SELECT
                entity AS {entity_alias},
                MAX(CASE WHEN split_value = '{split_a}' THEN metric_value END) AS {value_a_column},
                MAX(CASE WHEN split_value = '{split_b}' THEN metric_value END) AS {value_b_column},
                MAX(CASE WHEN split_value = '{split_a}' THEN sample_size END) AS {sample_a_column},
                MAX(CASE WHEN split_value = '{split_b}' THEN sample_size END) AS {sample_b_column}
              FROM split_rows
              GROUP BY entity
            )
            SELECT
              {entity_alias},
              {value_a_column},
              {value_b_column},
              {difference_expression} AS difference,
              {sample_a_column},
              {sample_b_column},
              {rank_expression} AS rank_value
            FROM pivoted
            WHERE {value_a_column} IS NOT NULL
              AND {value_b_column} IS NOT NULL
              AND {sample_a_column} >= ?
              AND {sample_b_column} >= ?
            ORDER BY rank_value DESC, {sample_a_column} + {sample_b_column} DESC
            LIMIT ?
            """
    columns = [
        entity_alias,
        value_a_column,
        value_b_column,
        "difference",
        sample_a_column,
        sample_b_column,
        "rank_value",
    ]
    return SplitCompareBuild(
        query=QueryBuildResult(
            sql=_clean_sql(sql),
            params=params,
            columns=columns,
            metric_column="difference",
            sample_columns=[sample_a_column, sample_b_column],
            description=f"Semantic V2 split comparison over {plan.split_by}: {split_a_label} versus {split_b_label}",
        ),
        value_a_column=value_a_column,
        value_b_column=value_b_column,
        sample_a_column=sample_a_column,
        sample_b_column=sample_b_column,
        split_a_label=split_a_label,
        split_b_label=split_b_label,
    )


def unsupported_reason(plan: CricketQueryPlan) -> str:
    if plan.split_by not in SUPPORTED_SPLITS:
        split = f" by {plan.split_by}" if plan.split_by else ""
        return f"Split comparison{split} is understood, but this split type is not implemented yet."
    if plan.metric not in SUPPORTED_METRICS:
        return f"Split comparison for metric {plan.metric} is understood, but that metric is not implemented yet."
    return "Split comparison was understood, but the V2 split_compare executor could not build a safe query."


def _entity_sql(entity: str) -> tuple[str, str]:
    if entity == "bowler":
        return "bowl", "bowler"
    if entity == "team":
        return "team_bat", "team"
    return "bat", "batter"


def _split_sql(plan: CricketQueryPlan) -> tuple[str, str, str, str, str, list[Any]]:
    compare_values = plan.compare_values or []
    if plan.split_by == "phase":
        split_a, split_b = _two_values(compare_values, "powerplay", "death")
        split_case = (
            "CASE WHEN TRY_CAST(over AS DOUBLE) <= 10 THEN 'powerplay' "
            "WHEN TRY_CAST(over AS DOUBLE) <= 40 THEN 'middle' ELSE 'death' END"
        )
        return split_case, split_a, split_b, split_a, split_b, []
    if plan.split_by == "batter_hand":
        split_a, split_b = _two_values(compare_values, "LHB", "RHB")
        return "bat_hand", split_a, split_b, _hand_label(split_a), _hand_label(split_b), []
    if plan.split_by == "bowling_style_group":
        split_a, split_b = _two_values(compare_values, "wrist_spin", "finger_spin")
        split_case = (
            "CASE "
            "WHEN bowl_style IN ('LBG', 'LB', 'LWS') THEN 'wrist_spin' "
            "WHEN bowl_style IN ('OB', 'SLA', 'SLO') THEN 'finger_spin' "
            "WHEN bowl_kind = 'pace bowler' THEN 'pace' "
            "WHEN bowl_kind = 'spin bowler' THEN 'spin' "
            "ELSE NULL END"
        )
        return split_case, split_a, split_b, split_a, split_b, []
    if plan.split_by == "balls_faced_window":
        split_a, split_b = _two_values(compare_values, "after_20_balls", "first_20_balls")
        split_case = (
            "CASE WHEN TRY_CAST(cur_bat_bf AS INTEGER) <= 20 THEN 'first_20_balls' "
            "WHEN TRY_CAST(cur_bat_bf AS INTEGER) > 20 THEN 'after_20_balls' ELSE NULL END"
        )
        return split_case, split_a, split_b, split_a, split_b, []
    if plan.split_by == "over_range":
        start, end = _over_range(plan)
        split_a = f"overs_{start}_to_{end}"
        split_b = f"before_over_{start}"
        split_case = (
            "CASE WHEN TRY_CAST(over AS DOUBLE) >= ? AND TRY_CAST(over AS DOUBLE) < ? THEN "
            f"'{split_a}' WHEN TRY_CAST(over AS DOUBLE) < ? THEN '{split_b}' ELSE NULL END"
        )
        return split_case, split_a, split_b, split_a, split_b, [float(start - 1), float(end), float(start - 1)]
    raise ValueError(unsupported_reason(plan))


def _two_values(compare_values: list[str], default_a: str, default_b: str) -> tuple[str, str]:
    if len(compare_values) >= 2:
        return compare_values[0], compare_values[1]
    return default_a, default_b


def _over_range(plan: CricketQueryPlan) -> tuple[int, int]:
    value = plan.filters.get("over_range")
    if isinstance(value, list) and value:
        start = int(value[0])
        end = int(value[-1])
        return start, end
    return 15, 20


def _metric_expression(plan: CricketQueryPlan) -> str:
    try:
        return split_metric_expression(plan.metric, entity=plan.entity)
    except KeyError as exc:
        raise ValueError(unsupported_reason(plan)) from exc


def _sample_expression(plan: CricketQueryPlan) -> str:
    if METRICS[plan.metric].denominator == "legal_balls" or plan.metric in {"economy_rate", "run_rate", "wickets"}:
        return "SUM(legal_balls)"
    return "SUM(balls_faced)"


def _difference_expression(plan: CricketQueryPlan, value_a_column: str, value_b_column: str) -> str:
    if plan.split_by == "balls_faced_window":
        return f"{value_b_column} - {value_a_column}"
    if plan.split_by == "batter_hand" and METRICS[plan.metric].good_direction == "asc":
        return f"{value_b_column} - {value_a_column}"
    return f"{value_a_column} - {value_b_column}"


def _rank_expression(plan: CricketQueryPlan, difference_expression: str) -> str:
    if plan.split_by == "phase":
        return f"ABS({difference_expression})"
    return difference_expression


def _minimum_sample(plan: CricketQueryPlan) -> int:
    sample = plan.minimum_sample
    if sample is not None:
        if METRICS[plan.metric].denominator == "legal_balls" or plan.metric in {"economy_rate", "run_rate", "wickets"}:
            return sample.legal_balls or sample.balls or 24
        return sample.balls or sample.legal_balls or 20
    defaults = METRICS[plan.metric].minimum_sample
    return defaults.legal_balls or defaults.balls or 20


def _dot_ball_condition(plan: CricketQueryPlan) -> str:
    if plan.entity == "bowler":
        return f"{LEGAL_BALL} AND COALESCE(TRY_CAST(bowlruns AS INTEGER), 0) = 0"
    return "TRY_CAST(ballfaced AS INTEGER) = 1 AND COALESCE(TRY_CAST(batruns AS INTEGER), 0) = 0"


def _boundary_condition(plan: CricketQueryPlan) -> str:
    if plan.entity == "bowler":
        return f"{LEGAL_BALL} AND TRY_CAST(batruns AS INTEGER) IN (4, 6)"
    return "TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) IN (4, 6)"


def _split_filter_keys(plan: CricketQueryPlan) -> set[str]:
    if plan.split_by == "phase":
        return {"phase"}
    if plan.split_by == "batter_hand":
        return {"batter_hand"}
    if plan.split_by == "bowling_style_group":
        return {"bowling_style"}
    if plan.split_by == "over_range":
        return {"over_range"}
    return set()


def _hand_label(value: str) -> str:
    if value == "LHB":
        return "left_handers"
    if value == "RHB":
        return "right_handers"
    return value.lower()


def _safe_identifier(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in value)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    if not cleaned:
        return "split"
    if cleaned[0].isdigit():
        return f"split_{cleaned}"
    return cleaned
