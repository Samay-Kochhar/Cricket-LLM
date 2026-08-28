from __future__ import annotations

import re

from backend.app.cricket_analytics.ontology import METRICS
from backend.app.cricket_analytics.metric_registry import canonical_metric_id
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, SortSpec


DIMENSION_SYNONYMS = {
    "shot": "shot_type",
    "shots": "shot_type",
    "scoring_zone": "field_zone",
    "scoring_zones": "field_zone",
    "wagon_zone": "field_zone",
    "bowling_type": "bowling_style",
    "bowling_types": "bowling_style",
    "bowling_kind": "bowling_style",
    "bat_hand": "batter_hand",
    "batting_hand": "batter_hand",
}


FILTER_SYNONYMS = {
    "bat": "batter",
    "bowl": "bowler",
    "bat_hand": "batter_hand",
    "batting_hand": "batter_hand",
    "shot": "shot_type",
    "bowling_type": "bowling_style",
    "bowling_kind": "bowling_style",
}


VALUE_SYNONYMS = {
    "phase": {
        "pp": "powerplay",
        "power play": "powerplay",
        "powerplay": "powerplay",
        "middle overs": "middle",
        "middle": "middle",
        "death overs": "death",
        "final overs": "death",
        "death": "death",
    },
    "field_zone": {
        "mid wicket": "midwicket",
        "mid-wicket": "midwicket",
        "midwicket": "midwicket",
        "cow corner": "midwicket",
        "third man": "third_man",
        "third-man": "third_man",
        "fine leg": "fine_leg",
        "fine-leg": "fine_leg",
        "square leg": "square_leg",
        "square-leg": "square_leg",
        "long on": "long_on",
        "long-on": "long_on",
        "long off": "long_off",
        "long-off": "long_off",
    },
    "length": {
        "yorker": "YORKER",
        "yorkers": "YORKER",
        "full": "FULL",
        "full ball": "FULL",
        "good length": "GOOD_LENGTH",
        "short of a good length": "SHORT_OF_A_GOOD_LENGTH",
        "short": "SHORT",
        "short ball": "SHORT",
        "full toss": "FULL_TOSS",
    },
    "batter_hand": {
        "left hand": "LHB",
        "left-hand": "LHB",
        "left-hander": "LHB",
        "left-handers": "LHB",
        "lhb": "LHB",
        "right hand": "RHB",
        "right-hand": "RHB",
        "right-hander": "RHB",
        "right-handers": "RHB",
        "rhb": "RHB",
    },
    "bowling_style": {
        "left arm spin": "left_arm_spin",
        "left-arm spin": "left_arm_spin",
        "left arm pace": "left_arm_pace",
        "left-arm pace": "left_arm_pace",
        "leg spin": "leg_spin",
        "leg-spin": "leg_spin",
        "legbreak": "leg_spin",
        "leg break": "leg_spin",
        "legbreak bowler": "leg_spin",
        "leg spinner": "leg_spin",
        "leg spinners": "leg_spin",
        "wrist spin": "wrist_spin",
        "finger spin": "finger_spin",
        "off spin": "off_spin",
        "off-spin": "off_spin",
        "off break": "off_spin",
        "off-break": "off_spin",
        "offbreak": "off_spin",
        "off spinner": "off_spin",
        "off spinners": "off_spin",
        "pace": "pace",
        "spin": "spin",
    },
}


METRIC_SYNONYMS = {
    "strike_rate": "batting_strike_rate",
    "sr": "batting_strike_rate",
    "fastest": "batting_strike_rate",
    "runs": "runs_scored",
    "wickets_taken": "wickets",
    "dot_percentage": "dot_ball_percentage",
    "bowler_dot_percentage": "bowler_dot_ball_percentage",
    "dots": "dot_ball_percentage",
    "boundaries": "boundary_percentage",
    "boundary_rate_per_100_balls": "boundary_percentage",
    "false_shots": "false_shot_percentage",
    "yorkers": "yorker_percentage",
    "control": "control_percentage",
}


BOWLING_STYLE_LIST_GROUPS = {
    frozenset({"left arm orthodox", "left arm unorthodox"}): "left_arm_spin",
    frozenset({"left arm pace", "right arm pace"}): "pace",
}

WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def requested_bowling_style(lowered_question: str) -> str | None:
    matches: list[str] = []
    for style, aliases in (
        ("left_arm_pace", ("left-arm pace", "left arm pace")),
        ("left_arm_spin", ("left-arm spin", "left arm spin")),
        ("off_spin", ("off spin", "off-spin", "off spinner", "off-break", "off break")),
        ("leg_spin", ("leg spin", "leg-spin", "leg spinner", "leg-break", "leg break")),
        ("wrist_spin", ("wrist spin", "wrist-spin")),
        ("finger_spin", ("finger spin", "finger-spin")),
        ("pace", ("against pace", "versus pace", "pace bowling")),
        ("spin", ("against spin", "versus spin", "spin bowling")),
    ):
        if any(alias in lowered_question for alias in aliases):
            matches.append(style)
    distinct = set(matches)
    specific = distinct - {"pace", "spin"}
    if specific:
        distinct = specific
    return next(iter(distinct)) if len(distinct) == 1 else None


def requested_metric_from_wording(lowered_question: str) -> str | None:
    if (
        re.search(r"\b(?:most|fewest)\s+yorkers\b", lowered_question)
        or "yorker count" in lowered_question
        or "how many yorkers" in lowered_question
    ):
        return "yorker_count"
    if "yorker percentage" in lowered_question or "percentage of yorkers" in lowered_question:
        return "yorker_percentage"
    if "false shots per over" in lowered_question or "false-shot per over" in lowered_question:
        return "false_shots_per_over"
    if "bowling strike rate" in lowered_question:
        return "bowling_strike_rate"
    if "economy" in lowered_question or "economical" in lowered_question:
        return "economy_rate"
    if "wicket count" in lowered_question or "how many wickets" in lowered_question:
        return "wickets_taken"
    if "dismissal count" in lowered_question or "how many dismissals" in lowered_question:
        return "dismissals"
    if "how many dot balls" in lowered_question or "dot ball count" in lowered_question:
        return (
            "bowler_dot_balls"
            if any(
                token in lowered_question
                for token in ("bowl", "bowler", "bowled", "bowls")
            )
            else "dot_balls"
        )
    return None


def requested_limit_from_wording(lowered_question: str) -> int | None:
    numeric = re.search(
        r"\b(?:top|bottom|first|last|show|list|give me|which)\s+(?:the\s+)?(\d{1,2})\b",
        lowered_question,
    )
    if numeric:
        return max(1, min(int(numeric.group(1)), 50))
    word_match = re.search(
        r"\b(?:top|bottom|first|last|show|list|give me|which)\s+(?:the\s+)?([a-z]+)\b",
        lowered_question,
    )
    if word_match and word_match.group(1) in WORD_NUMBERS:
        return WORD_NUMBERS[word_match.group(1)]
    nested_word_match = re.search(
        r"\b(?:show|list|give me)\s+(?:the\s+)?(?:top|bottom)\s+([a-z]+)\b",
        lowered_question,
    )
    if nested_word_match and nested_word_match.group(1) in WORD_NUMBERS:
        return WORD_NUMBERS[nested_word_match.group(1)]
    return None


def requested_minimum_sample(
    lowered_question: str,
    metric: str,
) -> MinimumSampleSpec | None:
    match = re.search(
        r"\b(?:minimum|min\.?|at least)\s+(\d{1,7})\s+"
        r"(legal balls?|balls?|deliver(?:y|ies)|innings?)\b",
        lowered_question,
    )
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("inning"):
        return MinimumSampleSpec(innings=value)
    if unit.startswith("legal ball") or (
        METRICS.get(metric) and METRICS[metric].denominator == "legal_balls"
    ):
        return MinimumSampleSpec(legal_balls=value)
    return MinimumSampleSpec(balls=value)


def is_passive_dismissal_question(lowered_question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:is|was|were|gets?|got|been)\b.{0,50}\bdismissed\b",
            lowered_question,
        )
    )


def requested_sort_direction(
    lowered_question: str,
    metric: str,
    entity: str,
    *,
    group_by: list[str] | None = None,
    filters: dict[str, object] | None = None,
) -> str | None:
    if any(token in lowered_question for token in ("highest", "biggest", "fastest")):
        return "desc"
    if any(token in lowered_question for token in ("lowest", "fewest", "smallest", "slowest")):
        return "asc"

    metric_definition = METRICS.get(metric)
    if metric_definition is None:
        return None
    good_direction = metric_definition.good_direction or metric_definition.default_sort
    if entity == "batter" and metric in {
        "batter_dot_ball_percentage",
        "dot_ball_percentage",
        "false_shot_percentage",
        "dismissal_rate",
    }:
        good_direction = "asc"
    elif entity == "bowler" and metric in {"boundary_percentage", "runs_conceded"}:
        good_direction = "asc"

    dimensions = set(group_by or [])
    plan_filters = filters or {}
    if (
        dimensions & {"line", "length", "bowling_style"}
        and "batter" in plan_filters
        and metric_definition.owner == "batter"
    ):
        good_direction = "asc" if good_direction == "desc" else "desc"

    if "worst" in lowered_question or re.search(r"\bbottom\s+(?:\d+|\w+)", lowered_question):
        return "asc" if good_direction == "desc" else "desc"
    if "best" in lowered_question or "top" in lowered_question:
        return good_direction
    if "most" in lowered_question:
        if "most economical" in lowered_question or "most effective" in lowered_question:
            return good_direction
        return "desc"
    if "least" in lowered_question:
        return "asc"
    return None


def normalize_plan(plan: CricketQueryPlan) -> CricketQueryPlan:
    group_by = [_normalize_dimension(item) for item in plan.group_by]
    filters = _normalize_filters(plan.filters)
    metric = METRIC_SYNONYMS.get(plan.metric, plan.metric)
    metric = canonical_metric_id(metric, entity=plan.entity, filters=filters)
    minimum_sample = plan.minimum_sample
    if metric in METRICS:
        minimum_sample = (minimum_sample or MinimumSampleSpec()).merged_with_defaults(
            METRICS[metric].minimum_sample.as_dict()
        )

    sort = plan.sort
    if sort is None and metric in METRICS:
        sort = SortSpec(by=metric, direction=METRICS[metric].default_sort)
    elif sort is not None:
        sort_by = METRIC_SYNONYMS.get(sort.by, sort.by)
        sort = SortSpec(by=canonical_metric_id(sort_by, entity=plan.entity, filters=filters), direction=sort.direction)

    limit = plan.limit if plan.limit and plan.limit > 0 else 10
    return plan.model_copy(
        update={
            "metric": metric,
            "group_by": group_by,
            "filters": filters,
            "minimum_sample": minimum_sample,
            "sort": sort,
            "limit": min(limit, 50),
        }
    )


def _normalize_dimension(value: str) -> str:
    return DIMENSION_SYNONYMS.get(value, value)


def _normalize_filters(filters: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for raw_key, raw_value in filters.items():
        key = FILTER_SYNONYMS.get(raw_key, raw_key)
        if isinstance(raw_value, str):
            normalized[key] = VALUE_SYNONYMS.get(key, {}).get(raw_value.lower(), raw_value)
        elif isinstance(raw_value, list):
            normalized_values = [
                VALUE_SYNONYMS.get(key, {}).get(item.lower(), item) if isinstance(item, str) else item
                for item in raw_value
            ]
            if key == "bowling_style":
                normalized[key] = _normalize_bowling_style_list(normalized_values)
            else:
                normalized[key] = normalized_values
        else:
            normalized[key] = raw_value
    return normalized


def _normalize_bowling_style_list(values: list[object]) -> object:
    if not all(isinstance(value, str) for value in values):
        return values
    style_phrases = frozenset(
        " ".join(value.lower().replace("-", " ").replace("_", " ").split())
        for value in values
        if isinstance(value, str)
    )
    return BOWLING_STYLE_LIST_GROUPS.get(style_phrases, values)
