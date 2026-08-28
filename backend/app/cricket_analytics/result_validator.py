from __future__ import annotations

from backend.app.cricket_analytics.schemas import CricketQueryPlan, QueryBuildResult, ResultValidation
from backend.app.cricket_analytics.metric_registry import percentage_metric_ids


PERCENTAGE_METRICS = percentage_metric_ids()


def validate_result(
    plan: CricketQueryPlan,
    build: QueryBuildResult,
    rows: list[dict[str, object]],
) -> ResultValidation:
    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        errors.append("Result set is empty.")
        return ResultValidation(valid=False, errors=errors, warnings=warnings)

    missing_columns = [column for column in build.columns if column not in rows[0]]
    if missing_columns:
        errors.append(f"Result is missing expected columns: {', '.join(missing_columns)}.")

    for dimension in plan.group_by:
        expected = "shot_type" if dimension == "shot_type" else dimension
        if expected not in rows[0]:
            errors.append(f"Result does not include requested group_by column '{expected}'.")

    if plan.metric not in rows[0]:
        errors.append(f"Result does not include metric column '{plan.metric}'.")

    for sample_column in build.sample_columns:
        if sample_column not in rows[0]:
            warnings.append(f"Sample size column '{sample_column}' is absent.")

    metric_values: list[float] = []
    for row in rows:
        raw_value = row.get(plan.metric)
        if raw_value is None:
            warnings.append(f"A row has null {plan.metric}.")
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            errors.append(f"Metric value for {plan.metric} is not numeric.")
            continue
        metric_values.append(value)
        if plan.metric in PERCENTAGE_METRICS and not 0 <= value <= 100:
            errors.append(f"Percentage metric {plan.metric} is outside 0-100: {value}.")
        if plan.metric == "economy_rate" and value < 0:
            errors.append("Economy rate cannot be negative.")

    if plan.sort:
        sort_values = [row.get(plan.sort.by) for row in rows]
        comparable_sort_values = [value for value in sort_values if isinstance(value, int | float | str)]
        if len(comparable_sort_values) == len(rows):
            sorted_values = sorted(comparable_sort_values, reverse=plan.sort.direction == "desc")
            if comparable_sort_values != sorted_values:
                warnings.append(f"Rows are not sorted {plan.sort.direction} by {plan.sort.by}.")

    return ResultValidation(valid=not errors, errors=errors, warnings=warnings)
