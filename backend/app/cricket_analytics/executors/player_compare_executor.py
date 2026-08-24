from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec


@dataclass(frozen=True, slots=True)
class PlayerCompareResult:
    rows: list[dict[str, object]]
    columns: list[str]
    metrics: list[str]
    players: list[str]
    sample_columns: list[str]
    executed_sql: list[str]
    view: str | None = None


def execute_player_compare(plan: CricketQueryPlan, repository: Any) -> PlayerCompareResult:
    players = [str(player) for player in plan.filters.get("compare_players", []) if isinstance(player, str)]
    metrics = _comparison_metrics(plan)
    if len(players) < 2:
        raise ValueError("Player comparison requires at least two named players.")
    if plan.filters.get("comparison_view") == "opposition":
        return _execute_opposition_compare(plan, repository, players, metrics)

    phase_view = plan.filters.get("comparison_view") == "phase"
    phases: list[str | None] = ["powerplay", "middle", "death"] if phase_view else [None]
    rows_by_key: dict[tuple[str, str | None], dict[str, object]] = {
        (player, phase): {
            "player": player,
            **({"phase": phase} if phase is not None else {}),
        }
        for player in players
        for phase in phases
    }
    executed_sql: list[str] = []
    for metric in metrics:
        for player in players:
            for phase in phases:
                player_plan = _single_player_plan(
                    plan,
                    player,
                    metric,
                    filter_overrides={"phase": phase} if phase is not None else None,
                )
                build = build_aggregate_query(player_plan)
                executed_sql.append(build.sql)
                result_rows = repository._fetchall(build.sql, build.params)
                result = rows_by_key[(player, phase)]
                if not result_rows:
                    result[metric] = None
                    continue
                row = dict(zip(build.columns, result_rows[0]))
                result[metric] = row.get(metric)
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
                        result[evidence_column] = row[evidence_column]

    evidence_columns = (
        ["balls_faced", "dismissals", "matches"]
        if plan.entity == "batter"
        else [
            "legal_balls",
            *(["wickets"] if "bowling_strike_rate" in metrics and "wickets_taken" not in metrics else []),
            "runs_conceded",
            "matches",
        ]
    )
    columns = [
        "player",
        *(["phase"] if phase_view else []),
        *metrics,
        *(column for column in evidence_columns if column not in metrics),
    ]
    sample_columns = ["balls_faced" if plan.entity == "batter" else "legal_balls"]
    return PlayerCompareResult(
        rows=list(rows_by_key.values()),
        columns=columns,
        metrics=metrics,
        players=players,
        sample_columns=sample_columns,
        executed_sql=executed_sql,
        view="phase" if phase_view else None,
    )


def _execute_opposition_compare(
    plan: CricketQueryPlan,
    repository: Any,
    players: list[str],
    metrics: list[str],
) -> PlayerCompareResult:
    dimension = "batting_team" if plan.entity == "bowler" else "bowling_team"
    rows_by_key: dict[tuple[str, str], dict[str, object]] = {}
    executed_sql: list[str] = []
    for metric in metrics:
        for player in players:
            player_plan = _single_player_plan(
                plan,
                player,
                metric,
                group_by=[dimension],
                limit=50,
            )
            build = build_aggregate_query(player_plan)
            executed_sql.append(build.sql)
            for raw_row in repository._fetchall(build.sql, build.params):
                row = dict(zip(build.columns, raw_row))
                opposition = row.get(dimension)
                if not isinstance(opposition, str):
                    continue
                result = rows_by_key.setdefault(
                    (player, opposition),
                    {"player": player, "opposition": opposition},
                )
                result[metric] = row.get(metric)
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
                        result[evidence_column] = row[evidence_column]

    evidence_columns = (
        ["balls_faced", "dismissals", "matches"]
        if plan.entity == "batter"
        else [
            "legal_balls",
            *(["wickets"] if "bowling_strike_rate" in metrics and "wickets_taken" not in metrics else []),
            "runs_conceded",
            "matches",
        ]
    )
    rows = [
        row
        for player in players
        for (row_player, _), row in rows_by_key.items()
        if row_player == player
    ]
    return PlayerCompareResult(
        rows=rows,
        columns=[
            "player",
            "opposition",
            *metrics,
            *(column for column in evidence_columns if column not in metrics),
        ],
        metrics=metrics,
        players=players,
        sample_columns=["balls_faced" if plan.entity == "batter" else "legal_balls"],
        executed_sql=executed_sql,
        view="opposition",
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


def _single_player_plan(
    plan: CricketQueryPlan,
    player: str,
    metric: str,
    filter_overrides: dict[str, object] | None = None,
    group_by: list[str] | None = None,
    limit: int = 1,
) -> CricketQueryPlan:
    filters = {
        key: value
        for key, value in plan.filters.items()
        if key not in {"compare_players", "comparison_metrics", "comparison_view"}
    }
    filters.update(filter_overrides or {})
    filters["bowler" if plan.entity == "bowler" else "batter"] = player
    return CricketQueryPlan(
        operation="aggregate",
        entity=plan.entity,
        metric=metric,
        group_by=group_by or [plan.entity],
        filters=filters,
        sort=SortSpec(by=metric, direction=get_metric(metric, entity=plan.entity).default_sort),
        limit=limit,
        minimum_sample=plan.minimum_sample if plan.minimum_sample_explicit else None,
        minimum_sample_explicit=plan.minimum_sample_explicit,
        question_subject=plan.question_subject,
        explanation_intent="player_compare_component",
    )
