"""Registered, database-identifiable match facts.

Language rules here only recognise what a question asks for. Competition
identity, match selection and fact values are resolved deterministically from
database metadata, and every requested match-identity concept is accounted for
before execution.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec


@dataclass(frozen=True, slots=True)
class MatchFactDefinition:
    fact_type: str
    source_field: str | None
    label: str
    value_column: str | None = None


MATCH_FACT_REGISTRY = {
    "winner": MatchFactDefinition("winner", "winner", "Match winner", "Match Winner"),
    "toss": MatchFactDefinition("toss", "toss", "Toss winner", "Toss Winner"),
    "team_total": MatchFactDefinition("team_total", None, "Team innings total"),
}

# The source uses "-" when a match has no recorded winner (for example a tie
# decided outside the stored result, or no result). It is never a team.
NO_RECORDED_WINNER_VALUES = frozenset({"-"})


@dataclass(frozen=True, slots=True)
class CompetitionDefinition:
    """A tournament family and the exact stored competition name per edition."""

    key: str
    label: str
    alias_pattern: str
    stored_by_year: Mapping[int, str]
    single_final: bool = True


COMPETITION_REGISTRY: tuple[CompetitionDefinition, ...] = (
    CompetitionDefinition(
        key="odi_world_cup",
        label="ICC Cricket World Cup",
        alias_pattern=(
            r"\b(?:icc\s+)?(?:men'?s\s+)?(?:odi\s+|cricket\s+)?world\s*cup\b|\bcwc\b"
        ),
        stored_by_year={
            2007: "ICC World Cup",
            2011: "ICC Cricket World Cup",
            2015: "ICC Cricket World Cup",
            2019: "ICC Cricket World Cup",
            2023: "World Cup 2023",
        },
    ),
    CompetitionDefinition(
        key="champions_trophy",
        label="ICC Champions Trophy",
        alias_pattern=r"\b(?:icc\s+)?champions\s+trophy\b",
        stored_by_year={
            year: "ICC Champions Trophy" for year in (2006, 2009, 2013, 2017)
        },
    ),
    CompetitionDefinition(
        key="asia_cup",
        label="Asia Cup",
        alias_pattern=r"\basia\s+cup\b",
        stored_by_year={
            year: "Asia Cup" for year in (2008, 2010, 2012, 2014, 2018, 2023)
        },
    ),
)

WORLD_CUP_COMPETITIONS_BY_YEAR = dict(COMPETITION_REGISTRY[0].stored_by_year)

# Stored competitions whose edition ends in exactly one final. Only these may
# use the latest-date final rule; bilateral series, tri-series with
# best-of-three finals, qualifiers and leagues are never guessed.
SINGLE_FINAL_COMPETITIONS = frozenset(
    stored
    for definition in COMPETITION_REGISTRY
    if definition.single_final
    for stored in definition.stored_by_year.values()
)

# Words that turn a registered alias into a different event (for example the
# T20 World Cup or the World Cup Super League). They must never broaden to the
# registered ODI tournament.
_OTHER_EVENT_PREFIX = re.compile(
    r"(?:\bt20i?|\btwenty20|\bwomen'?s|\bwomen|\bu-?19|\bunder[- ]19|\byouth|\bafro-)\s*$"
)
_OTHER_EVENT_SUFFIX = re.compile(
    r"^\s*(?:qualifiers?|qualifying|qualification|super\s+league|league|challenge)\b"
)

_STAGE_PATTERN = re.compile(
    r"\b(?:(?P<semi>semi)|(?P<quarter>quarter))[\s-]?finals?\b"
    r"|\b(?P<final>final)\b"
    r"|\b(?P<group>group|pool|league)\s+(?:stage|match|game|round)\b"
    r"|\b(?P<super>super\s+(?:sixes|six|eights?|fours?))\b"
    r"|\b(?P<opening>opening\s+(?:match|game))\b"
    r"|\b(?P<eliminator>eliminator|play-?offs?|knock-?outs?)\b"
)
_REGISTERED_STAGES = frozenset({"final"})

_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
_FUTURE_PATTERN = re.compile(
    r"\b(?:will|going to|gonna|predict(?:ion|ed)?|next|upcoming|today'?s?|tomorrow|tonight)\b"
)
_RANKING_PATTERN = re.compile(
    r"\b(?:most|fewest|highest|lowest|best|worst|top|bottom|rank(?:ed|ing)?|average|record|"
    r"matches|games|how often|times)\b"
)
# A "full toss" is a delivery type, not the coin toss.
TOSS_PATTERN = re.compile(r"(?<!full )(?<!full-)\btoss(?:es)?\b")
_TOSS_DECISION_PATTERN = re.compile(
    r"\b(?:elect(?:ed|s)?|cho(?:se|ose|osen)|decid(?:e|ed|es|ing)|decision|opt(?:ed|s)?|"
    r"(?:bat|batting|bowl|bowling|field|fielding)\s+first)\b"
)
_TOSS_AGGREGATE_PATTERN = re.compile(
    r"\btosses\b|\bhow\s+(?:many|often)\b|\bnumber\s+of\b|\btimes\b|\b(?:most|fewest)\b|"
    r"\b(?:percentage|rate|record)\b|\btoss[- ]winning\b|\btoss[- ](?:winners|losers)\b"
)
_TOSS_CONDITION_PATTERN = re.compile(
    r"\b(?:when|whenever|where|if|after|once|in\s+(?:matches|games|odis))\b"
    r"|\b(?:winning|losing)\s+the\s+toss\b"
)
_TOSS_LOSER_PATTERN = re.compile(r"\b(?:lost|lose|loses|loser)\b")
_MATCH_RESULT_PATTERN = re.compile(
    r"\b(?:match|game)\s+winner\b|\bresult\b|\boutcome\b|\band\s+(?:the\s+)?(?:match|game)\b|"
    r"\bwon\s+(?:the\s+)?(?:match|game|final|title|trophy|tournament|cup)\b"
)
_WINNER_PATTERN = re.compile(r"\b(?:won|winners?|victorious)\b|\bdid\b[^?]*\bwin\b")
_TOTAL_PATTERN = re.compile(r"\b(?:total|score|scored|make|made)\b")
_MATCH_ANCHOR_PATTERN = re.compile(r"\b(?:match|game|final)\b")
_POLAR_PATTERN = re.compile(r"^\s*(?:did|does|was|were|is|has|had)\b")


MATCH_METADATA_CANDIDATES_SQL = """
WITH matching_ids AS (
  SELECT DISTINCT p_match
  FROM analytics.deliveries_v1
  WHERE TRY_CAST(year AS INTEGER) = ? AND competition = ?
)
SELECT
  d.p_match,
  LIST(DISTINCT NULLIF(TRIM(CAST(d.year AS VARCHAR)), '')),
  LIST(DISTINCT NULLIF(TRIM(CAST(d.date AS VARCHAR)), '')),
  LIST(DISTINCT NULLIF(TRIM(CAST(d.competition AS VARCHAR)), '')),
  LIST(DISTINCT NULLIF(TRIM(CAST(d.ground AS VARCHAR)), '')),
  LIST(DISTINCT NULLIF(TRIM(CAST(d.winner AS VARCHAR)), '')),
  LIST(DISTINCT NULLIF(TRIM(CAST(d.toss AS VARCHAR)), '')),
  LIST(DISTINCT NULLIF(TRIM(CAST(d.team_bat AS VARCHAR)), '')),
  LIST(DISTINCT NULLIF(TRIM(CAST(d.team_bowl AS VARCHAR)), '')),
  COUNT(*) FILTER (WHERE NULLIF(TRIM(CAST(d.toss AS VARCHAR)), '') IS NULL),
  COUNT(*) FILTER (WHERE NULLIF(TRIM(CAST(d.winner AS VARCHAR)), '') IS NULL),
  COUNT(*)
FROM analytics.deliveries_v1 d
JOIN matching_ids ids ON ids.p_match = d.p_match
GROUP BY d.p_match
ORDER BY d.p_match
"""


@dataclass(frozen=True, slots=True)
class MatchFactIssue:
    """A requested concept that cannot be executed as asked."""

    fact_type: str
    concept: str
    requested: object
    outcome: Literal["clarification", "unsupported", "data_limitation"]
    reason: str
    evidence: str | None = None

    @property
    def disposition(self) -> str:
        return (
            "clarification_required" if self.outcome == "clarification" else "unsupported"
        )


@dataclass(frozen=True, slots=True)
class MatchFactMeaning:
    fact_type: str
    year: int | None
    competition: str | None
    stage: str | None
    team: str | None = None
    participants: tuple[str, ...] = ()
    venue: str | None = None
    polar: bool = False
    evidence: Mapping[str, str] = field(default_factory=dict)
    issues: tuple[MatchFactIssue, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.blocking_issues()

    def canonical(self) -> dict[str, object]:
        return {
            "family": "match_fact",
            "fact_type": self.fact_type,
            "year": self.year,
            "competition": self.competition,
            "stage": self.stage,
            "team": self.team,
            "participants": list(self.participants),
            "venue": self.venue,
        }

    def blocking_issues(self) -> list[MatchFactIssue]:
        issues = list(self.issues)
        raised = {issue.concept for issue in issues}
        for concept, value, label in (
            ("year", self.year, "year"),
            ("competition", self.competition, "competition"),
            ("stage", self.stage, "match stage"),
        ):
            if value is None and concept not in raised:
                issues.append(
                    MatchFactIssue(
                        fact_type="filter",
                        concept=concept,
                        requested=None,
                        outcome="clarification",
                        reason=f"Match fact requires {label}.",
                    )
                )
        return issues

    def outcome(self) -> tuple[str, str] | None:
        """Return the fail-closed outcome and message, or None when executable."""
        issues = self.blocking_issues()
        if not issues:
            return None
        limiting = [issue for issue in issues if issue.outcome != "clarification"]
        if limiting:
            status = (
                "data_limitation"
                if all(issue.outcome == "data_limitation" for issue in limiting)
                else "unsupported"
            )
            prefix = "Data limitation: " if status == "data_limitation" else ""
            return status, prefix + " ".join(
                dict.fromkeys(issue.reason for issue in limiting)
            )
        missing = [
            {"year": "year", "competition": "competition", "stage": "match stage"}[
                issue.concept
            ]
            for issue in issues
            if issue.requested is None
            and issue.concept in {"year", "competition", "stage"}
        ]
        explicit = [issue.reason for issue in issues if issue.requested is not None]
        parts: list[str] = []
        if explicit:
            parts.extend(dict.fromkeys(explicit))
        if missing:
            parts.append("Which " + ", ".join(missing) + " identifies the match?")
        return "clarification", " ".join(parts)

    def compile(self) -> CricketQueryPlan:
        filters: dict[str, object] = {}
        if self.year is not None:
            filters["years"] = [self.year]
        if self.competition is not None:
            filters["competition"] = self.competition
        if self.stage is not None:
            filters["match_stage"] = self.stage
        filters["fact_type"] = self.fact_type
        if self.team is not None:
            filters["team"] = self.team
        elif self.participants:
            filters["participants"] = list(self.participants)
        if self.venue is not None:
            filters["venue"] = self.venue
        return CricketQueryPlan(
            operation="match_fact",
            entity="team",
            metric="runs_scored",
            group_by=["team"],
            filters=filters,
            sort=SortSpec(by="runs_scored", direction="desc"),
            limit=10,
        )

    def completeness(self, question: str) -> dict[str, object]:
        facts: list[dict[str, object]] = []
        issue_concepts = {issue.concept for issue in self.blocking_issues()}

        def add_compiled(
            fact_type: str, concept: str, value: object, target: str
        ) -> None:
            if value is None or concept in issue_concepts:
                return
            facts.append(
                {
                    "fact_type": fact_type,
                    "concept": concept,
                    "requested": value,
                    "evidence": self.evidence.get(concept, question),
                    "disposition": "compiled",
                    "canonical_target": target,
                    "reason": None,
                }
            )

        add_compiled("metric", "fact_type", self.fact_type, f"match_fact.{self.fact_type}")
        add_compiled("filter", "year", self.year, "filters.years")
        add_compiled("filter", "competition", self.competition, "filters.competition")
        add_compiled("filter", "stage", self.stage, "filters.match_stage")
        add_compiled("filter", "venue", self.venue, "filters.venue")
        for participant in self.participants:
            facts.append(
                {
                    "fact_type": "entity",
                    "concept": "team",
                    "requested": participant,
                    "evidence": participant,
                    "disposition": "compiled",
                    "canonical_target": (
                        "filters.team" if participant == self.team else "filters.participants"
                    ),
                    "reason": None,
                }
            )
        for issue in self.blocking_issues():
            facts.append(
                {
                    "fact_type": issue.fact_type,
                    "concept": issue.concept,
                    "requested": issue.requested,
                    "evidence": issue.evidence or question,
                    "disposition": issue.disposition,
                    "canonical_target": None,
                    "reason": issue.reason,
                }
            )
        return {
            "complete": True,
            "allows_execution": self.complete,
            "facts": facts,
        }


def _normalized(question: str) -> str:
    return " ".join(
        question.lower().replace("’", "'").replace("–", "-").replace("—", "-").split()
    )


def is_polar_question(question: str) -> bool:
    return bool(_POLAR_PATTERN.search(_normalized(question)))


def _mentioned_teams(text: str, available_teams: Sequence[str]) -> tuple[str, ...]:
    found: list[tuple[int, str]] = []
    for team in sorted(available_teams, key=len, reverse=True):
        match = re.search(rf"(?<![\w-]){re.escape(team.lower())}(?![\w-])", text)
        if match and not any(
            start <= match.start() < start + len(other.lower())
            for start, other in found
        ):
            found.append((match.start(), team))
    return tuple(team for _, team in sorted(found))


def _competition(
    text: str, year: int | None
) -> tuple[str | None, str | None, list[MatchFactIssue], re.Match[str] | None]:
    """Resolve a competition alias to the exact stored name for the year."""
    hits: list[tuple[CompetitionDefinition, re.Match[str]]] = []
    issues: list[MatchFactIssue] = []
    for definition in COMPETITION_REGISTRY:
        for match in re.finditer(definition.alias_pattern, text):
            if _OTHER_EVENT_PREFIX.search(text[: match.start()]) or _OTHER_EVENT_SUFFIX.search(
                text[match.end():]
            ):
                prefix = re.search(r"(\S+\s*)$", text[: match.start()])
                suffix = re.search(r"^(\s*\S+(?:\s+league)?)", text[match.end():])
                phrase = (
                    (prefix.group(1) if prefix and _OTHER_EVENT_PREFIX.search(text[: match.start()]) else "")
                    + match.group(0)
                    + (suffix.group(1) if suffix and _OTHER_EVENT_SUFFIX.search(text[match.end():]) else "")
                ).strip()
                issues.append(
                    MatchFactIssue(
                        fact_type="filter",
                        concept="competition",
                        requested=phrase,
                        outcome="data_limitation",
                        reason=(
                            f"'{phrase}' is a different event from the registered {definition.label} "
                            "and has no registered ODI match-fact competition in the database."
                        ),
                        evidence=phrase,
                    )
                )
                continue
            hits.append((definition, match))
    definitions = list({definition.key: definition for definition, _ in hits}.values())
    if issues:
        return None, None, issues, None
    if not definitions:
        return None, None, [], None
    if len(definitions) > 1:
        labels = ", ".join(definition.label for definition in definitions)
        return None, None, [
            MatchFactIssue(
                fact_type="filter",
                concept="competition",
                requested=[definition.label for definition in definitions],
                outcome="clarification",
                reason=f"More than one competition is named ({labels}); which one identifies the match?",
            )
        ], None
    definition = definitions[0]
    match = hits[0][1]
    if year is None:
        return None, match.group(0), [
            MatchFactIssue(
                fact_type="filter",
                concept="competition",
                requested=definition.label,
                outcome="clarification",
                reason=f"The stored {definition.label} edition depends on the year.",
                evidence=match.group(0),
            )
        ], match
    stored = definition.stored_by_year.get(year)
    if stored is None:
        editions = ", ".join(str(edition) for edition in sorted(definition.stored_by_year))
        return None, match.group(0), [
            MatchFactIssue(
                fact_type="filter",
                concept="competition",
                requested=f"{year} {definition.label}",
                outcome="data_limitation",
                reason=(
                    f"The ODI database has no {definition.label} edition in {year}; "
                    f"stored editions are {editions}."
                ),
                evidence=match.group(0),
            )
        ], match
    return stored, match.group(0), [], match


def _stage(
    text: str,
    fact_type: str,
    competition_match: re.Match[str] | None,
) -> tuple[str | None, str | None, list[MatchFactIssue]]:
    stages: list[tuple[str, str]] = []
    for match in _STAGE_PATTERN.finditer(text):
        if match.group("semi"):
            stage = "semi-final"
        elif match.group("quarter"):
            stage = "quarter-final"
        elif match.group("final"):
            stage = "final"
        elif match.group("group"):
            stage = "group stage"
        elif match.group("super"):
            stage = " ".join(match.group("super").split())
        elif match.group("opening"):
            stage = "opening match"
        else:
            stage = match.group("eliminator")
        stages.append((stage, match.group(0)))
    distinct = list(dict.fromkeys(stage for stage, _ in stages))
    if len(distinct) > 1:
        return None, None, [
            MatchFactIssue(
                fact_type="filter",
                concept="stage",
                requested=distinct,
                outcome="clarification",
                reason=f"More than one match stage is named ({', '.join(distinct)}); which one identifies the match?",
            )
        ]
    if distinct:
        stage = distinct[0]
        evidence = stages[0][1]
        if stage not in _REGISTERED_STAGES:
            return None, evidence, [
                MatchFactIssue(
                    fact_type="filter",
                    concept="stage",
                    requested=stage,
                    outcome="data_limitation",
                    reason=(
                        f"The database stores no match-stage field, so a {stage} cannot be "
                        "identified; only a registered tournament's final (its sole match on "
                        "the latest recorded date) is identifiable."
                    ),
                    evidence=evidence,
                )
            ]
        return stage, evidence, []
    # "Who won the 2011 World Cup?" asks for the tournament winner, which is
    # the winner of its single registered final.
    if fact_type == "winner" and competition_match is not None:
        before = text[: competition_match.start()]
        after = text[competition_match.end():]
        if re.search(
            r"\b(?:won|win|winners?\s+of|champions?\s+of)\s+(?:the\s+)?(?:(?:19|20)\d{2}\s+)?$",
            before,
        ) or re.search(r"^\s*(?:(?:19|20)\d{2}\s+)?(?:winners?|champions?)\b", after):
            return "final", competition_match.group(0), []
    return None, None, []


def extract_match_fact_meaning(
    question: str,
    available_teams: Sequence[str] = (),
    mentioned_players: Sequence[str] = (),
    mentioned_venues: Sequence[str] = (),
) -> MatchFactMeaning | None:
    """Recognise a single-match fact request, or return None when it is not one."""
    text = _normalized(question)
    toss = TOSS_PATTERN.search(text)
    competition_hit = any(
        re.search(definition.alias_pattern, text) for definition in COMPETITION_REGISTRY
    )
    issues: list[MatchFactIssue] = []
    if toss:
        fact_type = "toss"
        if _TOSS_DECISION_PATTERN.search(text):
            issues.append(
                MatchFactIssue(
                    fact_type="metric",
                    concept="toss_decision",
                    requested="toss decision",
                    outcome="data_limitation",
                    reason="The database stores the toss winner but not the toss decision (bat or field first).",
                )
            )
        elif _TOSS_AGGREGATE_PATTERN.search(text):
            issues.append(
                MatchFactIssue(
                    fact_type="metric",
                    concept="toss_aggregate",
                    requested="toss count or rate",
                    outcome="unsupported",
                    reason=(
                        "Toss counts, toss rates and toss-winning splits are not registered; "
                        "only one identified match's toss winner is supported."
                    ),
                )
            )
        elif _TOSS_CONDITION_PATTERN.search(text):
            issues.append(
                MatchFactIssue(
                    fact_type="filter",
                    concept="toss_condition",
                    requested="toss result condition",
                    outcome="unsupported",
                    reason=(
                        "Filtering statistics by toss result is not registered; only one "
                        "identified match's toss winner is supported."
                    ),
                )
            )
        elif _TOSS_LOSER_PATTERN.search(text):
            issues.append(
                MatchFactIssue(
                    fact_type="metric",
                    concept="toss_loser",
                    requested="toss loser",
                    outcome="unsupported",
                    reason="Only the stored toss winner is a registered match fact; ask who won the toss.",
                )
            )
        elif _MATCH_RESULT_PATTERN.search(text):
            issues.append(
                MatchFactIssue(
                    fact_type="metric",
                    concept="fact_type",
                    requested=["toss", "winner"],
                    outcome="clarification",
                    reason=(
                        "The toss winner and the match winner are separate match facts; "
                        "ask for one of them at a time."
                    ),
                )
            )
        for player in mentioned_players:
            issues.append(
                MatchFactIssue(
                    fact_type="entity",
                    concept="player",
                    requested=player,
                    outcome="unsupported",
                    reason=(
                        f"The toss winner is a team-level match fact; player '{player}' "
                        "cannot be applied to it."
                    ),
                    evidence=player,
                )
            )
    else:
        if not (_MATCH_ANCHOR_PATTERN.search(text) or competition_hit):
            return None
        # Player statistics, rankings and predictions belong to other families.
        if mentioned_players or _FUTURE_PATTERN.search(text) or _RANKING_PATTERN.search(text):
            return None
        if _WINNER_PATTERN.search(text):
            fact_type = "winner"
        elif _TOTAL_PATTERN.search(text):
            fact_type = "team_total"
        else:
            return None

    evidence: dict[str, str] = {}
    years = list(dict.fromkeys(int(value) for value in _YEAR_PATTERN.findall(text)))
    year: int | None = None
    if len(years) > 1:
        issues.append(
            MatchFactIssue(
                fact_type="filter",
                concept="year",
                requested=years,
                outcome="clarification",
                reason=f"More than one year is named ({', '.join(map(str, years))}); which one identifies the match?",
            )
        )
    elif years:
        year = years[0]
        evidence["year"] = str(year)

    competition, competition_evidence, competition_issues, competition_match = _competition(
        text, year
    )
    issues.extend(competition_issues)
    if competition_evidence:
        evidence["competition"] = competition_evidence

    stage, stage_evidence, stage_issues = _stage(text, fact_type, competition_match)
    issues.extend(stage_issues)
    if stage_evidence:
        evidence["stage"] = stage_evidence

    toss_evidence = toss.group(0) if toss else None
    if toss_evidence:
        evidence["fact_type"] = toss_evidence

    participants = _mentioned_teams(text, available_teams)
    team = participants[0] if fact_type == "team_total" and participants else None
    venues = list(dict.fromkeys(mentioned_venues))
    venue: str | None = None
    if len(venues) > 1:
        issues.append(
            MatchFactIssue(
                fact_type="filter",
                concept="venue",
                requested=venues,
                outcome="clarification",
                reason=f"More than one venue is named ({', '.join(venues)}); which one identifies the match?",
            )
        )
    elif venues:
        venue = venues[0]
        evidence["venue"] = venue
    return MatchFactMeaning(
        fact_type=fact_type,
        year=year,
        competition=competition,
        stage=stage,
        team=team,
        participants=participants,
        venue=venue,
        polar=bool(_POLAR_PATTERN.search(text)),
        evidence=evidence,
        issues=tuple(issues),
    )


@dataclass(frozen=True, slots=True)
class MatchMetadataCandidate:
    match_id: str
    years: tuple[str, ...]
    dates: tuple[str, ...]
    competitions: tuple[str, ...]
    grounds: tuple[str, ...]
    winners: tuple[str, ...]
    toss_winners: tuple[str, ...]
    teams: tuple[str, ...] = ()
    missing_toss_rows: int = 0
    missing_winner_rows: int = 0
    delivery_rows: int = 0


class MatchMetadataRepository(Protocol):
    def match_metadata_candidates(
        self, *, year: int, competition: str
    ) -> list[MatchMetadataCandidate]: ...


@dataclass(frozen=True, slots=True)
class ResolvedMatchFact:
    status: Literal["resolved", "not_found", "ambiguous", "data_limitation"]
    detail: str
    match_id: str | None = None
    date: str | None = None
    competition: str | None = None
    stage: str | None = None
    ground: str | None = None
    toss: str | None = None
    winner: str | None = None
    fact_type: str | None = None
    fact_value: str | None = None
    teams: tuple[str, ...] = ()


def _one(values: tuple[str, ...]) -> str | None:
    cleaned = tuple(value.strip() for value in values if value and value.strip())
    return cleaned[0] if len(set(cleaned)) == 1 else None


FINAL_SELECTION_RULE = (
    "The final is the sole match on the latest recorded date within the exact stored "
    "competition and year of a registered single-final tournament."
)


def resolve_match_fact(
    repository: MatchMetadataRepository,
    *,
    year: int,
    competition: str,
    stage: str,
    fact_type: str,
    participants: Sequence[str] = (),
    venue: str | None = None,
) -> ResolvedMatchFact:
    definition = MATCH_FACT_REGISTRY.get(fact_type)
    if definition is None:
        return ResolvedMatchFact(
            status="data_limitation",
            detail=f"The match fact type '{fact_type}' is not registered.",
        )
    if stage != "final":
        return ResolvedMatchFact(
            status="ambiguous",
            detail="Specify the match stage; only the explicit final-selection rule is registered.",
        )
    if competition not in SINGLE_FINAL_COMPETITIONS:
        return ResolvedMatchFact(
            status="ambiguous",
            detail=(
                f"The final of '{competition}' cannot be identified: final selection is registered "
                "only for single-final tournaments (ICC Cricket World Cup, ICC Champions Trophy "
                "and Asia Cup editions)."
            ),
        )
    candidates = repository.match_metadata_candidates(year=year, competition=competition)
    if not candidates:
        return ResolvedMatchFact(
            status="not_found",
            detail=f"No ODI match was found for {competition} {year}.",
        )

    identities: list[tuple[date, MatchMetadataCandidate, str, str, str]] = []
    for candidate in candidates:
        candidate_year = _one(candidate.years)
        candidate_date = _one(candidate.dates)
        candidate_competition = _one(candidate.competitions)
        ground = _one(candidate.grounds)
        if not all(
            (
                candidate.match_id,
                candidate_year,
                candidate_date,
                candidate_competition,
                ground,
            )
        ):
            return ResolvedMatchFact(
                status="data_limitation",
                detail="Match identity metadata is missing or inconsistent across delivery rows.",
            )
        if candidate_year != str(year) or candidate_competition != competition:
            return ResolvedMatchFact(
                status="data_limitation",
                detail="Match year or competition metadata is inconsistent across delivery rows.",
            )
        try:
            parsed_date = date.fromisoformat(str(candidate_date))
        except ValueError:
            return ResolvedMatchFact(
                status="data_limitation",
                detail="Match date metadata is not a valid database identity.",
            )
        identities.append(
            (parsed_date, candidate, str(candidate_date), str(candidate_competition), str(ground))
        )

    latest_date = max(identity[0] for identity in identities)
    latest = [identity for identity in identities if identity[0] == latest_date]
    if len(latest) != 1:
        return ResolvedMatchFact(
            status="ambiguous",
            detail=(
                "The final could not be identified uniquely: more than one match is recorded "
                "on the competition's latest match date."
            ),
        )

    _, candidate, candidate_date, candidate_competition, ground = latest[0]
    teams = tuple(dict.fromkeys(team for team in candidate.teams if team and team.strip()))
    identity = {
        "match_id": candidate.match_id,
        "date": candidate_date,
        "competition": candidate_competition,
        "stage": stage,
        "ground": ground,
        "fact_type": fact_type,
        "teams": teams,
    }
    if candidate.teams and len(teams) != 2:
        return ResolvedMatchFact(
            status="data_limitation",
            detail=(
                f"Match {candidate.match_id} does not record exactly two teams, so it is not "
                "a verifiable final identity."
            ),
            **identity,
        )
    missing = [team for team in participants if teams and team not in teams]
    if missing:
        return ResolvedMatchFact(
            status="data_limitation",
            detail=(
                f"The {competition} {year} final in the database (match {candidate.match_id}) "
                f"was {' v '.join(teams)}; {', '.join(missing)} did not play in it."
            ),
            **identity,
        )
    if venue is not None and venue != ground:
        return ResolvedMatchFact(
            status="data_limitation",
            detail=(
                f"The {competition} {year} final in the database (match {candidate.match_id}) "
                f"was played at {ground}, not {venue}."
            ),
            **identity,
        )

    toss = _one(candidate.toss_winners) if not candidate.missing_toss_rows else None
    if toss is not None and (toss in NO_RECORDED_WINNER_VALUES or (teams and toss not in teams)):
        toss = None
    winner = _one(candidate.winners) if not candidate.missing_winner_rows else None
    identity["toss"] = toss
    identity["winner"] = winner

    if definition.source_field == "toss" and toss is None:
        return ResolvedMatchFact(
            status="data_limitation",
            detail=f"The selected match has missing or inconsistent {definition.label.lower()} metadata.",
            **identity,
        )
    if definition.source_field == "winner":
        if winner is None:
            return ResolvedMatchFact(
                status="data_limitation",
                detail=f"The selected match has missing or inconsistent {definition.label.lower()} metadata.",
                **identity,
            )
        if winner in NO_RECORDED_WINNER_VALUES:
            return ResolvedMatchFact(
                status="data_limitation",
                detail=(
                    f"The database records no match winner for the {competition} {year} final "
                    f"(match {candidate.match_id}, {candidate_date}, {ground}): the stored winner is "
                    f"'{winner}', which the source uses for a tie or no result. The result is not "
                    "inferred from any other field."
                ),
                **identity,
            )
    fact_value = (
        toss if definition.source_field == "toss" else winner if definition.source_field else None
    )
    return ResolvedMatchFact(
        status="resolved",
        detail=FINAL_SELECTION_RULE,
        fact_value=fact_value,
        **identity,
    )
