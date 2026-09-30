from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.canonical_meaning import CanonicalCricketMeaning
from backend.app.cricket_analytics.canonical_meaning import CanonicalMeaningResolver
from backend.app.cricket_analytics.canonical_patches import VersionedCanonicalMeaning
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.player_roles import PlayerParticipation
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.services.chat_service import ChatService
from backend.app.services.gemini_client import GeminiStructuredResult


class _UnconfiguredClient:
    def is_configured(self) -> bool:
        return False


class _RangeExtractionClient:
    def is_configured(self) -> bool:
        return True

    def generate_structured(
        self, prompt: str, **kwargs: object
    ) -> GeminiStructuredResult:
        payload = {
            "version": 1,
            "family": "direct",
            "entities": [
                {
                    "name": "Bumrah",
                    "kind": "player",
                    "role": "bowler",
                    "relationship": "subject",
                }
            ],
            "metric_concept": "economy rate",
            "role": "bowler",
            "filters": [
                {
                    "concept": "over range",
                    "operator": "between",
                    "values": [41, 50],
                    "evidence": "between overs 41 and 50",
                }
            ],
            "intent": "value",
        }
        return GeminiStructuredResult(
            text=json.dumps(payload),
            selected_model="test-flash",
            model_version="saved-test-response",
            finish_reason="STOP",
            latency_ms=0,
        )

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> None:
        return None


def _planner() -> SemanticQueryPlanner:
    return SemanticQueryPlanner(
        _UnconfiguredClient(),  # type: ignore[arg-type]
        ["Jasprit Bumrah"],
        allow_dev_fallback=True,
        player_participation={
            "Jasprit Bumrah": PlayerParticipation(balls_faced=10, balls_bowled=1000)
        },
    )


@pytest.mark.parametrize(
    ("question", "expected_range"),
    [
        ("How expensive has Bumrah been between overs 41 and 50?", [41, 50]),
        ("In overs 41–50, how expensive has Bumrah been?", [41, 50]),
        ("How expensive was Bumrah from the 41st through the 50th?", [41, 50]),
        ("Between overs 36 and 45: Bumrah economy?", [36, 45]),
    ],
)
def test_bounded_over_wording_compiles_as_one_filtered_statistic(
    question: str, expected_range: list[int]
) -> None:
    trace = QueryTrace(question)
    result = _planner().plan(question, trace)

    assert result.validation.valid, result.validation.errors
    assert result.plan is not None
    assert result.plan.operation == "aggregate"
    assert result.plan.metric == "economy_rate"
    assert result.plan.filters == {
        "bowler": "Jasprit Bumrah",
        "over_range": expected_range,
    }


def test_open_ended_death_over_wording_remains_supported() -> None:
    question = "How expensive is Bumrah from over 41 onwards?"
    result = _planner().plan(question, QueryTrace(question))

    assert result.validation.valid, result.validation.errors
    assert result.plan is not None
    assert result.plan.operation == "aggregate"
    assert result.plan.filters == {
        "bowler": "Jasprit Bumrah",
        "phase": "death",
    }


def test_two_explicit_over_ranges_compile_as_a_real_split() -> None:
    question = "Compare Bumrah's economy in overs 1–10 with overs 41–50."
    result = _planner().plan(question, QueryTrace(question))

    assert result.validation.valid, result.validation.errors
    assert result.plan is not None
    assert result.plan.operation == "split_compare"
    assert result.plan.split_by == "over_range"
    assert result.plan.compare_values == ["overs_1_to_10", "overs_41_to_50"]
    assert result.plan.filters == {"bowler": "Jasprit Bumrah"}

    config = AppConfig.from_env()
    response = SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=_UnconfiguredClient(),  # type: ignore[arg-type]
        app_env="development",
    ).answer_question(question)
    assert response.status.value == "supported"
    values = dict(
        zip(response.tables[0].columns, response.tables[0].rows[0], strict=True)
    )
    assert values["Overs 1 To 10 Value"] == 3.96
    assert values["Overs 41 To 50 Value"] == 5.78


def test_context_can_replace_and_remove_a_bounded_range() -> None:
    previous = CanonicalCricketMeaning(
        family="direct",
        role="bowler",
        metric="economy_rate",
        filters={"bowler": "Jasprit Bumrah", "over_range": [41, 50]},
        group_by=["bowler"],
        sort_direction="desc",
    )
    state = {
        "canonical_meaning": VersionedCanonicalMeaning(meaning=previous).model_dump(
            mode="json"
        )
    }

    replace_trace = QueryTrace("Now in overs 31-40?")
    replaced = _planner().plan(
        replace_trace.original_user_question, replace_trace, state
    )
    assert replaced.validation.valid, replaced.validation.errors
    assert replaced.plan is not None
    assert replaced.plan.filters["over_range"] == [31, 40]
    assert replace_trace.meaning_patch["operations"] == [
        {
            "action": "replace",
            "target": "filter.over_range",
            "value": [31, 40],
        }
    ]
    assert replace_trace.completeness_result["allows_execution"] is True
    assert replace_trace.completeness_result["facts"][0]["disposition"] == (
        "explicitly_replaced_removed"
    )

    remove_trace = QueryTrace("Now across all overs?")
    removed = _planner().plan(remove_trace.original_user_question, remove_trace, state)
    assert removed.validation.valid, removed.validation.errors
    assert removed.plan is not None
    assert "over_range" not in removed.plan.filters
    assert remove_trace.meaning_patch["operations"] == [
        {"action": "remove", "target": "filter.over_range", "value": None}
    ]
    assert remove_trace.completeness_result["facts"][0]["disposition"] == (
        "explicitly_replaced_removed"
    )


def test_every_extracted_range_fact_has_an_observable_disposition() -> None:
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "entities": [
                {
                    "name": "Bumrah",
                    "kind": "player",
                    "role": "bowler",
                    "relationship": "subject",
                }
            ],
            "metric_concept": "economy rate",
            "role": "bowler",
            "filters": [
                {
                    "concept": "over range",
                    "operator": "between",
                    "values": [41, 50],
                    "evidence": "between overs 41 and 50",
                }
            ],
            "intent": "value",
        }
    )
    resolver = CanonicalMeaningResolver(
        available_players=["Jasprit Bumrah"],
        player_participation={
            "Jasprit Bumrah": PlayerParticipation(balls_faced=10, balls_bowled=1000)
        },
    )

    resolution = resolver.resolve_candidate(
        "How expensive has Bumrah been between overs 41 and 50?", None, candidate
    )

    assert resolution.meaning is not None
    assert resolution.completeness is not None
    assert resolution.completeness.complete is True
    assert resolution.completeness.allows_execution is True
    assert {fact.fact_type for fact in resolution.completeness.facts} >= {
        "family",
        "metric",
        "role",
        "entity",
        "relationship",
        "filter",
        "operator",
        "value",
        "intent",
    }
    assert {fact.disposition for fact in resolution.completeness.facts} == {"compiled"}


def test_unregistered_evidenced_filter_cannot_disappear_from_a_split_plan() -> None:
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "split",
            "metric_concept": "economy rate",
            "role": "bowler",
            "filters": [
                {
                    "concept": "moonlight",
                    "values": ["bright"],
                    "evidence": "under bright moonlight",
                }
            ],
        }
    )
    resolver = CanonicalMeaningResolver(
        available_players=["Jasprit Bumrah"],
        player_participation={
            "Jasprit Bumrah": PlayerParticipation(balls_faced=10, balls_bowled=1000)
        },
    )

    resolution = resolver.resolve_candidate(
        "Compare Bumrah's economy in powerplay versus death overs under bright moonlight",
        None,
        candidate,
    )

    assert resolution.meaning is None
    assert resolution.status.value == "unsupported"
    assert resolution.completeness is not None
    moonlight = next(
        fact
        for fact in resolution.completeness.facts
        if fact.fact_type == "filter" and fact.concept == "moonlight"
    )
    assert moonlight.disposition == "unsupported"
    assert resolution.completeness.allows_execution is False


def test_unregistered_metric_cannot_leave_an_executable_partial_plan() -> None:
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "entities": [{"name": "Bumrah", "kind": "player", "role": "bowler"}],
            "metric_concept": "zorb rate",
            "role": "bowler",
        }
    )
    resolver = CanonicalMeaningResolver(available_players=["Jasprit Bumrah"])

    resolution = resolver.resolve_candidate("Bumrah's zorb rate?", None, candidate)

    assert resolution.meaning is None
    assert resolution.status.value == "unsupported"
    assert resolution.completeness is not None
    metric = next(
        fact for fact in resolution.completeness.facts if fact.fact_type == "metric"
    )
    assert metric.disposition == "unsupported"


def test_priority_question_executes_through_live_chat_with_visible_evidence_scope() -> (
    None
):
    config = AppConfig.from_env()
    repository = AnalyticsRepository(config.duckdb_path)
    client = _RangeExtractionClient()
    semantic = SemanticAnalyticsService(
        repository=repository,
        gemini_client=client,  # type: ignore[arg-type]
        app_env="production",
        allow_dev_fallback=False,
    )
    chat = ChatService(
        repository=repository,
        query_handler=semantic.answer_question,
        gemini_client=client,  # type: ignore[arg-type]
    )

    reply = chat.reply(
        "How expensive has Bumrah been between overs 41 and 50?", history=[]
    )

    assert reply.mode == "analysis"
    assert reply.query_response is not None
    response = reply.query_response
    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Jasprit Bumrah"]
    assert response.interpretation.filters["semantic_metric"] == "economy_rate"
    assert response.interpretation.filters["over_range"] == [41, 50]
    row = response.tables[0].rows[0]
    values = dict(zip(response.tables[0].columns, row, strict=True))
    assert values["Economy Rate"] == 5.78
    assert values["Runs Conceded"] == 1081
    assert values["Legal Balls"] == 1123
    assert "inclusive overs 41–50" in response.summaries[0].body
    trace = json.loads(
        next(
            note.detail
            for note in response.evidence_notes
            if note.title == "Semantic V2 trace"
        )
    )
    assert trace["completeness_result"]["complete"] is True
    assert trace["completeness_result"]["allows_execution"] is True
