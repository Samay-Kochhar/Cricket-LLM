from __future__ import annotations

from backend.app.cricket_analytics.capabilities import validate_capability
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.ontology import DIMENSIONS, ENTITIES, METRICS, OPERATION_TYPES
from backend.app.cricket_analytics.schemas import CricketQueryPlan, ValidationResult


COMPATIBLE_OWNER = {
    "batter": {"batter", "batter_or_bowler", "team", "matchup"},
    "bowler": {"bowler", "batter_or_bowler", "team", "matchup"},
    "team": {"team", "batter_or_bowler"},
    "matchup": {"matchup", "batter", "bowler", "batter_or_bowler"},
    "innings": {"team", "batter_or_bowler"},
    "venue": {"team", "batter_or_bowler"},
}


FILTER_DIMENSIONS = {
    "batter",
    "bowler",
    "batting_team",
    "bowling_team",
    "phase",
    "line",
    "length",
    "shot_type",
    "field_zone",
    "bowling_style",
    "batter_hand",
    "bowler_hand",
    "venue",
    "opposition",
    "innings",
    "over_range",
    "team",
}


def validate_plan(plan: CricketQueryPlan, original_question: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    lowered = original_question.lower()

    if plan.operation not in OPERATION_TYPES:
        errors.append(f"Unsupported operation '{plan.operation}'.")
    if plan.entity not in ENTITIES:
        errors.append(f"Unsupported entity '{plan.entity}'.")
    if plan.metric not in METRICS:
        errors.append(f"Unsupported metric '{plan.metric}'.")
    elif plan.operation == "aggregate":
        try:
            owner = get_metric(plan.metric, entity=plan.entity, filters=plan.filters).owner
        except KeyError:
            owner = METRICS[plan.metric].owner
        if plan.entity in COMPATIBLE_OWNER and owner not in COMPATIBLE_OWNER[plan.entity]:
            errors.append(f"Metric '{plan.metric}' is owned by {owner}, not compatible with entity '{plan.entity}'.")

    for dimension in plan.group_by:
        if dimension not in DIMENSIONS:
            errors.append(f"Unsupported group_by dimension '{dimension}'.")

    internal_filters = {"compare_players", "comparison_metrics"} if plan.operation == "player_compare" else set()
    if plan.operation == "match_fact":
        internal_filters |= {"match_stage", "fact_type"}
    for filter_name in plan.filters:
        if filter_name not in FILTER_DIMENSIONS and filter_name not in {"years", "year_mode", "competition"} and filter_name not in internal_filters:
            errors.append(f"Unsupported filter '{filter_name}'.")

    if plan.sort:
        if plan.sort.direction not in {"asc", "desc"}:
            errors.append("Sort direction must be 'asc' or 'desc'.")
        if plan.sort.by != plan.metric and plan.sort.by not in DIMENSIONS and plan.sort.by not in {"balls", "legal_balls"}:
            errors.append(f"Sort field '{plan.sort.by}' is not a known metric or dimension.")

    grouped_or_filtered = set(plan.group_by) | set(plan.filters)
    if "bowling type" in lowered or "bowling style" in lowered or "type of bowling" in lowered:
        if "bowling_style" not in grouped_or_filtered:
            errors.append("Question asks for bowling type but plan does not group or filter by bowling_style.")
        if "bowler" in plan.group_by and "bowling_style" not in plan.group_by:
            errors.append("Question asks for bowling type but plan groups by bowler. Use bowling_style.")
    asks_shot_type = "shot" in lowered and "false shot" not in lowered and "false-shot" not in lowered
    if asks_shot_type and "shot_type" not in grouped_or_filtered:
        errors.append("Question asks for shot but plan does not group or filter by shot_type.")
    if "length" in lowered and "length" not in grouped_or_filtered:
        errors.append("Question asks for length but plan does not group or filter by length.")
    if "line" in lowered and "line" not in grouped_or_filtered:
        errors.append("Question asks for line but plan does not group or filter by line.")
    if ("field zone" in lowered or "scoring zone" in lowered or "wagon" in lowered) and "field_zone" not in grouped_or_filtered:
        errors.append("Question asks for field/scoring zone but plan does not group or filter by field_zone.")
    if "phase" in lowered and "phase" not in grouped_or_filtered and plan.split_by != "phase":
        errors.append("Question asks for phase but plan does not group, filter, or split by phase.")

    is_matchup_question = "matchup" in lowered or "batter-bowler" in lowered
    if "which batter" in lowered and not is_matchup_question and "batter" not in grouped_or_filtered and plan.entity != "batter":
        errors.append("Question asks for a batter but plan does not group/filter batter or use batter entity.")
    if "which bowler" in lowered and not is_matchup_question and "bowler" not in grouped_or_filtered and plan.entity != "bowler":
        errors.append("Question asks for a bowler but plan does not group/filter bowler or use bowler entity.")

    if plan.operation == "aggregate" and not plan.group_by and plan.entity not in {"batter", "bowler", "team", "venue"}:
        warnings.append("Aggregate plans usually need group_by or a leaderboard entity.")
    if plan.limit is not None and plan.limit > 50:
        warnings.append("Limit above 50 will be capped by normalization.")

    errors.extend(validate_capability(plan))

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
