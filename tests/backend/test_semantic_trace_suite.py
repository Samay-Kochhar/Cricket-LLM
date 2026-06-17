from __future__ import annotations

import json

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.metric_catalog import MetricCatalog


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


TRACE_CASES = [
    {
        "question": "Which length dismisses David Miller most often?",
        "operation": "aggregate",
        "entity": "bowler",
        "metric": "wickets",
        "group_by": ["length"],
        "filters": {"batter": "David Miller"},
        "columns": {"length", "wickets", "balls"},
    },
    {
        "question": "Against which bowling type does Heinrich Klaasen score fastest?",
        "operation": "aggregate",
        "entity": "batter",
        "metric": "batting_strike_rate",
        "group_by": ["bowling_style"],
        "filters": {"batter": "Heinrich Klaasen"},
        "columns": {"bowling_style", "batting_strike_rate", "balls"},
        "must_not_columns": {"bowler"},
    },
    {
        "question": "Which line generates the most dot balls against Virat Kohli?",
        "operation": "aggregate",
        "entity": "bowler",
        "metric": "dot_ball_percentage",
        "group_by": ["line"],
        "filters": {"batter": "Virat Kohli"},
        "columns": {"line", "dot_ball_percentage", "dot_balls", "balls"},
    },
    {
        "question": "What shot does Jos Buttler score most runs from?",
        "operation": "aggregate",
        "entity": "batter",
        "metric": "runs_scored",
        "group_by": ["shot_type"],
        "filters": {"batter": "Jos Buttler"},
        "columns": {"shot_type", "runs_scored", "balls"},
    },
    {
        "question": "Which bowler bowls the highest percentage of yorkers?",
        "operation": "aggregate",
        "entity": "bowler",
        "metric": "yorker_percentage",
        "group_by": ["bowler"],
        "filters": {},
        "columns": {"bowler", "yorker_percentage", "yorker_balls", "legal_balls"},
    },
]


def test_semantic_v2_trace_shape_for_priority_questions() -> None:
    config = AppConfig.from_env()
    service = SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )

    for case in TRACE_CASES:
        response = service.answer_question(case["question"])
        assert response.status.value == "supported", case["question"]
        trace_note = next(note for note in response.evidence_notes if note.title == "Semantic V2 trace")
        trace = json.loads(trace_note.detail)
        plan = trace["normalized_plan"]

        assert trace["original_user_question"] == case["question"]
        assert "gemini_raw_response" in trace
        assert trace["operation_type"] == case["operation"]
        assert trace["selected_executor"] == "query_builders.aggregate_builder.build_aggregate_query"
        assert "analytics.deliveries_v1" in trace["final_sql_or_method"]
        assert trace["validation_result"]["valid"] is True
        assert trace["validation_result"]["errors"] == []

        assert plan["operation"] == case["operation"]
        assert plan["entity"] == case["entity"]
        assert plan["metric"] == case["metric"]
        assert plan["group_by"] == case["group_by"]
        assert plan["sort"] == {"by": case["metric"], "direction": "desc"}
        for key, value in case["filters"].items():
            assert plan["filters"].get(key) == value
        for unexpected_filter in set(plan["filters"]) - set(case["filters"]):
            assert unexpected_filter not in {"years", "competition"}, case["question"]

        result_columns = set(trace["result_columns"])
        assert case["columns"] <= result_columns
        assert not (set(case.get("must_not_columns", set())) & result_columns)


def test_legacy_yorker_percentage_leaderboard_uses_percentage_metric() -> None:
    config = AppConfig.from_env()
    repository = AnalyticsRepository(config.duckdb_path)
    service = AnalyticsService(repository=repository, metric_catalog=MetricCatalog())

    question = "Which bowler bowls the highest percentage of yorkers?"
    route = service.router.route(question)
    response = service.answer_route(question, route)

    assert route.filters["metric"] == "yorker_percentage"
    assert "length" not in route.filters
    assert response.status.value == "supported"
    table = response.tables[0]
    assert table.columns[-1] == "Yorker Percentage"
    assert table.rows[0][-1] != table.rows[0][7]
    assert "%" in response.summaries[0].body
