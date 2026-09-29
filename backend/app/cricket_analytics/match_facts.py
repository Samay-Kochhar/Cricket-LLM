from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec


@dataclass(frozen=True, slots=True)
class MatchFactDefinition:
    fact_type: str
    source_field: str | None
    label: str


MATCH_FACT_REGISTRY = {
    "winner": MatchFactDefinition("winner", "winner", "Match winner"),
    "toss": MatchFactDefinition("toss", "toss", "Toss winner"),
    "team_total": MatchFactDefinition("team_total", None, "Team innings total"),
}


WORLD_CUP_COMPETITIONS_BY_YEAR = {
    2007: "ICC World Cup",
    2011: "ICC Cricket World Cup",
    2015: "ICC Cricket World Cup",
    2019: "ICC Cricket World Cup",
    2023: "World Cup 2023",
}


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
  LIST(DISTINCT NULLIF(TRIM(CAST(d.toss AS VARCHAR)), ''))
FROM analytics.deliveries_v1 d
JOIN matching_ids ids ON ids.p_match = d.p_match
GROUP BY d.p_match
ORDER BY d.p_match
"""


@dataclass(frozen=True, slots=True)
class MatchFactMeaning:
    fact_type: str
    year: int | None
    competition: str | None
    stage: str | None
    team: str | None = None

    @property
    def complete(self) -> bool:
        return all((self.year, self.competition, self.stage, self.fact_type))

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
        requested = (
            ("metric", "fact_type", self.fact_type, f"match_fact.{self.fact_type}"),
            ("filter", "year", self.year, "filters.years"),
            ("filter", "competition", self.competition, "filters.competition"),
            ("filter", "stage", self.stage, "filters.match_stage"),
        )
        for fact_type, concept, value, target in requested:
            compiled = value is not None
            facts.append(
                {
                    "fact_type": fact_type,
                    "concept": concept,
                    "requested": value,
                    "evidence": question,
                    "disposition": "compiled" if compiled else "clarification_required",
                    "canonical_target": target if compiled else None,
                    "reason": None if compiled else f"Match fact requires {concept}.",
                }
            )
        return {
            "complete": self.complete,
            "allows_execution": self.complete,
            "facts": facts,
        }


def extract_match_fact_meaning(
    question: str, available_teams: tuple[str, ...] = ()
) -> MatchFactMeaning | None:
    lowered = question.lower()
    if re.search(r"\btoss\b", lowered):
        fact_type = "toss"
    elif re.search(r"\b(?:won|winner|win)\b", lowered) and re.search(
        r"\b(?:match|final|world cup)\b", lowered
    ):
        fact_type = "winner"
    elif re.search(r"\b(?:total|score)\b", lowered) and re.search(
        r"\b(?:match|final|world cup)\b", lowered
    ):
        fact_type = "team_total"
    else:
        return None

    year_match = re.search(r"\b(20\d{2})\b", lowered)
    year = int(year_match.group(1)) if year_match else None
    competition = None
    if re.search(r"\b(?:icc\s+)?(?:cricket\s+)?world cup\b", lowered):
        competition = WORLD_CUP_COMPETITIONS_BY_YEAR.get(year) if year else None
    stage = "final" if re.search(r"\bfinal\b", lowered) else None

    team = None
    if fact_type == "team_total":
        for candidate in available_teams:
            if re.search(rf"\b{re.escape(candidate.lower())}\b", lowered):
                team = candidate
                break
    return MatchFactMeaning(
        fact_type=fact_type,
        year=year,
        competition=competition,
        stage=stage,
        team=team,
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


def _one(values: tuple[str, ...]) -> str | None:
    cleaned = tuple(value.strip() for value in values if value and value.strip())
    return cleaned[0] if len(set(cleaned)) == 1 else None


def resolve_match_fact(
    repository: MatchMetadataRepository,
    *,
    year: int,
    competition: str,
    stage: str,
    fact_type: str,
) -> ResolvedMatchFact:
    definition = MATCH_FACT_REGISTRY.get(fact_type)
    if definition is None:
        return ResolvedMatchFact(
            status="data_limitation",
            detail=f"The match fact type '{fact_type}' is not registered.",
        )
    candidates = repository.match_metadata_candidates(year=year, competition=competition)
    if not candidates:
        return ResolvedMatchFact(
            status="not_found",
            detail=f"No ODI match was found for {competition} {year}.",
        )

    identities: list[tuple[date, MatchMetadataCandidate, str, str, str, str]] = []
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
            parsed_date = date.fromisoformat(candidate_date)
        except ValueError:
            return ResolvedMatchFact(
                status="data_limitation",
                detail="Match date metadata is not a valid database identity.",
            )
        identities.append(
            (
                parsed_date,
                candidate,
                candidate_date,
                candidate_competition,
                ground,
                candidate_year,
            )
        )

    if stage != "final":
        return ResolvedMatchFact(
            status="ambiguous",
            detail="Specify the match stage; only the explicit final-selection rule is registered.",
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

    _, candidate, candidate_date, candidate_competition, ground, _ = latest[0]
    toss = _one(candidate.toss_winners)
    winner = _one(candidate.winners)
    source_values = (
        candidate.toss_winners if definition.source_field == "toss" else candidate.winners
    )
    fact_value = _one(source_values) if definition.source_field else None
    if definition.source_field and fact_value is None:
        return ResolvedMatchFact(
            status="data_limitation",
            detail=f"The selected match has missing or inconsistent {definition.label.lower()} metadata.",
        )
    return ResolvedMatchFact(
        status="resolved",
        detail=(
            "The final is the sole match on the latest recorded date within the exact "
            "competition and year."
        ),
        match_id=candidate.match_id,
        date=candidate_date,
        competition=candidate_competition,
        stage=stage,
        ground=ground,
        toss=toss,
        winner=winner,
        fact_type=fact_type,
        fact_value=fact_value,
    )
