"""Typed changes to an already resolved player ranking."""

from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, SortSpec
from backend.app.cricket_analytics.semantic_service import _metric_evidence_columns


def ranking_options(plan: CricketQueryPlan) -> tuple[dict[str, str], dict[str, str]]:
    if plan.operation != "aggregate" or plan.entity not in {"batter", "bowler"}:
        raise ValueError("Sample and sort controls are available for batting and bowling rankings.")
    if (plan.group_by or [plan.entity]) != [plan.entity]:
        raise ValueError("This result does not support player ranking controls.")
    if plan.entity in plan.filters:
        raise ValueError("Sample and sort controls require a player ranking, not one named player.")
    sample_unit = "balls" if plan.entity == "batter" else "legal_balls"
    units = {
        sample_unit: "Balls faced" if plan.entity == "batter" else "Legal balls",
        "matches": "Matches",
    }
    if plan.minimum_sample and plan.minimum_sample.innings is not None:
        units["innings"] = "Innings"
    columns = [plan.metric, *_metric_evidence_columns(plan.metric, plan.entity), "matches"]
    if plan.sort:
        columns.append(plan.sort.by)
    available = set(build_aggregate_query(plan).columns)
    sorts = {
        column: column.replace("_", " ").title()
        for column in dict.fromkeys(columns)
        if column in available
    }
    return units, sorts


def controlled_plan(
    original: CricketQueryPlan,
    *,
    unit: str,
    minimum: int,
    sort_by: str,
    direction: str,
) -> CricketQueryPlan:
    units, sorts = ranking_options(original)
    if unit not in units:
        raise ValueError(f"{unit} is not a supported sample unit for this ranking.")
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum < 0
        or minimum > 1_000_000
    ):
        raise ValueError("The minimum sample must be a whole number from 0 to 1,000,000.")
    if sort_by not in sorts or direction not in {"asc", "desc"}:
        raise ValueError("Choose a supported sort column and direction.")
    sample = MinimumSampleSpec(**{unit: minimum}) if minimum else None
    if original.minimum_sample and getattr(original.minimum_sample, unit) == minimum:
        # A sort-only submission must retain any additional qualifications.
        sample = original.minimum_sample.model_copy(deep=True)
    return original.model_copy(
        update={
            "minimum_sample": sample,
            "minimum_sample_explicit": original.minimum_sample_explicit or sample != original.minimum_sample,
            "sort": SortSpec(by=sort_by, direction=direction),
        },
        deep=True,
    )
