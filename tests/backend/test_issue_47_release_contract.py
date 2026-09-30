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


# The 2026-09-30 fresh production Flash extraction for the lighting tracer. The
# model labelled the split axis "match_type" instead of a lighting concept.
FRESH_LIGHTING_EXTRACTION = {
    "version": 1,
    "family": "comparison",
    "entities": [{"kind": "player", "name": "Bumrah", "relationship": "subject", "role": None}],
    "metric_concept": "economy",
    "role": None,
    "breakdown_dimensions": [],
    "split_dimensions": ["match_type"],
    "filters": [],
    "intent": "comparison",
    "ordering": None,
    "limit": None,
    "sample_threshold": None,
    "ambiguity_candidates": [],
}


def _semantic_trace(response) -> dict:
    import json

    return json.loads(
        next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace")
    )


def test_unregistered_model_label_for_the_stated_lighting_axis_compiles(
    repository: AnalyticsRepository,
) -> None:
    from tests.backend.test_issue_41_required_run_rate import _chat

    chat, client = _chat(repository, FRESH_LIGHTING_EXTRACTION)
    response = chat.reply("Compare Bumrah's economy in day versus night matches.", history=[]).query_response

    assert client.calls == 1
    assert response.status.value == "supported"
    assert response.interpretation.filters["semantic_operation"] == "split_compare"
    values = _values(response)
    assert (values["Day Match Value"], values["Day Night Match Value"]) == (4.26, 4.76)
    fact = next(
        fact
        for fact in _semantic_trace(response)["completeness_result"]["facts"]
        if fact["concept"] == "match_type"
    )
    assert fact["disposition"] == "compiled"
    assert fact["canonical_target"] == "dimension.match_lighting"
    assert fact["reason"] == "model label for the split axis stated in the question"


def test_unregistered_label_without_a_stated_axis_stays_unsupported(
    repository: AnalyticsRepository,
) -> None:
    from tests.backend.test_issue_41_required_run_rate import _chat

    chat, _ = _chat(repository, FRESH_LIGHTING_EXTRACTION)
    response = chat.reply(
        "Compare Bumrah's economy in World Cup versus bilateral matches.", history=[]
    ).query_response

    assert response.status.value != "supported"
    facts = _semantic_trace(response)["completeness_result"]["facts"]
    assert any(
        fact["concept"] == "match_type" and fact["disposition"] != "compiled" for fact in facts
    )


def test_extra_unregistered_label_beside_the_lighting_axis_still_blocks(
    repository: AnalyticsRepository,
) -> None:
    from tests.backend.test_issue_41_required_run_rate import _chat

    extraction = {
        **FRESH_LIGHTING_EXTRACTION,
        "split_dimensions": ["day_night_condition", "match_type"],
    }
    chat, _ = _chat(repository, extraction)
    response = chat.reply("Compare Bumrah's economy in day versus night matches.", history=[]).query_response

    assert response.status.value != "supported"
    facts = _semantic_trace(response)["completeness_result"]["facts"]
    assert any(
        fact["concept"] == "match_type" and fact["disposition"] == "unsupported" for fact in facts
    )


# Recorded 2026-09-30 fresh-150 extractions (d11f438). The extraction contract
# asks the model to preserve each filter's operator, so ordinary registered
# bounds now arrive with typed operators and must be accounted exactly.
def _candidate(filters: list[dict], **updates: object) -> dict:
    return {
        "version": 1,
        "family": "direct",
        "entities": [],
        "metric_concept": None,
        "role": None,
        "breakdown_dimensions": [],
        "split_dimensions": [],
        "filters": filters,
        "intent": "value",
        "ordering": None,
        "limit": None,
        "sample_threshold": None,
        "ambiguity_candidates": [],
        **updates,
    }


STARC_POWERPLAY = _candidate(
    [{"concept": "overs", "evidence": "inside the opening ten overs", "operator": "between", "values": [1, 10]}],
    entities=[{"kind": "player", "name": "Starc", "relationship": "subject", "role": "bowler"}],
    metric_concept="wickets",
    role="bowler",
)
BUMRAH_FROM_41 = _candidate(
    [{"concept": "over number", "evidence": "from over 41 onwards", "operator": "gte", "values": [41]}],
    entities=[{"kind": "player", "name": "Bumrah", "relationship": "subject", "role": "bowler"}],
    metric_concept="economy rate",
    role="bowler",
)
STARC_SINCE_2018 = _candidate(
    [
        {"concept": "overs_phase", "evidence": "death-over", "operator": "eq", "values": ["death"]},
        {"concept": "year", "evidence": "since 2018", "operator": "gte", "values": [2018]},
    ],
    family="trend",
    entities=[{"kind": "player", "name": "Starc", "relationship": "subject", "role": None}],
    metric_concept="economy",
    role="bowler",
    breakdown_dimensions=["year"],
)
KOHLI_AGAINST_AUSTRALIA = _candidate(
    [{"concept": "opponent_team", "evidence": "Against Australia", "operator": "eq", "values": ["Australia"]}],
    entities=[
        {"kind": "player", "name": "Virat Kohli", "relationship": "subject", "role": None},
        {"kind": "team", "name": "Australia", "relationship": "opponent", "role": None},
    ],
    metric_concept="runs",
    role="batter",
)
WARNER_DISMISSERS = _candidate(
    [{"concept": "dismissed_player", "evidence": "gets David Warner out", "operator": "eq", "values": ["David Warner"]}],
    family="ranking",
    entities=[{"kind": "player", "name": "David Warner", "relationship": "participant", "role": None}],
    metric_concept="dismissals",
    role="bowler",
    intent="ranking",
    ordering="highest",
)
KLAASEN_SPIN_TYPE = _candidate(
    [{"concept": "spin type", "evidence": "across wrist and finger spin", "operator": "in", "values": ["wrist spin", "finger spin"]}],
    family="split",
    entities=[{"kind": "player", "name": "Heinrich Klaasen", "relationship": "subject", "role": None}],
    metric_concept="strike rate",
    role="batter",
    intent="comparison",
    split_dimensions=["spin type"],
)


def _reply(repository: AnalyticsRepository, extraction: dict, question: str):
    from tests.backend.test_issue_41_required_run_rate import _chat

    chat, client = _chat(repository, extraction)
    response = chat.reply(question, history=[]).query_response
    assert client.calls == 1
    return response


@pytest.mark.parametrize(
    ("extraction", "question", "expected_filters"),
    [
        (STARC_POWERPLAY, "Starc wickets inside the opening ten overs?", {"phase": "powerplay"}),
        (BUMRAH_FROM_41, "How expensive is Bumrah from over 41 onwards?", {"phase": "death"}),
        (
            STARC_SINCE_2018,
            "Starc death-over economy year by year since 2018.",
            {"phase": "death", "years": [2018], "year_mode": "after"},
        ),
        (KOHLI_AGAINST_AUSTRALIA, "Against Australia, how many runs has Virat Kohli made?", {"opposition": "Australia"}),
        (WARNER_DISMISSERS, "Which bowler gets David Warner out most?", {"batter": "David Warner"}),
    ],
)
def test_recorded_typed_operators_compile_to_the_equal_registered_scope(
    repository: AnalyticsRepository,
    extraction: dict,
    question: str,
    expected_filters: dict,
) -> None:
    response = _reply(repository, extraction, question)

    assert response.status.value == "supported"
    filters = response.interpretation.filters
    assert {key: filters.get(key) for key in expected_filters} == expected_filters
    facts = _semantic_trace(response)["completeness_result"]["facts"]
    assert all(fact["disposition"] != "unsupported" for fact in facts)


def test_recorded_operator_answers_match_independent_queries(repository: AnalyticsRepository) -> None:
    bumrah = _values(_reply(repository, BUMRAH_FROM_41, "How expensive is Bumrah from over 41 onwards?"))
    kohli = _values(
        _reply(repository, KOHLI_AGAINST_AUSTRALIA, "Against Australia, how many runs has Virat Kohli made?")
    )

    assert (bumrah["Economy Rate"], bumrah["Legal Balls"]) == (5.78, 1123)
    assert kohli["Runs Scored"] == 2367


def test_recorded_spin_type_label_names_the_bowling_style_group_split(repository: AnalyticsRepository) -> None:
    response = _reply(
        repository, KLAASEN_SPIN_TYPE, "Compare Heinrich Klaasen's strike rate across wrist and finger spin."
    )

    assert response.status.value == "supported"
    assert response.interpretation.filters["semantic_operation"] == "split_compare"
    facts = _semantic_trace(response)["completeness_result"]["facts"]
    assert all(fact["disposition"] != "unsupported" for fact in facts)


@pytest.mark.parametrize(
    ("extraction", "question", "changed_filter"),
    [
        # Overs 1-12 is not the powerplay; a strict bound after over 41 is not overs 41-50.
        (STARC_POWERPLAY, "Starc wickets inside the opening ten overs?",
         {"concept": "overs", "evidence": "inside the opening ten overs", "operator": "between", "values": [1, 12]}),
        (BUMRAH_FROM_41, "How expensive is Bumrah from over 41 onwards?",
         {"concept": "over number", "evidence": "from over 41 onwards", "operator": "gt", "values": [41]}),
        # "After 2018" as a strict bound is not the inclusive registered "since 2018" scope.
        (STARC_SINCE_2018, "Starc death-over economy year by year since 2018.",
         {"concept": "year", "evidence": "since 2018", "operator": "gt", "values": [2018]}),
    ],
)
def test_operators_that_differ_from_the_compiled_scope_still_block(
    repository: AnalyticsRepository,
    extraction: dict,
    question: str,
    changed_filter: dict,
) -> None:
    filters = [
        changed_filter if item["concept"] == changed_filter["concept"] else item
        for item in extraction["filters"]
    ]
    response = _reply(repository, {**extraction, "filters": filters}, question)

    assert response.status.value != "supported"
