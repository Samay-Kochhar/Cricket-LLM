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


SPLIT_COMPARE_CASES = [
    (
        "Which bowler has the biggest difference between powerplay and death-over economy?",
        "bowler",
        "economy_rate",
        "phase",
        ["powerplay", "death"],
        {"powerplay_value", "death_value", "difference", "powerplay_sample", "death_sample", "rank_value"},
    ),
    (
        "Which bowler performs significantly better against left-handers than right-handers?",
        "bowler",
        "economy_rate",
        "batter_hand",
        ["left-hand batter", "right-hand batter"],
        {"left_handers_value", "right_handers_value", "difference", "left_handers_sample", "right_handers_sample", "rank_value"},
    ),
    (
        "Which batter dominates wrist spin but struggles against finger spin?",
        "batter",
        "batting_strike_rate",
        "bowling_style_group",
        ["wrist_spin", "finger_spin"],
        {"wrist_spin_value", "finger_spin_value", "difference", "wrist_spin_sample", "finger_spin_sample", "rank_value"},
    ),
    (
        "Which batter improves their strike rate the most after facing 20 balls?",
        "batter",
        "batting_strike_rate",
        "balls_faced_window",
        ["first_20_balls", "after_20_balls"],
        {
            "first_20_balls_value",
            "after_20_balls_value",
            "difference",
            "first_20_balls_sample",
            "after_20_balls_sample",
            "rank_value",
        },
    ),
    (
        "Which team accelerates most effectively between overs 15 and 20?",
        "team",
        "run_rate",
        "over_range",
        ["requested_over_range"],
        {"overs_15_to_20_value", "before_over_15_value", "difference", "overs_15_to_20_sample", "before_over_15_sample", "rank_value"},
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
    "question,entity,metric,split_by,compare_values,expected_columns",
    SPLIT_COMPARE_CASES,
)
def test_split_compare_executor_returns_real_answer_and_trace(
    semantic_service: SemanticAnalyticsService,
    question: str,
    entity: str,
    metric: str,
    split_by: str,
    compare_values: list[str],
    expected_columns: set[str],
) -> None:
    response = semantic_service.answer_question(question)
    trace = json.loads(next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace"))
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "split_compare"
    assert plan["entity"] == entity
    assert plan["metric"] == metric
    assert plan["split_by"] == split_by
    assert plan["compare_values"] == compare_values
    assert trace["selected_executor"] == "executors.split_compare_executor.build_split_compare_query"
    assert "analytics.deliveries_v1" in trace["final_sql_or_method"]
    assert expected_columns.issubset(set(trace["result_columns"]))
    assert response.tables
    assert response.tables[0].rows
