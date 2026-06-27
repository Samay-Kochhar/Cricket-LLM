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


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    config = AppConfig.from_env()
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


def _trace(response) -> dict[str, object]:
    return json.loads(next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace"))


def test_batter_dot_ball_question_uses_batter_formula(semantic_service: SemanticAnalyticsService) -> None:
    response = semantic_service.answer_question("what is dot ball percentage of virat kohli?")
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["normalized_plan"]["filters"]["batter"] == "Virat Kohli"
    assert trace["normalized_plan"]["entity"] == "batter"
    assert "dot_balls / NULLIF(sample_balls, 0) * 100.0" in trace["final_sql_or_method"]
    assert "bowler_dot_balls / NULLIF(legal_balls, 0)" not in trace["final_sql_or_method"]
    assert "Junaid Khan" not in response.summaries[0].body


def test_bowler_dot_ball_question_uses_bowler_formula(semantic_service: SemanticAnalyticsService) -> None:
    response = semantic_service.answer_question("what is dot ball percentage of jasprit bumrah as a bowler?")
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["normalized_plan"]["entity"] == "bowler"
    assert "bowler_dot_balls / NULLIF(legal_balls, 0) * 100.0" in trace["final_sql_or_method"]


def test_hardik_scoring_profile_names_player_and_humanizes_shots(semantic_service: SemanticAnalyticsService) -> None:
    response = semantic_service.answer_question("Where does Hardik Pandya score the most and on which shots?")
    body = " ".join(summary.body for summary in response.summaries)
    table_text = json.dumps([table.model_dump(mode="json") for table in response.tables])

    assert response.status.value == "supported"
    assert "Hardik Pandya" in body
    assert "on drive" in table_text.lower() or "pull" in table_text.lower()
    assert "ON_DRIVE" not in body
    assert "ON_DRIVE" not in table_text


def test_short_ball_after_2023_returns_weakness_context(semantic_service: SemanticAnalyticsService) -> None:
    response = semantic_service.answer_question("Does Shreyas Iyer still struggle against the short ball after 2023?")
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["normalized_plan"]["filters"]["batter"] == "Shreyas Iyer"
    assert trace["normalized_plan"]["filters"]["length"] == "short"
    assert trace["normalized_plan"]["filters"]["year_mode"] == "after"
    assert response.summaries
    assert "short" in response.summaries[0].body.lower()
