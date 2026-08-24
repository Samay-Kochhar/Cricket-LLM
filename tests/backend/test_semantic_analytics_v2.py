from __future__ import annotations

from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.result_validator import validate_result
from backend.app.cricket_analytics.schemas import CricketQueryPlan
from backend.app.cricket_analytics.trace import QueryTrace


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


PLAYERS = ["Heinrich Klaasen", "David Miller", "Jos Buttler"]


def test_fallback_planner_shapes_bowling_style_question() -> None:
    planner = SemanticQueryPlanner(FakeGeminiClient(), PLAYERS)

    result = planner.plan(
        "Against which bowling type does Heinrich Klaasen score fastest?",
        QueryTrace(original_user_question="Against which bowling type does Heinrich Klaasen score fastest?"),
    )

    assert result.plan is not None
    assert result.plan.operation == "aggregate"
    assert result.plan.entity == "batter"
    assert result.plan.metric == "batting_strike_rate"
    assert result.plan.group_by == ["bowling_style"]
    assert result.plan.filters["batter"] == "Heinrich Klaasen"
    assert result.validation.valid is True


def test_validator_rejects_bowling_type_grouped_by_bowler() -> None:
    plan = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="batting_strike_rate",
        group_by=["bowler"],
        filters={"batter": "Heinrich Klaasen"},
    )

    validation = validate_plan(plan, "Against which bowling type does Heinrich Klaasen score fastest?")

    assert validation.valid is False
    assert any("bowling type" in error for error in validation.errors)


def test_aggregate_builder_uses_metric_and_minimum_sample() -> None:
    planner = SemanticQueryPlanner(FakeGeminiClient(), PLAYERS)
    result = planner.plan(
        "Against which bowling type does Heinrich Klaasen score fastest?",
        QueryTrace(original_user_question="Against which bowling type does Heinrich Klaasen score fastest?"),
    )
    assert result.plan is not None

    build = build_aggregate_query(result.plan)

    assert "analytics.deliveries_v1" in build.sql
    assert "bowl_style AS bowling_style" in build.sql
    assert "batting_strike_rate" in build.columns
    assert "Heinrich Klaasen" in build.params
    assert 60 in build.params


def test_result_validator_catches_empty_result() -> None:
    planner = SemanticQueryPlanner(FakeGeminiClient(), PLAYERS)
    result = planner.plan(
        "Which bowler bowls the highest percentage of yorkers?",
        QueryTrace(original_user_question="Which bowler bowls the highest percentage of yorkers?"),
    )
    assert result.plan is not None
    build = build_aggregate_query(result.plan)

    validation = validate_result(result.plan, build, [])

    assert validation.valid is False
    assert validation.errors == ["Result set is empty."]
