from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


class ScriptedGeminiClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return self.responses.pop(0) if self.responses else None


def _plan_json(**overrides: object) -> str:
    plan = {
        "operation": "aggregate",
        "entity": "batter",
        "metric": "batting_strike_rate",
        "group_by": ["batter"],
        "filters": {"batter": "Virat Kohli", "opposition": "Australia"},
        "sort": {"by": "batting_strike_rate", "direction": "desc"},
        "limit": 10,
        "confidence": 0.9,
    }
    plan.update(overrides)
    return json.dumps(plan)


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    config = AppConfig.from_env()
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


def _trace(response) -> dict[str, object]:
    trace_note = next(note for note in response.evidence_notes if note.title == "Semantic V2 trace")
    return json.loads(trace_note.detail)


def test_leaderboard_minimum_sample_is_enforced_and_explained(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Show the top five batting strike rates with minimum 999999 balls"
    )
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "insufficient_evidence"
    assert response.failure_state == "data_limitation"
    assert plan["operation"] == "aggregate"
    assert plan["minimum_sample"]["balls"] == 999999
    assert "minimum sample" in response.insufficiencies[0].detail.lower()


def test_failure_states_distinguish_data_limitation_unsupported_and_planner_uncertainty(
    semantic_service: SemanticAnalyticsService,
) -> None:
    catches = semantic_service.answer_question("Who has taken the most catches in the 2019 World Cup?")
    assert catches.status.value == "insufficient_evidence"
    assert catches.failure_state == "data_limitation"
    assert "fielding" in catches.insufficiencies[0].detail.lower()
    assert "missing" in catches.insufficiencies[0].detail.lower()

    unsupported = semantic_service.answer_question("Which team has the best economy against India?")
    assert unsupported.status.value == "unsupported"
    assert unsupported.failure_state == "unsupported_capability"

    no_llm = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=FakeGeminiClient(),
        app_env="production",
        allow_dev_fallback=False,
    ).answer_question("What is Kohli's strike rate against Australia?")
    assert no_llm.status.value == "unsupported"
    assert no_llm.failure_state == "planner_uncertainty"
    assert "not confident" in no_llm.insufficiencies[0].detail.lower()


def test_tactical_bowling_plan_returns_checked_evidence_probes(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Build a bowling plan against David Miller.")

    assert response.status.value == "supported"
    assert response.interpretation.filters["semantic_operation"] == "tactical_recommendation"
    assert response.interpretation.entities == ["David Miller"]
    assert response.summaries
    assert "checked" in response.summaries[0].body.lower()
    assert len(response.tables) >= 4
    assert len(response.evidence_queries) >= 4
    assert any("length" in table.title.lower() for table in response.tables)
    assert any("line" in table.title.lower() for table in response.tables)
    assert any("bowling style" in table.title.lower() for table in response.tables)
    assert any("scoring zone" in table.title.lower() for table in response.tables)
    assert response.evidence_notes


def test_database_backed_match_facts_use_match_metadata_and_innings_rows(
    semantic_service: SemanticAnalyticsService,
) -> None:
    total = semantic_service.answer_question("What was India's total in the 2011 World Cup final?")
    total_trace = _trace(total)

    assert total.status.value == "supported"
    assert total.interpretation.filters["semantic_operation"] == "match_fact"
    assert total.interpretation.filters["team"] == "India"
    assert total_trace["normalized_plan"]["filters"]["competition"] == "ICC Cricket World Cup"
    assert "analytics.deliveries_v1" in total_trace["final_sql_or_method"]
    assert "277/4" in total.summaries[0].body
    assert total.evidence_queries

    winner = semantic_service.answer_question("Who won the 2011 World Cup final?")
    assert winner.status.value == "supported"
    assert winner.interpretation.filters["semantic_operation"] == "match_fact"
    assert "India won" in winner.summaries[0].body


def test_configured_llm_plan_executes_after_validation(semantic_service: SemanticAnalyticsService) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient([_plan_json()]),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question("What is Kohli's strike rate against Australia?")
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["gemini_raw_response"]
    assert trace["normalized_plan"]["filters"]["batter"] == "Virat Kohli"


def test_invalid_llm_plan_can_be_repaired_before_execution(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient([
            _plan_json(metric="not_a_metric", sort={"by": "not_a_metric", "direction": "desc"}),
            _plan_json(),
        ]),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question("What is Kohli's strike rate against Australia?")
    trace = _trace(response)

    assert response.status.value == "supported"
    assert "REPAIR:" in trace["gemini_raw_response"]
    assert trace["normalized_plan"]["metric"] == "batting_strike_rate"


def test_invalid_llm_plan_fails_when_repair_is_still_invalid(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient([
            _plan_json(metric="not_a_metric", sort={"by": "not_a_metric", "direction": "desc"}),
            _plan_json(metric="still_not_a_metric", sort={"by": "still_not_a_metric", "direction": "desc"}),
        ]),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question("What is Kohli's strike rate against Australia?")

    assert response.status.value == "unsupported"
    assert response.failure_state == "planner_uncertainty"
    assert "not confident" in response.insufficiencies[0].detail.lower()


def test_production_semantic_v2_disables_dev_fallback_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SEMANTIC_V2_DEV_FALLBACK", raising=False)

    config = AppConfig.from_env()

    assert config.app_env == "production"
    assert config.semantic_v2_dev_fallback is False
