from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.match_facts import (
    MatchMetadataCandidate,
    resolve_match_fact,
)
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(AppConfig.from_env().duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


def _trace(response) -> dict[str, object]:
    trace_note = next(
        note for note in response.evidence_notes if note.title == "Semantic V2 trace"
    )
    return json.loads(trace_note.detail)


def test_2019_world_cup_final_toss_uses_toss_metadata_not_match_winner(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Who won the toss in the 2019 World Cup final?"
    )
    trace = _trace(response)

    assert response.status.value == "supported"
    assert "New Zealand won the toss" in response.summaries[0].body
    assert response.interpretation.filters["fact_type"] == "toss"
    assert trace["normalized_plan"]["filters"] == {
        "years": [2019],
        "competition": "ICC Cricket World Cup",
        "match_stage": "final",
        "fact_type": "toss",
    }
    assert trace["final_answer_metadata"] == {
        "status": "supported",
        "match_id": "1144530",
        "date": "2019-07-14",
        "competition": "ICC Cricket World Cup",
        "stage": "final",
        "ground": "Lord's, London",
        "fact_type": "toss",
        "fact_value": "New Zealand",
        "toss": "New Zealand",
        "winner": "-",
    }
    assert response.tables[0].rows == [
        [
            "1144530",
            "ICC Cricket World Cup",
            "Final",
            "2019-07-14",
            "Lord's, London",
            "New Zealand",
        ]
    ]


@pytest.mark.parametrize(
    "question",
    [
        "In the 2019 World Cup final, who won the toss?",
        "The toss in the World Cup final of 2019 was won by which team?",
        "Which team was the 2019 cricket World Cup final toss winner?",
    ],
)
def test_toss_paraphrases_preserve_canonical_match_and_fact_identity(
    semantic_service: SemanticAnalyticsService,
    question: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "supported"
    assert "New Zealand won the toss" in response.summaries[0].body
    assert trace["canonical_meaning"] == {
        "family": "match_fact",
        "fact_type": "toss",
        "year": 2019,
        "competition": "ICC Cricket World Cup",
        "stage": "final",
        "team": None,
    }
    completeness = trace["completeness_result"]
    assert completeness["complete"] is True
    assert completeness["allows_execution"] is True
    assert {
        (fact["concept"], fact["disposition"])
        for fact in completeness["facts"]
    } == {
        ("fact_type", "compiled"),
        ("year", "compiled"),
        ("competition", "compiled"),
        ("stage", "compiled"),
    }
    assert trace["final_answer_metadata"]["match_id"] == "1144530"


def test_registered_toss_fact_does_not_depend_on_model_memory(
    semantic_service: SemanticAnalyticsService,
) -> None:
    production_service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=FakeGeminiClient(),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = production_service.answer_question(
        "Who won the toss in the 2019 World Cup final?"
    )
    trace = _trace(response)

    assert response.status.value == "supported"
    assert "New Zealand won the toss" in response.summaries[0].body
    assert trace["planner_outcome"]["parse_outcome"] == "registered_match_fact"
    assert trace["gemini_raw_response"] is None


class StubMatchMetadataRepository:
    def __init__(self, candidates: list[MatchMetadataCandidate]) -> None:
        self.candidates = candidates

    def match_metadata_candidates(
        self, *, year: int, competition: str
    ) -> list[MatchMetadataCandidate]:
        return self.candidates


def _candidate(
    match_id: str = "1144530",
    *,
    match_date: str = "2019-07-14",
    toss_winners: tuple[str, ...] = ("New Zealand",),
) -> MatchMetadataCandidate:
    return MatchMetadataCandidate(
        match_id=match_id,
        years=("2019",),
        dates=(match_date,),
        competitions=("ICC Cricket World Cup",),
        grounds=("Lord's, London",),
        winners=("-",),
        toss_winners=toss_winners,
    )


def test_inconsistent_toss_values_fail_closed() -> None:
    result = resolve_match_fact(
        StubMatchMetadataRepository(
            [_candidate(toss_winners=("New Zealand", "England"))]
        ),
        year=2019,
        competition="ICC Cricket World Cup",
        stage="final",
        fact_type="toss",
    )

    assert result.status == "data_limitation"
    assert "inconsistent toss winner" in result.detail.lower()
    assert result.fact_value is None


def test_missing_toss_value_returns_data_limitation() -> None:
    result = resolve_match_fact(
        StubMatchMetadataRepository([_candidate(toss_winners=())]),
        year=2019,
        competition="ICC Cricket World Cup",
        stage="final",
        fact_type="toss",
    )

    assert result.status == "data_limitation"
    assert "missing or inconsistent toss winner" in result.detail.lower()
    assert result.fact_value is None


def test_duplicate_delivery_metadata_collapses_to_one_match_fact() -> None:
    result = resolve_match_fact(
        StubMatchMetadataRepository(
            [_candidate(toss_winners=("New Zealand", "New Zealand"))]
        ),
        year=2019,
        competition="ICC Cricket World Cup",
        stage="final",
        fact_type="toss",
    )

    assert result.status == "resolved"
    assert result.match_id == "1144530"
    assert result.fact_value == "New Zealand"


def test_final_selection_fails_when_latest_match_date_is_not_unique() -> None:
    result = resolve_match_fact(
        StubMatchMetadataRepository(
            [
                _candidate("1144530"),
                _candidate("another-final", toss_winners=("England",)),
            ]
        ),
        year=2019,
        competition="ICC Cricket World Cup",
        stage="final",
        fact_type="toss",
    )

    assert result.status == "ambiguous"
    assert "more than one match" in result.detail.lower()
    assert result.match_id is None


@pytest.mark.parametrize(
    ("question", "missing_concept"),
    [
        ("Who won the toss in the 2019 final?", "competition"),
        ("Who won the toss in the World Cup final?", "year"),
        ("Who won the toss in the 2019 World Cup?", "stage"),
    ],
)
def test_missing_match_identity_requests_focused_clarification(
    semantic_service: SemanticAnalyticsService,
    question: str,
    missing_concept: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "unsupported"
    assert response.failure_state == "planner_uncertainty"
    assert missing_concept in response.clarification_question.lower()
    assert trace["completeness_result"]["allows_execution"] is False
    missing_fact = next(
        fact
        for fact in trace["completeness_result"]["facts"]
        if fact["concept"] == missing_concept
    )
    assert missing_fact["disposition"] == "clarification_required"
