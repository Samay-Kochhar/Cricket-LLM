from __future__ import annotations

import json
from typing import Any

import httpx

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


def test_structured_generation_reports_safe_http_status_for_quota_failure(monkeypatch) -> None:
    def quota_response(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            429,
            request=httpx.Request("POST", url),
            json={"error": {"status": "RESOURCE_EXHAUSTED"}},
        )

    monkeypatch.setattr("backend.app.services.gemini_client.httpx.post", quota_response)
    client = GeminiClient(
        api_key="secret-test-key",
        default_model="gemini-default",
        complex_model="gemini-complex",
    )

    result = client.generate_structured("Return a plan", response_schema={"type": "object"})

    assert result.error_kind == "http_429"
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
        available_venues=["R Premadasa Stadium, Colombo"],
        available_teams=["Sri Lanka", "Australia", "India"],
        allow_dev_fallback=False,
    )


def test_novel_named_player_question_still_uses_gemini() -> None:
    client = _ScriptedStructuredClient([
        _structured_result(
            _plan_json(filters={"batter": "Virat Kohli"}),
        )
    ])
    planner = SemanticQueryPlanner(
        gemini_client=client,  # type: ignore[arg-type]
        available_players=["Virat Kohli"],
        allow_dev_fallback=True,
    )
    question = "How has Virat Kohli adapted his batting approach under pressure?"

    result = planner.plan(question, QueryTrace(original_user_question=question))

    assert result.validation.valid is True
    assert result.used_gemini is True
    assert len(client.calls) == 1


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


def test_production_unqualified_comparison_uses_core_metrics_for_gemini_role() -> None:
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
    assert result.plan.entity == "batter"
    assert result.plan.filters["comparison_metrics"] == [
        "batting_strike_rate",
        "runs_scored",
        "batting_average",
        "batter_dot_ball_percentage",
        "boundary_percentage",
    ]
    assert trace.planner_outcome["repair_outcome"] == "not_needed"


def test_production_metric_specific_comparison_preserves_requested_total_runs() -> None:
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
    trace = QueryTrace(original_user_question="Compare Virat and Rohit by total runs")

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.filters["comparison_metrics"] == ["runs_scored"]


def test_production_repairs_comparison_with_mixed_role_metrics() -> None:
    mixed_role = _plan_json(
        operation="player_compare",
        entity="bowler",
        metric="economy_rate",
        group_by=["bowler"],
        filters={
            "compare_players": ["Jasprit Bumrah", "Mitchell Starc"],
            "comparison_metrics": ["economy_rate", "batting_average"],
        },
        sort={"by": "economy_rate", "direction": "asc"},
    )
    repaired = _plan_json(
        operation="player_compare",
        entity="bowler",
        metric="economy_rate",
        group_by=["bowler"],
        filters={
            "compare_players": ["Jasprit Bumrah", "Mitchell Starc"],
            "comparison_metrics": ["economy_rate", "bowling_average"],
        },
        sort={"by": "economy_rate", "direction": "asc"},
    )
    client = _ScriptedStructuredClient([
        _structured_result(mixed_role),
        _structured_result(repaired),
    ])
    trace = QueryTrace(
        original_user_question="Compare Bumrah and Starc on economy and bowling average"
    )

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.filters["comparison_metrics"] == ["economy_rate", "bowling_average"]
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["validation_outcome"] == "invalid"
    assert trace.planner_outcome["repair_outcome"] == "succeeded"


def test_production_repairs_silently_broadened_bowling_style_filter() -> None:
    broadened = _plan_json(
        filters={"batter": "Glenn Maxwell", "bowling_style": "spin"},
    )
    repaired = _plan_json(
        filters={"batter": "Glenn Maxwell", "bowling_style": "off_spin"},
    )
    client = _ScriptedStructuredClient([
        _structured_result(broadened),
        _structured_result(repaired),
    ])
    trace = QueryTrace(
        original_user_question="What is Maxwell's batting strike rate against off spin?"
    )

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.filters["bowling_style"] == "off_spin"
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["validation_outcome"] == "invalid"
    assert trace.planner_outcome["repair_outcome"] == "succeeded"


def test_production_repairs_named_bowler_false_shot_rate_perspective() -> None:
    batter_plan = _plan_json(
        entity="batter",
        metric="false_shot_percentage",
        group_by=["line"],
        filters={"batter": "Jasprit Bumrah"},
        sort={"by": "false_shot_percentage", "direction": "desc"},
    )
    bowler_plan = _plan_json(
        entity="bowler",
        metric="false_shots_per_over",
        group_by=["line"],
        filters={"bowler": "Jasprit Bumrah"},
        sort={"by": "false_shots_per_over", "direction": "desc"},
    )
    client = _ScriptedStructuredClient([
        _structured_result(batter_plan),
        _structured_result(bowler_plan),
    ])
    trace = QueryTrace(
        original_user_question="Show Bumrah's false shots per over by line."
    )

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.entity == "bowler"
    assert result.plan.metric == "false_shots_per_over"
    assert result.plan.filters["bowler"] == "Jasprit Bumrah"
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["validation_outcome"] == "invalid"


def test_production_repairs_passive_dismissal_player_ownership() -> None:
    wrong_player_role = _plan_json(
        entity="bowler",
        metric="wickets_taken",
        group_by=["length"],
        filters={"bowler": "David Miller"},
        sort={"by": "wickets_taken", "direction": "desc"},
    )
    repaired = _plan_json(
        entity="bowler",
        metric="wickets_taken",
        group_by=["length"],
        filters={"batter": "David Miller"},
        sort={"by": "wickets_taken", "direction": "desc"},
    )
    client = _ScriptedStructuredClient([
        _structured_result(wrong_player_role),
        _structured_result(repaired),
    ])
    trace = QueryTrace(
        original_user_question="Where is David Miller dismissed most often by length?"
    )

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.filters["batter"] == "David Miller"
    assert "bowler" not in result.plan.filters
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["validation_outcome"] == "invalid"


def test_production_repairs_dropped_ranking_limit_and_explicit_sample() -> None:
    dropped_constraints = _plan_json(
        entity="bowler",
        metric="yorker_count",
        group_by=["bowler"],
        filters={"phase": "death"},
        sort={"by": "yorker_count", "direction": "asc"},
        limit=10,
        minimum_sample=None,
        minimum_sample_explicit=False,
    )
    repaired = _plan_json(
        entity="bowler",
        metric="yorker_count",
        group_by=["bowler"],
        filters={"phase": "death"},
        sort={"by": "yorker_count", "direction": "asc"},
        limit=3,
        minimum_sample={"legal_balls": 100},
        minimum_sample_explicit=True,
    )
    client = _ScriptedStructuredClient([
        _structured_result(dropped_constraints),
        _structured_result(repaired),
    ])
    trace = QueryTrace(
        original_user_question=(
            "Show the bottom 3 bowlers with the fewest yorkers at the death, "
            "minimum 100 legal balls"
        )
    )

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.limit == 3
    assert result.plan.minimum_sample is not None
    assert result.plan.minimum_sample.legal_balls == 100
    assert result.plan.minimum_sample_explicit is True
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["validation_outcome"] == "invalid"


def test_production_repairs_dropped_ranking_scope_filters() -> None:
    dropped_scope = _plan_json(
        entity="batter",
        metric="false_shot_percentage",
        group_by=["batter"],
        filters={"bowling_style": "spin"},
        sort={"by": "false_shot_percentage", "direction": "desc"},
        limit=5,
        minimum_sample={"balls": 20},
        minimum_sample_explicit=True,
    )
    repaired = _plan_json(
        entity="batter",
        metric="false_shot_percentage",
        group_by=["batter"],
        filters={
            "bowling_style": "spin",
            "venue": "R Premadasa Stadium, Colombo",
            "phase": "middle",
            "years": [2009],
            "opposition": "Sri Lanka",
        },
        sort={"by": "false_shot_percentage", "direction": "desc"},
        limit=5,
        minimum_sample={"balls": 20},
        minimum_sample_explicit=True,
    )
    client = _ScriptedStructuredClient([
        _structured_result(dropped_scope),
        _structured_result(repaired),
    ])
    trace = QueryTrace(
        original_user_question=(
            "Show the top 5 batters by highest false shot percentage against spin "
            "at R Premadasa Stadium, Colombo in middle overs in 2009 against Sri Lanka, "
            "minimum 20 balls"
        )
    )

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.filters == {
        "bowling_style": "spin",
        "venue": "R Premadasa Stadium, Colombo",
        "phase": "middle",
        "years": [2009],
        "opposition": "Sri Lanka",
    }
    assert len(client.calls) == 2
    assert trace.planner_attempts[0]["validation_outcome"] == "invalid"


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


def test_typed_batter_comparison_preserves_players_style_metric_and_sample_in_live_chat() -> None:
    client = _ScriptedStructuredClient([
        _structured_result(
            _plan_json(
                operation="player_compare",
                entity="batter",
                metric="batting_average",
                group_by=["batter"],
                filters={
                    "compare_players": ["KL Rahul", "Shreyas Iyer"],
                    "comparison_metrics": ["batting_average"],
                    "bowling_style": "spin",
                },
                sort={"by": "batting_average", "direction": "desc"},
            )
        )
    ])

    reply = _live_chat(client).reply(
        "How do KL Rahul and Shreyas Iyer compare by batting average against spin?",
        history=[],
    )

    assert reply.mode == "analysis"
    assert reply.query_response is not None
    response = reply.query_response
    assert response.status.value == "supported"
    assert response.interpretation.entities == ["KL Rahul", "Shreyas Iyer"]
    assert response.interpretation.filters["bowling_style"] == "spin"
    assert response.interpretation.filters["comparison_metrics"] == ["batting_average"]
    assert response.tables[0].columns == [
        "Player",
        "Batting Average",
        "Balls Faced",
        "Dismissals",
        "Matches",
    ]
    assert response.summaries[0].body == (
        "Shreyas Iyer had a higher batting average than KL Rahul: 71.4 vs 54."
    )


def test_typed_bowler_comparison_preserves_phase_and_bowler_metrics_in_live_chat() -> None:
    client = _ScriptedStructuredClient([
        _structured_result(
            _plan_json(
                operation="player_compare",
                entity="bowler",
                metric="wickets_per_over",
                group_by=["bowler"],
                filters={
                    "compare_players": ["Mitchell Starc", "Jasprit Bumrah"],
                    "comparison_metrics": ["wickets_per_over", "economy_rate"],
                    "phase": "death",
                },
                sort={"by": "wickets_per_over", "direction": "desc"},
            )
        )
    ])

    reply = _live_chat(client).reply(
        "How do Starc and Bumrah compare on economy and wicket rate at the death?",
        history=[],
    )

    assert reply.mode == "analysis"
    assert reply.query_response is not None
    response = reply.query_response
    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Mitchell Starc", "Jasprit Bumrah"]
    assert response.interpretation.filters["phase"] == "death"
    assert response.interpretation.filters["comparison_metrics"] == [
        "wickets_per_over",
        "economy_rate",
    ]
    assert response.tables[0].columns == [
        "Player",
        "Wickets Per Over",
        "Economy Rate",
        "Legal Balls",
        "Runs Conceded",
        "Matches",
    ]
    summary = response.summaries[0].body
    assert "took wickets more frequently than" in summary
    assert " vs " in summary
    assert "The table includes" not in summary


def test_typed_materially_mixed_role_comparison_is_clearly_unsupported_in_live_chat() -> None:
    reason = (
        "This comparison mixes a batter and a bowler without one shared statistical role. "
        "Ask to compare both players as batters or both as bowlers."
    )
    client = _ScriptedStructuredClient([
        _structured_result(
            _plan_json(
                operation="player_compare",
                entity="batter",
                metric="batting_strike_rate",
                group_by=["batter"],
                filters={
                    "compare_players": ["Virat Kohli", "Jasprit Bumrah"],
                    "comparison_metrics": ["batting_strike_rate"],
                },
                sort={"by": "batting_strike_rate", "direction": "desc"},
                unsupported_reason=reason,
            )
        )
    ])

    reply = _live_chat(client).reply(
        "Compare Virat Kohli and Jasprit Bumrah.",
        history=[],
    )

    assert reply.mode == "analysis"
    assert reply.query_response is not None
    assert reply.query_response.status.value == "unsupported"
    assert reply.query_response.failure_state == "unsupported_capability"
    assert reply.query_response.summaries[0].body == reason


def test_production_repairs_named_phase_split_misclassified_as_aggregate() -> None:
    misclassified = _plan_json(
        operation="aggregate",
        entity="bowler",
        metric="economy_rate",
        group_by=["bowler"],
        filters={"bowler": "Mitchell Starc", "phase": "powerplay"},
        sort={"by": "economy_rate", "direction": "asc"},
    )
    repaired = _plan_json(
        operation="split_compare",
        entity="bowler",
        metric="economy_rate",
        group_by=["bowler"],
        filters={"bowler": "Mitchell Starc"},
        split_by="phase",
        compare_values=["powerplay", "death"],
        sort={"by": "economy_rate", "direction": "asc"},
    )
    client = _ScriptedStructuredClient([
        _structured_result(misclassified),
        _structured_result(repaired),
    ])
    trace = QueryTrace(
        original_user_question="Compare Mitchell Starc's economy in the powerplay versus death overs"
    )

    result = _planner(client).plan(trace.original_user_question, trace)

    assert result.validation.valid is True
    assert result.plan is not None
    assert result.plan.operation == "split_compare"
    assert result.plan.split_by == "phase"
    assert len(client.calls) == 2
