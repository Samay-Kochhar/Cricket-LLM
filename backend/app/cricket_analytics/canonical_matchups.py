"""Resolve matchup relationships, then compile named values or opponent rankings."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, Mapping, cast

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.plan_normalizer import (
    requested_bowling_style,
    requested_sort_direction,
)
from backend.app.cricket_analytics.player_roles import Role
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


def resolve_matchup(
    resolver: CanonicalMeaningResolver,
    question: str,
    state: Mapping[str, object] | None,
) -> MeaningResolution | None:
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalCricketMeaning,
        MeaningResolution,
        MeaningStatus,
        _extract_players,
        _normalized_text,
        _explicit_sample,
        _ranking_limit,
        _state_filters,
    )

    text = _normalized_text(question)
    players = _extract_players(question, resolver.available_players)
    if re.search(r"\bcompar(?:e|ed|ison)\b", text):
        return None
    ranked_role: Role | None = None
    if re.search(
        r"\b(?:which|rank|top|best|worst)\s+(?:(?:the|opposing|pace|spin|five|ten|\d+)\s+)*bowlers?\b(?!\s+(?:types?|styles?|categories)\b)",
        text,
    ) or re.search(
        r"\b(?:dismissor|dismissers?|toughest bowler|who (?:dismisses|has dismissed|controls|gets))\b",
        text,
    ):
        ranked_role = "bowler"
    elif re.search(
        r"\b(?:which|rank|top|best|worst)\s+(?:(?:the|opposing|five|ten|\d+)\s+)*batters?\b",
        text,
    ) or re.search(r"\bwho (?:finds boundaries|scores|succeeds)\b", text):
        ranked_role = "batter"

    relation = bool(
        re.search(
            r"\b(?:v\.?|vs\.?|versus|against|off|from|facing|faces|face|bowling to|bowls to|dismissed by|head.to.head|matchup)\b",
            text,
        )
    )
    inherited = _state_filters(state)
    inherited_pair = (
        not players
        and state
        and state.get("operation") == "matchup"
        and all(isinstance(inherited.get(role), str) for role in ("batter", "bowler"))
    )
    named = len(players) == 2 and relation
    ranking = len(players) == 1 and ranked_role is not None
    if not named and not ranking and not inherited_pair:
        return None

    def unclear(message: str, options: list[str] | None = None) -> MeaningResolution:
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification=message,
            clarification_options=options or [],
            candidate_sources=["deterministic"],
        )

    filters = {
        k: v
        for k, v in inherited.items()
        if k not in {"batter", "bowler", "compare_players"}
    }
    filters.update(resolver._explicit_filters(question, text))
    style = requested_bowling_style(text)
    if style is None:
        style_match = re.search(r"\b(pace|spin) bowlers?\b", text)
        style = style_match.group(1) if style_match else None
    if style:
        filters["bowling_style"] = style

    if named:
        masked = _mask_players(text, players, resolver)
        pair = _explicit_pair(masked, players)
        if pair is None:
            primary = [resolver.player_roles.primary_role(player) for player in players]
            if (
                primary[0] is not None
                and primary[0] == primary[1]
                and not re.search(r"\b(?:matchup|head.to.head)\b", text)
            ):
                return None
            pair = resolver.player_roles.default_pair(*players)
        if pair is None:
            return unclear(
                "Who is batting and who is bowling in this matchup?",
                [
                    f"{players[0]} batting against {players[1]}",
                    f"{players[1]} batting against {players[0]}",
                ],
            )
        batter, bowler = pair
        if not resolver.player_roles.supports(
            batter, "batter"
        ) or not resolver.player_roles.supports(bowler, "bowler"):
            return unclear(
                "That batting/bowling direction is not present in the available player data."
            )
        filters.update(batter=batter, bowler=bowler)
    elif inherited_pair:
        filters.update({role: inherited[role] for role in ("batter", "bowler")})
    else:
        subject_role: Role = "batter" if ranked_role == "bowler" else "bowler"
        if not resolver.player_roles.supports(players[0], subject_role):
            return unclear(
                f"The data does not show {players[0]} participating as a {subject_role}."
            )
        filters[subject_role] = players[0]

    role: Role = ranked_role or (
        "bowler"
        if re.search(
            r"\b(?:bowling strike rate|bowling average|economy|runs conceded|bowler dot|bowled|wickets)\b",
            text,
        )
        else "batter"
    )
    metric = _matchup_metric(text, role)
    if metric is None:
        return unclear(
            "Which matchup statistic do you mean: runs, strike rate, wickets, or a percentage?"
        )
    if not ranking and get_metric(metric).owner in {"batter", "bowler"}:
        role = cast(Role, get_metric(metric).owner)
    sample = _explicit_sample(text, metric)
    # “with 60 balls faced” and “after 60 deliveries” also express eligibility.
    if sample is None:
        threshold = re.search(
            r"\b(?:with|after)\s+(\d+)\s+(?:balls(?: faced)?|deliveries)\b", text
        )
        if threshold:
            unit = (
                "legal_balls"
                if get_metric(metric).denominator == "legal_balls"
                else "balls"
            )
            sample = MinimumSampleSpec(**{unit: int(threshold.group(1))})
    explicit = sample is not None
    if ranking and sample is None:
        defaults = get_metric(
            metric, entity=role, filters=filters
        ).minimum_sample.as_dict()
        sample = MinimumSampleSpec(**defaults) if defaults else None
    direction = requested_sort_direction(
        text, metric, role, group_by=[role], filters=filters
    )
    if direction is None:
        direction = (
            "desc"
            if metric
            in {
                "bowler_dot_ball_percentage",
                "false_shot_percentage",
                "boundary_percentage",
            }
            else get_metric(metric).default_sort
        )
    return MeaningResolution(
        status=MeaningStatus.resolved,
        candidate_sources=["deterministic"],
        meaning=CanonicalCricketMeaning(
            family="matchup",
            role=role,
            metric=metric,
            filters=filters,
            relationship=(
                ("bowler_ranking" if ranked_role == "bowler" else "batter_ranking")
                if ranking
                else "named"
            ),
            group_by=[role] if ranking else [],
            limit=_ranking_limit(text) if ranking else 1,
            sort_direction=cast("LiteralDirection", direction),
            minimum_sample=sample,
            minimum_sample_explicit=explicit,
        ),
    )


LiteralDirection = Literal["asc", "desc"]


def _mask_players(
    text: str, players: list[str], resolver: CanonicalMeaningResolver
) -> str:
    from backend.app.cricket_analytics.canonical_meaning import _player_aliases

    aliases = _player_aliases(resolver.available_players)
    relevant = {
        alias: players.index(player)
        for alias, player in aliases.items()
        if player in players
    }
    pattern = (
        r"(?<!\w)(?:"
        + "|".join(re.escape(a) for a in sorted(relevant, key=len, reverse=True))
        + r")(?!\w)"
    )
    return re.sub(pattern, lambda m: f"p{relevant[m.group(0)]}", text)


def _explicit_pair(text: str, players: list[str]) -> tuple[str, str] | None:
    if re.search(r"\bp0\s+(?:v\.?|vs\.?|versus)\s+p1\s+(?:run tally|runs)\b", text):
        return players[0], players[1]
    for b, w in ((0, 1), (1, 0)):
        batter, bowler = f"p{b}", f"p{w}"
        if "wicket" in text and re.search(
            rf"{bowler}\s+(?:has\s+)?taken\b.*?\b(?:against|off|from)\s+{batter}\b",
            text,
        ):
            return players[b], players[w]
        if re.search(rf"\bbatter\s+{batter}\b", text) or re.search(
            rf"\bbowler\s+{bowler}\b", text
        ):
            return players[b], players[w]
        if re.search(
            rf"{batter}\s+(?:(?:has|had|did)\s+)?(?:score|scored|scores|made|faced)\b",
            text,
        ):
            return players[b], players[w]
        if re.search(
            rf"{bowler}\s+(?:(?:has|had|did)\s+)?(?:bowled|bowls|conceded)\b", text
        ):
            return players[b], players[w]
        if re.search(
            rf"{bowler}\b.*?\b(?:bowls?|bowling|delivers?)\s+(?:to|at)\s+{batter}\b",
            text,
        ):
            return players[b], players[w]
        if re.search(
            rf"{batter}\b.*?\b(?:facing|faces|face|dismissed by|batting against)\s+{bowler}\b",
            text,
        ):
            return players[b], players[w]
        if re.search(rf"{bowler}\b.*?\b(?:dismissed|dismisses|got)\s+{batter}\b", text):
            return players[b], players[w]
        if re.search(
            rf"{batter}(?:'s)?\s+(?:(?:batting )?strike rate|scoring|run tally|runs)\b",
            text,
        ):
            return players[b], players[w]
        if "wicket" not in text and re.search(
            rf"{batter}\b.*?\b(?:scored|scores|made|taken|earned)\b.*?\b(?:against|off|from)\s+{bowler}\b",
            text,
        ):
            return players[b], players[w]
    return None


def _matchup_metric(text: str, role: Role) -> str | None:
    rate = bool(
        re.search(r"\b(?:percentage|percent|rate|share|fraction|proportion)\b|%", text)
    )
    count = (
        bool(re.search(r"\b(?:how many|count|number of|total)\b", text)) and not rate
    )
    if "false shots per over" in text:
        return "false_shots_per_over"
    if "false" in text and "shot" in text:
        return None if count else "false_shot_percentage"
    if "dot" in text or "controls" in text:
        return (
            ("bowler_dot_balls" if role == "bowler" else "dot_balls")
            if count
            else (
                "bowler_dot_ball_percentage"
                if role == "bowler"
                else "batter_dot_ball_percentage"
            )
        )
    if "boundar" in text:
        return None if count else "boundary_percentage"
    if "bowling strike rate" in text:
        return "bowling_strike_rate"
    if "economy" in text:
        return "economy_rate"
    if "bowling average" in text:
        return "bowling_average"
    if "average" in text:
        return "bowling_average" if role == "bowler" else "batting_average"
    if "strike rate" in text or "scoring rate" in text:
        return "batting_strike_rate"
    if "dismissor" in text or re.search(r"\bgets?\b.*\bout\b", text):
        return "dismissals"
    if re.search(r"\b(?:dismissed|dismisses|wickets?)\b", text):
        return "wickets_taken"
    if "runs conceded" in text:
        return "runs_conceded"
    if re.search(r"\b(?:runs?|run tally)\b", text):
        return "runs_scored"
    if "balls faced" in text or "deliveries faced" in text:
        return "balls_faced"
    return "batting_strike_rate"


def compile_matchup_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
    if meaning.family != "matchup" or meaning.relationship is None:
        raise ValueError("Matchup compilation requires a resolved relationship.")
    return CricketQueryPlan(
        operation="matchup" if meaning.relationship == "named" else "aggregate",
        entity=meaning.role,
        metric=meaning.metric,
        group_by=meaning.group_by,
        filters=meaning.filters,
        sort=SortSpec(by=meaning.metric, direction=meaning.sort_direction),
        limit=meaning.limit,
        minimum_sample=meaning.minimum_sample,
        minimum_sample_explicit=meaning.minimum_sample_explicit,
        question_subject="matchup",
        explanation_intent="canonical cricket meaning",
        confidence=1.0,
    )
