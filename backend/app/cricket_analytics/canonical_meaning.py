from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.plan_normalizer import (
    requested_bowling_style,
    requested_sort_direction,
)
from backend.app.cricket_analytics.schemas import (
    CricketQueryPlan,
    MinimumSampleSpec,
    SortSpec,
)
from backend.app.cricket_analytics.venue_resolution import venue_alias_matches
from backend.app.services.player_resolution import ALIASES


class MeaningStatus(str, Enum):
    resolved = "resolved"
    clarification = "clarification"
    unsupported = "unsupported"
    data_limitation = "data_limitation"
    not_applicable = "not_applicable"


class CanonicalCricketMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: Literal["direct", "ranking"]
    role: Literal["batter", "bowler"]
    metric: str
    filters: dict[str, object] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    limit: int = 10
    sort_direction: Literal["asc", "desc"]
    minimum_sample: MinimumSampleSpec | None = None
    minimum_sample_explicit: bool = False


class MeaningResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    status: MeaningStatus
    meaning: CanonicalCricketMeaning | None = None
    clarification: str | None = None
    clarification_options: list[str] = Field(default_factory=list)
    reason: str | None = None
    candidate_sources: list[str] = Field(default_factory=list)


CandidateExtractor = Callable[[str, Mapping[str, object] | None], CricketQueryPlan | None]


_NUMBER_WORDS = {
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
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
}
_KNOWN_BOWLERS = {
    "Jasprit Bumrah",
    "Mitchell Starc",
    "Kagiso Rabada",
    "Pat Cummins",
    "Trent Boult",
    "Rashid Khan",
    "Lasith Malinga",
    "Ravichandran Ashwin",
}
_CANONICAL_PLAYER_ALIASES = {
    "kohli": "Virat Kohli",
    "rohit": "Rohit Sharma",
    "babar": "Babar Azam",
    "klaasen": "Heinrich Klaasen",
    "buttler": "Jos Buttler",
    "bumrah": "Jasprit Bumrah",
    "starc": "Mitchell Starc",
    "rashid": "Rashid Khan",
    "malinga": "Lasith Malinga",
    "ashwin": "Ravichandran Ashwin",
    "boult": "Trent Boult",
    "warner": "David Warner",
    "maxwell": "Glenn Maxwell",
    "miller": "David Miller",
    "rabada": "Kagiso Rabada",
    "shaheen": "Shaheen Shah Afridi",
}
_RANKING_WORDS = re.compile(
    r"\b(?:rank|top|bottom|leading|highest|lowest|largest|best|worst|most|fewest|fastest|slowest|leads?)\b"
)
_BREAKDOWN_WORDS = re.compile(
    r"\b(?:breakdown|split|by line|by length|by year|year[- ]wise|which line|which length|which shot)\b"
)
_OTHER_FAMILY_WORDS = re.compile(
    r"\b(?:compare|comparison|matchup|head[- ]to[- ]head|trend|over time)\b"
)
_OUTSIDE_SLICE_WORDING = re.compile(
    r"\b(?:"
    r"by venue|which venue|which ground|by ground|"
    r"shot type|which shot|what shot|field zone|scoring zone|bowling type|"
    r"short balls?|good length|delivery length|"
    r"(?:since|after|from) \d{4}(?: onward| onwards)?|"
    r"false shots? per over|wicket opportunity|immediately after|"
    r"after facing|dot balls? (?:has|have).* faced|"
    r"what about at"
    r")\b"
)


class CanonicalMeaningResolver:
    """Resolve direct/ranking language into one execution-independent cricket meaning."""

    def __init__(
        self,
        *,
        available_players: Sequence[str],
        available_venues: Sequence[str] = (),
        available_teams: Sequence[str] = (),
        candidate_extractors: Sequence[tuple[str, CandidateExtractor]] = (),
    ) -> None:
        self.available_players = tuple(available_players)
        self.available_venues = tuple(available_venues)
        self.available_teams = tuple(available_teams)
        self.candidate_extractors = tuple(candidate_extractors)

    def resolve(
        self,
        question: str,
        conversation_state: Mapping[str, object] | BaseModel | None,
    ) -> MeaningResolution:
        state = _state_mapping(conversation_state)
        deterministic = self._meaning_from_language(question, state)
        candidates: list[tuple[str, CanonicalCricketMeaning]] = []
        if deterministic.status == MeaningStatus.resolved and deterministic.meaning is not None:
            candidates.append(("deterministic", deterministic.meaning))

        for source, extractor in self.candidate_extractors:
            try:
                plan = extractor(question, state)
            except Exception:
                continue
            candidate = self._meaning_from_plan(question, state, plan)
            if candidate is not None:
                candidates.append((source, candidate))

        if not candidates:
            return deterministic

        distinct: dict[str, CanonicalCricketMeaning] = {}
        sources: list[str] = []
        for source, candidate in candidates:
            key = candidate.model_dump_json(exclude_none=True)
            distinct.setdefault(key, candidate)
            sources.append(source)
        if len(distinct) == 1:
            return MeaningResolution(
                status=MeaningStatus.resolved,
                meaning=next(iter(distinct.values())),
                candidate_sources=list(dict.fromkeys(sources)),
            )

        # Explicit language is authoritative. Candidate disagreement only remains material
        # when the question itself cannot choose between two valid metric/role meanings.
        if deterministic.status == MeaningStatus.resolved and deterministic.meaning is not None:
            return MeaningResolution(
                status=MeaningStatus.resolved,
                meaning=deterministic.meaning,
                candidate_sources=list(dict.fromkeys(sources)),
            )
        options = sorted({f"{item.role} {item.metric}" for item in distinct.values()})
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Which cricket metric and player role do you mean?",
            clarification_options=options,
            candidate_sources=list(dict.fromkeys(sources)),
        )

    def _meaning_from_plan(
        self,
        question: str,
        state: Mapping[str, object] | None,
        plan: CricketQueryPlan | None,
    ) -> CanonicalCricketMeaning | None:
        if plan is None or plan.operation != "aggregate":
            return None
        language = self._meaning_from_language(question, state)
        if language.status == MeaningStatus.resolved:
            return language.meaning
        filters = dict(plan.filters)
        player = filters.get(plan.entity)
        family = "direct" if isinstance(player, str) else "ranking"
        if plan.entity not in {"batter", "bowler"}:
            return None
        return CanonicalCricketMeaning(
            family=family,
            role=plan.entity,
            metric=plan.metric,
            filters=filters,
            group_by=list(plan.group_by or [plan.entity]),
            limit=plan.limit or 10,
            sort_direction=plan.sort.direction if plan.sort else get_metric(plan.metric).default_sort,
            minimum_sample=plan.minimum_sample if family == "ranking" else None,
            minimum_sample_explicit=plan.minimum_sample_explicit if family == "ranking" else False,
        )

    def _meaning_from_language(
        self,
        question: str,
        state: Mapping[str, object] | None,
    ) -> MeaningResolution:
        lowered = _normalized_text(question)
        if (
            _BREAKDOWN_WORDS.search(lowered)
            or _OTHER_FAMILY_WORDS.search(lowered)
            or _OUTSIDE_SLICE_WORDING.search(lowered)
        ):
            return MeaningResolution(status=MeaningStatus.not_applicable)
        if re.search(r"\bteams?\b", lowered):
            return MeaningResolution(status=MeaningStatus.not_applicable)
        if re.search(r"\b(?:catches|run[- ]outs?|captain(?:cy|s)?)\b", lowered):
            return MeaningResolution(
                status=MeaningStatus.data_limitation,
                reason="The ODI delivery data does not contain the requested fielding or captaincy facts.",
            )
        if re.search(r"\b(?:salary|weather|forecast|predict|will win)\b", lowered):
            return MeaningResolution(
                status=MeaningStatus.unsupported,
                reason="The requested concept is outside supported historical ODI analytics.",
            )

        players = _extract_players(question, self.available_players)
        if len(players) > 1:
            return MeaningResolution(status=MeaningStatus.not_applicable)
        player = players[0] if players else None
        if player is not None and re.search(r"\bwhich\s+(?:bowler|batter)\b", lowered):
            return MeaningResolution(status=MeaningStatus.not_applicable)
        state_players = state.get("players") if state else None
        if player is None and isinstance(state_players, list) and len(state_players) == 1:
            state_player = state_players[0]
            if isinstance(state_player, str) and state_player in self.available_players:
                player = state_player
        ranking = bool(_RANKING_WORDS.search(lowered)) and player is None
        state_group_by = state.get("group_by") if state else None
        state_ranking = (
            player is None
            and state is not None
            and state.get("operation") == "aggregate"
            and isinstance(state_group_by, list)
            and any(item in {"batter", "bowler"} for item in state_group_by)
        )
        family: Literal["direct", "ranking"] | None = (
            "ranking" if ranking or state_ranking else "direct" if player else None
        )
        if family is None:
            return MeaningResolution(status=MeaningStatus.not_applicable)

        if (
            "strike rate" in lowered
            and "batting strike rate" not in lowered
            and "bowling strike rate" not in lowered
            and player in _KNOWN_BOWLERS
        ):
            return MeaningResolution(
                status=MeaningStatus.clarification,
                clarification="Do you mean batting strike rate or bowling strike rate?",
                clarification_options=["batting strike rate", "bowling strike rate"],
            )

        metric, role = _metric_and_role(lowered, player)
        state_metric = state.get("metric") if state else None
        if metric is None and isinstance(state_metric, str):
            try:
                rule = get_metric(state_metric)
            except KeyError:
                pass
            else:
                metric = rule.metric_id
                if rule.owner in {"batter", "bowler"}:
                    role = rule.owner
                elif isinstance(state_group_by, list):
                    role = next(
                        (item for item in state_group_by if item in {"batter", "bowler"}),
                        None,
                    )
        if metric is None or role is None:
            if "strike rate" in lowered:
                return MeaningResolution(
                    status=MeaningStatus.clarification,
                    clarification="Do you mean batting strike rate or bowling strike rate?",
                    clarification_options=["batting strike rate", "bowling strike rate"],
                )
            return MeaningResolution(
                status=MeaningStatus.unsupported,
                reason="No supported direct or ranking metric was identified.",
            )

        filters = _state_filters(state)
        filters.update(self._explicit_filters(question, lowered))
        filters.pop("batter", None)
        filters.pop("bowler", None)
        if player:
            filters[role] = player

        limit = _ranking_limit(lowered) if family == "ranking" else 10
        direction = (
            "desc"
            if family == "direct"
            else requested_sort_direction(
                re.sub(r"\bat least\b", "minimum", lowered),
                metric,
                role,
                group_by=[role],
                filters=filters,
            )
            or get_metric(metric, entity=role, filters=filters).default_sort
        )
        sample = _explicit_sample(lowered, metric) if family == "ranking" else None
        sample_is_explicit = sample is not None
        if family == "ranking" and sample is None:
            defaults = get_metric(metric, entity=role, filters=filters).minimum_sample.as_dict()
            sample = MinimumSampleSpec(**defaults) if defaults else None
        return MeaningResolution(
            status=MeaningStatus.resolved,
            meaning=CanonicalCricketMeaning(
                family=family,
                role=role,
                metric=metric,
                filters=filters,
                group_by=[role],
                limit=limit,
                sort_direction=direction,
                minimum_sample=sample,
                minimum_sample_explicit=sample_is_explicit,
            ),
            candidate_sources=["deterministic"],
        )

    def _explicit_filters(self, question: str, lowered: str) -> dict[str, object]:
        filters: dict[str, object] = {}
        phase = _phase(lowered)
        if phase:
            filters["phase"] = phase
        else:
            over_range = _over_range(lowered)
            if over_range:
                filters["over_range"] = over_range
        years = sorted({int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", lowered)})
        if years:
            filters["years"] = years
        style = requested_bowling_style(lowered)
        if style is None and re.search(r"\b(?:facing|face)\s+spin\b", lowered):
            style = "spin"
        if style:
            filters["bowling_style"] = style
        if re.search(r"\b(?:lefties|lhb|left[- ]hand(?:ed)?(?: batters?|ers?)?)\b", lowered):
            filters["batter_hand"] = "LHB"
        elif re.search(r"\b(?:righties|rhb|right[- ]hand(?:ed)?(?: batters?|ers?)?)\b", lowered):
            filters["batter_hand"] = "RHB"
        venues = venue_alias_matches(question, self.available_venues)
        if not venues:
            normalized_question = _normalized_lookup_text(question)
            venues = [
                venue
                for venue in self.available_venues
                if _normalized_lookup_text(venue) in normalized_question
            ]
        if len(venues) == 1:
            filters["venue"] = venues[0]
        elif len(venues) > 1:
            filters["venues"] = venues
        opposition = _extract_team(question, self.available_teams)
        if opposition:
            filters["opposition"] = opposition
        return filters


def compile_canonical_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
    return CricketQueryPlan(
        operation="aggregate",
        entity=meaning.role,
        metric=meaning.metric,
        group_by=meaning.group_by,
        filters=meaning.filters,
        sort=SortSpec(by=meaning.metric, direction=meaning.sort_direction),
        limit=meaning.limit,
        minimum_sample=meaning.minimum_sample,
        minimum_sample_explicit=meaning.minimum_sample_explicit,
        question_subject=meaning.family,
        explanation_intent="canonical cricket meaning",
        confidence=1.0,
    )


def _metric_and_role(lowered: str, player: str | None) -> tuple[str | None, str | None]:
    if "yorker" in lowered:
        count = bool(
            re.search(
                r"\b(?:(?:most|fewest) yorkers|yorker (?:count|volume)|how many yorkers)\b",
                lowered,
            )
        ) or (
            "not yorker rate" in lowered
        )
        return ("yorker_count" if count else "yorker_percentage"), "bowler"
    if "boundar" in lowered or "find the rope" in lowered:
        bowling = bool(re.search(r"\b(?:bowlers?|concede|conceded|concedes)\b", lowered))
        return "boundary_percentage", "bowler" if bowling else "batter"
    if "econom" in lowered or "expensive" in lowered or "concede" in lowered:
        return "economy_rate", "bowler"
    if re.search(r"\bwickets?\b", lowered):
        return "wickets_taken", "bowler"
    if "false shot" in lowered or "false-shot" in lowered:
        return "false_shot_percentage", "batter"
    if "dot" in lowered:
        bowling = bool(
            re.search(r"\b(?:bowlers?|legal (?:balls|deliveries)|to (?:left|right)[- ]hand)\b", lowered)
        ) or player in _KNOWN_BOWLERS
        return (
            "bowler_dot_ball_percentage" if bowling else "batter_dot_ball_percentage",
            "bowler" if bowling else "batter",
        )
    if "bowling strike rate" in lowered:
        return "bowling_strike_rate", "bowler"
    if "strike rate" in lowered or "fastest scorer" in lowered or "fastest" in lowered or "quickly" in lowered:
        if re.search(r"\bbowlers?\b", lowered):
            return "bowling_strike_rate", "bowler"
        return "batting_strike_rate", "batter"
    if "bowling average" in lowered:
        return "bowling_average", "bowler"
    if "average" in lowered:
        return "batting_average", "batter"
    if re.search(r"\b(?:runs?|run tally|run totals?|scorers?)\b", lowered):
        return "runs_scored", "batter"
    return None, None


def _extract_player(question: str, available_players: Sequence[str]) -> str | None:
    players = _extract_players(question, available_players)
    return players[0] if players else None


def _extract_players(question: str, available_players: Sequence[str]) -> list[str]:
    lowered = question.lower().replace("’", "'")
    aliases: dict[str, str] = {key.lower(): value for key, value in ALIASES.items()}
    for player in available_players:
        aliases[player.lower()] = player
    aliases.update(_CANONICAL_PLAYER_ALIASES)
    matches = [
        (match.start(), -len(alias), canonical)
        for alias, canonical in aliases.items()
        if (match := re.search(rf"(?<!\w){re.escape(alias)}(?:'s)?(?!\w)", lowered))
        and canonical in available_players
    ]
    ordered: list[str] = []
    for _, _, canonical in sorted(matches):
        if canonical not in ordered:
            ordered.append(canonical)
    return ordered


def _extract_team(question: str, available_teams: Sequence[str]) -> str | None:
    lowered = question.lower()
    aliases = {"aus": "Australia", "aussies": "Australia"}
    for team in available_teams:
        aliases[team.lower()] = team
    for alias, team in sorted(aliases.items(), key=lambda item: -len(item[0])):
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lowered):
            return team
    return None


def _phase(lowered: str) -> str | None:
    if re.search(r"\b(?:power\s*play|opening ten|first ten|overs?\s*1\s*(?:-|to|–)\s*10)\b", lowered):
        return "powerplay"
    if re.search(r"\b(?:middle(?:[- ]overs?| phase)?|overs?\s*11\s*(?:-|to|–)\s*40)\b", lowered):
        return "middle"
    if re.search(r"\b(?:death|final overs?|over\s*41\s+onwards|after\s+over\s*40)\b", lowered):
        return "death"
    return None


def _over_range(lowered: str) -> list[int] | None:
    match = re.search(r"\bovers?\s*(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\b", lowered)
    return [int(match.group(1)), int(match.group(2))] if match else None


def _ranking_limit(lowered: str) -> int:
    number = r"\d{1,2}|" + "|".join(_NUMBER_WORDS)
    patterns = (
        rf"\b(?:top|bottom|leading|highest|lowest|best|worst|fastest|slowest|give|list)\s+(?:the\s+)?({number})\b",
        rf"\b({number})\s+(?:most|leading|highest|lowest|largest|best|worst|fastest|slowest|bowlers?|batters?)\b",
        rf"\b(?:rank|which)\s+(?:the\s+)?(?:best|worst|top|bottom)?\s*({number})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            raw = match.group(1)
            return max(1, min(int(raw) if raw.isdigit() else _NUMBER_WORDS[raw], 50))
    return 10


def _explicit_sample(lowered: str, metric: str) -> MinimumSampleSpec | None:
    patterns = (
        r"\b(?:minimum|min\.?|at least)\s+(?:sample\s+)?(\d{1,7})\s*(legal\s+)?(?:balls?|deliver(?:y|ies)|innings?)?",
        r"\b(?:with\s+)?(?:a\s+)?(\d{1,7})[- ]ball\s+(?:cutoff|floor|minimum)\b",
        r"\b(\d{1,7})\s+(legal\s+)?balls?\s+(?:minimum|cutoff|floor)\b",
        r"\b(\d{1,7})\+\s*(legal\s+)?(?:balls?|deliver(?:y|ies))\b",
        r"\bafter\s+(\d{1,7})\s+(legal\s+)?balls?\b",
        r"\bminimum\s+sample\s+(\d{1,7})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        value = int(match.group(1))
        explicit_legal = len(match.groups()) > 1 and bool(match.group(2))
        denominator = get_metric(metric).denominator
        if explicit_legal or denominator == "legal_balls":
            return MinimumSampleSpec(legal_balls=value)
        return MinimumSampleSpec(balls=value)
    return None


def _state_mapping(value: Mapping[str, object] | BaseModel | None) -> Mapping[str, object] | None:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    return value


def _state_filters(state: Mapping[str, object] | None) -> dict[str, object]:
    if not state:
        return {}
    filters = state.get("filters")
    return dict(filters) if isinstance(filters, Mapping) else {}


def _normalized_text(value: str) -> str:
    return " ".join(value.lower().replace("’", "'").replace("–", "-").split())


def _normalized_lookup_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
