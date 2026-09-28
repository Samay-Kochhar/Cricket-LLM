from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.canonical_meaning import CanonicalMeaningResolver
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.db.repository import AnalyticsRepository
from backend.app.services.chat_service import ChatService
from backend.app.services.gemini_client import GeminiStructuredResult


class _UnconfiguredClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> None:
        return None


class _LegacyRunsExtractionClient:
    def is_configured(self) -> bool:
        return True

    def generate_structured(
        self, prompt: str, **kwargs: object
    ) -> GeminiStructuredResult:
        payload = {
            "version": 1,
            "family": "direct",
            "entities": [
                {
                    "name": "Virat Kohli",
                    "kind": "player",
                    "role": "batter",
                    "relationship": "subject",
                }
            ],
            "metric_concept": "runs_scored",
            "role": "batter",
            "intent": "value",
        }
        return GeminiStructuredResult(
            text=json.dumps(payload),
            selected_model="saved-test-flash",
            model_version="saved-response",
            finish_reason="STOP",
            latency_ms=0,
        )

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> None:
        return None


def _chat() -> ChatService:
    repository = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    client = _UnconfiguredClient()
    semantic = SemanticAnalyticsService(
        repository=repository,
        gemini_client=client,  # type: ignore[arg-type]
        app_env="development",
    )
    return ChatService(
        repository=repository,
        query_handler=semantic.answer_question,
        gemini_client=client,  # type: ignore[arg-type]
    )


def _planner() -> SemanticQueryPlanner:
    repository = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    return SemanticQueryPlanner(
        _UnconfiguredClient(),  # type: ignore[arg-type]
        repository.list_player_names(),
        repository.list_venues(),
        repository.list_teams(),
        allow_dev_fallback=True,
        player_participation=repository.player_participation(),
    )


def test_kohli_six_count_executes_end_to_end_with_database_evidence() -> None:
    reply = _chat().reply("How many sixes has Virat Kohli hit?", history=[])

    assert reply.mode == "analysis"
    assert reply.query_response is not None
    response = reply.query_response
    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Virat Kohli"]
    assert response.interpretation.filters["semantic_metric"] == "six_count"
    assert response.tables[0].columns == [
        "Batter",
        "Six Count",
        "Balls Faced",
        "Matches",
    ]
    assert response.tables[0].rows[0][1] == 154
    assert "ODI database" in response.summaries[0].body
    assert "154" in response.summaries[0].body
    trace = json.loads(
        next(
            note.detail
            for note in response.evidence_notes
            if note.title == "Semantic V2 trace"
        )
    )
    assert trace["canonical_meaning"]["metric"] == "six_count"
    assert trace["normalized_plan"]["sort"] == {
        "by": "six_count",
        "direction": "desc",
    }


def test_kohli_four_count_executes_through_the_same_evidence_path() -> None:
    reply = _chat().reply("How many fours has Virat Kohli hit?", history=[])

    assert reply.query_response is not None
    response = reply.query_response
    assert response.status.value == "supported"
    assert response.interpretation.filters["semantic_metric"] == "four_count"
    assert response.tables[0].columns == [
        "Batter",
        "Four Count",
        "Balls Faced",
        "Matches",
    ]
    assert response.tables[0].rows[0][1] == 1309
    assert "Four Count is 1309" in response.summaries[0].body


@pytest.mark.parametrize(
    ("question", "metric"),
    [
        ("How many sixes has Kohli hit?", "six_count"),
        ("What is Virat's six-hitting count?", "six_count"),
        ("Virat Kohli six count?", "six_count"),
        ("How many 6s did Kohli hit?", "six_count"),
        ("How many six did Kohli hit?", "six_count"),
        ("How many fours has Kohli hit?", "four_count"),
        ("What is Virat's four-hitting tally?", "four_count"),
        ("Virat Kohli four count?", "four_count"),
        ("How many 4s did Kohli hit?", "four_count"),
        ("How many four did Kohli hit?", "four_count"),
    ],
)
def test_count_wording_and_player_aliases_keep_boundary_count_meaning(
    question: str, metric: str
) -> None:
    result = _planner().plan(question, QueryTrace(question))

    assert result.validation.valid, result.validation.errors
    assert result.plan is not None
    assert result.plan.metric == metric
    assert result.plan.entity == "batter"
    assert result.plan.filters["batter"] == "Virat Kohli"


@pytest.mark.parametrize(
    ("question", "metric"),
    [
        ("How many fours has Kohli hit?", "four_count"),
        ("How many sixes has Kohli hit?", "six_count"),
        ("How many boundaries has Kohli hit?", "boundary_ball_count"),
        ("What is Kohli's boundary percentage?", "boundary_percentage"),
        ("How many boundary runs has Kohli scored?", "boundary_runs"),
        ("How many runs has Kohli scored?", "runs_scored"),
    ],
)
def test_related_boundary_metrics_compile_to_distinct_plans(
    question: str, metric: str
) -> None:
    result = _planner().plan(question, QueryTrace(question))

    assert result.validation.valid, result.validation.errors
    assert result.plan is not None
    assert result.plan.metric == metric
    assert result.plan.sort is not None
    assert result.plan.sort.by == metric


def test_unknown_boundary_concept_does_not_fall_back_to_runs_or_percentage() -> None:
    question = "What is Kohli's average boundary distance?"
    result = _planner().plan(question, QueryTrace(question))

    assert result.plan is None
    assert not result.validation.valid
    assert any(
        "supported" in error.lower() or "metric" in error.lower()
        for error in result.validation.errors
    )


@pytest.mark.parametrize(
    ("question", "group_by", "filters"),
    [
        (
            "How many sixes did Kohli hit against Australia in 2019?",
            ["batter"],
            {"batter": "Virat Kohli", "opposition": "Australia", "years": [2019]},
        ),
        (
            "How many sixes did Kohli hit in innings 2 between overs 41 and 50?",
            ["batter"],
            {"batter": "Virat Kohli", "innings": 2, "over_range": [41, 50]},
        ),
        (
            "How many sixes did Kohli hit at Wankhede Stadium, Mumbai?",
            ["batter"],
            {"batter": "Virat Kohli", "venue": "Wankhede Stadium, Mumbai"},
        ),
        (
            "How many fours did Kohli hit against spin in the middle overs?",
            ["batter"],
            {"batter": "Virat Kohli", "bowling_style": "spin", "phase": "middle"},
        ),
        (
            "Kohli's six count by innings phase",
            ["phase"],
            {"batter": "Virat Kohli"},
        ),
        (
            "Which bowling style has Kohli hit the most sixes against?",
            ["bowling_style"],
            {"batter": "Virat Kohli"},
        ),
        (
            "Who hit the most sixes in 2019?",
            ["batter"],
            {"years": [2019]},
        ),
        (
            "Who hit the maximum sixes in 2019?",
            ["batter"],
            {"years": [2019]},
        ),
    ],
)
def test_direct_filtered_breakdown_and_ranking_forms_share_the_registered_path(
    question: str, group_by: list[str], filters: dict[str, object]
) -> None:
    result = _planner().plan(question, QueryTrace(question))

    assert result.validation.valid, result.validation.errors
    assert result.plan is not None
    assert result.plan.operation == "aggregate"
    assert result.plan.metric in {"four_count", "six_count"}
    assert result.plan.group_by == group_by
    assert result.plan.filters == filters
    assert result.plan.sort is not None
    assert result.plan.sort.by == result.plan.metric
    assert result.plan.sort.direction == "desc"


def test_six_count_ranking_uses_the_same_metric_for_table_sort_and_narrative() -> None:
    reply = _chat().reply("Who hit the most sixes in 2019?", history=[])

    assert reply.query_response is not None
    response = reply.query_response
    assert response.status.value == "supported"
    assert response.tables[0].columns[:3] == [
        "Batter",
        "Six Count",
        "Balls Faced",
    ]
    values: list[int] = []
    for row in response.tables[0].rows:
        assert isinstance(row[1], int)
        values.append(row[1])
    assert values == sorted(values, reverse=True)
    assert "Six Count" in response.summaries[0].body
    assert str(values[0]) in response.summaries[0].body


@pytest.mark.parametrize(
    ("metric_id", "label", "numerator"),
    [
        ("four_count", "Four Count", "four_count"),
        ("six_count", "Six Count", "six_count"),
    ],
)
def test_boundary_counts_are_registered_batter_owned_count_metrics(
    metric_id: str, label: str, numerator: str
) -> None:
    rule = get_metric(metric_id)

    assert rule.label == label
    assert rule.owner == "batter"
    assert rule.aggregation == "count"
    assert rule.numerator == numerator
    assert rule.denominator is None
    assert rule.default_sort == "desc"
    assert rule.minimum_sample.as_dict() == {}
    assert {
        "opposition",
        "years",
        "venue",
        "innings",
        "phase",
        "over_range",
        "bowling_style",
    } <= rule.allowed_filters
    assert {"batter", "year", "venue", "phase", "bowling_style"} <= (
        rule.allowed_groupings
    )


def test_boundary_event_treatment_matches_frozen_source_rows() -> None:
    repository = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    totals = repository._fetchone(
        """
        SELECT
          COUNT(*) FILTER (
            WHERE TRY_CAST(ballfaced AS INTEGER) = 1
              AND TRY_CAST(batruns AS INTEGER) = 4
          ),
          COUNT(*) FILTER (
            WHERE TRY_CAST(ballfaced AS INTEGER) = 1
              AND TRY_CAST(batruns AS INTEGER) = 6
          ),
          COUNT(*) FILTER (
            WHERE TRY_CAST(ballfaced AS INTEGER) = 1
              AND TRY_CAST(batruns AS INTEGER) IN (4, 6)
          ),
          SUM(CASE
            WHEN TRY_CAST(ballfaced AS INTEGER) = 1
              AND TRY_CAST(batruns AS INTEGER) IN (4, 6)
            THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END),
          SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1
            THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
        FROM analytics.deliveries_v1
        WHERE bat = ?
        """,
        ["Virat Kohli"],
    )
    assert totals == (1309, 154, 1463, 6160, 13950)

    source_shape = repository._fetchone(
        """
        SELECT
          COUNT(*) FILTER (
            WHERE batruns IS NULL OR ballfaced IS NULL
              OR wide IS NULL OR noball IS NULL
          ),
          COUNT(*) FILTER (
            WHERE TRY_CAST(batruns AS INTEGER) = 6
              AND COALESCE(TRY_CAST(wide AS INTEGER), 0) <> 0
          ),
          COUNT(*) FILTER (
            WHERE TRY_CAST(batruns AS INTEGER) = 6
              AND COALESCE(TRY_CAST(noball AS INTEGER), 0) <> 0
          ),
          COUNT(*) FILTER (
            WHERE TRY_CAST(batruns AS INTEGER) NOT BETWEEN 0 AND 6
          )
        FROM analytics.deliveries_v1
        """
    )
    assert source_shape == (0, 0, 116, 24)


def test_extracted_boundary_metric_is_accounted_for_by_completeness_invariant() -> None:
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "entities": [
                {
                    "name": "Kohli",
                    "kind": "player",
                    "role": "batter",
                    "relationship": "subject",
                }
            ],
            "metric_concept": "six-hitting count",
            "role": "batter",
            "intent": "value",
        }
    )
    resolver = CanonicalMeaningResolver(available_players=["Virat Kohli"])

    resolution = resolver.resolve_candidate(
        "What is Kohli's six-hitting count?", None, candidate
    )

    assert resolution.meaning is not None
    assert resolution.meaning.metric == "six_count"
    assert resolution.completeness is not None
    assert resolution.completeness.complete is True
    assert resolution.completeness.allows_execution is True
    metric_fact = next(
        fact
        for fact in resolution.completeness.facts
        if fact.fact_type == "metric"
    )
    assert metric_fact.disposition == "compiled"
    assert metric_fact.canonical_target == "metric.six_count"


def test_explicit_six_wording_overrides_legacy_runs_extraction_in_production() -> None:
    repository = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    client = _LegacyRunsExtractionClient()
    service = SemanticAnalyticsService(
        repository=repository,
        gemini_client=client,  # type: ignore[arg-type]
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question("How many sixes has Virat Kohli hit?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["semantic_metric"] == "six_count"
    assert response.tables[0].rows[0][1] == 154
    trace = json.loads(
        next(
            note.detail
            for note in response.evidence_notes
            if note.title == "Semantic V2 trace"
        )
    )
    metric_fact = next(
        fact
        for fact in trace["completeness_result"]["facts"]
        if fact["fact_type"] == "metric"
    )
    assert metric_fact["disposition"] == "explicitly_replaced_removed"
    assert metric_fact["canonical_target"] == "metric.six_count"
