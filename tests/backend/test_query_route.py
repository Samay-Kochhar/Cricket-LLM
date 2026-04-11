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

    app.dependency_overrides[get_services] = lambda: {
        "repository": FakeRepository(),
        "query_handler": fake_query_handler,
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
