from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


MATCHUP_CASES = [
    (
        "Which bowler has dismissed David Miller most often?",
        "bowler",
        "wickets_taken",
        {"batter": "David Miller"},
        {"batter", "bowler", "wickets", "sample_size", "low_sample"},
    ),
    (
        "Which bowler controls Virat Kohli best?",
        "bowler",
        "bowler_dot_ball_percentage",
        {"batter": "Virat Kohli"},
        {"batter", "bowler", "bowler_dot_percentage", "sample_size", "low_sample"},
    ),
    (
        "Which batter-bowler matchup has produced the most wickets?",
        "matchup",
        "wickets_taken",
        {},
        {"batter", "bowler", "wickets", "sample_size", "low_sample"},
    ),
    (
        "Which matchup produces the highest false-shot percentage?",
        "matchup",
        "false_shot_percentage",
        {},
        {"batter", "bowler", "false_shot_percentage", "sample_size", "low_sample"},
    ),
    (
        "Which matchup has produced the most wickets in death overs?",
        "matchup",
        "wickets_taken",
        {"phase": "death"},
        {"batter", "bowler", "wickets", "sample_size", "low_sample"},
    ),
    (
        "Which bowler is most successful against finishers?",
        "bowler",
        "wickets_taken",
        {"phase": "death"},
        {"bowler", "wickets", "sample_size", "low_sample"},
    ),
    (
        "How does Heinrich Klaasen perform against wrist spin?",
        "batter",
        "batting_strike_rate",
        {"batter": "Heinrich Klaasen", "bowling_style": "wrist_spin"},
        {"batter", "bowling_style", "strike_rate", "sample_size", "low_sample"},
    ),
    (
        "Which batter dominates left-arm pace?",
        "batter",
        "batting_strike_rate",
        {"bowling_style": "left_arm_pace"},
        {"batter", "bowling_style", "strike_rate", "sample_size", "low_sample"},
    ),
]


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    config = AppConfig.from_env()
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


@pytest.mark.parametrize(
    "question,entity,metric,filters,expected_columns",
    MATCHUP_CASES,
)
def test_matchup_executor_returns_supported_trace_and_shape(
    semantic_service: SemanticAnalyticsService,
    question: str,
    entity: str,
    metric: str,
    filters: dict[str, object],
    expected_columns: set[str],
) -> None:
    response = semantic_service.answer_question(question)
    trace = json.loads(next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace"))
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "matchup"
    assert plan["entity"] == entity
    assert plan["metric"] == metric
    for key, value in filters.items():
        assert plan["filters"].get(key) == value
    assert trace["selected_executor"] == "executors.matchup_executor.build_matchup_query"
    assert "analytics.deliveries_v1" in trace["final_sql_or_method"]
    assert expected_columns.issubset(set(trace["result_columns"]))
    assert "sample_size" in trace["result_columns"]
    assert "low_sample" in trace["result_columns"]
    assert response.tables
    assert response.tables[0].rows


def test_death_over_matchup_keeps_phase_filter(semantic_service: SemanticAnalyticsService) -> None:
    response = semantic_service.answer_question("Which matchup has produced the most wickets in death overs?")
    trace = json.loads(next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace"))

    assert trace["normalized_plan"]["filters"]["phase"] == "death"
    assert "TRY_CAST(over AS DOUBLE) > ?" in trace["final_sql_or_method"]


def test_matchup_does_not_fall_back_to_legacy(semantic_service: SemanticAnalyticsService) -> None:
    response = semantic_service.answer_question("Which matchup produces the highest false-shot percentage?")
    trace = json.loads(next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace"))

    assert response.status.value == "supported"
    assert trace["selected_executor"] == "executors.matchup_executor.build_matchup_query"
    assert trace["selected_executor"] != "query_builders.aggregate_builder.build_aggregate_query"
