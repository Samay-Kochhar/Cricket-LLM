from __future__ import annotations

import json

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


class ScriptedGeminiClient:
    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return """{
          "operation": "aggregate",
          "entity": "bowler",
          "metric": "boundary_rate_per_100_balls",
          "group_by": ["bowler"],
          "sort": {"by": "boundary_rate_per_100_balls", "direction": "asc"}
        }"""


def test_bowler_boundaries_per_100_uses_boundary_percentage_over_balls_faced() -> None:
    service = SemanticAnalyticsService(
        repository=AnalyticsRepository(AppConfig.from_env().duckdb_path),
        gemini_client=FakeGeminiClient(),
    )

    response = service.answer_question(
        "Which bowler concedes the fewest boundaries per 100 balls?"
    )
    trace_note = next(
        note for note in response.evidence_notes if note.title == "Semantic V2 trace"
    )
    plan = json.loads(trace_note.detail)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["entity"] == "bowler"
    assert plan["group_by"] == ["bowler"]
    assert plan["metric"] == "boundary_percentage"
    assert response.tables[0].columns == [
        "Bowler",
        "Boundary Percentage",
        "Boundary Balls",
        "Balls Faced",
        "Matches",
    ]
    _, percentage, boundary_balls, balls_faced, _ = response.tables[0].rows[0]
    assert percentage == round(boundary_balls / balls_faced * 100, 2)


def test_legacy_gemini_boundary_rate_plan_normalizes_to_boundary_percentage() -> None:
    service = SemanticAnalyticsService(
        repository=AnalyticsRepository(AppConfig.from_env().duckdb_path),
        gemini_client=ScriptedGeminiClient(),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question(
        "Which bowler concedes the fewest boundaries per 100 balls?"
    )
    trace_note = next(
        note for note in response.evidence_notes if note.title == "Semantic V2 trace"
    )
    plan = json.loads(trace_note.detail)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["metric"] == "boundary_percentage"
    assert plan["sort"] == {"by": "boundary_percentage", "direction": "asc"}
    assert response.tables[0].columns[3] == "Balls Faced"
