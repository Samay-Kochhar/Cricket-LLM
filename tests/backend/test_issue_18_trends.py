from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.bootstrap import get_services
from backend.app.config import AppConfig
from backend.app.cricket_analytics.cricket_definitions import LEGAL_BALL_PREDICATE
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
    repository = AnalyticsRepository(AppConfig.from_env().duckdb_path)
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


def test_batter_change_question_returns_comparable_yearly_evidence(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "Has Shimron Hetmyer become more destructive after 2020?", "history": []},
    )

    assert response.status_code == 200
    result = response.json()["query_response"]
    filters = result["interpretation"]["filters"]
    table = result["tables"][0]
    chart = result["charts"][0]

    assert result["status"] == "supported"
    assert filters["semantic_metric"] == "batting_strike_rate"
    assert filters["semantic_group_by"] == ["year"]
    assert filters["batter"] == "Shimron Hetmyer"
    assert filters["year_mode"] == "after"
    assert filters["years"] == [2020]
    assert table["columns"][:3] == ["Year", "Batting Strike Rate", "Runs Scored"]
    assert chart["chart_type"] == "line"
    assert chart["series"] == [
        {"label": str(row[0]), "value": row[1]}
        for row in table["rows"]
    ]
    assert "comparable yearly sample" in result["summaries"][0]["body"].lower()
    assert "statistical significance" in result["summaries"][0]["body"].lower()
    threshold_note = next(note for note in result["evidence_notes"] if note["title"] == "Yearly evidence threshold")
    assert "60 balls" in threshold_note["detail"]


def test_destructiveness_noun_returns_evidence_without_external_planner(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "Assess Shimron Hetmyer's destructiveness", "history": []},
    )

    assert response.status_code == 200
    result = response.json()["query_response"]

    assert result["status"] == "supported"
    assert result["interpretation"]["filters"]["batter"] == "Shimron Hetmyer"
    assert result["interpretation"]["filters"]["semantic_metric"] == "batting_strike_rate"
    assert "105.49" in result["summaries"][0]["body"]
    assert "1457 balls" in result["summaries"][0]["body"]


def test_filtered_bowler_trend_matches_database_truth(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "Mitchell Starc death-over economy trend after 2018", "history": []},
    )

    assert response.status_code == 200
    result = response.json()["query_response"]
    filters = result["interpretation"]["filters"]
    table = result["tables"][0]
    chart = result["charts"][0]
    repository = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    expected = repository._fetchall(
        f"""
        SELECT
          TRY_CAST(year AS INTEGER) AS year,
          ROUND(SUM(TRY_CAST(bowlruns AS INTEGER)) /
            NULLIF(SUM(CASE WHEN {LEGAL_BALL_PREDICATE} THEN 1 ELSE 0 END) / 6.0, 0), 2) AS economy,
          SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
          SUM(CASE WHEN {LEGAL_BALL_PREDICATE} THEN 1 ELSE 0 END) AS legal_balls,
          COUNT(DISTINCT p_match) AS matches
        FROM analytics.deliveries_v1
        WHERE bowl = ? AND TRY_CAST(year AS INTEGER) >= ? AND TRY_CAST(over AS DOUBLE) > 40.0
        GROUP BY TRY_CAST(year AS INTEGER)
        HAVING SUM(CASE WHEN {LEGAL_BALL_PREDICATE} THEN 1 ELSE 0 END) >= 60
        ORDER BY year ASC
        """,
        ["Mitchell Starc", 2018],
    )

    assert result["status"] == "supported"
    assert filters["semantic_group_by"] == ["year"]
    assert filters["semantic_metric"] == "economy_rate"
    assert filters["bowler"] == "Mitchell Starc"
    assert filters["phase"] == "death"
    assert filters["year_mode"] == "after"
    assert table["columns"] == ["Year", "Economy Rate", "Runs Conceded", "Legal Balls", "Matches"]
    assert table["rows"] == [list(row) for row in expected]
    assert chart["series"] == [
        {"label": str(row[0]), "value": row[1]}
        for row in table["rows"]
    ]
    assert "descriptive change" in result["summaries"][0]["body"].lower()
    assert "not a claim of statistical significance" in result["summaries"][0]["body"].lower()
    trace = json.loads(next(note["detail"] for note in result["evidence_notes"] if note["title"] == "Semantic V2 trace"))
    assert trace["final_answer_metadata"]["result_validation"]["warnings"] == []


def test_trend_questions_retain_style_venue_and_opposition_filters(client: TestClient) -> None:
    style_response = client.post(
        "/api/chat",
        json={"message": "Has Heinrich Klaasen improved against spin over time?", "history": []},
    ).json()["query_response"]
    scoped_response = client.post(
        "/api/chat",
        json={
            "message": "Show Jasprit Bumrah's economy trend year by year against Australia at Sydney Cricket Ground in death overs",
            "history": [],
        },
    ).json()["query_response"]

    assert style_response["interpretation"]["filters"] | {
        "batter": "Heinrich Klaasen",
        "bowling_style": "spin",
        "semantic_metric": "batting_strike_rate",
        "semantic_group_by": ["year"],
    } == style_response["interpretation"]["filters"]
    assert scoped_response["interpretation"]["filters"] | {
        "bowler": "Jasprit Bumrah",
        "phase": "death",
        "opposition": "Australia",
        "venue": "Sydney Cricket Ground",
        "semantic_metric": "economy_rate",
        "semantic_group_by": ["year"],
    } == scoped_response["interpretation"]["filters"]
