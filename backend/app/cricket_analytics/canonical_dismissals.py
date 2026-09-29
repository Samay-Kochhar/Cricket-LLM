"""Canonical meaning for one batter's dismissals by recorded dismissal type."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, cast

from backend.app.cricket_analytics.dismissal_types import requested_dismissal_types
from backend.app.cricket_analytics.plan_normalizer import (
    requested_limit_from_wording,
    requested_sort_direction,
)
from backend.app.cricket_analytics.query_builders.dismissal_type_builder import (
    DISMISSAL_TYPE_FILTERS,
)

if TYPE_CHECKING:
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalMeaningResolver,
        MeaningResolution,
    )


DISMISSAL_TYPE_GROUP_BY = ["dismissal_type"]
# Marks every outcome of the registered dismissal-type path, including targeted
# clarifications and limitations, so the planner answers them itself instead of
# falling through to the legacy planner.
DISMISSAL_TYPE_SOURCE = "registered_dismissal_type"


def resolve_dismissal_types(
    resolver: CanonicalMeaningResolver,
    question: str,
    state: Mapping[str, object] | None,
) -> MeaningResolution | None:
    """Claim explicit dismissal-type wording before comparison/matchup routing.

    The named player is always the dismissed batter, whatever the voice of the
    sentence. Every requested category, filter or unsupported qualifier is
    either compiled or returned as a targeted limitation.
    """
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalCricketMeaning,
        MeaningResolution,
        MeaningStatus,
        _extract_players,
        _normalized_text,
        _player_aliases,
        _state_filters,
    )

    request = requested_dismissal_types(question)
    if request is None or request.fielding_perspective:
        # Fielding wording (catches, run outs effected) keeps the existing
        # data-limitation policy: fielders are not recorded.
        return None
    lowered = _normalized_text(question)

    def limitation(reason: str, *, data: bool = False) -> MeaningResolution:
        return MeaningResolution(
            status=MeaningStatus.data_limitation if data else MeaningStatus.unsupported,
            reason=reason,
            candidate_sources=["deterministic", DISMISSAL_TYPE_SOURCE],
        )

    if request.unrecorded_reason:
        return limitation(request.unrecorded_reason, data=True)

    players = _extract_players(question, resolver.available_players)
    bowler: str | None = None
    if len(players) == 2:
        aliases = _player_aliases(resolver.available_players)
        after_by = [
            player
            for player in players
            if any(
                canonical == player
                and re.search(
                    rf"\b(?:by|off|to|against|from)\s+(?:the\s+)?{re.escape(alias)}(?:'s)?(?!\w)",
                    lowered,
                )
                for alias, canonical in aliases.items()
            )
        ]
        if len(after_by) != 1:
            return MeaningResolution(
                status=MeaningStatus.clarification,
                clarification="Which named player was the dismissed batter, and which was the bowler?",
                candidate_sources=["deterministic", DISMISSAL_TYPE_SOURCE],
            )
        bowler = after_by[0]
        players = [player for player in players if player != bowler]
    if len(players) != 1:
        if not players:
            return limitation(
                "Dismissal types are answered for one named dismissed batter. "
                "Rankings or totals of all batters by dismissal type are not yet supported."
            )
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Which one batter's dismissals should be broken down by dismissal type?",
            clarification_options=players,
            candidate_sources=["deterministic", DISMISSAL_TYPE_SOURCE],
        )
    if request.single_match:
        return limitation(
            "Dismissal types are counted across the database scope; a single match or "
            "tournament stage is not a supported dismissal-type filter."
        )
    if request.ratio:
        return limitation(
            "A ratio between dismissal types is not a registered metric. Ask for the "
            "dismissal counts or for each type's percentage share of dismissals."
        )
    if request.other_metric:
        return limitation(
            "Only dismissal counts and dismissal shares are registered by dismissal type; "
            "other statistics by dismissal type are not supported."
        )

    if re.search(
        r"\b(?:chases?|chased|successful(?:ly)?|won|wins?|winning|lost|losing|defeats?)\b",
        lowered,
    ):
        # Chase-outcome and match-result conditions are not registered filters
        # yet ("chasing" alone is the registered second-innings filter).
        return limitation(
            "Match-result and chase-outcome conditions are not yet supported filters "
            "for dismissal types; 'chasing' (second innings) and 'batting first' are."
        )
    filters = _state_filters(state)
    filters.update(resolver._explicit_filters(question, lowered))
    filters.pop("batter", None)
    filters.pop("bowler", None)
    unsupported = sorted(key for key in filters if key not in DISMISSAL_TYPE_FILTERS)
    if unsupported:
        label = ", ".join(key.replace("_", " ") for key in unsupported)
        return limitation(
            f"Dismissal types are attributed to the dismissed batter; the {label} "
            "filter describes the striker's delivery and is not supported for dismissal types."
        )
    filters["batter"] = players[0]
    if bowler:
        filters["bowler"] = bowler
    if request.categories:
        filters["dismissal_type"] = list(request.categories)
    metric = "dismissal_type_percentage" if request.share else "dismissals"
    direction = (
        requested_sort_direction(
            lowered,
            metric,
            "batter",
            group_by=DISMISSAL_TYPE_GROUP_BY,
            filters=filters,
        )
        or "desc"
    )
    return MeaningResolution(
        status=MeaningStatus.resolved,
        meaning=CanonicalCricketMeaning(
            family="breakdown",
            role="batter",
            metric=metric,
            filters=filters,
            group_by=list(DISMISSAL_TYPE_GROUP_BY),
            limit=requested_limit_from_wording(lowered),
            sort_direction=cast(Literal["asc", "desc"], direction),
            minimum_sample=None,
            minimum_sample_explicit=False,
        ),
        candidate_sources=["deterministic", DISMISSAL_TYPE_SOURCE],
    )


def is_dismissal_type_meaning(group_by: list[str]) -> bool:
    return "dismissal_type" in group_by
