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


STAGE2_CASES = [
    ("Which batter is hardest to bowl dot balls to?", "aggregate", "batter", "dot_ball_percentage", ["batter"], {}, "asc", "supported"),
    ("Which bowler has the best control?", "aggregate", "bowler", "control_percentage", ["bowler"], {}, "desc", "supported"),
    ("Which bowler concedes the fewest boundaries per 100 balls?", "aggregate", "bowler", "boundary_rate_per_100_balls", ["bowler"], {}, "asc", "supported"),
    ("Which batter has the highest false-shot percentage against spin?", "aggregate", "batter", "false_shot_percentage", ["batter"], {"bowling_style": "spin"}, "desc", "supported"),
    ("Which bowler generates the most false shots per over?", "aggregate", "bowler", "false_shots_per_over", ["bowler"], {}, "desc", "supported"),
    ("Which bowler has the biggest difference between powerplay and death-over economy?", "split_compare", "bowler", "economy_rate", ["bowler"], {}, "asc", "supported"),
    ("Which bowler performs significantly better against left-handers than right-handers?", "split_compare", "bowler", "economy_rate", ["bowler"], {}, "asc", "supported"),
    ("Which batter dominates wrist spin but struggles against finger spin?", "split_compare", "batter", "batting_strike_rate", ["batter"], {}, "desc", "supported"),
    ("Which batter improves their strike rate the most after facing 20 balls?", "split_compare", "batter", "batting_strike_rate", ["batter"], {}, "desc", "supported"),
    ("Which team accelerates most effectively between overs 15 and 20?", "split_compare", "team", "run_rate", ["team"], {"over_range": [15, 20]}, "desc", "supported"),
    ("Which batter is most vulnerable immediately after reaching a milestone?", "event_window", "batter", "wickets", ["batter"], {}, "desc", "unsupported"),
    ("Which bowler is most effective immediately after a wicket falls?", "event_window", "bowler", "economy_rate", ["bowler"], {}, "asc", "unsupported"),
    ("Which team loses momentum most frequently after the powerplay?", "event_window", "team", "runs_scored", ["team"], {}, "desc", "unsupported"),
    ("Which team recovers best after losing early wickets?", "event_window", "team", "batting_strike_rate", ["team"], {}, "desc", "unsupported"),
    ("Which batter’s scoring zones are most concentrated?", "distribution_analysis", "batter", "runs_scored", ["field_zone"], {}, "desc", "unsupported"),
    ("Which bowler’s length changes the most depending on the batter faced?", "distribution_analysis", "bowler", "balls_faced", ["length"], {}, "desc", "unsupported"),
    ("Which batter-bowler matchup is most one-sided?", "matchup", "matchup", "batting_strike_rate", ["matchup"], {}, "desc", "unsupported"),
    ("Which matchup produces the highest false-shot percentage?", "matchup", "matchup", "false_shot_percentage", ["matchup"], {}, "desc", "unsupported"),
    ("Which matchup has produced the most wickets in death overs?", "matchup", "matchup", "wickets", ["matchup"], {"phase": "death"}, "desc", "unsupported"),
    ("Which bowler is most successful against finishers?", "matchup", "bowler", "wickets", ["bowler"], {}, "desc", "unsupported"),
]


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    config = AppConfig.from_env()
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


@pytest.mark.parametrize(
    "question,operation,entity,metric,group_by,filters,sort_direction,status",
    STAGE2_CASES,
)
def test_semantic_stage2_shape(
    semantic_service: SemanticAnalyticsService,
    question: str,
    operation: str,
    entity: str,
    metric: str,
    group_by: list[str],
    filters: dict[str, object],
    sort_direction: str,
    status: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace_note = next(note for note in response.evidence_notes if note.title == "Semantic V2 trace")
    trace = json.loads(trace_note.detail)
    plan = trace["normalized_plan"]

    assert response.status.value == status
    assert trace["original_user_question"] == question
    assert trace["validation_result"]["valid"] is True
    assert trace["validation_result"]["errors"] == []
    assert trace["operation_type"] == operation
    assert plan["operation"] == operation
    assert plan["entity"] == entity
    assert plan["metric"] == metric
    assert plan["group_by"] == group_by
    assert plan["sort"]["direction"] == sort_direction
    for key, value in filters.items():
        assert plan["filters"].get(key) == value

    if operation == "aggregate":
        assert trace["selected_executor"] == "query_builders.aggregate_builder.build_aggregate_query"
        assert metric in trace["result_columns"]
        for column in group_by:
            assert column in trace["result_columns"]
        assert response.tables
    elif operation == "split_compare":
        assert trace["selected_executor"] == "executors.split_compare_executor.build_split_compare_query"
        assert "difference" in trace["result_columns"]
        assert "rank_value" in trace["result_columns"]
        for column in group_by:
            assert column in trace["result_columns"]
        assert any(column.endswith("_sample") for column in trace["result_columns"])
        assert response.tables
    else:
        assert trace["selected_executor"] == f"executors.{operation}"
        assert trace["result_columns"] == []
        assert response.insufficiencies
