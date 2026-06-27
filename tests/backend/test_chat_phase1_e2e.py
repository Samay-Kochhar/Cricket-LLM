from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.bootstrap import get_services
from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.main import app
from backend.app.services.chat_service import ChatService


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture()
def client() -> Iterator[TestClient]:
    config = AppConfig.from_env()
    repository = AnalyticsRepository(config.duckdb_path)
    gemini = FakeGeminiClient()
    semantic = SemanticAnalyticsService(repository=repository, gemini_client=gemini, app_env="development")
    chat_service = ChatService(repository=repository, query_handler=semantic.answer_question, gemini_client=gemini)
    app.dependency_overrides[get_services] = lambda: {
        "repository": repository,
        "query_handler": semantic.answer_question,
        "chat_service": chat_service,
    }
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "message,expected_operation",
    [
        ("what is dot ball percentage of virat kohli?", "aggregate"),
        ("Where does Hardik Pandya score the most and on which shots?", "batting_profile"),
        ("Which bowler has dismissed David Miller most often?", "matchup"),
        ("Which bowler has the biggest difference between powerplay and death-over economy?", "split_compare"),
    ],
)
def test_chat_path_answers_phase1_question_shapes(
    client: TestClient,
    message: str,
    expected_operation: str,
) -> None:
    response = client.post("/api/chat", json={"message": message, "history": []})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "analysis"
    assert payload["query_response"]["status"] == "supported"
    assert expected_operation in str(payload["query_response"]["interpretation"]["filters"].values())
    assert "ON_DRIVE" not in str(payload)


def test_chat_false_shot_leaderboard_states_scope_and_uses_reliable_default_sample(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "Who has the worst false shot percentage against leg spinners?",
            "history": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    message = payload["message"]
    plan = payload["query_response"]["interpretation"]["filters"]

    assert payload["query_response"]["status"] == "supported"
    assert "against leg spin" in message.lower()
    assert "available odi dataset" not in message.lower()
    assert "minimum sample" not in message.lower()
    assert plan["bowling_style"] == "leg_spin"


def test_style_filtered_player_answer_suggests_relevant_style_and_phase_follow_ups(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "What is Maxwell's strike rate against off spinners?", "history": []},
    )

    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    assert any("leg spin" in suggestion.lower() and "pace" in suggestion.lower() for suggestion in suggestions)
    assert any("powerplay" in suggestion.lower() and "death" in suggestion.lower() for suggestion in suggestions)
    assert all("venue" not in suggestion.lower() for suggestion in suggestions)
