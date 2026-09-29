"""Resolve and compile comparisons between two slices of the same subject."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, Mapping, cast

from backend.app.cricket_analytics.match_lighting import requested_lighting_values
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.schemas import (
    CricketQueryPlan,
    MinimumSampleSpec,
    SortSpec,
)

if TYPE_CHECKING:
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalCricketMeaning,
        CanonicalMeaningResolver,
        MeaningResolution,
    )

SplitDimension = Literal[
    "phase",
    "batter_hand",
    "bowling_style_group",
    "balls_faced_window",
    "over_range",
    "match_lighting",
]
Subject = Literal["batter", "bowler", "team"]
Role = Literal["batter", "bowler"]


def resolve_split(
    resolver: CanonicalMeaningResolver,
    question: str,
    state: Mapping[str, object] | None,
) -> MeaningResolution | None:
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalCricketMeaning,
        MeaningResolution,
        MeaningStatus,
        _explicit_sample,
        _extract_players,
        _metric_and_role,
        _normalized_text,
        _ranking_limit,
        _state_filters,
    )

    text = _normalized_text(question)
    players = _extract_players(question, resolver.available_players)
    if len(players) > 1:
        return None

    split = _split_dimension_and_values(text)
    if split is None:
        return None
    split_by, compare_values = split
    if not _has_split_intent(text, split_by, compare_values):
        return None

    player = players[0] if players else _state_player(state, resolver.available_players)
    subject = _explicit_subject(text)
    role_hint = resolver.player_roles.primary_role(player)
    metric, metric_role = _split_metric_and_role(text, player, role_hint, subject)
    if subject is None:
        subject = cast(Subject, metric_role) if metric_role else None
    if subject is None and player:
        subject = cast(Subject, role_hint) if role_hint else None
    if subject is None:
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Should this split rank batters, bowlers, or teams?",
            clarification_options=["Rank batters", "Rank bowlers", "Rank teams"],
            candidate_sources=["deterministic"],
        )
    if metric is None:
        metric, metric_role = _default_metric(subject)

    role: Role = "batter" if subject == "team" else cast(Role, subject)
    if metric_role and metric_role != role:
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification=(
                f"The requested statistic does not match the {subject} split. "
                "Which statistic should be compared?"
            ),
            candidate_sources=["deterministic"],
        )
    if player and not resolver.player_roles.supports(player, role):
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification=f"The available data does not show {player} participating as a {role}.",
            candidate_sources=["deterministic"],
        )

    split_direction = _split_direction(text)
    compare_values = _ordered_values(text, split_by, compare_values, split_direction)
    filters = _state_filters(state)
    filters.update(resolver._explicit_filters(question, text))
    filters.pop("batter", None)
    filters.pop("bowler", None)
    _remove_split_filter(filters, split_by)
    if split_by == "over_range":
        filters.pop("phase", None)
        if any(value.startswith("before_over_") for value in compare_values):
            filters["over_range"] = _over_range_from_values(compare_values)
    if player:
        filters[role] = player

    sample_text = text
    if split_by == "balls_faced_window":
        sample_text = re.sub(r"\bafter (?:facing )?20 balls?\b", "", sample_text)
    sample = _explicit_sample(sample_text, metric)
    sample_is_explicit = sample is not None
    if sample is None:
        defaults = _minimum_sample_defaults(metric, role, filters)
        sample = MinimumSampleSpec(**defaults) if defaults else None

    ranking = player is None
    return MeaningResolution(
        status=MeaningStatus.resolved,
        candidate_sources=["deterministic"],
        meaning=CanonicalCricketMeaning(
            family="split",
            role=role,
            subject=subject,
            metric=metric,
            filters=filters,
            group_by=[subject],
            split_by=split_by,
            compare_values=compare_values,
            split_intent="ranking" if ranking else "descriptive",
            split_direction=split_direction,
            limit=_ranking_limit(text) if ranking else 10,
            sort_direction=cast(
                Literal["asc", "desc"],
                _default_sort(metric, role, filters),
            ),
            minimum_sample=sample,
            minimum_sample_explicit=sample_is_explicit,
        ),
    )


def compile_split_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
    if (
        meaning.family != "split"
        or meaning.subject is None
        or meaning.split_by is None
        or len(meaning.compare_values) != 2
        or meaning.split_intent is None
        or meaning.split_direction is None
    ):
        raise ValueError(
            "Split compilation requires a subject, dimension, and two values."
        )
    return CricketQueryPlan(
        operation="split_compare",
        entity=meaning.subject,
        metric=meaning.metric,
        group_by=[meaning.subject],
        filters=meaning.filters,
        split_by=meaning.split_by,
        compare_values=meaning.compare_values,
        sort=SortSpec(by=meaning.metric, direction=meaning.sort_direction),
        limit=meaning.limit,
        minimum_sample=meaning.minimum_sample,
        minimum_sample_explicit=meaning.minimum_sample_explicit,
        question_subject=f"split_{meaning.split_intent}_{meaning.split_direction}",
        explanation_intent="canonical cricket meaning",
        confidence=1.0,
    )


def _split_dimension_and_values(text: str) -> tuple[SplitDimension, list[str]] | None:
    phases = _ordered_matches(
        text,
        {
            "powerplay": r"\b(?:power\s*play|opening[- ]ten|first[- ]ten|at the start)\b",
            "middle": r"\bmiddle(?:[- ]overs?| phase)?\b",
            "death": r"\b(?:death(?:[- ]overs?)?|final ten|final overs?|at the death)\b",
        },
    )
    if len(phases) == 2:
        return "phase", phases
    if len(phases) > 2:
        return None
    if re.search(r"\b(?:by phase|across phases|phase split)\b", text):
        return "phase", ["powerplay", "death"]

    # Registered match-lighting categories (stored ``daynight`` labels).
    lighting = requested_lighting_values(text)
    if len(lighting) == 2:
        return "match_lighting", lighting

    hands = _ordered_matches(
        text,
        {
            "LHB": r"\b(?:lhb|lefties|left[- ]hand(?:ed)?(?: batters?|ers?)?)\b",
            "RHB": r"\b(?:rhb|righties|right[- ]hand(?:ed)?(?: batters?|ers?)?)\b",
        },
    )
    if len(hands) >= 2:
        return "batter_hand", hands[:2]
    if re.search(r"\b(?:by batter hand|batter handedness|by handedness)\b", text):
        return "batter_hand", ["LHB", "RHB"]

    paired_spin = re.search(
        r"\b(wrist|finger)(?:[- ]spin)?\s+(?:and|versus|vs\.?|compared with)\s+"
        r"(wrist|finger)[- ]spin\b",
        text,
    )
    if paired_spin and paired_spin.group(1) != paired_spin.group(2):
        return "bowling_style_group", [
            f"{paired_spin.group(1)}_spin",
            f"{paired_spin.group(2)}_spin",
        ]
    styles = _ordered_matches(
        text,
        {
            "wrist_spin": r"\bwrist[- ]spin\b",
            "finger_spin": r"\bfinger[- ]spin\b",
            "pace": r"\bpace(?: bowling)?\b",
            "spin": r"(?<!wrist[- ])(?<!finger[- ])\bspin(?: bowling)?\b",
        },
    )
    if len(styles) >= 2:
        return "bowling_style_group", styles[:2]
    if re.search(r"\b(?:by spin type|spin[- ]type split)\b", text):
        return "bowling_style_group", ["wrist_spin", "finger_spin"]

    balls = re.search(r"\bafter (?:facing )?(20) balls?\b", text)
    if balls:
        return "balls_faced_window", ["after_20_balls", "first_20_balls"]

    explicit_ranges = [
        (int(match.group(1)), int(match.group(2)))
        for match in re.finditer(
            r"\bovers?\s*(\d{1,2})\s*(?:-|to|–|—)\s*(\d{1,2})\b",
            text,
        )
    ]
    if len(explicit_ranges) == 2 and all(
        1 <= start <= end <= 50 for start, end in explicit_ranges
    ):
        return "over_range", [
            f"overs_{start}_to_{end}" for start, end in explicit_ranges
        ]

    over_range = re.search(
        r"\bbetween overs?\s+(\d{1,2})\s+(?:and|to|-)\s+(\d{1,2})\b",
        text,
    ) or re.search(r"\bovers?\s+(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\b", text)
    if over_range:
        start, end = (int(over_range.group(1)), int(over_range.group(2)))
        if 1 <= start <= end <= 50 and re.search(
            rf"\bbefore (?:over )?{start}\b", text
        ):
            return "over_range", [f"overs_{start}_to_{end}", f"before_over_{start}"]
    return None


def _ordered_matches(text: str, patterns: Mapping[str, str]) -> list[str]:
    matches = [
        (match.start(), value)
        for value, pattern in patterns.items()
        if (match := re.search(pattern, text))
    ]
    return [value for _, value in sorted(matches)]


def _has_split_intent(
    text: str, split_by: SplitDimension, compare_values: list[str]
) -> bool:
    if re.search(r"^does\b.+\b(?:more|fewer|less)\b.+\bor\b", text):
        return False
    if len(compare_values) == 2 and re.search(
        r"\b(?:versus|vs\.?|compared|compare|difference|different|gap|or|"
        r"improv\w*|increas\w*|decreas\w*|accelerat\w*|chang\w*|"
        r"struggl\w*|dominat\w*|better|faster)\b",
        text,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:by phase|across phases|phase split|by batter hand|batter handedness|"
            r"by handedness|by spin type|spin[- ]type split)\b",
            text,
        )
        and re.search(r"\b(?:compare|change|difference|gap|rank|which|how)\b", text)
    )


def _explicit_subject(text: str) -> Subject | None:
    subject_text = re.sub(r"\b(?:left|right)[- ]hand(?:ed)? batters?\b", "", text)
    subject_text = re.sub(r"\bbatter (?:hand|handedness)\b", "", subject_text)
    subjects = [
        subject
        for subject, pattern in (
            ("team", r"\bteams?\b"),
            ("bowler", r"\bbowlers?\b"),
            ("batter", r"\b(?:batters?|batsm(?:a|e)n)\b"),
        )
        if re.search(pattern, subject_text)
    ]
    return cast(Subject, subjects[0]) if len(subjects) == 1 else None


def _split_metric_and_role(
    text: str,
    player: str | None,
    role_hint: str | None,
    subject: Subject | None,
) -> tuple[str | None, str | None]:
    from backend.app.cricket_analytics.canonical_meaning import _metric_and_role
    from backend.app.cricket_analytics.match_state_filters import (
        strip_match_state_phrases,
    )

    # "required run rate above 8" is a filter, never the run-rate metric.
    text = strip_match_state_phrases(text)
    if re.search(r"\brun[- ]rate\b", text) or (
        subject == "team" and re.search(r"\baccelerat", text)
    ):
        return "run_rate", "batter"
    return _metric_and_role(text, player, role_hint)


def _default_metric(subject: Subject) -> tuple[str, Role]:
    if subject == "bowler":
        return "economy_rate", "bowler"
    if subject == "team":
        return "run_rate", "batter"
    return "batting_strike_rate", "batter"


def _minimum_sample_defaults(
    metric: str, role: Role, filters: dict[str, object]
) -> dict[str, int]:
    if metric == "run_rate":
        return {"legal_balls": 24}
    return get_metric(metric, entity=role, filters=filters).minimum_sample.as_dict()


def _default_sort(
    metric: str, role: Role, filters: dict[str, object]
) -> Literal["asc", "desc"]:
    if metric == "run_rate":
        return "desc"
    return cast(
        Literal["asc", "desc"],
        get_metric(metric, entity=role, filters=filters).default_sort,
    )


def _split_direction(text: str) -> Literal["absolute", "increase", "decrease"]:
    if re.search(r"\b(?:increase|improve|accelerat|rise|gain)", text):
        return "increase"
    if re.search(r"\b(?:decrease|decline|drop|fall|slow)", text):
        return "decrease"
    return "absolute"


def _ordered_values(
    text: str,
    split_by: SplitDimension,
    values: list[str],
    direction: Literal["absolute", "increase", "decrease"],
) -> list[str]:
    if split_by == "balls_faced_window":
        return ["after_20_balls", "first_20_balls"]
    if direction in {"increase", "decrease"} and re.search(r"\bfrom\b.+\bto\b", text):
        return list(reversed(values))
    return values


def _remove_split_filter(filters: dict[str, object], split_by: SplitDimension) -> None:
    key = {
        "phase": "phase",
        "batter_hand": "batter_hand",
        "bowling_style_group": "bowling_style",
        "balls_faced_window": "balls_faced_window",
        "over_range": "over_range",
        "match_lighting": "match_lighting",
    }[split_by]
    filters.pop(key, None)


def _over_range_from_values(values: list[str]) -> list[int]:
    match = re.match(r"overs_(\d+)_to_(\d+)", values[0])
    if not match:
        raise ValueError("Canonical over-range split values are invalid.")
    return [int(match.group(1)), int(match.group(2))]


def _state_player(
    state: Mapping[str, object] | None, available_players: list[str]
) -> str | None:
    players = state.get("players") if state else None
    if isinstance(players, list) and len(players) == 1:
        player = players[0]
        if isinstance(player, str) and player in available_players:
            return player
    return None
