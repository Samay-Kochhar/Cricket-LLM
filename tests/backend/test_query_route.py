from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.bootstrap import get_services
from backend.app.domain.evidence_models import (
    Citation,
    CitationSource,
    EvidenceStatus,
    QueryInterpretation,
    QueryResponse,
    SummaryBlock,
)
from backend.app.services.chat_service import ChatReply, ConversationState
from backend.app.main import app


class FakeRepository:
    def health(self) -> dict[str, object]:
        return {"database_available": True, "delivery_rows": 42}

    def list_player_names(self) -> list[str]:
        return ["Steven Smith", "Virat Kohli"]

    def search_players(self, query: str) -> list[str]:
        return ["Steven Smith"] if "steve" in query.lower() else ["Virat Kohli"]

    def get_player_batting_summary(self, player_name: str) -> dict[str, object] | None:
        if player_name == "Steven Smith":
            return {"player_name": "Steven Smith", "runs_scored": 300, "balls_faced": 280}
        if player_name == "Virat Kohli":
            return {"player_name": "Virat Kohli", "runs_scored": 320, "balls_faced": 290}
        return None

    def get_player_year_trend(self, player_name: str) -> list[dict[str, object]]:
        return [{"year": 2024, "runs_scored": 120, "balls_faced": 100, "control_percentage": 81.2}]

    def get_venue_bowling_leaderboard(self, venue_name: str) -> list[dict[str, object]]:
        return [{"player_name": "Jasprit Bumrah", "wickets": 6, "deliveries": 60, "runs_conceded": 42, "economy_rate": 4.2}]


@pytest.fixture()
def client() -> Iterator[TestClient]:
    def fake_query_handler(question: str) -> QueryResponse:
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=QueryInterpretation(
                original_question=question,
                query_class="role_comparison",
                entities=["Virat Kohli", "Steven Smith"],
            ),
            summaries=[SummaryBlock(title="Comparison", body="Virat Kohli leads the sample comparison.")],
            citations=[
                Citation(
                    label="Database evidence",
                    source_type=CitationSource.database,
                    locator="analytics.deliveries_v1",
                )
            ],
        )

    class FakeChatService:
        def reply(
            self,
            message: str,
            history: list[dict[str, str]],
            conversation_state: ConversationState | None = None,
        ) -> ChatReply:
            state_suffix = f" [{conversation_state.metric}]" if conversation_state else ""
            return ChatReply(
                mode="conversation",
                message=f"Atlas heard: {message}{state_suffix}",
                suggestions=["Compare Virat Kohli at number 3 vs opening in ODIs"],
            )

    app.dependency_overrides[get_services] = lambda: {
        "repository": FakeRepository(),
        "query_handler": fake_query_handler,
        "matchup_handler": lambda **kwargs: {
            "matchup": fake_query_handler(f"{kwargs['batter']} vs {kwargs['bowler']}"),
            "baseline": fake_query_handler(f"{kwargs['batter']} baseline"),
        },
        "chat_service": FakeChatService(),
    }
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_query_route_returns_structured_payload(client: TestClient) -> None:
    response = client.post("/api/query", json={"question": "Compare Virat Kohli and Steven Smith"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "supported"
    assert payload["interpretation"]["query_class"] == "role_comparison"
    assert payload["summaries"][0]["title"] == "Comparison"


def test_matchup_route_accepts_filters_without_language_interpretation(client: TestClient) -> None:
    response = client.post(
        "/api/matchups",
        json={
            "batter": "Steven Smith",
            "bowler": "Jasprit Bumrah",
            "phase": "death",
            "year": 2023,
            "venue": "Sydney Cricket Ground",
        },
    )

    assert response.status_code == 200
    assert response.json()["matchup"]["interpretation"]["original_question"] == "Steven Smith vs Jasprit Bumrah"
    assert response.json()["baseline"]["interpretation"]["original_question"] == "Steven Smith baseline"


def test_player_search_route_returns_items(client: TestClient) -> None:
    response = client.get("/api/players/search", params={"q": "steve"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"] == ["Steven Smith"]


def test_player_profile_route_resolves_aliases(client: TestClient) -> None:
    response = client.get("/api/players/Steve%20Smith")

    assert response.status_code == 200
    payload = response.json()
    assert payload["player_name"] == "Steven Smith"
    assert payload["summary"]["runs_scored"] == 300


def test_chat_route_returns_chat_payload(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "Tell me about Virat Kohli",
            "history": [{"role": "user", "content": "Hi"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "conversation"
    assert payload["message"] == "Atlas heard: Tell me about Virat Kohli"
    assert payload["suggestions"] == ["Compare Virat Kohli at number 3 vs opening in ODIs"]


def test_chat_route_accepts_structured_conversation_state(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "What about powerplay?",
            "history": [],
            "conversation_state": {
                "players": ["Jasprit Bumrah", "Mitchell Starc"],
                "metric": "economy_rate",
                "comparison_participants": ["Jasprit Bumrah", "Mitchell Starc"],
                "comparison_metrics": ["economy_rate", "bowling_strike_rate"],
                "filters": {"phase": "death"},
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Atlas heard: What about powerplay? [economy_rate]"
