from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, SortSpec


@dataclass(frozen=True, slots=True)
class PlayerCompareResult:
    rows: list[dict[str, object]]
    columns: list[str]
    metrics: list[str]
    players: list[str]
    sample_columns: list[str]
    executed_sql: list[str]


def execute_player_compare(plan: CricketQueryPlan, repository: Any) -> PlayerCompareResult:
    players = [str(player) for player in plan.filters.get("compare_players", []) if isinstance(player, str)]
    metrics = _comparison_metrics(plan)
    if len(players) < 2:
        raise ValueError("Player comparison requires at least two named players.")

    rows_by_player: dict[str, dict[str, object]] = {player: {"player": player} for player in players}
    executed_sql: list[str] = []
    for metric in metrics:
        for player in players:
            player_plan = _single_player_plan(plan, player, metric)
            build = build_aggregate_query(player_plan)
            executed_sql.append(build.sql)
            result_rows = repository._fetchall(build.sql, build.params)
            if not result_rows:
                rows_by_player[player][metric] = None
                continue
            row = dict(zip(build.columns, result_rows[0]))
            rows_by_player[player][metric] = row.get(metric)
            for evidence_column in (
                "balls_faced",
                "legal_balls",
                "runs_scored",
                "runs_conceded",
                "dismissals",
                "wickets",
                "matches",
            ):
                if row.get(evidence_column) is not None:
                    rows_by_player[player][evidence_column] = row[evidence_column]

    evidence_columns = (
        ["balls_faced", "dismissals", "matches"]
        if plan.entity == "batter"
        else ["legal_balls", "runs_conceded", "matches"]
    )
    columns = ["player", *metrics, *(column for column in evidence_columns if column not in metrics)]
    sample_columns = ["balls_faced" if plan.entity == "batter" else "legal_balls"]
    return PlayerCompareResult(
        rows=list(rows_by_player.values()),
        columns=columns,
        metrics=metrics,
        players=players,
        sample_columns=sample_columns,
        executed_sql=executed_sql,
    )


def unsupported_reason(plan: CricketQueryPlan) -> str:
    return plan.unsupported_reason or "Player comparison is understood, but this comparison shape is not implemented yet."


def _comparison_metrics(plan: CricketQueryPlan) -> list[str]:
    raw_metrics = plan.filters.get("comparison_metrics")
    if isinstance(raw_metrics, list):
        metrics = [str(metric) for metric in raw_metrics if isinstance(metric, str)]
        if metrics:
            return metrics
    return [plan.metric]


def _single_player_plan(plan: CricketQueryPlan, player: str, metric: str) -> CricketQueryPlan:
    filters = {
        key: value
        for key, value in plan.filters.items()
        if key not in {"compare_players", "comparison_metrics"}
    }
    filters["bowler" if plan.entity == "bowler" else "batter"] = player
    minimum_sample = plan.minimum_sample
    try:
        defaults = get_metric(metric, entity=plan.entity).minimum_sample.as_dict()
        default_sample = MinimumSampleSpec(**defaults) if defaults else None
        if minimum_sample and default_sample:
            minimum_sample = minimum_sample.merged_with_defaults(defaults)
        elif default_sample:
            minimum_sample = default_sample
    except KeyError:
        minimum_sample = plan.minimum_sample
    return CricketQueryPlan(
        operation="aggregate",
        entity=plan.entity,
        metric=metric,
        group_by=[plan.entity],
        filters=filters,
        sort=SortSpec(by=metric, direction=get_metric(metric, entity=plan.entity).default_sort),
        limit=1,
        minimum_sample=minimum_sample,
        question_subject=plan.question_subject,
        explanation_intent="player_compare_component",
    )
