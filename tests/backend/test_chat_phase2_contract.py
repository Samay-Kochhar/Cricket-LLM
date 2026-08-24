from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.bootstrap import get_services
from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.main import app
from backend.app.services.analytics_service import AnalyticsService
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
    "message,operation,metric",
    [
        ("What is Virat Kohli's batting strike rate in ODIs?", "aggregate", "batting_strike_rate"),
        ("Which bowler has the best death-over economy?", "aggregate", "economy_rate"),
        ("Who has dismissed David Miller most often?", "matchup", "wickets_taken"),
        ("Which line generates the most dot balls against Virat Kohli?", "aggregate", "bowler_dot_ball_percentage"),
        ("Which length produces the most false shots against Shreyas Iyer?", "aggregate", "false_shot_percentage"),
        ("Which shot does Hardik Pandya score most from?", "aggregate", "runs_scored"),
        ("Where does Hardik Pandya score the most and on which shots?", "batting_profile", None),
        ("Which bowler performs significantly better against left-handers than right-handers?", "split_compare", "economy_rate"),
        ("Which bowler bowls the highest percentage of yorkers at the death?", "aggregate", "yorker_percentage"),
        ("What is Bumrah's false shots per over against right-handers?", "aggregate", "false_shots_per_over"),
    ],
)
def test_chat_path_uses_semantic_v2_for_production_capabilities(
    client: TestClient,
    message: str,
    operation: str,
    metric: str | None,
) -> None:
    response = client.post("/api/chat", json={"message": message, "history": []})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "analysis"
    query_response = payload["query_response"]
    assert query_response["status"] == "supported"
    filters = query_response["interpretation"]["filters"]
    assert filters["semantic_operation"] == operation
    if metric is not None:
        assert filters["semantic_metric"] == metric
    payload_text = str(payload)
    assert "ON_DRIVE" not in payload_text
    assert "GOOD_LENGTH" not in payload_text


def test_normal_chat_does_not_fall_back_to_legacy_when_v2_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_legacy(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("legacy analytics fallback was called")

    monkeypatch.setenv("USE_SEMANTIC_ANALYTICS_V2", "true")
    monkeypatch.setenv("SEMANTIC_V2_DEV_FALLBACK", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setattr(AnalyticsService, "answer_route", fail_legacy)
    get_services.cache_clear()
    app.dependency_overrides.clear()

    with TestClient(app) as test_client:
        response = test_client.post("/api/chat", json={"message": "Predict who will win if India chase 280.", "history": []})

    get_services.cache_clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "analysis"
    assert payload["query_response"]["status"] == "unsupported"
    assert payload["query_response"]["interpretation"]["filters"]["semantic_operation"] == "predictive_analysis"
