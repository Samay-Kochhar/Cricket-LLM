from __future__ import annotations

import json

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class ScriptedGeminiClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return self.response


def _trace(response) -> dict[str, object]:
    trace_note = next(note for note in response.evidence_notes if note.title == "Semantic V2 trace")
    return json.loads(trace_note.detail)


def test_generic_left_arm_spin_merges_orthodox_and_unorthodox_planner_values() -> None:
    service = SemanticAnalyticsService(
        repository=AnalyticsRepository(AppConfig.from_env().duckdb_path),
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "aggregate",
              "entity": "batter",
              "metric": "batting_strike_rate",
              "filters": {
                "batter": "Glenn Maxwell",
                "bowling_style": ["Left arm orthodox", "Left arm unorthodox"]
              }
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question(
        "What is Glenn Maxwell's batting strike rate against left arm spinners?"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["filters"]["bowling_style"] == "left_arm_spin"
    assert response.tables[0].rows[0] == ["Glenn Maxwell", 127.69, 641, 502, 54]


def test_generic_pace_merges_left_and_right_arm_planner_values() -> None:
    service = SemanticAnalyticsService(
        repository=AnalyticsRepository(AppConfig.from_env().duckdb_path),
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "aggregate",
              "entity": "batter",
              "metric": "batting_strike_rate",
              "filters": {
                "batter": "Glenn Maxwell",
                "bowling_style": ["Left arm pace", "Right arm pace"]
              }
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question(
        "What is Glenn Maxwell's batting strike rate against pace?"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["filters"]["bowling_style"] == "pace"
    assert response.tables[0].rows[0] == ["Glenn Maxwell", 124.36, 2175, 1749, 122]
