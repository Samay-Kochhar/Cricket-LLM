from __future__ import annotations

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.schemas import CricketQueryPlan
from backend.app.domain.evidence_models import ChartBlock, TableBlock


def select_chart(plan: CricketQueryPlan, table: TableBlock) -> ChartBlock | None:
    """Select a chart only when the validated evidence shape makes it useful."""
    if plan.operation == "aggregate":
        return _aggregate_chart(plan, table)
    if plan.operation == "player_compare":
        return _player_comparison_chart(plan, table)
    if plan.operation == "split_compare":
        return _split_comparison_chart(plan, table)
    return None


def _aggregate_chart(plan: CricketQueryPlan, table: TableBlock) -> ChartBlock | None:
    if set(plan.group_by) == {"line", "length"} and len(plan.group_by) == 2:
        dimension_indexes = {dimension: plan.group_by.index(dimension) for dimension in plan.group_by}
        metric_index = len(plan.group_by)
        series = [
            {
                "label": f"{row[dimension_indexes['line']]} / {row[dimension_indexes['length']]}",
                "x": str(row[dimension_indexes["line"]]),
                "y": str(row[dimension_indexes["length"]]),
                "value": row[metric_index],
            }
            for row in table.rows
            if len(row) > metric_index and isinstance(row[metric_index], int | float)
        ]
        if len({point["x"] for point in series}) < 2 or len({point["y"] for point in series}) < 2:
            return None
        return ChartBlock(
            title=f"{_label(plan.metric)} by Line and Length",
            chart_type="heatmap",
            series=series,
        )

    if len(plan.group_by) != 1:
        return None
    dimension = plan.group_by[0]
    is_trend = dimension == "year" and plan.question_subject == "yearly_trend"
    is_breakdown = dimension in {"line", "length", "bowling_style"}
    is_ranking = dimension == plan.entity and dimension not in plan.filters and bool(
        plan.sort and plan.sort.by == plan.metric
    )
    if not is_trend and not is_breakdown and not is_ranking:
        return None
    series = [
        {"label": str(row[0]), "value": row[1]}
        for row in table.rows
        if len(row) > 1 and isinstance(row[1], int | float)
    ]
    if not series:
        return None
    return ChartBlock(
        title=(
            f"{_label(plan.metric)} by {_label(dimension)}"
            if is_breakdown or is_trend
            else f"{_label(plan.metric)} ranking"
        ),
        chart_type="line" if is_trend else "horizontal_bar",
        series=series,
    )


def _player_comparison_chart(plan: CricketQueryPlan, table: TableBlock) -> ChartBlock | None:
    metrics = plan.filters.get("comparison_metrics")
    comparison_view = plan.filters.get("comparison_view")
    if (
        comparison_view == "opposition"
        or not isinstance(metrics, list)
        or not metrics
        or not all(isinstance(metric, str) for metric in metrics)
        or len(table.columns) < 2
    ):
        return None
    metric_ids = [str(metric) for metric in metrics]
    try:
        units = {get_metric(metric).unit for metric in metric_ids}
    except KeyError:
        return None
    if len(units) != 1:
        return None
    metric_labels = [_label(metric) for metric in metric_ids]
    try:
        metric_indexes = [table.columns.index(label) for label in metric_labels]
    except ValueError:
        return None
    series = [
        {
            "label": str(row[0]),
            "value": row[metric_index],
            "group": (
                f"{row[1]} — {metric_label}"
                if comparison_view == "phase"
                else metric_label
            ),
        }
        for row in table.rows
        for metric_label, metric_index in zip(metric_labels, metric_indexes, strict=True)
        if isinstance(row[metric_index], int | float)
    ]
    if len(series) != len(table.rows) * len(metric_indexes):
        return None
    return ChartBlock(
        title=(metric_labels[0] + " comparison" if len(metric_labels) == 1 else "Player metric comparison"),
        chart_type="grouped_bar",
        series=series,
    )


def _split_comparison_chart(plan: CricketQueryPlan, table: TableBlock) -> ChartBlock | None:
    if not table.rows or len(table.columns) < 3 or len(table.rows[0]) < 3:
        return None
    values = table.rows[0][1:3]
    if not all(isinstance(value, int | float) for value in values):
        return None
    labels = [column.removesuffix(" Value") for column in table.columns[1:3]]
    metric_label = _label(plan.metric)
    return ChartBlock(
        title=f"{metric_label}: {labels[0]} versus {labels[1]}",
        chart_type="grouped_bar",
        series=[
            {"label": label, "value": value, "group": metric_label}
            for label, value in zip(labels, values, strict=True)
        ],
    )


def _label(value: str) -> str:
    try:
        return get_metric(value).label
    except KeyError:
        return value.replace("_", " ").title()
