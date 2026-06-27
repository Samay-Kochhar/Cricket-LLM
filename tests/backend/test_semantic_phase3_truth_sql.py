from __future__ import annotations

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


LEGAL = "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
WICKET = "LOWER(CAST(dismissal AS VARCHAR)) IN ('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture(scope="module")
def repository() -> AnalyticsRepository:
    return AnalyticsRepository(AppConfig.from_env().duckdb_path)


@pytest.fixture(scope="module")
def semantic_service(repository: AnalyticsRepository) -> SemanticAnalyticsService:
    return SemanticAnalyticsService(repository=repository, gemini_client=FakeGeminiClient(), app_env="development")


def _single_cell(response, label: str, player_label: str | None = None) -> float:
    assert response.status.value == "supported"
    assert response.tables
    table = response.tables[0]
    column_index = table.columns.index(label)
    if player_label is None:
        return float(table.rows[0][column_index])
    player_index = table.columns.index("Player")
    for row in table.rows:
        if row[player_index] == player_label:
            return float(row[column_index])
    raise AssertionError(f"{player_label} not found in response rows")


def _sql_value(repository: AnalyticsRepository, sql: str, params: list[object]) -> float:
    row = repository._fetchone(sql, params)
    assert row is not None
    return float(row[0])


TRUTH_CASES = [
    (
        "What is Kohli's strike rate against Australia?",
        "Batting Strike Rate",
        None,
        f"""
        SELECT ROUND(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
            / NULLIF(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END), 0) * 100.0, 2)
        FROM analytics.deliveries_v1 WHERE bat = ? AND team_bowl = ?
        """,
        ["Virat Kohli", "Australia"],
    ),
    (
        "What is Rohit Sharma's strike rate versus Pakistan?",
        "Batting Strike Rate",
        None,
        f"""
        SELECT ROUND(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
            / NULLIF(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END), 0) * 100.0, 2)
        FROM analytics.deliveries_v1 WHERE bat = ? AND team_bowl = ?
        """,
        ["Rohit Sharma", "Pakistan"],
    ),
    (
        "What is Bumrah's economy against Australia?",
        "Economy Rate",
        None,
        f"""
        SELECT ROUND(SUM(TRY_CAST(bowlruns AS INTEGER))
            / NULLIF(SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) / 6.0, 0), 2)
        FROM analytics.deliveries_v1 WHERE bowl = ? AND team_bat = ?
        """,
        ["Jasprit Bumrah", "Australia"],
    ),
    (
        "How many wickets has Starc taken against India?",
        "Wickets Taken",
        None,
        f"""
        SELECT SUM(CASE WHEN {WICKET} THEN 1 ELSE 0 END)
        FROM analytics.deliveries_v1 WHERE bowl = ? AND team_bat = ?
        """,
        ["Mitchell Starc", "India"],
    ),
    (
        "What is Rabada's dot-ball percentage versus Australia?",
        "Bowler Dot Ball Percentage",
        None,
        f"""
        SELECT ROUND(SUM(CASE WHEN {LEGAL} AND TRY_CAST(bowlruns AS INTEGER)=0 THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END), 0) * 100.0, 2)
        FROM analytics.deliveries_v1 WHERE bowl = ? AND team_bat = ?
        """,
        ["Kagiso Rabada", "Australia"],
    ),
    (
        "What is Bumrah's economy at Wankhede?",
        "Economy Rate",
        None,
        f"""
        SELECT ROUND(SUM(TRY_CAST(bowlruns AS INTEGER))
            / NULLIF(SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) / 6.0, 0), 2)
        FROM analytics.deliveries_v1 WHERE bowl = ? AND ground = ?
        """,
        ["Jasprit Bumrah", "Wankhede Stadium, Mumbai"],
    ),
    (
        "How many runs has Virat Kohli scored at Wankhede?",
        "Runs Scored",
        None,
        """
        SELECT SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
        FROM analytics.deliveries_v1 WHERE bat = ? AND ground = ?
        """,
        ["Virat Kohli", "Wankhede Stadium, Mumbai"],
    ),
    (
        "What is Rohit Sharma's strike rate at Lord's?",
        "Batting Strike Rate",
        None,
        f"""
        SELECT ROUND(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
            / NULLIF(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END), 0) * 100.0, 2)
        FROM analytics.deliveries_v1 WHERE bat = ? AND ground = ?
        """,
        ["Rohit Sharma", "Lord's, London"],
    ),
    (
        "Compare Kohli and Rohit against Australia.",
        "Batting Strike Rate",
        "Virat Kohli",
        f"""
        SELECT ROUND(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
            / NULLIF(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END), 0) * 100.0, 2)
        FROM analytics.deliveries_v1 WHERE bat = ? AND team_bowl = ?
        """,
        ["Virat Kohli", "Australia"],
    ),
    (
        "Compare Kohli and Rohit against Australia.",
        "Batting Strike Rate",
        "Rohit Sharma",
        f"""
        SELECT ROUND(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
            / NULLIF(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END), 0) * 100.0, 2)
        FROM analytics.deliveries_v1 WHERE bat = ? AND team_bowl = ?
        """,
        ["Rohit Sharma", "Australia"],
    ),
    (
        "Who has the better death-over economy, Bumrah or Starc?",
        "Economy Rate",
        "Jasprit Bumrah",
        f"""
        SELECT ROUND(SUM(TRY_CAST(bowlruns AS INTEGER))
            / NULLIF(SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) / 6.0, 0), 2)
        FROM analytics.deliveries_v1 WHERE bowl = ? AND TRY_CAST(over AS DOUBLE) > 40
        """,
        ["Jasprit Bumrah"],
    ),
    (
        "Who has the better death-over economy, Bumrah or Starc?",
        "Economy Rate",
        "Mitchell Starc",
        f"""
        SELECT ROUND(SUM(TRY_CAST(bowlruns AS INTEGER))
            / NULLIF(SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) / 6.0, 0), 2)
        FROM analytics.deliveries_v1 WHERE bowl = ? AND TRY_CAST(over AS DOUBLE) > 40
        """,
        ["Mitchell Starc"],
    ),
    (
        "Show Kohli's strike rate by venue.",
        "Batting Strike Rate",
        None,
        """
        SELECT ROUND(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
            / NULLIF(SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END), 0) * 100.0, 2)
        FROM analytics.deliveries_v1 WHERE bat = ? GROUP BY ground HAVING SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END) >= 20
        ORDER BY 1 DESC, SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN 1 ELSE 0 END) DESC LIMIT 1
        """,
        ["Virat Kohli"],
    ),
    (
        "Where has Hardik Pandya scored most runs by venue?",
        "Runs Scored",
        None,
        """
        SELECT SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER)=1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
        FROM analytics.deliveries_v1 WHERE bat = ? GROUP BY ground ORDER BY 1 DESC LIMIT 1
        """,
        ["Hardik Pandya"],
    ),
    (
        "Which ground has Starc taken the most wickets at?",
        "Wickets Taken",
        None,
        f"""
        SELECT SUM(CASE WHEN {WICKET} THEN 1 ELSE 0 END)
        FROM analytics.deliveries_v1 WHERE bowl = ? GROUP BY ground ORDER BY 1 DESC LIMIT 1
        """,
        ["Mitchell Starc"],
    ),
]


@pytest.mark.parametrize("question,label,player_label,sql,params", TRUTH_CASES)
def test_semantic_phase3_answers_match_direct_sql(
    semantic_service: SemanticAnalyticsService,
    repository: AnalyticsRepository,
    question: str,
    label: str,
    player_label: str | None,
    sql: str,
    params: list[object],
) -> None:
    response = semantic_service.answer_question(question)
    actual = _single_cell(response, label, player_label)
    expected = _sql_value(repository, sql, params)
    assert actual == pytest.approx(expected, abs=0.01)
