from __future__ import annotations

import re

from backend.app.cricket_analytics.capabilities import validate_capability
from backend.app.cricket_analytics.dismissal_types import (
    DISMISSAL_TYPE_REGISTRY,
    requested_dismissal_types,
)
from backend.app.cricket_analytics.match_facts import MATCH_FACT_REGISTRY
from backend.app.cricket_analytics.match_lighting import (
    MATCH_LIGHTING,
    is_lighting_value,
    requested_lighting_values,
)
from backend.app.cricket_analytics.match_result_conditions import (
    BATTING_RESULT_FILTER,
    is_batting_result,
    removes_result_condition,
    requested_result_filters,
    result_condition_problem,
    unsupported_role_reason,
)
from backend.app.cricket_analytics.match_state_filters import (
    MATCH_STATE_FIELDS,
    predicate_from_filter,
    registered_predicates,
    removed_fields,
    strip_match_state_phrases,
    unresolved_mention,
)
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.ontology import DIMENSIONS, ENTITIES, METRICS, OPERATION_TYPES
from backend.app.cricket_analytics.plan_normalizer import (
    is_passive_dismissal_question,
    requested_bowling_style,
    requested_limit_from_wording,
    requested_metric_from_wording,
    requested_minimum_sample,
    requested_sort_direction,
)
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, ValidationResult


COMPATIBLE_OWNER = {
    "batter": {"batter", "batter_or_bowler", "team", "matchup"},
    "bowler": {"bowler", "batter_or_bowler", "team", "matchup"},
    "team": {"team", "batter_or_bowler"},
    "matchup": {"matchup", "batter", "bowler", "batter_or_bowler"},
    "innings": {"team", "batter_or_bowler"},
    "venue": {"team", "batter_or_bowler"},
}

COMPARISON_COMPATIBLE_OWNER = {
    "batter": {"batter", "batter_or_bowler"},
    "bowler": {"bowler", "batter_or_bowler"},
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
    "venues",
    "opposition",
    "player_team",
    "match_lighting",
    "innings",
    "over_range",
    "team",
    "dismissal_type",
    *MATCH_STATE_FIELDS,
    BATTING_RESULT_FILTER,
}

RESULT_CONDITION_OPERATIONS = {"aggregate", "matchup", "split_compare", "player_compare"}


def validate_plan(plan: CricketQueryPlan, original_question: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(_match_state_errors(plan, original_question))
    errors.extend(_result_condition_errors(plan, original_question))
    errors.extend(_match_lighting_errors(plan, original_question))
    # Threshold wording such as "at least 8" belongs to its typed predicate and
    # is never reread as a sample, ranking direction or metric request.
    lowered = strip_match_state_phrases(original_question)

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

    internal_filters = {"compare_players", "comparison_metrics", "comparison_view"} if plan.operation == "player_compare" else set()
    if plan.operation == "match_fact":
        internal_filters |= {"match_stage", "fact_type", "participants"}
        fact_type = plan.filters.get("fact_type")
        if fact_type not in MATCH_FACT_REGISTRY:
            errors.append("Match facts require a registered fact_type.")
    for filter_name in plan.filters:
        if filter_name not in FILTER_DIMENSIONS and filter_name not in {"years", "year_mode", "competition"} and filter_name not in internal_filters:
            errors.append(f"Unsupported filter '{filter_name}'.")

    if plan.sort:
        if plan.sort.direction not in {"asc", "desc"}:
            errors.append("Sort direction must be 'asc' or 'desc'.")
        if plan.sort.by != plan.metric and plan.sort.by not in DIMENSIONS and plan.sort.by not in {"balls", "legal_balls"}:
            errors.append(f"Sort field '{plan.sort.by}' is not a known metric or dimension.")

    if plan.operation == "player_compare":
        compare_players = plan.filters.get("compare_players")
        if not isinstance(compare_players, list) or len(compare_players) < 2:
            errors.append("Player comparison requires at least two named players.")
        comparison_metrics = plan.filters.get("comparison_metrics")
        if not isinstance(comparison_metrics, list) or not comparison_metrics:
            errors.append("Player comparison requires at least one explicit comparison metric.")
        elif any(not isinstance(metric, str) or metric not in METRICS for metric in comparison_metrics):
            errors.append("Player comparison contains an unsupported comparison metric.")
        else:
            for comparison_metric in comparison_metrics:
                try:
                    owner = get_metric(
                        comparison_metric,
                        entity=plan.entity,
                        filters=plan.filters,
                    ).owner
                except KeyError:
                    owner = METRICS[comparison_metric].owner
                if (
                    plan.entity in COMPARISON_COMPATIBLE_OWNER
                    and owner not in COMPARISON_COMPATIBLE_OWNER[plan.entity]
                ):
                    errors.append(
                        f"Comparison metric '{comparison_metric}' is owned by {owner}, "
                        f"not compatible with entity '{plan.entity}'."
                    )

    grouped_or_filtered = set(plan.group_by) | set(plan.filters)
    dismissal_type_plan = "dismissal_type" in grouped_or_filtered
    if dismissal_type_plan:
        errors.extend(_dismissal_type_errors(plan))
    dismissal_request = requested_dismissal_types(original_question)
    if (
        dismissal_request is not None
        and not dismissal_request.fielding_perspective
        and plan.operation in {"aggregate", "matchup", "split_compare", "player_compare"}
    ):
        if not dismissal_type_plan:
            errors.append(
                "Question requests batter dismissal types, but the plan does not group or filter by dismissal_type."
            )
        elif dismissal_request.categories and set(
            plan.filters.get("dismissal_type") or []
        ) != set(dismissal_request.categories):
            errors.append(
                "Plan does not preserve every requested dismissal type: "
                + ", ".join(dismissal_request.categories)
                + "."
            )
    if (
        plan.operation == "aggregate"
        and not dismissal_type_plan
        and is_passive_dismissal_question(lowered)
        and ("batter" not in plan.filters or "bowler" in plan.filters)
    ):
        errors.append("Passive dismissal wording must retain the named player in the batter filter.")
    requested_metric = (
        requested_metric_from_wording(lowered)
        if plan.operation == "aggregate"
        else None
    )
    if requested_metric and plan.metric != requested_metric:
        errors.append(
            f"Question requests metric '{requested_metric}', but the plan uses '{plan.metric}'."
        )
    if requested_metric in METRICS:
        requested_owner = METRICS[requested_metric].owner
        canonical_opponent_ranking = (
            plan.question_subject == "matchup"
            and plan.explanation_intent == "canonical cricket meaning"
            and plan.group_by == [plan.entity]
            and plan.entity == requested_owner
        )
        if not canonical_opponent_ranking and requested_owner == "bowler" and "batter" in plan.filters and "bowler" not in plan.filters:
            errors.append("The named player must be retained as a bowler for this bowler-owned metric.")
        if not canonical_opponent_ranking and requested_owner == "batter" and "bowler" in plan.filters and "batter" not in plan.filters:
            errors.append("The named player must be retained as a batter for this batter-owned metric.")
    requested_direction = requested_sort_direction(
        lowered,
        plan.metric,
        plan.entity,
        group_by=plan.group_by,
        filters=plan.filters,
    )
    if (
        plan.operation == "aggregate"
        and requested_direction
        and (not plan.sort or plan.sort.direction != requested_direction)
    ):
        errors.append(
            f"Question requests '{requested_direction}' ranking direction for '{plan.metric}'."
        )
    requested_limit = requested_limit_from_wording(lowered)
    if plan.operation == "aggregate" and requested_limit and plan.limit != requested_limit:
        errors.append(
            f"Question requests a top/bottom limit of {requested_limit}, but the plan uses {plan.limit}."
        )
    explicit_sample = requested_minimum_sample(lowered, plan.metric)
    if plan.operation == "aggregate" and explicit_sample:
        actual_sample = plan.minimum_sample or MinimumSampleSpec()
        if actual_sample != explicit_sample or not plan.minimum_sample_explicit:
            errors.append("Plan does not preserve the explicitly requested minimum sample.")
    requested_style = requested_bowling_style(lowered)
    if (
        requested_style
        and plan.split_by != "bowling_style_group"
        and plan.filters.get("bowling_style") != requested_style
    ):
        errors.append(
            f"Question requests bowling style '{requested_style}', but the plan does not preserve that exact filter."
        )
    if "bowling type" in lowered or "bowling style" in lowered or "type of bowling" in lowered:
        if (
            "bowling_style" not in grouped_or_filtered
            and plan.split_by != "bowling_style_group"
        ):
            errors.append("Question asks for bowling type but plan does not group or filter by bowling_style.")
        if (
            "bowler" in plan.group_by
            and "bowling_style" not in plan.group_by
            and plan.split_by != "bowling_style_group"
        ):
            errors.append("Question asks for bowling type but plan groups by bowler. Use bowling_style.")
    asks_shot_type = "shot" in lowered and "false shot" not in lowered and "false-shot" not in lowered
    if asks_shot_type and "shot_type" not in grouped_or_filtered:
        errors.append("Question asks for shot but plan does not group or filter by shot_type.")
    if "length" in lowered and "length" not in grouped_or_filtered:
        errors.append("Question asks for length but plan does not group or filter by length.")
    if re.search(r"\blines?\b", lowered) and "line" not in grouped_or_filtered:
        errors.append("Question asks for line but plan does not group or filter by line.")
    if ("field zone" in lowered or "scoring zone" in lowered or "wagon" in lowered) and "field_zone" not in grouped_or_filtered:
        errors.append("Question asks for field/scoring zone but plan does not group or filter by field_zone.")
    if (
        "phase" in lowered
        and "phase" not in grouped_or_filtered
        and plan.split_by != "phase"
        and plan.filters.get("comparison_view") != "phase"
    ):
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


def _match_state_errors(plan: CricketQueryPlan, question: str) -> list[str]:
    """Numeric match-state predicates compile only from registered, typed shapes."""
    errors: list[str] = []
    for key, value in plan.filters.items():
        field = MATCH_STATE_FIELDS.get(key)
        if field is not None and predicate_from_filter(value, field) is None:
            errors.append(
                f"Filter '{key}' must be one registered comparison "
                "(gt, gte, lt, lte with a numeric value, or an inclusive between range)."
            )
    problem = unresolved_mention(question)
    if problem is not None:
        errors.append(problem.problem or f"Unresolved match-state concept: {problem.concept}.")
    for key, requested in registered_predicates(question).items():
        if plan.filters.get(key) != requested:
            label = MATCH_STATE_FIELDS[key].label
            errors.append(
                f"Question requests {label} predicate {requested!r}, but the plan does not preserve it exactly."
            )
    for key in removed_fields(question):
        if key in plan.filters:
            errors.append(
                f"Question removes the {MATCH_STATE_FIELDS[key].label} filter, but the plan still applies it."
            )
    return errors


def _result_condition_errors(plan: CricketQueryPlan, question: str) -> list[str]:
    """The chase/result condition compiles only from its registered shape and is
    never dropped, changed or kept after the question removes it."""
    errors: list[str] = []
    value = plan.filters.get(BATTING_RESULT_FILTER)
    if BATTING_RESULT_FILTER in plan.filters:
        if not is_batting_result(value):
            errors.append("Filter 'batting_result' must be the registered value 'won' or 'lost'.")
        if plan.entity == "bowler":
            errors.append(unsupported_role_reason())
        innings = plan.filters.get("innings")
        if innings is not None and innings not in {1, 2}:
            errors.append("A result condition only combines with innings 1 or 2.")
    if plan.operation not in RESULT_CONDITION_OPERATIONS:
        return errors
    problem = result_condition_problem(question)
    if problem is not None:
        errors.append(problem)
        return errors
    for key, requested in requested_result_filters(question).items():
        if plan.filters.get(key) != requested:
            errors.append(
                f"Question requests the chase/result condition {key}={requested!r}, "
                "but the plan does not preserve it exactly."
            )
    if (
        removes_result_condition(question)
        and not requested_result_filters(question)
        and BATTING_RESULT_FILTER in plan.filters
    ):
        errors.append("Question removes the match-result condition, but the plan still applies it.")
    return errors


def _match_lighting_errors(plan: CricketQueryPlan, question: str) -> list[str]:
    """Requested lighting categories compile literally and are never dropped."""
    errors: list[str] = []
    value = plan.filters.get(MATCH_LIGHTING)
    if MATCH_LIGHTING in plan.filters and not is_lighting_value(value):
        errors.append("Filter 'match_lighting' must be a recorded lighting category.")
    if plan.split_by == MATCH_LIGHTING and not (
        len(plan.compare_values or []) == 2
        and all(is_lighting_value(item) for item in plan.compare_values or [])
    ):
        errors.append("A match-lighting split needs two recorded lighting categories.")
    if plan.operation not in {"aggregate", "matchup", "split_compare", "player_compare"}:
        return errors
    requested = requested_lighting_values(question)
    if len(requested) == 2:
        if plan.split_by != MATCH_LIGHTING or set(plan.compare_values or []) != set(requested):
            errors.append(
                "Question compares the match-lighting categories "
                f"{requested}, but the plan does not split by exactly those categories."
            )
    elif len(requested) == 1:
        in_split = plan.split_by == MATCH_LIGHTING and requested[0] in (plan.compare_values or [])
        if value != requested[0] and not in_split:
            errors.append(
                f"Question requests match lighting {requested[0]!r}, but the plan does not preserve it."
            )
    return errors


def _dismissal_type_errors(plan: CricketQueryPlan) -> list[str]:
    """The registered dismissal-type dimension has one supported plan shape."""
    from backend.app.cricket_analytics.query_builders.dismissal_type_builder import (
        DISMISSAL_TYPE_FILTERS,
        DISMISSAL_TYPE_METRICS,
    )

    errors: list[str] = []
    if plan.operation != "aggregate" or plan.entity != "batter":
        errors.append("Dismissal types are answered as a batter aggregate.")
    if plan.group_by != ["dismissal_type"]:
        errors.append("Dismissal-type plans must group by dismissal_type only.")
    if plan.metric not in DISMISSAL_TYPE_METRICS:
        errors.append(
            f"Metric '{plan.metric}' is not registered by dismissal type; use dismissal counts or shares."
        )
    if not isinstance(plan.filters.get("batter"), str):
        errors.append("Dismissal types require one named dismissed batter.")
    requested = plan.filters.get("dismissal_type")
    if requested is not None and (
        not isinstance(requested, list)
        or not requested
        or any(value not in DISMISSAL_TYPE_REGISTRY for value in requested)
    ):
        errors.append("Dismissal-type filters must list registered stored categories.")
    unsupported = sorted(key for key in plan.filters if key not in DISMISSAL_TYPE_FILTERS)
    if unsupported:
        errors.append(
            "Dismissal types do not support filters: " + ", ".join(unsupported) + "."
        )
    return errors
