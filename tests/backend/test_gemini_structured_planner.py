from __future__ import annotations

import json
from typing import Any

from backend.app.config import AppConfig
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.db.repository import AnalyticsRepository
from backend.app.services.chat_service import ChatService
from backend.app.services.gemini_client import GeminiClient, GeminiStructuredResult


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"operation":"aggregate"}'}]},
                }
            ],
            "modelVersion": "gemini-test-version",
            "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 25},
        }


def test_structured_generation_sends_schema_and_reports_safe_metadata(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse()

    monkeypatch.setattr("backend.app.services.gemini_client.httpx.post", fake_post)
    client = GeminiClient(
        api_key="secret-test-key",
        default_model="gemini-default",
        complex_model="gemini-complex",
    )
    schema = {"type": "object", "required": ["operation"]}

    result = client.generate_structured(
        "Return a cricket plan",
        response_schema=schema,
        prefer_complex=True,
    )

    config = captured["json"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == schema
    assert config["maxOutputTokens"] >= 1024
    assert result.text == '{"operation":"aggregate"}'
    assert result.selected_model == "gemini-complex"
    assert result.model_version == "gemini-test-version"
    assert result.finish_reason == "STOP"
    assert result.prompt_token_count == 50
    assert result.output_token_count == 25
    assert result.latency_ms >= 0
    assert "secret-test-key" not in repr(result)


class _ScriptedStructuredClient:
    def __init__(self, results: list[GeminiStructuredResult]) -> None:
        self.results = results
        self.calls: list[dict[str, Any]] = []

    def is_configured(self) -> bool:
        return True

    def generate_structured(self, prompt: str, **kwargs: Any) -> GeminiStructuredResult:
        self.calls.append({"prompt": prompt, **kwargs})
        return self.results.pop(0)

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


def _structured_result(text: str | None, finish_reason: str = "STOP") -> GeminiStructuredResult:
    return GeminiStructuredResult(
        text=text,
        selected_model="gemini-planner",
        model_version="gemini-planner-001",
        finish_reason=finish_reason,
        latency_ms=12.5,
        prompt_token_count=100,
        output_token_count=50,
    )


def _plan_json(**overrides: Any) -> str:
    plan: dict[str, Any] = {
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


def _planner(client: _ScriptedStructuredClient) -> SemanticQueryPlanner:
    return SemanticQueryPlanner(
        gemini_client=client,  # type: ignore[arg-type]
        available_players=["Virat Kohli", "Rohit Sharma", "Mitchell Starc"],
        allow_dev_fallback=False,
    )


def test_truncated_plan_is_repaired_once_even_when_its_json_looks_valid() -> None:
    client = _ScriptedStructuredClient([
        _structured_result(_plan_json(), finish_reason="MAX_TOKENS"),
        _structured_result(_plan_json()),
    ])
    trace = QueryTrace(original_user_question="What is Kohli's strike rate against Australia?")

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["parse_outcome"] == "truncated"
    assert trace.planner_attempts[0]["validation_outcome"] == "not_run"
    assert trace.planner_attempts[0]["schema_constrained"] is True
    assert trace.planner_outcome["repair_outcome"] == "succeeded"
    assert trace.planner_outcome["selected_model"] == "gemini-planner"
    assert trace.planner_outcome["latency_ms"] == 25.0
    assert client.calls[0]["response_schema"]
    assert client.calls[0]["max_output_tokens"] >= 1024


def test_invalid_plan_is_repaired_once_then_reported_honestly() -> None:
    client = _ScriptedStructuredClient([
        _structured_result("not-json"),
        _structured_result(_plan_json(metric="unknown_metric")),
    ])
    trace = QueryTrace(original_user_question="Give me a valid ODI statistic")

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is False
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["parse_outcome"] == "invalid_json"
    assert trace.planner_attempts[1]["validation_outcome"] == "invalid"
    assert trace.planner_outcome["repair_outcome"] == "failed"
    assert trace.planner_outcome["attempt_count"] == 2


def test_unknown_plan_fields_are_rejected_by_the_typed_contract() -> None:
    client = _ScriptedStructuredClient([
        _structured_result(_plan_json(invented_field="not allowed")),
        _structured_result(_plan_json()),
    ])
    trace = QueryTrace(original_user_question="What is Kohli's strike rate against Australia?")

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert trace.planner_attempts[0]["parse_outcome"] == "schema_invalid"
    assert trace.planner_outcome["repair_outcome"] == "succeeded"


def test_production_preserves_gemini_comparison_meaning() -> None:
    comparison = _plan_json(
        operation="player_compare",
        entity="batter",
        metric="runs_scored",
        group_by=["batter"],
        filters={
            "compare_players": ["Virat Kohli", "Rohit Sharma"],
            "comparison_metrics": ["runs_scored"],
        },
        sort={"by": "runs_scored", "direction": "desc"},
    )
    client = _ScriptedStructuredClient([_structured_result(comparison)])
    trace = QueryTrace(original_user_question="Compare Virat and Rohit in ODIs")

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.filters["comparison_metrics"] == ["runs_scored"]
    assert trace.planner_outcome["repair_outcome"] == "not_needed"


def _live_chat(client: _ScriptedStructuredClient) -> ChatService:
    config = AppConfig.from_env()
    repository = AnalyticsRepository(config.duckdb_path)
    semantic = SemanticAnalyticsService(
        repository=repository,
        gemini_client=client,  # type: ignore[arg-type]
        app_env="production",
        allow_dev_fallback=False,
    )
    return ChatService(
        repository=repository,
        query_handler=semantic.answer_question,
        gemini_client=client,  # type: ignore[arg-type]
    )


def test_canonical_typed_planner_questions_pass_through_live_chat() -> None:
    direct_client = _ScriptedStructuredClient([_structured_result(_plan_json())])
    direct = _live_chat(direct_client).reply(
        "What is Virat Kohli's batting strike rate against Australia?",
        history=[],
    )
    assert direct.mode == "analysis"
    assert direct.query_response is not None
    assert direct.query_response.status.value == "supported"

    matchup_client = _ScriptedStructuredClient([
        _structured_result(
            _plan_json(
                operation="matchup",
                entity="matchup",
                metric="batting_strike_rate",
                group_by=["matchup"],
                filters={"batter": "Virat Kohli", "bowler": "Mitchell Starc"},
            )
        )
    ])
    matchup = _live_chat(matchup_client).reply(
        "Show the ODI matchup between Virat Kohli and Mitchell Starc.",
        history=[],
    )
    assert matchup.mode == "analysis"
    assert matchup.query_response is not None
    assert matchup.query_response.status.value == "supported"

    invalid_client = _ScriptedStructuredClient([
        _structured_result("not-json"),
        _structured_result("still-not-json"),
    ])
    invalid = _live_chat(invalid_client).reply(
        "What is Virat Kohli's batting average in ODIs?",
        history=[],
    )
    assert invalid.query_response is not None
    assert invalid.query_response.failure_state == "planner_uncertainty"

    ambiguous_client = _ScriptedStructuredClient([])
    ambiguous = _live_chat(ambiguous_client).reply(
        "What is Jasprit Bumrah's strike rate?",
        history=[],
    )
    assert ambiguous.mode == "clarification"
    assert ambiguous.query_response is None
    assert ambiguous_client.calls == []
