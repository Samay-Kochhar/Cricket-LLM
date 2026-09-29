from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from backend.app.cricket_analytics.language_meaning import (
    AnalyticalFactDisposition,
    ExpressedFilter,
    LanguageMeaningCandidate,
    MeaningCompletenessResult,
)
from backend.app.cricket_analytics.dismissal_types import (
    DISMISSAL_TYPE_REGISTRY,
    canonical_dismissal_type,
    is_dismissal_share_concept,
    is_dismissal_type_concept,
)
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.plan_normalizer import (
    requests_boundary_percentage,
    requests_four_count,
    requests_six_count,
    requested_bowling_style,
    requested_limit_from_wording,
    requested_sort_direction,
)
from backend.app.cricket_analytics.schemas import (
    CricketQueryPlan,
    MinimumSampleSpec,
    SortSpec,
)
from backend.app.cricket_analytics.venue_resolution import venue_alias_matches
from backend.app.services.player_resolution import ALIASES
from backend.app.cricket_analytics.player_roles import (
    PlayerParticipation,
    PlayerRoleResolver,
)


class MeaningStatus(str, Enum):
    resolved = "resolved"
    clarification = "clarification"
    unsupported = "unsupported"
    data_limitation = "data_limitation"
    not_applicable = "not_applicable"


class CanonicalCricketMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: Literal[
        "direct", "ranking", "breakdown", "matchup", "comparison", "split", "trend"
    ]
    role: Literal["batter", "bowler"]
    metric: str
    filters: dict[str, object] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    limit: int | None = 10
    sort_direction: Literal["asc", "desc"]
    minimum_sample: MinimumSampleSpec | None = None
    minimum_sample_explicit: bool = False
    relationship: Literal["named", "bowler_ranking", "batter_ranking"] | None = None
    participants: list[str] = Field(default_factory=list)
    comparison_metrics: list[str] = Field(default_factory=list)
    subject: Literal["batter", "bowler", "team"] | None = None
    split_by: (
        Literal[
            "phase",
            "batter_hand",
            "bowling_style_group",
            "balls_faced_window",
            "over_range",
        ]
        | None
    ) = None
    compare_values: list[str] = Field(default_factory=list)
    split_intent: Literal["descriptive", "ranking"] | None = None
    split_direction: Literal["absolute", "increase", "decrease"] | None = None


class MeaningResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    status: MeaningStatus
    meaning: CanonicalCricketMeaning | None = None
    clarification: str | None = None
    clarification_options: list[str] = Field(default_factory=list)
    reason: str | None = None
    candidate_sources: list[str] = Field(default_factory=list)
    fallback_reason: (
        Literal[
            "malformed_flash", "unavailable_flash", "explicit_language_authoritative"
        ]
        | None
    ) = None
    completeness: MeaningCompletenessResult | None = None


CandidateExtractor = Callable[
    [str, Mapping[str, object] | None], LanguageMeaningCandidate | None
]


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
_CANONICAL_PLAYER_ALIASES = {
    "kohli": "Virat Kohli",
    "virat": "Virat Kohli",
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
    "smith": "Steven Smith",
    "jadeja": "Ravindra Jadeja",
}
_RANKING_WORDS = re.compile(
    r"\b(?:rank|top|bottom|leading|highest|lowest|maximum|minimum|largest|best|worst|most|fewest|fastest|slowest|leads?)\b"
)
_BREAKDOWN_WORDS = re.compile(
    r"\b(?:breakdown|split|year[- ]wise|"
    r"(?:by|across|each|every|which|what)\s+(?:(?:bowling|innings|shot|delivery|each|every)\s+){0,2}"
    r"(?:lines?|lengths?|years?|shots?|zones?|styles?|phases?))\b"
)
_OTHER_FAMILY_WORDS = re.compile(
    r"\b(?:compare|compared|comparison|matchup|head[- ]to[- ]head|trend|over time|"
    r"annual|year over year|season by season|season to season|dismissor)\b"
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


BREAKDOWN_DIMENSIONS = {
    "line": r"lines?",
    "length": r"lengths?",
    "bowling_style": r"(?:bowling|bowler) (?:styles?|types?|categories)",
    "shot_type": r"(?<!false )(?<!false-)shots?(?: types?| selections?)?",
    "field_zone": r"(?:field |scoring )?zones?|regions?|areas? of the (?:field|ground)",
    "phase": r"(?:innings |over )?phases?|stages? of (?:the )?innings",
    "batter_hand": r"(?:batter |batting )?(?:handedness|hands?)",
    "year": r"years?|annual|annually",
    "dismissal_type": (
        r"(?:dismissal|out) (?:types?|modes?|methods?|kinds?|categor(?:y|ies))"
        r"|(?:types?|modes?|methods?|kinds?|forms?) of (?:dismissals?|getting out)"
    ),
}


def breakdown_dimensions(text: str) -> list[str]:
    """Resolve the categorical axis independently of statistic and player ownership."""
    grouping = bool(
        re.search(
            r"\b(?:by|across|per|each|every|which|where|breakdown|split|"
            r"grouped|grouping|partition|categorize|categorise|distribution|"
            r"accounts? for|most productive)\b",
            text,
        )
    )
    grouping = grouping or bool(
        re.search(
            r"\bwhat (?:bowling |delivery |shot |field |innings )?(?:line|length|style|type|zone|phase|year)",
            text,
        )
    )
    axis_text = re.sub(r"\bgood[- ]length(?: balls?)?\b", "", text)
    dimensions = [
        dimension
        for dimension, pattern in BREAKDOWN_DIMENSIONS.items()
        if grouping and re.search(rf"\b(?:{pattern})\b", axis_text)
    ]
    if all(
        re.search(rf"\b{phase}\b", text) for phase in ("powerplay", "middle", "death")
    ):
        dimensions.append("phase")
    if re.search(r"\b(?:lefties|lhb|left.hand(?:ed)?)", text) and re.search(
        r"\b(?:righties|rhb|right.hand(?:ed)?)", text
    ):
        # Preserve the existing explicit comparison family.
        if not re.search(r"\bcompar(?:e|ison)\b", text):
            dimensions.append("batter_hand")
    return list(dict.fromkeys(dimensions))


class CanonicalMeaningResolver:
    """Resolve supported language into one execution-independent cricket meaning."""

    def __init__(
        self,
        *,
        available_players: Sequence[str],
        available_venues: Sequence[str] = (),
        available_teams: Sequence[str] = (),
        candidate_extractors: Sequence[tuple[str, CandidateExtractor]] = (),
        player_participation: Mapping[str, PlayerParticipation] | None = None,
    ) -> None:
        self.available_players = tuple(available_players)
        self.available_venues = tuple(available_venues)
        self.available_teams = tuple(available_teams)
        self.candidate_extractors = tuple(candidate_extractors)
        self.player_roles = PlayerRoleResolver(player_participation)

    def resolve(
        self,
        question: str,
        conversation_state: Mapping[str, object] | BaseModel | None,
    ) -> MeaningResolution:
        state = _state_mapping(conversation_state)
        deterministic = self._meaning_from_language(question, state)
        candidates: list[tuple[str, CanonicalCricketMeaning]] = []
        if (
            deterministic.status == MeaningStatus.resolved
            and deterministic.meaning is not None
        ):
            candidates.append(("deterministic", deterministic.meaning))

        for source, extractor in self.candidate_extractors:
            try:
                extracted = extractor(question, state)
            except Exception:
                continue
            if extracted is None:
                continue
            resolution = self.resolve_candidate(
                question, state, extracted, source=source
            )
            if resolution.meaning is not None:
                candidates.append((source, resolution.meaning))

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
        if (
            deterministic.status == MeaningStatus.resolved
            and deterministic.meaning is not None
        ):
            merged = deterministic.meaning.model_copy(deep=True)
            for _, candidate in candidates:
                for key, value in candidate.filters.items():
                    if key in merged.filters and merged.filters[key] != value:
                        return MeaningResolution(
                            status=MeaningStatus.clarification,
                            clarification=f"Which {key.replace('_', ' ')} constraint do you mean?",
                            candidate_sources=list(dict.fromkeys(sources)),
                        )
                    merged.filters[key] = value
                if candidate.minimum_sample_explicit:
                    merged.minimum_sample = candidate.minimum_sample
                    merged.minimum_sample_explicit = True
            return MeaningResolution(
                status=MeaningStatus.resolved,
                meaning=merged,
                candidate_sources=list(dict.fromkeys(sources)),
            )
        options = sorted({f"{item.role} {item.metric}" for item in distinct.values()})
        return MeaningResolution(
            status=MeaningStatus.clarification,
            clarification="Which cricket metric and player role do you mean?",
            clarification_options=options,
            candidate_sources=list(dict.fromkeys(sources)),
        )

    def accepts(
        self, question: str, state: Mapping[str, object] | BaseModel | None = None
    ) -> bool:
        """A compiler-owned boundary, independent of model output or its validity."""
        resolution = self._meaning_from_language(question, _state_mapping(state))
        if resolution.status == MeaningStatus.not_applicable:
            return False
        if _is_dismissal_type_resolution(resolution):
            return True
        if resolution.status == MeaningStatus.unsupported:
            return bool(
                resolution.reason
                == "No supported direct or ranking metric was identified."
                and (
                    "boundar" in question.lower()
                    or re.search(
                        r"\b(?:scoring pace|rank players|statistics?|numbers)\b",
                        question.lower(),
                    )
                )
                and not re.search(
                    r"\b(?:approach|profile|strategy|plan|analysis)\b", question.lower()
                )
            )
        return resolution.status in {
            MeaningStatus.resolved,
            MeaningStatus.clarification,
        }

    def resolve_candidate(
        self,
        question: str,
        state: Mapping[str, object] | BaseModel | None,
        candidate: LanguageMeaningCandidate,
        *,
        source: str = "flash",
    ) -> MeaningResolution:
        resolution = self._resolve_candidate(question, state, candidate, source=source)
        return self._account_for_candidate_facts(question, candidate, resolution)

    def _resolve_candidate(
        self,
        question: str,
        state: Mapping[str, object] | BaseModel | None,
        candidate: LanguageMeaningCandidate,
        *,
        source: str = "flash",
    ) -> MeaningResolution:
        deterministic = self._meaning_from_language(question, _state_mapping(state))
        sources = list(dict.fromkeys([*deterministic.candidate_sources, source]))

        def unclear(reason: str, options: list[str] | None = None) -> MeaningResolution:
            return MeaningResolution(
                status=MeaningStatus.clarification,
                reason=reason,
                clarification=reason,
                clarification_options=options or [],
                candidate_sources=sources,
            )

        if not self.accepts(question, state):
            return deterministic
        # A model cannot make an explicitly ambiguous question unambiguous by guessing.
        if deterministic.status == MeaningStatus.clarification or (
            _is_dismissal_type_resolution(deterministic)
            and deterministic.status != MeaningStatus.resolved
        ):
            return deterministic.model_copy(update={"candidate_sources": sources})
        base = deterministic.meaning
        if base and base.family in {"matchup", "comparison", "split", "trend"}:
            # Relationship, identity and metric are already resolved from explicit
            # wording and repository participation. Surface family/role labels do
            # not get to replace that relationship with a comparison or ranking.
            meaning = base.model_copy(deep=True)
            lowered = _normalized_text(question)
            for fact in candidate.filters:
                if not fact.evidence or _normalized_text(fact.evidence) not in lowered:
                    continue
                normalized = self._candidate_filter(fact)
                for key, value in normalized.items():
                    if base.family == "split" and key == {
                        "phase": "phase",
                        "batter_hand": "batter_hand",
                        "bowling_style_group": "bowling_style",
                    }.get(base.split_by):
                        continue
                    if key not in meaning.filters:
                        meaning.filters[key] = value
            return MeaningResolution(
                status=MeaningStatus.resolved,
                meaning=meaning,
                candidate_sources=sources,
            )
        if base and "dismissal_type" in base.group_by:
            # The registered dismissal-type meaning is compiled from explicit
            # wording; extracted facts are accounted for, not merged, so a
            # family gloss such as "comparison" cannot reroute it.
            return deterministic.model_copy(update={"candidate_sources": sources})
        candidate_dimensions = (
            candidate.breakdown_dimensions or candidate.split_dimensions
        )
        equivalent_breakdown = bool(
            base
            and base.family == "breakdown"
            and candidate_dimensions
            and set(
                breakdown_dimensions(
                    "by "
                    + " and ".join(
                        item.replace("_", " ") for item in candidate_dimensions
                    )
                )
            )
            == set(base.group_by)
        )
        if (
            candidate.family not in {"direct", "ranking", "breakdown", "unknown"}
            or candidate_dimensions
        ) and not equivalent_breakdown:
            if base and base.family == "breakdown":
                # A contradictory family gloss cannot override an explicit axis.
                return deterministic.model_copy(update={"candidate_sources": sources})
            return unclear(
                "The requested relationships or dimensions need a different cricket meaning."
            )
        if candidate.ambiguity_candidates and base is None:
            return unclear(
                "Which cricket meaning do you intend?", candidate.ambiguity_candidates
            )

        lowered = _normalized_text(question)
        players = _extract_players(question, self.available_players)
        if not players and base and isinstance(base.filters.get(base.role), str):
            players = [str(base.filters[base.role])]
        filters = _state_filters(_state_mapping(state))
        explicit_filters = self._explicit_filters(question, lowered)
        filters.update(explicit_filters)
        if base:
            filters.update(base.filters)
        metric, role = _metric_and_role(
            _normalized_text(candidate.metric_concept or "").replace("_", " "), None
        )
        if candidate.metric_concept:
            try:
                rule = get_metric(candidate.metric_concept)
            except KeyError:
                pass
            else:
                metric = rule.metric_id
                role = (
                    rule.owner if rule.owner in {"batter", "bowler"} else candidate.role
                )
        if base:
            # Explicit question wording outranks a contradictory surface gloss.
            metric, role = base.metric, base.role
        else:
            role = candidate.role or role
        if metric is None or role not in {"batter", "bowler"}:
            return unclear("Which batting or bowling statistic do you mean?")
        rule = get_metric(metric, entity=role, filters=filters)
        if rule.owner not in {role, "batter_or_bowler"}:
            return unclear("The requested metric and player role disagree.")

        for entity in candidate.entities:
            if entity.kind == "player":
                if (
                    base
                    and base.family == "ranking"
                    and _normalized_text(entity.name)
                    in {
                        "player",
                        "players",
                        "batter",
                        "batters",
                        "bowler",
                        "bowlers",
                        "batsman",
                        "batsmen",
                        "null",
                        "none",
                        "",
                    }
                ):
                    continue
                matches = _extract_players(entity.name, self.available_players)
                if len(matches) != 1:
                    cohort = self._explicit_filters(
                        entity.name, _normalized_text(entity.name)
                    )
                    if cohort and all(
                        filters.get(key) == value for key, value in cohort.items()
                    ):
                        continue
                    return unclear(f"Which player do you mean by {entity.name}?")
                player = matches[0]
                # Require an actual mention; invented participants cannot broaden scope.
                if player not in players:
                    return unclear(f"Please confirm the player {entity.name}.")
                if (
                    base
                    and base.filters.get("batter") == player
                    and base.role == "bowler"
                ):
                    continue
                entity_role = entity.role or role
                if entity.relationship == "opponent" or entity_role != role:
                    return unclear(
                        "Please clarify the batting and bowling roles in this relationship."
                    )
                filters[role] = player
            elif entity.kind == "team":
                team = _extract_team(entity.name, self.available_teams)
                if not team or team != _extract_team(question, self.available_teams):
                    return unclear(f"Which team do you mean by {entity.name}?")
                if entity.relationship != "opponent":
                    return unclear(
                        "Should this team filter select the player's team or the opposition?"
                    )
                filters["opposition"] = team
            elif entity.kind == "venue":
                venues = venue_alias_matches(entity.name, self.available_venues)
                if not venues:
                    venues = [
                        v
                        for v in self.available_venues
                        if _normalized_lookup_text(v)
                        == _normalized_lookup_text(entity.name)
                    ]
                if len(venues) != 1 or venues[0] not in {
                    filters.get("venue"),
                    *cast(list[str], filters.get("venues") or []),
                }:
                    return unclear(f"Which venue do you mean by {entity.name}?")
        candidate_filters: dict[str, object] = {}
        for fact in candidate.filters:
            if not fact.evidence or _normalized_text(fact.evidence) not in lowered:
                return unclear(f"Please clarify the requested {fact.concept} filter.")
            # ODI is the fixed dataset scope, so stating it adds no row filter.
            if _normalized_text(fact.concept).replace("_", " ") in {
                "format",
                "match format",
                "match type",
                "competition",
            }:
                if (
                    all(
                        _normalized_text(str(v))
                        in {
                            "odi",
                            "odis",
                            "one day international",
                            "one day internationals",
                        }
                        for v in fact.values
                    )
                    and fact.values
                ):
                    continue
            if _normalized_text(fact.concept) == "city" and isinstance(
                filters.get("venue"), str
            ):
                if fact.values and all(
                    _normalized_lookup_text(str(value))
                    in _normalized_lookup_text(str(filters["venue"]))
                    for value in fact.values
                ):
                    continue
            if "deliver" in fact.concept.lower() or "ball" in fact.concept.lower():
                values = {_normalized_text(str(v)) for v in fact.values}
                if (
                    values
                    and values <= {"legal", "legal balls", "legal deliveries"}
                    and rule.denominator == "legal_balls"
                ):
                    continue
                if (
                    values
                    and values <= {"yorker", "yorkers"}
                    and metric in {"yorker_count", "yorker_percentage"}
                ):
                    continue
            if _normalized_text(fact.concept) in {"player", "batter", "bowler"}:
                matches = _extract_players(
                    " ".join(str(v) for v in fact.values), self.available_players
                )
                if len(matches) == 1 and matches[0] in players:
                    continue
                return unclear("Which player should this filter select?")
            normalized = self._candidate_filter(fact)
            if not normalized:
                return unclear(
                    f"The requested {fact.concept} filter could not be resolved."
                )
            for key, value in normalized.items():
                # Keep directly extracted constraints when the surface candidate disagrees.
                if key in explicit_filters:
                    continue
                if key == "dismissal_type" and isinstance(
                    candidate_filters.get(key), list
                ):
                    # Several requested categories of one registered dimension.
                    value = list(
                        dict.fromkeys(
                            [*cast(list[str], candidate_filters[key]), *cast(list[str], value)]
                        )
                    )
                elif key in candidate_filters and candidate_filters[key] != value:
                    return unclear(
                        f"Which {key.replace('_', ' ')} constraint do you mean?"
                    )
                candidate_filters[key] = value
                filters[key] = value
        if base and base.family == "breakdown":
            for dimension in base.group_by:
                # A candidate may repeat listed categories as a filter. Keep the
                # canonical enumeration intact unless the question restricted it.
                if dimension not in base.filters:
                    filters.pop(dimension, None)
        family = base.family if base else ("direct" if players else candidate.family)
        group_by = base.group_by if base else [role]
        if "dismissal_type" in filters:
            # Requested dismissal categories always use the registered
            # dimension path for one dismissed batter.
            if not (
                players
                and role == "batter"
                and metric in {"dismissals", "dismissal_type_percentage"}
            ):
                return unclear(
                    "Dismissal types are answered as one named batter's dismissal counts or shares."
                )
            family, group_by = "breakdown", ["dismissal_type"]
        if family not in {"direct", "ranking", "breakdown"}:
            return unclear("Do you want a player's statistic or a player ranking?")
        if players and not (
            base and base.filters.get("batter") == players[0] and role == "bowler"
        ):
            filters[role] = players[0]
        if family == "direct" and role not in filters:
            return unclear("Which player should this statistic describe?")
        limit = base.limit if base else _ranking_limit(lowered)
        direction = base.sort_direction if base else rule.default_sort
        sample = base.minimum_sample if base else _explicit_sample(lowered, metric)
        sample_explicit = base.minimum_sample_explicit if base else sample is not None
        if candidate.sample_threshold and not sample_explicit:
            threshold = candidate.sample_threshold
            if (
                _normalized_text(threshold.evidence) not in lowered
                or not threshold.evidence
            ):
                return unclear("Please clarify the minimum sample.")
            sample = MinimumSampleSpec(
                **{threshold.unit.replace(" ", "_"): threshold.value}
            )
            sample_explicit = True
        if family == "ranking":
            if candidate.ordering and not base:
                ordering_directions: dict[str, Literal["asc", "desc"]] = {
                    "highest": "desc",
                    "lowest": "asc",
                    "ascending": "asc",
                    "descending": "desc",
                    "best": rule.default_sort,
                    "worst": "asc" if rule.default_sort == "desc" else "desc",
                }
                direction = ordering_directions[candidate.ordering]
            if sample is None:
                defaults = rule.minimum_sample.as_dict()
                sample = MinimumSampleSpec(**defaults) if defaults else None
        return MeaningResolution(
            status=MeaningStatus.resolved,
            candidate_sources=sources,
            meaning=CanonicalCricketMeaning(
                family=cast(Literal["direct", "ranking", "breakdown"], family),
                role=cast(Literal["batter", "bowler"], role),
                metric=metric,
                filters=filters,
                group_by=group_by,
                limit=limit,
                sort_direction=cast(Literal["asc", "desc"], direction),
                minimum_sample=sample,
                minimum_sample_explicit=sample_explicit,
            ),
        )

    def _account_for_candidate_facts(
        self,
        question: str,
        candidate: LanguageMeaningCandidate,
        resolution: MeaningResolution,
    ) -> MeaningResolution:
        """Account for every extracted fact before allowing a plan to compile."""
        meaning = resolution.meaning
        unresolved_disposition: Literal["clarification_required", "unsupported"] = (
            "unsupported"
            if resolution.status
            in {MeaningStatus.unsupported, MeaningStatus.data_limitation}
            else "clarification_required"
        )
        facts: list[AnalyticalFactDisposition] = []

        def add(
            fact_type: str,
            concept: str,
            requested: object | None,
            *,
            disposition: str,
            target: str | None = None,
            evidence: str | None = None,
            reason: str | None = None,
        ) -> None:
            facts.append(
                AnalyticalFactDisposition(
                    fact_type=fact_type,
                    concept=concept,
                    requested=requested,
                    evidence=evidence,
                    disposition=disposition,
                    canonical_target=target,
                    reason=reason,
                )
            )

        if meaning is None:
            for fact_type, concept, requested, evidence in _candidate_fact_inventory(
                candidate
            ):
                add(
                    fact_type,
                    concept,
                    requested,
                    disposition=unresolved_disposition,
                    evidence=evidence,
                    reason=resolution.reason or resolution.clarification,
                )
            resolution.completeness = MeaningCompletenessResult(
                complete=True, allows_execution=False, facts=facts
            )
            return resolution

        add(
            "family",
            candidate.family,
            candidate.family,
            disposition="compiled",
            target=f"family.{meaning.family}",
        )

        if candidate.metric_concept:
            metric_text = _normalized_text(candidate.metric_concept).replace("_", " ")
            candidate_metric, _ = _metric_and_role(metric_text, None, meaning.role)
            try:
                candidate_metric = get_metric(candidate.metric_concept).metric_id
            except KeyError:
                pass
            broad_comparison_metric = bool(
                meaning.family == "comparison"
                and meaning.comparison_metrics
                and re.search(
                    r"\b(?:numbers|statistics|stats|records|performance)\b", metric_text
                )
            )
            canonical_metric_words = meaning.metric.replace("_", " ")
            count_alias = bool(
                meaning.metric == "yorker_count"
                and "yorker" in metric_text
                and re.search(
                    r"\b(?:most|fewest|how many|count|number)\b",
                    _normalized_text(question),
                )
            )
            dismissal_share = bool(
                meaning.metric == "dismissal_type_percentage"
                and is_dismissal_share_concept(metric_text)
            )
            if (
                candidate_metric == meaning.metric
                or dismissal_share
                or (
                    candidate_metric is None
                    and metric_text in _normalized_text(question)
                )
                or canonical_metric_words in metric_text
                or count_alias
                or broad_comparison_metric
            ):
                add(
                    "metric",
                    candidate.metric_concept,
                    candidate.metric_concept,
                    disposition="compiled",
                    target=f"metric.{meaning.metric}",
                )
            elif metric_text not in _normalized_text(question):
                add(
                    "metric",
                    candidate.metric_concept,
                    candidate.metric_concept,
                    disposition="explicitly_replaced_removed",
                    target=f"metric.{meaning.metric}",
                    reason="Explicit question wording replaced a contradictory extracted metric.",
                )
            else:
                add(
                    "metric",
                    candidate.metric_concept,
                    candidate.metric_concept,
                    disposition="unsupported",
                    reason="The extracted metric is not registered.",
                )

        if candidate.role:
            disposition = (
                "compiled"
                if candidate.role == meaning.role
                else "explicitly_replaced_removed"
            )
            add(
                "role",
                candidate.role,
                candidate.role,
                disposition=disposition,
                target=f"role.{meaning.role}",
            )

        for entity in candidate.entities:
            target = None
            disposition = "unsupported"
            if entity.kind == "player":
                if (
                    _normalized_text(entity.name)
                    in {
                        "player",
                        "players",
                        "batter",
                        "batters",
                        "bowler",
                        "bowlers",
                        "batsman",
                        "batsmen",
                    }
                    and meaning.role in meaning.group_by
                ):
                    target = f"group_by.{meaning.role}"
                    disposition = "compiled"
                else:
                    cohort = self._explicit_filters(
                        entity.name, _normalized_text(entity.name)
                    )
                    cohort_matches = [
                        key
                        for key, value in cohort.items()
                        if meaning.filters.get(key) == value
                    ]
                    if cohort_matches:
                        target = f"filter.{cohort_matches[0]}"
                        disposition = "compiled"
                    matches = _extract_players(entity.name, self.available_players)
                    if len(matches) == 1:
                        player = matches[0]
                        if (
                            player in meaning.participants
                            or player in meaning.filters.values()
                        ):
                            target = f"entity.player.{player}"
                            disposition = "compiled"
            elif entity.kind == "team":
                if _normalized_text(entity.name) in {"team", "teams"} and (
                    meaning.subject == "team" or "team" in meaning.group_by
                ):
                    target, disposition = "group_by.team", "compiled"
                elif entity.name in meaning.filters.values():
                    target, disposition = f"entity.team.{entity.name}", "compiled"
            elif entity.kind == "venue":
                matches = venue_alias_matches(entity.name, self.available_venues)
                if any(venue in meaning.filters.values() for venue in matches):
                    target, disposition = "filter.venue", "compiled"
            add(
                "entity",
                entity.name,
                entity.name,
                disposition=disposition,
                target=target,
            )
            add(
                "relationship",
                entity.relationship,
                entity.relationship,
                disposition=disposition,
                target=target,
            )
            if entity.role:
                add(
                    "role",
                    entity.role,
                    entity.role,
                    disposition=(
                        "compiled"
                        if entity.role == meaning.role
                        else "explicitly_replaced_removed"
                    ),
                    target=f"role.{meaning.role}",
                )

        for dimension in [*candidate.breakdown_dimensions, *candidate.split_dimensions]:
            normalized = breakdown_dimensions("by " + dimension.replace("_", " "))
            target_dimension = normalized[0] if len(normalized) == 1 else dimension
            if not normalized and is_dismissal_type_concept(dimension):
                target_dimension = "dismissal_type"
            if target_dimension in {"season", "annual"} and "year" in meaning.group_by:
                target_dimension = "year"
            compiled = (
                target_dimension in meaning.group_by
                or target_dimension == meaning.split_by
            )
            add(
                "dimension",
                dimension,
                dimension,
                disposition="compiled" if compiled else "unsupported",
                target=f"dimension.{target_dimension}" if compiled else None,
            )

        for fact in candidate.filters:
            normalized = self._candidate_filter(fact)
            compiled_items = [
                (key, value)
                for key, value in normalized.items()
                if meaning.filters.get(key) == value
                or (
                    meaning.family == "split"
                    and key
                    == {
                        "phase": "phase",
                        "batter_hand": "batter_hand",
                        "bowling_style_group": "bowling_style",
                        "over_range": "over_range",
                    }.get(meaning.split_by)
                )
            ]
            dismissal_target = _dismissal_type_filter_target(normalized, meaning)
            if dismissal_target is not None and not compiled_items:
                compiled_items = [("dismissal_type", normalized["dismissal_type"])]
            relationship_target = _relationship_filter_target(fact, meaning)
            axis_target = _axis_filter_target(fact, meaning)
            compiled = (
                bool(compiled_items)
                or relationship_target is not None
                or axis_target is not None
                or _is_semantic_noop_filter(fact, meaning)
            )
            target = (
                dismissal_target
                if dismissal_target is not None
                else f"filter.{compiled_items[0][0]}"
                if compiled_items
                else (
                    relationship_target
                    if relationship_target is not None
                    else axis_target
                    if axis_target is not None
                    else "deterministic_scope" if compiled else None
                )
            )
            add(
                "filter",
                fact.concept,
                fact.values,
                disposition="compiled" if compiled else "unsupported",
                target=target,
                evidence=fact.evidence,
            )
            if fact.operator:
                operator_compiled = compiled and (
                    fact.operator in {"eq", "in"}
                    or (fact.operator == "between" and "over_range" in normalized)
                )
                add(
                    "operator",
                    fact.operator,
                    fact.operator,
                    disposition="compiled" if operator_compiled else "unsupported",
                    target=target,
                    evidence=fact.evidence,
                )
            for value in fact.values:
                add(
                    "value",
                    fact.concept,
                    value,
                    disposition="compiled" if compiled else "unsupported",
                    target=target,
                    evidence=fact.evidence,
                )

        if candidate.intent:
            expected_intent = (
                "ranking"
                if meaning.family == "ranking"
                else "comparison"
                if meaning.family in {"comparison", "split", "matchup"}
                else "value"
            )
            intent_disposition = (
                "compiled"
                if candidate.intent == expected_intent
                else "unsupported"
                if candidate.intent in _normalized_text(question)
                else "explicitly_replaced_removed"
            )
            add(
                "intent",
                candidate.intent,
                candidate.intent,
                disposition=intent_disposition,
                target=f"family.{meaning.family}",
            )
        if candidate.ordering:
            try:
                default_sort = get_metric(
                    meaning.metric, entity=meaning.role, filters=meaning.filters
                ).default_sort
            except KeyError:
                default_sort = meaning.sort_direction
            ordering_directions: dict[str, Literal["asc", "desc"]] = {
                "highest": "desc",
                "lowest": "asc",
                "ascending": "asc",
                "descending": "desc",
                "best": default_sort,
                "worst": "asc" if default_sort == "desc" else "desc",
            }
            requested_direction = ordering_directions[candidate.ordering]
            ordering_disposition = (
                "compiled"
                if requested_direction == meaning.sort_direction
                else "unsupported"
                if candidate.ordering in _normalized_text(question)
                else "explicitly_replaced_removed"
            )
            add(
                "ordering",
                candidate.ordering,
                candidate.ordering,
                disposition=ordering_disposition,
                target=f"sort.{meaning.sort_direction}",
            )
        if candidate.limit is not None:
            limit_disposition = (
                "compiled"
                if candidate.limit == meaning.limit
                else "unsupported"
                if requested_limit_from_wording(_normalized_text(question))
                == candidate.limit
                else "explicitly_replaced_removed"
            )
            add(
                "limit",
                "limit",
                candidate.limit,
                disposition=limit_disposition,
                target="limit" if candidate.limit == meaning.limit else None,
                reason=(
                    None
                    if candidate.limit == meaning.limit
                    else "The extracted limit was not explicitly requested."
                ),
            )
        if candidate.sample_threshold is not None:
            unit = candidate.sample_threshold.unit.replace(" ", "_")
            actual = (
                getattr(meaning.minimum_sample, unit, None)
                if meaning.minimum_sample
                else None
            )
            actual_unit = unit
            if (
                actual is None
                and meaning.minimum_sample is not None
                and unit == "balls"
            ):
                actual = meaning.minimum_sample.legal_balls
                actual_unit = "legal_balls"
            add(
                "sample_threshold",
                unit,
                candidate.sample_threshold.value,
                disposition=(
                    "compiled"
                    if actual == candidate.sample_threshold.value
                    else "unsupported"
                ),
                target=(
                    f"minimum_sample.{actual_unit}"
                    if actual == candidate.sample_threshold.value
                    else None
                ),
                evidence=candidate.sample_threshold.evidence,
            )

        blocking = [
            fact
            for fact in facts
            if fact.disposition in {"unsupported", "clarification_required"}
        ]
        completeness = MeaningCompletenessResult(
            complete=True, allows_execution=not blocking, facts=facts
        )
        if blocking:
            labels = ", ".join(dict.fromkeys(fact.concept for fact in blocking))
            return MeaningResolution(
                status=MeaningStatus.unsupported,
                reason=f"Unsupported extracted analytical fact: {labels}.",
                candidate_sources=resolution.candidate_sources,
                completeness=completeness,
            )
        resolution.completeness = completeness
        return resolution

    def resolve_refinement(
        self,
        question: str,
        state: Mapping[str, object] | BaseModel | None,
        previous: LanguageMeaningCandidate,
        refinement: LanguageMeaningCandidate,
    ) -> MeaningResolution:
        # No new user evidence arrived. Distinct viable alternatives cannot be
        # resolved just because the second model happens to prefer one of them.
        alternatives = {
            _metric_and_role(_normalized_text(option).replace("_", " "), None)
            for option in previous.ambiguity_candidates
        }
        if len(alternatives) > 1:
            result = self.resolve_candidate(question, state, previous)
        else:
            merged = refinement.model_copy(
                update={
                    "entities": list(
                        {
                            e.model_dump_json(): e
                            for e in [*previous.entities, *refinement.entities]
                        }.values()
                    ),
                    "filters": list(
                        {
                            f.model_dump_json(): f
                            for f in [*previous.filters, *refinement.filters]
                        }.values()
                    ),
                    "breakdown_dimensions": list(
                        dict.fromkeys(
                            [
                                *previous.breakdown_dimensions,
                                *refinement.breakdown_dimensions,
                            ]
                        )
                    ),
                    "split_dimensions": list(
                        dict.fromkeys(
                            [*previous.split_dimensions, *refinement.split_dimensions]
                        )
                    ),
                    "sample_threshold": previous.sample_threshold
                    or refinement.sample_threshold,
                }
            )
            result = self.resolve_candidate(question, state, merged, source="pro")
        result.candidate_sources = list(
            dict.fromkeys([*result.candidate_sources, "flash", "pro"])
        )
        return result

    def _candidate_filter(self, fact: ExpressedFilter) -> dict[str, object]:
        concept = _normalized_text(fact.concept).replace("_", " ")
        values = fact.values
        categories = [canonical_dismissal_type(value) for value in values]
        if is_dismissal_type_concept(concept) or (
            categories and all(categories)
        ):
            # Registered categorical dimension: every value must map to one
            # literal stored category or the whole filter stays unresolved.
            if not categories or not all(categories):
                return {}
            return {"dismissal_type": list(dict.fromkeys(cast(list[str], categories)))}
        # Language labels are intentionally not database column names. Normalize
        # categories and their source wording before interpreting requested values.
        if "phase" in concept or "over" in concept:
            evidence = _normalized_text(fact.evidence)
            phase = _phase(evidence)
            if phase:
                return {"phase": phase}
            over_range = _over_range(evidence)
            if over_range:
                return {"over_range": over_range}
            concept = "phase" if "phase" in concept else "overs"
        elif "bowl" in concept and any(word in concept for word in {"style", "type"}):
            concept = "bowling style"
        elif "hand" in concept and ("batt" in concept or "opponent" in concept):
            concept = "batter hand"
        elif "year" in concept:
            concept = "years"
        if concept in {"year", "years"}:
            try:
                years = sorted({int(v) for v in values})
            except (ValueError, TypeError):
                return {}
            return (
                {"years": years}
                if years and all(1900 <= y <= 2100 for y in years)
                else {}
            )
        if concept == "innings" and len(values) == 1 and str(values[0]) in {"1", "2"}:
            return {"innings": int(values[0])}
        if concept in {"over range", "overs"} and len(values) == 2:
            try:
                start, end = [int(v) for v in values]
            except (ValueError, TypeError):
                return {}
            return {"over_range": [start, end]} if 1 <= start <= end <= 50 else {}
        text = " ".join(str(v) for v in values)
        if concept in {
            "phase",
            "bowling style",
            "batter hand",
            "venue",
            "opposition",
            "opponent",
        }:
            normalized = self._explicit_filters(
                fact.evidence, _normalized_text(fact.evidence)
            )
            if not normalized:
                normalized = self._explicit_filters(text, _normalized_text(text))
            key = "opposition" if concept == "opponent" else concept.replace(" ", "_")
            if key == "bowling_style" and text.lower() in {"pace", "spin"}:
                return {key: text.lower()}
            return {key: normalized[key]} if key in normalized else {}
        return {}

    def _meaning_from_language(
        self,
        question: str,
        state: Mapping[str, object] | None,
    ) -> MeaningResolution:
        from backend.app.cricket_analytics.canonical_comparisons import (
            resolve_comparison,
        )
        from backend.app.cricket_analytics.canonical_matchups import resolve_matchup
        from backend.app.cricket_analytics.canonical_splits import resolve_split
        from backend.app.cricket_analytics.canonical_trends import resolve_trend
        from backend.app.cricket_analytics.canonical_dismissals import (
            resolve_dismissal_types,
        )

        # A one-batter categorical breakdown ("caught versus bowled") is not a
        # two-player comparison or a matchup, so it is claimed first.
        dismissal_types = resolve_dismissal_types(self, question, state)
        if dismissal_types is not None:
            return dismissal_types

        trend = resolve_trend(self, question, state)
        if trend is not None:
            return trend
        split = resolve_split(self, question, state)
        if split is not None:
            return split
        comparison = resolve_comparison(self, question, state)
        if comparison is not None:
            return comparison
        matchup = resolve_matchup(self, question, state)
        if matchup is not None:
            return matchup
        lowered = _normalized_text(question)
        dimensions = breakdown_dimensions(lowered)
        phases = {
            phase
            for phase in ("powerplay", "middle", "death")
            if re.search(rf"\b{phase}\b", lowered)
        }
        both_hands = bool(
            re.search(r"\b(?:left|lefties|lhb)", lowered)
            and re.search(r"\b(?:right|righties|rhb)", lowered)
        )
        if (
            not dimensions
            and (
                _BREAKDOWN_WORDS.search(lowered)
                or _OTHER_FAMILY_WORDS.search(lowered)
                or _OUTSIDE_SLICE_WORDING.search(lowered)
                or len(phases) > 1
                or both_hands
            )
        ) or re.search(r"\b(?:matchup|head.to.head|immediately after)\b", lowered):
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
        if (
            dimensions
            and not players
            and _extract_players(
                question,
                list(set(ALIASES.values()) | set(_CANONICAL_PLAYER_ALIASES.values())),
            )
        ):
            return MeaningResolution(
                status=MeaningStatus.clarification,
                clarification="Which available player should this breakdown describe?",
            )
        if len(players) > 1:
            return MeaningResolution(status=MeaningStatus.not_applicable)
        player = players[0] if players else None
        if player and not dimensions and re.search(r"\bwho\b.*\bdismiss", lowered):
            return MeaningResolution(status=MeaningStatus.not_applicable)

        if player and re.search(
            r"\b(?:rank (?:opposing )?bowlers|toughest bowler|which (?:pace |spin )?bowler|who controls|who finds|scoring record)\b",
            lowered,
        ):
            return MeaningResolution(status=MeaningStatus.not_applicable)
        if player is not None and re.search(r"\bwhich\s+(?:bowler|batter)\b", lowered):
            return MeaningResolution(status=MeaningStatus.not_applicable)
        state_players = state.get("players") if state else None
        if (
            player is None
            and isinstance(state_players, list)
            and len(state_players) == 1
        ):
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
        family: Literal["direct", "ranking", "breakdown"] | None = (
            "breakdown"
            if dimensions
            else "ranking" if ranking or state_ranking else "direct" if player else None
        )
        if family is None:
            return MeaningResolution(status=MeaningStatus.not_applicable)

        if (
            "strike rate" in lowered
            and "batting strike rate" not in lowered
            and "bowling strike rate" not in lowered
            and self.player_roles.primary_role(player) == "bowler"
        ):
            return MeaningResolution(
                status=MeaningStatus.clarification,
                clarification="Do you mean batting strike rate or bowling strike rate?",
                clarification_options=["batting strike rate", "bowling strike rate"],
            )

        metric_text = (
            re.sub(r"\b(?:bowler|bowling) (?:styles?|types?|categories)\b", "", lowered)
            if dimensions
            else lowered
        )
        # “Produces dots against” describes bowling pressure unless a count is
        # explicit. Preserve the established rate meaning of this idiom.
        pressure = bool(
            dimensions
            and player
            and "against" in lowered
            and re.search(r"\b(?:generates?|produces?)\b.*\b(?:dot|false)[- ]", lowered)
        )
        if pressure and not re.search(r"\b(?:count|number of|how many)\b", lowered):
            metric_text = re.sub(
                r"\bmost dot balls\b", "dot-ball percentage", metric_text
            )
        metric, role = _metric_and_role(
            metric_text, player, self.player_roles.primary_role(player)
        )
        if pressure and metric in {
            "dot_balls",
            "batter_dot_ball_percentage",
            "false_shot_percentage",
        }:
            role = "bowler"
            metric = {
                "dot_balls": "bowler_dot_balls",
                "batter_dot_ball_percentage": "bowler_dot_ball_percentage",
            }.get(metric, metric)

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
                        (
                            item
                            for item in state_group_by
                            if item in {"batter", "bowler"}
                        ),
                        None,
                    )
        if metric is None or role is None:
            if "strike rate" in lowered:
                return MeaningResolution(
                    status=MeaningStatus.clarification,
                    clarification="Do you mean batting strike rate or bowling strike rate?",
                    clarification_options=[
                        "batting strike rate",
                        "bowling strike rate",
                    ],
                )
            return MeaningResolution(
                status=MeaningStatus.unsupported,
                reason="No supported direct or ranking metric was identified.",
            )

        filters = _state_filters(state)
        filters.update(self._explicit_filters(question, lowered))
        if "yorker" in lowered and metric not in {"yorker_count", "yorker_percentage"}:
            filters["length"] = "YORKER"
        filters.pop("batter", None)
        filters.pop("bowler", None)
        if player:
            filters["batter" if pressure else role] = player

        if family == "breakdown":
            # Enumerating phases/hands selects categories, not a single row filter.
            if len(phases) > 1:
                filters.pop("phase", None)
            if both_hands:
                filters.pop("batter_hand", None)
        limit = (
            _ranking_limit(lowered)
            if family == "ranking"
            else requested_limit_from_wording(lowered) if family == "breakdown" else 10
        )
        direction = (
            "desc"
            if family == "direct"
            else requested_sort_direction(
                re.sub(r"\bat least\b", "minimum", lowered),
                metric,
                role,
                group_by=dimensions or [role],
                filters=filters,
            )
            or get_metric(metric, entity=role, filters=filters).default_sort
        )
        if (
            family == "breakdown"
            and "quietest" in lowered
            and metric in {"batter_dot_ball_percentage", "false_shot_percentage"}
        ):
            direction = "desc"
        sample = _explicit_sample(lowered, metric)
        sample_is_explicit = sample is not None
        if family in {"ranking", "breakdown"} and sample is None:
            defaults = get_metric(
                metric, entity=role, filters=filters
            ).minimum_sample.as_dict()
            sample = MinimumSampleSpec(**defaults) if defaults else None
        return MeaningResolution(
            status=MeaningStatus.resolved,
            meaning=CanonicalCricketMeaning(
                family=cast(Literal["direct", "ranking", "breakdown"], family),
                role=cast(Literal["batter", "bowler"], role),
                metric=metric,
                filters=filters,
                group_by=dimensions or [role],
                limit=limit,
                sort_direction=cast(Literal["asc", "desc"], direction),
                minimum_sample=sample,
                minimum_sample_explicit=sample_is_explicit,
            ),
            candidate_sources=["deterministic"],
        )

    def _explicit_filters(self, question: str, lowered: str) -> dict[str, object]:
        filters: dict[str, object] = {}
        if re.search(r"\b(?:chasing|second innings|innings 2)\b", lowered):
            filters["innings"] = 2
        elif re.search(r"\b(?:batting first|first innings|innings 1)\b", lowered):
            filters["innings"] = 1
        phase = _phase(lowered)
        if phase:
            filters["phase"] = phase
        else:
            over_range = _over_range(lowered)
            if over_range:
                filters["over_range"] = over_range
        years = sorted(
            {int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", lowered)}
        )
        if years:
            filters["years"] = years
            if re.search(
                r"\b(?:(?:since|after)\s+\d{4}|from\s+\d{4}\s+onwards?)", lowered
            ):
                filters["year_mode"] = "after"
            elif re.search(r"\bbefore\s+\d{4}", lowered):
                filters["year_mode"] = "before"
        for value, pattern in (
            ("SHORT", r"\bshort[- ]balls?\b"),
            ("GOOD_LENGTH", r"\bgood[- ]length\b"),
            ("FULL", r"\bfull[- ]balls?\b"),
        ):
            if re.search(pattern, lowered):
                filters["length"] = value
        for value, phrase in (
            ("OUTSIDE_OFFSTUMP", "outside off stump"),
            ("ON_THE_STUMPS", "on the stumps"),
            ("DOWN_LEG", "down leg"),
        ):
            if phrase in lowered:
                filters["line"] = value
        style = requested_bowling_style(lowered)
        if style is None and re.search(r"\b(?:facing|face)\s+spin\b", lowered):
            style = "spin"
        if style is None:
            cohort = re.search(r"\b(pace|spin) bowlers?\b", lowered)
            style = cohort.group(1) if cohort else None
        if style:
            filters["bowling_style"] = style
        if re.search(
            r"\b(?:lefties|lhb|left[- ]hand(?:ed)?(?: batters?|ers?)?)\b", lowered
        ):
            filters["batter_hand"] = "LHB"
        elif re.search(
            r"\b(?:righties|rhb|right[- ]hand(?:ed)?(?: batters?|ers?)?)\b", lowered
        ):
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


def _is_dismissal_type_resolution(resolution: MeaningResolution) -> bool:
    from backend.app.cricket_analytics.canonical_dismissals import (
        DISMISSAL_TYPE_SOURCE,
    )

    return DISMISSAL_TYPE_SOURCE in resolution.candidate_sources


def _candidate_fact_inventory(
    candidate: LanguageMeaningCandidate,
) -> list[tuple[str, str, object | None, str | None]]:
    facts: list[tuple[str, str, object | None, str | None]] = [
        ("family", candidate.family, candidate.family, None)
    ]
    if candidate.metric_concept:
        facts.append(
            ("metric", candidate.metric_concept, candidate.metric_concept, None)
        )
    if candidate.role:
        facts.append(("role", candidate.role, candidate.role, None))
    for entity in candidate.entities:
        facts.append(("entity", entity.name, entity.name, None))
        facts.append(("relationship", entity.relationship, entity.relationship, None))
        if entity.role:
            facts.append(("role", entity.role, entity.role, None))
    for dimension in [*candidate.breakdown_dimensions, *candidate.split_dimensions]:
        facts.append(("dimension", dimension, dimension, None))
    for fact in candidate.filters:
        facts.append(("filter", fact.concept, fact.values, fact.evidence))
        if fact.operator:
            facts.append(("operator", fact.operator, fact.operator, fact.evidence))
        facts.extend(
            ("value", fact.concept, value, fact.evidence) for value in fact.values
        )
    if candidate.intent:
        facts.append(("intent", candidate.intent, candidate.intent, None))
    if candidate.ordering:
        facts.append(("ordering", candidate.ordering, candidate.ordering, None))
    if candidate.limit is not None:
        facts.append(("limit", "limit", candidate.limit, None))
    if candidate.sample_threshold:
        facts.append(
            (
                "sample_threshold",
                candidate.sample_threshold.unit,
                candidate.sample_threshold.value,
                candidate.sample_threshold.evidence,
            )
        )
    return facts


def _is_semantic_noop_filter(
    fact: ExpressedFilter, meaning: CanonicalCricketMeaning
) -> bool:
    concept = _normalized_text(fact.concept).replace("_", " ")
    values = {_normalized_text(str(value)) for value in fact.values}
    if concept in {"format", "match format", "match type", "competition"}:
        return bool(values) and values <= {
            "odi",
            "odis",
            "one day international",
            "one day internationals",
        }
    if "deliver" in concept or "ball" in concept:
        if values and values <= {"legal", "legal balls", "legal deliveries"}:
            return get_metric(meaning.metric).denominator == "legal_balls"
        if values and values <= {"yorker", "yorkers"}:
            return meaning.metric in {"yorker_count", "yorker_percentage"}
    if concept in {"player", "batter", "bowler"}:
        return any(value in meaning.filters.values() for value in fact.values)
    if "dismissal_type" in meaning.group_by and is_dismissal_type_concept(concept):
        # "dismissed"/"out" restates the dismissal metric, not a category.
        return bool(values) and values <= {
            "dismissed",
            "dismissal",
            "dismissals",
            "out",
            "got out",
        }
    return False


def _dismissal_type_filter_target(
    normalized: Mapping[str, object], meaning: CanonicalCricketMeaning
) -> str | None:
    """Every extracted category must be one the compiled meaning returns."""
    requested = normalized.get("dismissal_type")
    if not isinstance(requested, list) or "dismissal_type" not in meaning.group_by:
        return None
    compiled = meaning.filters.get("dismissal_type")
    if isinstance(compiled, list):
        return (
            "filter.dismissal_type"
            if set(requested) <= set(compiled)
            else None
        )
    # An unrestricted breakdown enumerates every registered category.
    return (
        "dimension.dismissal_type"
        if set(requested) <= set(DISMISSAL_TYPE_REGISTRY)
        else None
    )


def _relationship_filter_target(
    fact: ExpressedFilter, meaning: CanonicalCricketMeaning
) -> str | None:
    concept = _normalized_text(fact.concept).replace("_", " ")
    values = {_normalized_lookup_text(str(value)) for value in fact.values}
    relationship_keys = {
        "batter dismissed": "batter",
        "dismissed batter": "batter",
        "batter": "batter",
        "bowler faced": "bowler",
        "opposing bowler": "bowler",
        "bowler": "bowler",
    }
    key = relationship_keys.get(concept)
    if key is None:
        return None
    canonical = meaning.filters.get(key)
    if isinstance(canonical, str) and _normalized_lookup_text(canonical) in values:
        return f"filter.{key}"
    return None


def _axis_filter_target(
    fact: ExpressedFilter, meaning: CanonicalCricketMeaning
) -> str | None:
    concept = _normalized_text(fact.concept).replace("_", " ")
    axes = (
        ("phase", "phase"),
        ("bowling type", "bowling_style_group"),
        ("bowling style", "bowling_style_group"),
        ("batter hand", "batter_hand"),
        ("handedness", "batter_hand"),
    )
    for phrase, canonical in axes:
        if phrase not in concept:
            continue
        if canonical == meaning.split_by or canonical in meaning.group_by:
            return f"dimension.{canonical}"
    return None


def compile_canonical_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
    if meaning.family == "trend":
        from backend.app.cricket_analytics.canonical_trends import compile_trend_meaning

        return compile_trend_meaning(meaning)
    if meaning.family == "split":
        from backend.app.cricket_analytics.canonical_splits import compile_split_meaning

        return compile_split_meaning(meaning)
    if meaning.family == "comparison":
        from backend.app.cricket_analytics.canonical_comparisons import (
            compile_comparison_meaning,
        )

        return compile_comparison_meaning(meaning)
    if meaning.family == "matchup":
        from backend.app.cricket_analytics.canonical_matchups import (
            compile_matchup_meaning,
        )

        return compile_matchup_meaning(meaning)
    if meaning.family == "breakdown":
        return compile_breakdown_meaning(meaning)
    return _compile_aggregate_meaning(meaning)


def compile_breakdown_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
    if (
        meaning.family != "breakdown"
        or not meaning.group_by
        or any(dimension not in BREAKDOWN_DIMENSIONS for dimension in meaning.group_by)
    ):
        raise ValueError("A breakdown requires supported canonical dimensions.")
    return _compile_aggregate_meaning(meaning)


def _compile_aggregate_meaning(meaning: CanonicalCricketMeaning) -> CricketQueryPlan:
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


def _metric_and_role(
    lowered: str, player: str | None, role_hint: str | None = None
) -> tuple[str | None, str | None]:
    if requests_six_count(lowered):
        return "six_count", "batter"
    if requests_four_count(lowered):
        return "four_count", "batter"
    if "boundary runs" in lowered:
        return "boundary_runs", "batter"
    if requests_boundary_percentage(lowered):
        bowling = bool(
            re.search(r"\b(?:bowlers?|concede|conceded|concedes)\b", lowered)
        )
        return "boundary_percentage", "bowler" if bowling else "batter"
    if re.search(
        r"\b(?:how many|number of|count of|most|fewest)\s+boundar(?:y|ies)\b",
        lowered,
    ):
        return "boundary_ball_count", "batter"
    if "runs conceded" in lowered or "runs given away" in lowered:
        return ("economy_rate" if "per over" in lowered else "runs_conceded"), "bowler"
    if "wickets per over" in lowered:
        return "wickets_per_over", "bowler"
    if "balls faced" in lowered and not "dot" in lowered:
        return "balls_faced", "batter"
    if "overs" in lowered and "bowled" in lowered and "most" in lowered:
        return "overs_bowled", "bowler"
    if re.search(r"\bdismiss(?:al|als|es|ed)?\b", lowered):
        return "dismissals", "batter"
    if "yorker" in lowered and not re.search(
        r"\b(?:economy|expensive|wickets?|runs? conceded|false[- ]shots?|dot[- ]balls?|boundar(?:y|ies)|strike rate|average)\b",
        lowered,
    ):
        count = bool(
            re.search(
                r"\b(?:(?:most|fewest) yorkers|yorker (?:count|volume)|how many yorkers)\b",
                lowered,
            )
        ) or ("not yorker rate" in lowered)
        return ("yorker_count" if count else "yorker_percentage"), "bowler"
    if "boundar" in lowered:
        # A boundary-related phrase that did not match a registered count, run,
        # or percentage meaning must fail closed instead of borrowing another
        # metric merely because words such as "average" also appear.
        return None, None
    if "econom" in lowered or "expensive" in lowered or "concede" in lowered:
        return "economy_rate", "bowler"
    if re.search(r"\bwickets?\b", lowered):
        return "wickets_taken", "bowler"
    if "false shots per over" in lowered or "false-shot per over" in lowered:
        return "false_shots_per_over", "bowler"
    if "false shot" in lowered or "false-shot" in lowered:
        bowling = bool(re.search(r"\b(?:bowlers?|induces?|forces?|causes?)\b", lowered))
        return "false_shot_percentage", "bowler" if bowling else "batter"
    if "dot" in lowered:
        bowling = (
            bool(
                re.search(
                    r"\b(?:bowlers?|legal (?:balls|deliveries)|to (?:left|right)[- ]hand)\b",
                    lowered,
                )
            )
            or role_hint == "bowler"
        )
        if re.search(r"\b(?:as a batter|batting|faced)\b", lowered):
            bowling = False
        if re.search(
            r"\b(?:how many|number of|count|most|fewest)\b", lowered
        ) and not re.search(
            r"\b(?:percentage|rate|share|percent|fraction|proportion)\b", lowered
        ):
            return ("bowler_dot_balls" if bowling else "dot_balls"), (
                "bowler" if bowling else "batter"
            )
        return (
            "bowler_dot_ball_percentage" if bowling else "batter_dot_ball_percentage",
            "bowler" if bowling else "batter",
        )
    if "bowling strike rate" in lowered:
        return "bowling_strike_rate", "bowler"
    if (
        "strike rate" in lowered
        or "scoring rate" in lowered
        or "fastest scorer" in lowered
        or "fastest" in lowered
        or "quickly" in lowered
    ):
        if re.search(r"\bbowlers?\b", lowered):
            return "bowling_strike_rate", "bowler"
        return "batting_strike_rate", "batter"
    if "bowling average" in lowered:
        return "bowling_average", "bowler"
    if "average" in lowered:
        return "batting_average", "batter"
    if "productive" in lowered or re.search(
        r"\b(?:runs?|run tally|run totals?|scorers?)\b", lowered
    ):
        return "runs_scored", "batter"
    if "legal balls" in lowered:
        return "legal_balls", "bowler"
    return None, None


def _extract_player(question: str, available_players: Sequence[str]) -> str | None:
    players = _extract_players(question, available_players)
    return players[0] if players else None


def _extract_players(question: str, available_players: Sequence[str]) -> list[str]:
    lowered = question.lower().replace("’", "'")
    aliases = _player_aliases(available_players)
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


def _player_aliases(available_players: Sequence[str]) -> dict[str, str]:
    aliases: dict[str, str] = {key.lower(): value for key, value in ALIASES.items()}
    initial_aliases: dict[str, list[str]] = {}
    for player in available_players:
        aliases[player.lower()] = player
        parts = player.lower().split()
        if len(parts) > 1:
            alias = parts[0][0] + " " + " ".join(parts[1:])
            initial_aliases.setdefault(alias, []).append(player)
    for alias, players in initial_aliases.items():
        if len(players) == 1:
            aliases[alias] = players[0]
            aliases[alias.replace(" ", ". ", 1)] = players[0]
    aliases.update(_CANONICAL_PLAYER_ALIASES)
    return aliases


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
    if re.search(
        r"\b(?:power\s*play|opening ten|first ten|overs?\s*1\s*(?:-|to|–)\s*10)\b",
        lowered,
    ):
        return "powerplay"
    if re.search(
        r"\b(?:middle(?:[- ]overs?| phase)?|overs?\s*11\s*(?:-|to|–)\s*40)\b", lowered
    ):
        return "middle"
    if re.search(
        r"\b(?:death|final overs?|over\s*41\s+onwards|after\s+over\s*40)\b", lowered
    ):
        return "death"
    return None


def _over_range(lowered: str) -> list[int] | None:
    ordinal = r"(?:st|nd|rd|th)?"
    patterns = (
        r"\bbetween\s+overs?\s+(\d{1,2})\s*(?:and|to|&|[-–—])\s*(\d{1,2})\b",
        r"\bovers?\s*(\d{1,2})\s*(?:-|to|–|—)\s*(\d{1,2})\b",
        rf"\bfrom\s+(?:over\s+)?(?:the\s+)?(\d{{1,2}}){ordinal}\s+"
        rf"(?:through|to|until)\s+(?:over\s+)?(?:the\s+)?(\d{{1,2}}){ordinal}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        start, end = int(match.group(1)), int(match.group(2))
        return [start, end] if 1 <= start <= end <= 50 else None
    return None


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
        if "inning" in match.group(0):
            return MinimumSampleSpec(innings=value)
        explicit_legal = len(match.groups()) > 1 and bool(match.group(2))
        denominator = get_metric(metric).denominator
        if explicit_legal or denominator == "legal_balls":
            return MinimumSampleSpec(legal_balls=value)
        return MinimumSampleSpec(balls=value)
    return None


def _state_mapping(
    value: Mapping[str, object] | BaseModel | None
) -> Mapping[str, object] | None:
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
    normalized = " ".join(
        value.lower()
        .replace("’", "'")
        .replace("–", "-")
        .replace("strike-rate", "strike rate")
        .split()
    )
    # Expand language-level cricket abbreviations before family and metric
    # resolution so they receive exactly the same ownership and ambiguity rules
    # as their long forms.
    normalized = re.sub(r"\bs\.?r\.?\b", "strike rate", normalized)
    return normalized


def _normalized_lookup_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
