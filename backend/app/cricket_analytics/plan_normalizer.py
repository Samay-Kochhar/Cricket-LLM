from __future__ import annotations

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
    "false_shots": "false_shot_percentage",
    "yorkers": "yorker_percentage",
    "control": "control_percentage",
}


BOWLING_STYLE_LIST_GROUPS = {
    frozenset({"left arm orthodox", "left arm unorthodox"}): "left_arm_spin",
    frozenset({"left arm pace", "right arm pace"}): "pace",
}


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
