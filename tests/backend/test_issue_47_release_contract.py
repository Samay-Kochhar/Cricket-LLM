"""Release-gate contracts for issue 47 that need no model call.

Stored ``over`` is the 1-based over number: legal ball n of an innings lies in
stored over ceil(n / 6). Human over ranges are therefore inclusive on stored
overs, so "overs 41-50" equals the death phase and "overs 1-10" the powerplay.
"""

from __future__ import annotations

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class OfflineGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


class ForbiddenGeminiClient:
    """A configured client that fails the test if any model call is made."""

    def is_configured(self) -> bool:
        return True

    def generate_text(self, *args: object, **kwargs: object) -> str | None:
        raise AssertionError("structured Matchups selections must not call Gemini")

    def generate_structured(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("structured Matchups selections must not call Gemini")


@pytest.fixture(scope="module")
def repository() -> AnalyticsRepository:
    return AnalyticsRepository(AppConfig.from_env().duckdb_path)


@pytest.fixture(scope="module")
def semantic_service(repository: AnalyticsRepository) -> SemanticAnalyticsService:
    return SemanticAnalyticsService(
        repository=repository,
        gemini_client=OfflineGeminiClient(),  # type: ignore[arg-type]
        app_env="development",
    )


def _values(response) -> dict[str, object]:
    table = response.tables[0]
    return dict(zip(table.columns, table.rows[0], strict=True))


def test_bounded_over_range_uses_inclusive_one_based_stored_overs(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "How expensive has Bumrah been between overs 41 and 50?"
    )

    values = _values(response)
    assert response.interpretation.filters["over_range"] == [41, 50]
    assert (values["Runs Conceded"], values["Legal Balls"], values["Economy Rate"]) == (1081, 1123, 5.78)


def test_overs_41_to_50_equal_the_death_phase_and_overs_1_to_10_the_powerplay(
    semantic_service: SemanticAnalyticsService,
) -> None:
    death = _values(semantic_service.answer_question("How expensive is Bumrah from over 41 onwards?"))
    last_ten = _values(semantic_service.answer_question("What is Bumrah's economy in overs 41 to 50?"))
    powerplay = _values(semantic_service.answer_question("What is Bumrah's economy in the powerplay?"))
    first_ten = _values(semantic_service.answer_question("What is Bumrah's economy in overs 1 to 10?"))

    assert last_ten["Economy Rate"] == death["Economy Rate"] == 5.78
    assert last_ten["Legal Balls"] == death["Legal Balls"] == 1123
    assert first_ten["Economy Rate"] == powerplay["Economy Rate"] == 3.96
    assert first_ten["Legal Balls"] == powerplay["Legal Balls"] == 1944


def test_repository_over_range_clause_is_inclusive() -> None:
    clause, params = AnalyticsRepository._over_range_clause([41, 50])

    assert clause == " AND TRY_CAST(over AS DOUBLE) >= ? AND TRY_CAST(over AS DOUBLE) <= ?"
    assert params == [41.0, 50.0]


def test_matchup_page_structured_selections_never_call_gemini(
    repository: AnalyticsRepository,
) -> None:
    service = SemanticAnalyticsService(
        repository=repository,
        gemini_client=ForbiddenGeminiClient(),  # type: ignore[arg-type]
        app_env="production",
        allow_dev_fallback=False,
    )

    result = service.answer_matchup_page(batter="Steven Smith", bowler="Jasprit Bumrah")

    assert result["matchup"].status.value == "supported"
    assert "Steven Smith scored 103 runs from 121 balls" in result["matchup"].summaries[0].body
