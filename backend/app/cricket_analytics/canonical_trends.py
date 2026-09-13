"""Canonical annual time series: subject, statistic, scope and sample per year."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Mapping, cast, Literal

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


def has_annual_meaning(text: str) -> bool:
    period = r"(?:year|season)"
    return bool(
        re.search(
            rf"\b(?:annual(?:ly)?|yearly|trend|over time|{period}[- ](?:by|over|to)[- ]{period}|{period}[- ]wise|(?:by|each|every|per) {period})\b",
            text,
        )
        or (
            re.search(
                r"\b(?:chang\w*|mov\w*|improv\w*|declin\w*|increas\w*|decreas\w*|become|became|evolv\w*)\b",
                text,
            )
            and re.search(r"\b(?:since|after|from)\s+(?:19|20)\d{2}\b", text)
        )
    )


def resolve_trend(
    resolver: CanonicalMeaningResolver,
    question: str,
    state: Mapping[str, object] | None,
) -> MeaningResolution | None:
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalCricketMeaning,
        MeaningResolution,
        MeaningStatus,
        _normalized_text,
        _extract_players,
        _metric_and_role,
        _explicit_sample,
        _state_filters,
    )

    text = _normalized_text(question)
    if not has_annual_meaning(text):
        return None
    players = _extract_players(question, resolver.available_players)
    if len(players) != 1:
        return None  # Multi-subject comparisons keep their own compiler.
    player = players[0]
    if (
        "strike rate" in text
        and "batting strike rate" not in text
        and "bowling strike rate" not in text
        and resolver.player_roles.primary_role(player) == "bowler"
    ):
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Do you mean batting strike rate or bowling strike rate?",
            clarification_options=["batting strike rate", "bowling strike rate"],
        )
    metric, role = _metric_and_role(
        text, player, resolver.player_roles.primary_role(player)
    )
    if metric is None and "destructive" in text:
        metric, role = "batting_strike_rate", "batter"
    if metric is None or role not in {"batter", "bowler"}:
        return None
    if not resolver.player_roles.supports(
        player, cast(Literal["batter", "bowler"], role)
    ):
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification=f"The available data does not show {player} participating as a {role}.",
        )
    filters = _state_filters(state)
    explicit = resolver._explicit_filters(question, text)
    if "years" in explicit:
        filters.pop("year_mode", None)
    filters.update(explicit)
    filters.pop("batter", None)
    filters.pop("bowler", None)
    filters[role] = player
    sample = _explicit_sample(text, metric)
    sample_explicit = sample is not None
    if sample is None:
        defaults = get_metric(
            metric, entity=role, filters=filters
        ).minimum_sample.as_dict()
        sample = MinimumSampleSpec(**defaults) if defaults else None
    return MeaningResolution(
        status=MeaningStatus.resolved,
        candidate_sources=["deterministic"],
        meaning=CanonicalCricketMeaning(
            family="trend",
            subject=cast(Literal["batter", "bowler"], role),
            role=cast(Literal["batter", "bowler"], role),
            metric=metric,
            filters=filters,
            group_by=["year"],
            sort_direction="asc",
            limit=None,
            minimum_sample=sample,
            minimum_sample_explicit=sample_explicit,
        ),
    )


def compile_trend_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
    if meaning.family != "trend":
        raise ValueError("Annual compilation requires a trend meaning.")
    return CricketQueryPlan(
        operation="aggregate",
        entity=meaning.role,
        metric=meaning.metric,
        filters=meaning.filters,
        group_by=["year"],
        sort=SortSpec(by="year", direction="asc"),
        limit=None,
        minimum_sample=meaning.minimum_sample,
        minimum_sample_explicit=meaning.minimum_sample_explicit,
        question_subject="yearly_trend",
        explanation_intent="canonical cricket meaning",
        confidence=1.0,
    )
