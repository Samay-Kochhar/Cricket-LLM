"""Resolve and compile same-role player comparisons."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, Mapping, cast

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec

if TYPE_CHECKING:
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalCricketMeaning,
        CanonicalMeaningResolver,
        MeaningResolution,
    )

Role = Literal["batter", "bowler"]

BATTER_CORE = [
    "batting_strike_rate",
    "runs_scored",
    "batting_average",
    "batter_dot_ball_percentage",
    "boundary_percentage",
]
BOWLER_CORE = [
    "economy_rate",
    "wickets_taken",
    "bowling_strike_rate",
    "bowler_dot_ball_percentage",
]
BATTER_TACTICAL_CORE = [
    "batting_strike_rate",
    "runs_scored",
    "boundary_percentage",
]
BOWLER_TACTICAL_CORE = [
    "economy_rate",
    "wickets_taken",
    "bowler_dot_ball_percentage",
]


def resolve_comparison(
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
        _normalized_text,
        _state_filters,
    )

    text = _normalized_text(question)
    players = _extract_players(question, resolver.available_players)
    if not players and state and state.get("operation") == "player_compare":
        state_players = state.get("players")
        if isinstance(state_players, list):
            players = [
                player
                for player in state_players
                if isinstance(player, str) and player in resolver.available_players
            ]
    players = sorted(players)
    comparison_wording = _is_comparison_wording(text)
    if (
        not comparison_wording
        and len(players) >= 2
        and re.search(r"\b(?:v\.?|vs\.?|versus)\b", text)
    ):
        role_context = bool(
            re.search(
                r"\b(?:as batters?|as bowlers?|batting|bowling|records?|metrics?|economy|wickets?|strike rate|average|boundar(?:y|ies)|dot rate|runs?)\b",
                text,
            )
        )
        opposing_role_nouns = bool(
            re.search(r"\bbatter\b", text) and re.search(r"\bbowler\b", text)
        )
        comparison_wording = bool(
            role_context
            and not opposing_role_nouns
            and not re.search(r"\b(?:head.to.head|matchup|run tally)\b", text)
            and (
                _shared_primary_role(resolver, players) is not None
                or re.search(r"\bas (?:batters?|bowlers?)\b", text)
            )
        )
    if not comparison_wording:
        return None

    def unclear(message: str, options: list[str] | None = None) -> MeaningResolution:
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification=message,
            clarification_options=options or [],
            candidate_sources=["deterministic"],
        )

    if len(players) < 2:
        if re.search(
            r"\b(?:powerplay|opening ten)\b.*\b(?:middle|death)\b|\b(?:powerplay|opening ten)\s+(?:v\.?|vs\.?|versus)\s+death\b",
            text,
        ) or (
            re.search(r"\b(?:left|lefties|lhb)\b", text)
            and re.search(r"\b(?:right|righties|rhb)\b", text)
        ):
            return None
        return unclear("Which second player should be included in this comparison?")

    filters = {
        key: value
        for key, value in _state_filters(state).items()
        if key not in {"batter", "bowler", "compare_players", "comparison_metrics"}
    }
    filters.update(resolver._explicit_filters(question, text))
    if (
        "phase-wise" in text
        or "phase wise" in text
        or all(phase in text for phase in ("powerplay", "middle", "death"))
    ):
        filters["comparison_view"] = "phase"
        filters.pop("phase", None)
    elif re.search(r"\b(?:team[- ]wise|by opposition)\b", text):
        filters["comparison_view"] = "opposition"
    if "bowling_style" not in filters:
        style = re.search(r"\b(pace|spin) bowlers?\b|\bbowling (pace|spin)\b", text)
        if style:
            filters["bowling_style"] = style.group(1) or style.group(2)
    explicit_role = _explicit_role(text)
    explicit_metrics = _explicit_metrics(text, explicit_role)
    metric_roles = {
        cast(Role, get_metric(metric).owner)
        for metric in explicit_metrics
        if get_metric(metric).owner in {"batter", "bowler"}
    }
    if len(metric_roles) > 1:
        return unclear(
            "Should these players be compared as batters or as bowlers?",
            ["Compare their batting", "Compare their bowling"],
        )
    metric_role = next(iter(metric_roles), None)
    if explicit_role and metric_role and explicit_role != metric_role:
        return unclear(
            "The requested role and statistics disagree. Compare batting or bowling statistics?",
            ["Compare their batting", "Compare their bowling"],
        )
    shared_primary = _shared_primary_role(resolver, players)
    if (
        explicit_role is None
        and shared_primary is None
        and resolver.player_roles.participation
    ):
        options = []
        if all(resolver.player_roles.supports(player, "batter") for player in players):
            options.append("Compare their batting")
        if all(resolver.player_roles.supports(player, "bowler") for player in players):
            options.append("Compare their bowling")
        options.append("Treat it as a batter-bowler matchup")
        return unclear(
            "Should these players be compared as batters, as bowlers, or as a matchup?",
            options,
        )
    role = explicit_role or metric_role or shared_primary
    if role is None:
        options = []
        if all(resolver.player_roles.supports(player, "batter") for player in players):
            options.append("Compare their batting")
        if all(resolver.player_roles.supports(player, "bowler") for player in players):
            options.append("Compare their bowling")
        if len(players) == 2:
            options.append("Treat it as a batter-bowler matchup")
        return unclear(
            "Should these players be compared as batters, as bowlers, or as a matchup?",
            options,
        )
    if not all(resolver.player_roles.supports(player, role) for player in players):
        return unclear(
            f"The available data does not show every named player participating as a {role}."
        )
    explicit_metrics = _explicit_metrics(text, role)
    if role == "bowler" and "bowling_style" not in filters:
        shared_kind = resolver.player_roles.shared_bowling_kind(players)
        if shared_kind == "spin":
            filters["bowling_style"] = shared_kind

    metrics = explicit_metrics or _default_metrics(role, filters, text)
    if any(
        get_metric(metric).owner not in {role, "batter_or_bowler"} for metric in metrics
    ):
        return unclear(f"Choose statistics that belong to the shared {role} role.")
    primary = metrics[0]
    sample = _explicit_sample(text, primary)
    filters["compare_players"] = players
    filters["comparison_metrics"] = metrics
    return MeaningResolution(
        status=MeaningStatus.resolved,
        candidate_sources=["deterministic"],
        meaning=CanonicalCricketMeaning(
            family="comparison",
            role=role,
            metric=primary,
            filters=filters,
            group_by=[role],
            limit=len(players),
            sort_direction=cast("LiteralDirection", get_metric(primary).default_sort),
            minimum_sample=sample,
            minimum_sample_explicit=sample is not None,
            participants=players,
            comparison_metrics=metrics,
        ),
    )


LiteralDirection = Literal["asc", "desc"]


def _is_comparison_wording(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:compare|compared|comparison|contrast|side[- ]by[- ]side)\b", text
        )
        or re.search(
            r"\bwho\s+(?:scores?|has|takes?|bowls?)\b.*\b(?:better|faster|more|less)\b",
            text,
        )
        or re.search(r"\b(?:better|faster)\b.*\b(?:or|between)\b", text)
    )


def _explicit_role(text: str) -> Role | None:
    facing = bool(
        re.search(r"\b(?:facing|against)\s+(?:pace|spin)(?: bowling)?\b", text)
    )
    batting = (
        bool(
            re.search(
                r"\b(?:as batters?|batting|scores?|run scoring|with the bat)\b", text
            )
        )
        or facing
    )
    bowling = bool(
        re.search(r"\b(?:as bowlers?|bowling|with the ball)\b", text)
    ) and not (facing and not re.search(r"\bas bowlers?\b", text))
    if batting == bowling:
        return None
    return "batter" if batting else "bowler"


def _explicit_metrics(text: str, role: Role | None) -> list[str]:
    found: list[tuple[int, str]] = []

    def add(metric: str, *patterns: str) -> None:
        positions = [
            match.start() for pattern in patterns if (match := re.search(pattern, text))
        ]
        if positions:
            found.append((min(positions), metric))

    add("bowling_strike_rate", r"\bbowling strike rate\b")
    add(
        "batting_strike_rate",
        r"\bbatting strike rate\b",
        r"(?<!bowling )\bstrike rate\b",
        r"\bscores? faster\b",
    )
    add("bowling_average", r"\bbowling average\b")
    add("batting_average", r"\bbatting average\b")
    add("economy_rate", r"\beconom(?:y|ical)\b")
    add("wickets_per_over", r"\bwickets? per over\b", r"\bwicket rate\b")
    add("wickets_taken", r"\bwickets? taken\b", r"\btotal wickets?\b")
    if role is not None:
        add(
            (
                "bowler_dot_ball_percentage"
                if role == "bowler"
                else "batter_dot_ball_percentage"
            ),
            r"\bdot[- ]ball percentage\b",
            r"\bdot percentage\b",
            r"\bdot rate\b",
        )
    add("boundary_percentage", r"\bboundar(?:y|ies)(?: percentage| rate)?\b")
    add("runs_scored", r"\b(?:total |most )?runs(?: scored)?\b", r"\brun count\b")
    ordered = [metric for _, metric in sorted(found)]
    if "wickets_per_over" in ordered:
        ordered.remove("wickets_per_over")
        ordered.insert(0, "wickets_per_over")
    return list(dict.fromkeys(ordered))


def _shared_primary_role(
    resolver: CanonicalMeaningResolver, players: list[str]
) -> Role | None:
    roles = {resolver.player_roles.primary_role(player) for player in players}
    known = roles - {None}
    if len(known) != 1:
        return None
    role = cast(Role, next(iter(known)))
    return (
        role
        if all(resolver.player_roles.supports(player, role) for player in players)
        else None
    )


def _default_metrics(role: Role, filters: Mapping[str, object], text: str) -> list[str]:
    if role == "batter":
        tactical = filters.get("phase") == "powerplay" or "bowling_style" in filters
        metrics = list(BATTER_TACTICAL_CORE if tactical else BATTER_CORE)
        volume_first = (
            filters.get("phase") == "powerplay"
            or filters.get("bowling_style") == "pace"
            or bool(
                re.search(
                    r"\b(?:as (?:odi )?batters?|batting (?:records?|numbers?|metrics?))\b",
                    text,
                )
            )
        )
        if volume_first:
            metrics.remove("runs_scored")
            metrics.insert(0, "runs_scored")
        return metrics
    tactical = "phase" in filters or "bowling_style" in filters
    metrics = list(BOWLER_TACTICAL_CORE if tactical else BOWLER_CORE)
    wickets_first = (
        filters.get("phase") == "powerplay"
        or filters.get("bowling_style") == "spin"
        or bool(
            re.search(r"\b(?:as (?:odi |spin )?bowlers?|main bowling metrics)\b", text)
        )
    )
    if wickets_first:
        metrics.remove("wickets_taken")
        metrics.insert(0, "wickets_taken")
    return metrics


def compile_comparison_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
    if (
        meaning.family != "comparison"
        or len(meaning.participants) < 2
        or not meaning.comparison_metrics
    ):
        raise ValueError(
            "Comparison compilation requires players and compatible metrics."
        )
    filters = dict(meaning.filters)
    filters["compare_players"] = list(meaning.participants)
    filters["comparison_metrics"] = list(meaning.comparison_metrics)
    return CricketQueryPlan(
        operation="player_compare",
        entity=meaning.role,
        metric=meaning.metric,
        group_by=[meaning.role],
        filters=filters,
        sort=SortSpec(by=meaning.metric, direction=meaning.sort_direction),
        limit=meaning.limit,
        minimum_sample=meaning.minimum_sample,
        minimum_sample_explicit=meaning.minimum_sample_explicit,
        question_subject="comparison",
        explanation_intent="canonical cricket meaning",
        confidence=1.0,
    )
