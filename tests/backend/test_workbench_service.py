from __future__ import annotations

from backend.app.domain.evidence_models import EvidenceStatus, QueryInterpretation, QueryResponse, SummaryBlock
from backend.app.services.workbench_service import WorkbenchService


class FakeRepository:
    def search_players(self, query: str, limit: int = 5) -> list[str]:
        if "virat" in query.lower():
            return ["Virat Kohli"]
        return []

    def search_teams(self, query: str, limit: int = 5) -> list[str]:
        if "india" in query.lower():
            return ["India"]
        return []

    def get_team_available_years(self, team_name: str) -> list[int]:
        return [2023, 2022, 2021]

    def get_team_year_squad(self, team_name: str, year: int) -> list[dict[str, object]]:
        return [{"player_name": "Virat Kohli", "role_summary": "Right-hand bat | ODI batter profile"}]

    def get_player_batting_summary(self, player_name: str, phase: str | None = None) -> dict[str, object]:
        return {"runs_scored": 13848, "balls_faced": 15000}

    def get_primary_batting_hand(self, player_name: str, bowler_name: str | None = None, phase: str | None = None) -> str:
        return "RHB"

    def get_player_split_summary(self, player_name: str, phase: str | None = None) -> dict[str, float]:
        return {"pace_strike_rate": 92.0, "spin_strike_rate": 88.0}


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False


def fake_query_handler(question: str) -> QueryResponse:
    return QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question=question,
            query_class="role_comparison",
            entities=["Virat Kohli"],
        ),
        summaries=[SummaryBlock(title="Snapshot", body="Virat Kohli ODI snapshot.")],
    )


def test_workbench_search_returns_player_result() -> None:
    service = WorkbenchService(FakeRepository(), fake_query_handler, FakeGeminiClient())

    payload = service.search("Virat Kohli")

    assert payload["kind"] == "player_result"
    assert payload["player_name"] == "Virat Kohli"


def test_workbench_search_requests_year_for_team_query() -> None:
    service = WorkbenchService(FakeRepository(), fake_query_handler, FakeGeminiClient())

    payload = service.search("India")

    assert payload["kind"] == "team_year_required"
    assert payload["team_name"] == "India"
