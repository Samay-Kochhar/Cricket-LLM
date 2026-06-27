from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@dataclass(frozen=True, slots=True)
class ParaphraseGroup:
    intent_id: str
    questions: tuple[str, ...]
    operation: str
    entity: str
    metric: str
    group_by: tuple[str, ...]
    filters: dict[str, object]
    columns: tuple[str, ...]


PHASE1_PARAPHRASE_GROUPS = (
    ParaphraseGroup(
        intent_id="kohli_batting_strike_rate_vs_australia",
        questions=(
            "What is Kohli's strike rate against Australia?",
            "How quickly does Virat Kohli score versus Australia?",
            "Kohli SR vs Aus?",
            "Against the Aussies, what is Virat Kohli's scoring rate?",
        ),
        operation="aggregate",
        entity="batter",
        metric="batting_strike_rate",
        group_by=("batter",),
        filters={"batter": "Virat Kohli", "opposition": "Australia"},
        columns=("batter", "batting_strike_rate", "balls"),
    ),
    ParaphraseGroup(
        intent_id="bumrah_economy_at_death",
        questions=(
            "What is Bumrah's economy at the death?",
            "Bumrah economy rate in death overs?",
            "How economical is Jasprit Bumrah in the final overs?",
        ),
        operation="aggregate",
        entity="bowler",
        metric="economy_rate",
        group_by=("bowler",),
        filters={"bowler": "Jasprit Bumrah", "phase": "death"},
        columns=("bowler", "economy_rate", "legal_balls"),
    ),
    ParaphraseGroup(
        intent_id="hardik_runs_by_shot",
        questions=(
            "Which shot does Hardik Pandya score most from?",
            "What shot does Hardik get the most runs from?",
            "Show Hardik Pandya's runs by shot type.",
        ),
        operation="aggregate",
        entity="batter",
        metric="runs_scored",
        group_by=("shot_type",),
        filters={"batter": "Hardik Pandya"},
        columns=("shot_type", "runs_scored"),
    ),
)


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


@pytest.mark.parametrize(
    "group",
    PHASE1_PARAPHRASE_GROUPS,
    ids=lambda group: group.intent_id,
)
def test_phase1_paraphrases_share_the_same_plan_and_sql_evidence(
    semantic_service: SemanticAnalyticsService,
    group: ParaphraseGroup,
) -> None:
    for question in group.questions:
        response = semantic_service.answer_question(question)
        trace = _trace(response)
        plan = trace["normalized_plan"]

        assert response.status.value == "supported", question
        assert plan["operation"] == group.operation
        assert plan["entity"] == group.entity
        assert plan["metric"] == group.metric
        assert plan["group_by"] == list(group.group_by)
        for key, value in group.filters.items():
            assert plan["filters"].get(key) == value
        assert "analytics.deliveries_v1" in trace["final_sql_or_method"]
        result_columns = set(trace["result_columns"])
        for column in group.columns:
            assert column in result_columns


def test_semantic_v2_can_disable_dev_fallback_when_llm_planning_is_unavailable() -> None:
    config = AppConfig.from_env()
    service = SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question("What is Kohli's strike rate against Australia?")

    assert response.status.value == "unsupported"
    assert response.insufficiencies
    assert "could not produce a validated LLM plan" in response.insufficiencies[0].detail
