"""Post-interpretation policy for ambiguity, capability, data, and safeguards."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from backend.app.cricket_analytics.canonical_meaning import (
    MeaningResolution,
    MeaningStatus,
    _extract_players,
)
from backend.app.cricket_analytics.dismissal_types import requested_dismissal_types
from backend.app.cricket_analytics.player_roles import PlayerRoleResolver


POLICY_SOURCE = "response_policy"
TEAM_ANALYSIS_UNSUPPORTED = (
    "Team analysis questions need explicit tested team semantics that are not yet supported."
)


def apply_response_policy(
    question: str,
    resolution: MeaningResolution,
    *,
    available_players: Sequence[str],
    player_roles: PlayerRoleResolver,
    conversation_state: Mapping[str, object] | BaseModel | None = None,
) -> MeaningResolution:
    """Classify a resolved candidate without changing its metric or operation."""
    text = _normalized(question)

    capability = _capability_outcome(text)
    if capability is not None:
        status, reason = capability
        return MeaningResolution(
            status=status,
            reason=reason,
            candidate_sources=[POLICY_SOURCE],
        )

    surname_options = (
        _ambiguous_surname_options(text, available_players)
        if _is_vague_player_request(text)
        else []
    )
    if surname_options:
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Which player do you mean?",
            clarification_options=surname_options,
            candidate_sources=[POLICY_SOURCE],
        )

    if _is_vague_metric_request(text):
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Which metric should define the ranking?",
            clarification_options=[
                "Runs scored",
                "Batting strike rate",
                "Wickets taken",
                "Economy rate",
            ],
            candidate_sources=[POLICY_SOURCE],
        )

    if resolution.status != MeaningStatus.resolved and _ambiguous_strike_rate(
        text,
        available_players=available_players,
        player_roles=player_roles,
        conversation_state=conversation_state,
    ):
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Do you mean batting strike rate or bowling strike rate?",
            clarification_options=["Batting strike rate", "Bowling strike rate"],
            candidate_sources=[POLICY_SOURCE],
        )

    return resolution


def capability_outcome(question: str) -> tuple[MeaningStatus, str] | None:
    """Return the policy outcome that takes precedence over any executable family."""
    return _capability_outcome(_normalized(question))


def _capability_outcome(
    text: str,
) -> tuple[MeaningStatus, str] | None:
    if re.search(
        r"\b(?:catches|catcher|fielding|captain(?:ed|cy|s)?)\b", text
    ) or (
        re.search(r"\brun[- ]outs?\b", text) and not _is_batter_run_out_dismissal(text)
    ):
        return (
            MeaningStatus.data_limitation,
            "Fielding catcher records are missing, and the ODI delivery data does not contain captaincy facts.",
        )
    if re.search(r"\b(?:weather|rain|humid(?:ity)?|forecast)\b", text):
        return (
            MeaningStatus.unsupported,
            "Weather is not available as a filter in the historical ODI analytics capability.",
        )
    if re.search(r"\b(?:salary|salaries|wages?|million dollars?)\b", text):
        return (
            MeaningStatus.unsupported,
            "Salary data is outside the historical ODI analytics capability.",
        )
    if re.search(
        r"\b(?:predict(?:ion)?|will win|next world cup champion|next odi)\b", text
    ):
        return (
            MeaningStatus.unsupported,
            "Future match prediction is outside the historical ODI analytics capability.",
        )
    if (
        re.search(r"\b(?:teams?|national sides?)\b", text)
        and re.search(
            r"\b(?:rank|best|worst|highest|lowest|economy|strike rate|average|analysis)\b",
            text,
        )
        and not re.search(
            r"\b(?:compare|gap|between|across|by phase|after losing|recovers?)\b",
            text,
        )
    ):
        return (MeaningStatus.unsupported, TEAM_ANALYSIS_UNSUPPORTED)
    return None


def _is_batter_run_out_dismissal(text: str) -> bool:
    """"Was Kohli run out" is a recorded batter dismissal type, not fielding."""
    request = requested_dismissal_types(text)
    return bool(
        request is not None
        and not request.fielding_perspective
        and "run out" in request.categories
    )


def _is_vague_metric_request(text: str) -> bool:
    return bool(
        re.search(r"\b(?:best|strongest|top)\s+(?:numbers|statistics?|stats)\b", text)
        and not re.search(
            r"\b(?:runs?|strike rate|average|wickets?|economy|dot balls?|boundar(?:y|ies))\b",
            text,
        )
    )


def _is_vague_player_request(text: str) -> bool:
    return bool(
        re.search(r"\b(?:good|record|numbers|performed|performance)\b", text)
        and not re.search(r"\b(?:against|off|versus|vs\.?|compare)\b", text)
        and not re.search(
            r"\b(?:runs?|strike rate|average|wickets?|economy|dot balls?|boundar(?:y|ies)|dismissed|line|length|style)\b",
            text,
        )
    )


def _ambiguous_surname_options(
    text: str, available_players: Sequence[str]
) -> list[str]:
    normalized_players = [(player, _normalized(player)) for player in available_players]
    for raw_token in re.findall(r"\b[a-z][a-z'-]{2,}\b", text):
        token = raw_token.removesuffix("'s")
        matches = [
            player
            for player, normalized in normalized_players
            if normalized.split()[-1] == token
        ]
        if len(matches) < 2:
            continue
        if any(
            normalized in text
            for player, normalized in normalized_players
            if player in matches
        ):
            continue
        return sorted(matches)
    return []


def _ambiguous_strike_rate(
    text: str,
    *,
    available_players: Sequence[str],
    player_roles: PlayerRoleResolver,
    conversation_state: Mapping[str, object] | BaseModel | None,
) -> bool:
    if not re.search(r"\b(?:strike rate|sr)\b", text):
        return False
    if re.search(r"\b(?:batting|batter|as a batter|faced)\b", text):
        return False
    if re.search(r"\b(?:bowling|bowler|as a bowler|bowled)\b", text):
        return False
    state = (
        conversation_state.model_dump(mode="python")
        if isinstance(conversation_state, BaseModel)
        else conversation_state
    )
    canonical = state.get("canonical_meaning") if state else None
    if isinstance(canonical, Mapping):
        meaning = canonical.get("meaning")
        if isinstance(meaning, Mapping) and meaning.get("role") in {"batter", "bowler"}:
            return False
    players = _extract_players(text, available_players)
    if len(players) != 1:
        return False
    player = players[0]
    if player_roles.primary_role(player) == "batter":
        return False
    return player_roles.supports(player, "batter") and player_roles.supports(
        player, "bowler"
    )


def _normalized(value: str) -> str:
    return " ".join(
        value.lower()
        .replace("’", "'")
        .replace("–", "-")
        .replace("strike-rate", "strike rate")
        .split()
    )
