from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.cricket_analytics.cricket_definitions import public_label
from backend.app.db.repository import AnalyticsRepository
from tests.backend.golden_factual_chat_cases import GOLDEN_FACTUAL_CHAT_CASES


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    config = AppConfig.from_env()
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


def _trace(response) -> dict[str, object] | None:
    for note in response.evidence_notes:
        if note.title == "Semantic V2 trace":
            return json.loads(note.detail)
    return None


def _public_payload(response) -> str:
    return response.model_dump_json()


def _assert_no_raw_enums(response) -> None:
    payload = _public_payload(response)
    leaked = [token for token in ("ON_DRIVE", "GOOD_LENGTH", "SHORT_OF_A_GOOD_LENGTH", "THIRD_MAN") if token in payload]
    assert leaked == []


def test_golden_suite_has_at_least_140_structured_cases() -> None:
    assert len(GOLDEN_FACTUAL_CHAT_CASES) >= 140
    for case in GOLDEN_FACTUAL_CHAT_CASES:
        assert case["question"]
        assert case["status"] in {"supported", "unsupported", "insufficient_evidence"}
        assert "filters" in case
        assert "group_by" in case


@pytest.mark.parametrize(
    "case",
    GOLDEN_FACTUAL_CHAT_CASES,
    ids=lambda case: str(case["question"])[:80],
)
def test_golden_factual_chat_contract(semantic_service: SemanticAnalyticsService, case: dict[str, object]) -> None:
    response = semantic_service.answer_question(str(case["question"]))
    trace = _trace(response)

    assert response.status.value == case["status"]
    _assert_no_raw_enums(response)

    expected_operation = case.get("operation")
    if expected_operation in {"batting_profile", "batting_position_compare"}:
        assert response.interpretation.filters.get("semantic_operation") == expected_operation
        assert response.summaries
        return

    assert trace is not None
    plan = trace["normalized_plan"]
    assert plan["operation"] == expected_operation
    assert plan["entity"] == case["entity"]
    assert plan["metric"] == case["metric"]

    expected_group_by = case.get("group_by") or []
    if expected_group_by:
        assert plan["group_by"] == expected_group_by

    for key, value in dict(case.get("filters") or {}).items():
        actual = plan["filters"].get(key)
        if key == "compare_players" and isinstance(actual, list) and isinstance(value, list):
            assert set(actual) == set(value)
            continue
        assert actual == value or actual == public_label(value)

    if case.get("limit") is not None:
        assert plan["limit"] == case["limit"]

    if case["status"] == "supported":
        assert response.tables or response.visual_payload
        columns = set(trace.get("result_columns") or [])
        for column in case.get("columns") or []:
            assert column in columns or column in _public_payload(response)
        if case["metric"] in {
            "batting_strike_rate",
            "economy_rate",
            "batter_dot_ball_percentage",
            "bowler_dot_ball_percentage",
            "boundary_percentage",
            "false_shot_percentage",
            "yorker_percentage",
            "false_shots_per_over",
            "boundary_rate_per_100_balls",
        }:
            assert "balls" in _public_payload(response).lower()
    elif case["status"] == "unsupported":
        assert response.summaries or response.insufficiencies
        lowered = _public_payload(response).lower()
        assert (
            "not implemented" in lowered
            or "not support" in lowered
            or "invalid" in lowered
            or "not compatible" in lowered
            or "not production-ready" in lowered
        )
    else:
        assert response.insufficiencies
