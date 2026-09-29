from __future__ import annotations

import json

import duckdb
import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.match_facts import (
    COMPETITION_REGISTRY,
    SINGLE_FINAL_COMPETITIONS,
    MatchMetadataCandidate,
    extract_match_fact_meaning,
    resolve_match_fact,
)
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(AppConfig.from_env().duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


def _trace(response) -> dict[str, object]:
    trace_note = next(
        note for note in response.evidence_notes if note.title == "Semantic V2 trace"
    )
    return json.loads(trace_note.detail)


def _text(response) -> str:
    parts = [block.body for block in response.summaries]
    parts += [block.detail for block in response.insufficiencies]
    parts.append(response.clarification_question or "")
    return " ".join(parts)


def test_2019_world_cup_final_toss_uses_toss_metadata_not_match_winner(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Who won the toss in the 2019 World Cup final?"
    )
    trace = _trace(response)

    assert response.status.value == "supported"
    assert "New Zealand won the toss" in response.summaries[0].body
    assert response.interpretation.filters["fact_type"] == "toss"
    assert trace["normalized_plan"]["filters"] == {
        "years": [2019],
        "competition": "ICC Cricket World Cup",
        "match_stage": "final",
        "fact_type": "toss",
    }
    assert trace["final_answer_metadata"] == {
        "status": "supported",
        "match_id": "1144530",
        "date": "2019-07-14",
        "competition": "ICC Cricket World Cup",
        "stage": "final",
        "ground": "Lord's, London",
        "fact_type": "toss",
        "fact_value": "New Zealand",
        "toss": "New Zealand",
        "winner": "-",
        "teams": ["England", "New Zealand"],
    }
    assert response.tables[0].rows == [
        [
            "1144530",
            "ICC Cricket World Cup",
            "Final",
            "2019-07-14",
            "Lord's, London",
            "New Zealand",
        ]
    ]
    evidence = response.evidence_queries[0]
    assert "sole match on the latest recorded date" in evidence.description
    assert "toss" in evidence.sql.lower()
    assert trace["planner_outcome"]["parse_outcome"] == "registered_match_fact"


@pytest.mark.parametrize(
    "question",
    [
        "In the 2019 World Cup final, who won the toss?",
        "The toss in the World Cup final of 2019 was won by which team?",
        "Which team was the 2019 cricket World Cup final toss winner?",
        "Who won the toss in the final of the 2019 World Cup?",
        "World Cup 2019 final toss winner?",
        "Toss winner, 2019 CWC final",
        "who WON the toss at the 2019 ICC Cricket World Cup final",
    ],
)
def test_toss_paraphrases_preserve_canonical_match_and_fact_identity(
    semantic_service: SemanticAnalyticsService,
    question: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "supported"
    assert "New Zealand won the toss" in response.summaries[0].body
    assert trace["canonical_meaning"] == {
        "family": "match_fact",
        "fact_type": "toss",
        "year": 2019,
        "competition": "ICC Cricket World Cup",
        "stage": "final",
        "team": None,
        "participants": [],
        "venue": None,
    }
    completeness = trace["completeness_result"]
    assert completeness["complete"] is True
    assert completeness["allows_execution"] is True
    assert {
        (fact["concept"], fact["disposition"])
        for fact in completeness["facts"]
    } == {
        ("fact_type", "compiled"),
        ("year", "compiled"),
        ("competition", "compiled"),
        ("stage", "compiled"),
    }
    targets = {
        fact["concept"]: fact["canonical_target"] for fact in completeness["facts"]
    }
    assert targets == {
        "fact_type": "match_fact.toss",
        "year": "filters.years",
        "competition": "filters.competition",
        "stage": "filters.match_stage",
    }
    assert trace["final_answer_metadata"]["match_id"] == "1144530"


def test_registered_toss_fact_does_not_depend_on_model_memory(
    semantic_service: SemanticAnalyticsService,
) -> None:
    production_service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=FakeGeminiClient(),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = production_service.answer_question(
        "Who won the toss in the 2019 World Cup final?"
    )
    trace = _trace(response)

    assert response.status.value == "supported"
    assert "New Zealand won the toss" in response.summaries[0].body
    assert trace["planner_outcome"]["parse_outcome"] == "registered_match_fact"
    assert trace["gemini_raw_response"] is None


def test_tied_final_match_winner_is_a_data_limitation_never_the_toss_winner(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Who won the 2019 World Cup final?")
    trace = _trace(response)

    assert response.status.value == "insufficient_evidence"
    assert response.failure_state == "data_limitation"
    assert trace["normalized_plan"]["filters"]["fact_type"] == "winner"
    assert trace["final_answer_metadata"]["status"] == "match_fact_data_limitation"
    assert trace["final_answer_metadata"]["match_id"] == "1144530"
    assert trace["final_answer_metadata"]["winner"] == "-"
    assert trace["final_answer_metadata"]["toss"] == "New Zealand"
    text = _text(response)
    assert "records no match winner" in text
    assert "New Zealand won" not in text
    assert "- won" not in text


@pytest.mark.parametrize(
    ("question", "summary", "match_id"),
    [
        ("Who won the 2011 World Cup final?", "India won the 2011 ICC Cricket World Cup final", "433606"),
        ("Who won the 2011 World Cup?", "India won the 2011 ICC Cricket World Cup final", "433606"),
        ("Who won India vs Sri Lanka 2011 World Cup final?", "India won", "433606"),
        ("Who won the 2023 World Cup final?", "Australia won the World Cup 2023 final", "1384439"),
    ],
)
def test_existing_match_winner_fact_remains_correct(
    semantic_service: SemanticAnalyticsService,
    question: str,
    summary: str,
    match_id: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "supported"
    assert summary in response.summaries[0].body
    assert trace["normalized_plan"]["filters"]["fact_type"] == "winner"
    assert trace["final_answer_metadata"]["match_id"] == match_id
    assert response.tables[0].columns[-1] == "Match Winner"


def test_existing_innings_score_fact_remains_correct(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "What was India's total in the 2011 World Cup final?"
    )
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["normalized_plan"]["filters"]["fact_type"] == "team_total"
    assert trace["normalized_plan"]["filters"]["team"] == "India"
    assert "India made 277/4 in innings 2" in response.summaries[0].body


@pytest.mark.parametrize(
    ("question", "competition", "match_id", "toss"),
    [
        ("Who won the toss in the 2007 World Cup final?", "ICC World Cup", "247507", "Australia"),
        ("Who won the toss in the 2011 Cricket World Cup final?", "ICC Cricket World Cup", "433606", "Sri Lanka"),
        ("Who won the toss in the 2015 World Cup final?", "ICC Cricket World Cup", "656495", "New Zealand"),
        ("Who won the toss in the 2023 World Cup final?", "World Cup 2023", "1384439", "Australia"),
        ("Who won the toss in the 2017 Champions Trophy final?", "ICC Champions Trophy", "1022375", "India"),
        ("Who won the toss in the final of the 2023 Asia Cup?", "Asia Cup", "1388414", "Sri Lanka"),
    ],
)
def test_competition_aliases_resolve_to_exact_stored_edition(
    semantic_service: SemanticAnalyticsService,
    question: str,
    competition: str,
    match_id: str,
    toss: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["normalized_plan"]["filters"]["competition"] == competition
    assert trace["final_answer_metadata"]["match_id"] == match_id
    assert trace["final_answer_metadata"]["toss"] == toss
    assert f"{toss} won the toss" in response.summaries[0].body


def test_competition_registry_matches_stored_database_editions() -> None:
    connection = duckdb.connect(str(AppConfig.from_env().duckdb_path), read_only=True)
    try:
        for definition in COMPETITION_REGISTRY:
            stored_names = sorted(set(definition.stored_by_year.values()))
            placeholders = ", ".join("?" for _ in stored_names)
            rows = connection.execute(
                f"""
                SELECT DISTINCT TRY_CAST(year AS INTEGER), competition
                FROM analytics.deliveries_v1
                WHERE competition IN ({placeholders})
                """,
                stored_names,
            ).fetchall()
            assert dict(rows) == dict(definition.stored_by_year), definition.key
        assert "World Cup Super League" not in SINGLE_FINAL_COMPETITIONS
        assert "ICC World Cup Qualifiers" not in SINGLE_FINAL_COMPETITIONS
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Who won the toss in the 2022 T20 World Cup final?", "different event"),
        ("Who won the toss in the 2007 T20 World Cup final?", "different event"),
        ("Who won the toss in the 2021 World Cup Super League final?", "different event"),
        ("Who won the toss in the 2022 Women's World Cup final?", "different event"),
        ("Who won the toss in the 2009 World Cup final?", "no ICC Cricket World Cup edition in 2009"),
        ("Who won the toss in the 1999 World Cup final?", "no ICC Cricket World Cup edition in 1999"),
    ],
)
def test_competition_aliases_never_broaden_to_another_event_or_year(
    semantic_service: SemanticAnalyticsService,
    question: str,
    fragment: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "insufficient_evidence"
    assert response.failure_state == "data_limitation"
    assert fragment in _text(response)
    assert trace["normalized_plan"] is None
    competition = next(
        fact
        for fact in trace["completeness_result"]["facts"]
        if fact["concept"] == "competition"
    )
    assert competition["disposition"] == "unsupported"


@pytest.mark.parametrize(
    "question",
    [
        "Who won the toss in the 2019 World Cup semi-final?",
        "Who won the toss in the 2019 World Cup semifinal?",
        "Who won the toss in the 2011 World Cup quarter final?",
        "Who won the toss in the 2019 World Cup group stage match?",
    ],
)
def test_unregistered_stages_never_select_the_final(
    semantic_service: SemanticAnalyticsService,
    question: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "insufficient_evidence"
    assert response.failure_state == "data_limitation"
    assert "no match-stage field" in _text(response)
    assert trace["normalized_plan"] is None
    stage = next(
        fact
        for fact in trace["completeness_result"]["facts"]
        if fact["concept"] == "stage"
    )
    assert stage["disposition"] == "unsupported"
    assert stage["requested"] != "final"


@pytest.mark.parametrize(
    ("question", "failure_state", "concept"),
    [
        (
            "What did New Zealand decide after winning the toss in the 2019 World Cup final?",
            "data_limitation",
            "toss_decision",
        ),
        ("Did the toss winner choose to bat first in the 2019 World Cup final?", "data_limitation", "toss_decision"),
        ("How many tosses did India win in the 2011 World Cup?", "unsupported_capability", "toss_aggregate"),
        (
            "What is Kohli's batting average in matches where India won the toss?",
            "unsupported_capability",
            "toss_condition",
        ),
        ("Who lost the toss in the 2019 World Cup final?", "unsupported_capability", "toss_loser"),
    ],
)
def test_unregistered_toss_concepts_fail_closed_with_named_reason(
    semantic_service: SemanticAnalyticsService,
    question: str,
    failure_state: str,
    concept: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.failure_state == failure_state
    assert trace["normalized_plan"] is None
    blocked = next(
        fact
        for fact in trace["completeness_result"]["facts"]
        if fact["concept"] == concept
    )
    assert blocked["disposition"] == "unsupported"
    assert "New Zealand won the toss" not in _text(response)


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Who won the toss and the match in the 2019 World Cup final?", "separate match facts"),
        ("Who won the toss in the 2015 or 2019 World Cup final?", "more than one year"),
    ],
)
def test_multi_valued_requests_ask_a_focused_clarification(
    semantic_service: SemanticAnalyticsService,
    question: str,
    fragment: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.failure_state == "planner_uncertainty"
    assert fragment in response.clarification_question.lower()
    assert trace["completeness_result"]["allows_execution"] is False


@pytest.mark.parametrize(
    ("question", "prefix", "toss"),
    [
        ("Did India win the toss in the 2011 World Cup final?", "No.", "Sri Lanka"),
        ("Did New Zealand win the toss in the 2019 World Cup final?", "Yes.", "New Zealand"),
    ],
)
def test_named_team_is_kept_and_answered_for_polar_toss_questions(
    semantic_service: SemanticAnalyticsService,
    question: str,
    prefix: str,
    toss: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "supported"
    assert response.summaries[0].body.startswith(prefix)
    assert f"{toss} won the toss" in response.summaries[0].body
    assert trace["normalized_plan"]["filters"]["participants"]
    team_fact = next(
        fact for fact in trace["completeness_result"]["facts"] if fact["concept"] == "team"
    )
    assert team_fact["canonical_target"] == "filters.participants"


def test_named_team_absent_from_selected_final_fails_closed(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Did India win the toss in the 2019 World Cup final?"
    )

    assert response.failure_state == "data_limitation"
    assert "India did not play" in _text(response)


def test_named_venue_is_verified_against_the_selected_final(
    semantic_service: SemanticAnalyticsService,
) -> None:
    matching = semantic_service.answer_question(
        "Who won the toss in the 2019 World Cup final at Lord's?"
    )
    mismatched = semantic_service.answer_question(
        "Who won the toss in the 2019 World Cup final at the MCG?"
    )

    assert matching.status.value == "supported"
    assert _trace(matching)["normalized_plan"]["filters"]["venue"] == "Lord's, London"
    assert "New Zealand won the toss" in matching.summaries[0].body
    assert mismatched.failure_state == "data_limitation"
    assert "played at Lord's, London, not Melbourne Cricket Ground" in _text(mismatched)


@pytest.mark.parametrize(
    "question",
    [
        "How many runs has Virat Kohli scored off full tosses?",
        "How many runs did Virat Kohli score in the 2023 World Cup final?",
        "How many runs did Kane Williamson score in the 2019 World Cup semi-final?",
        "Who has the highest score in World Cup matches?",
    ],
)
def test_non_match_fact_questions_are_not_claimed(question: str) -> None:
    players = ("Virat Kohli", "Kane Williamson")
    mentioned = tuple(player for player in players if player.lower() in question.lower())
    assert extract_match_fact_meaning(question, ("India",), mentioned) is None


def test_future_prediction_keeps_policy_precedence(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Who will win today's India match?")

    assert response.failure_state == "unsupported_capability"
    assert "Future match prediction" in _text(response)


class StubMatchMetadataRepository:
    def __init__(self, candidates: list[MatchMetadataCandidate]) -> None:
        self.candidates = candidates

    def match_metadata_candidates(
        self, *, year: int, competition: str
    ) -> list[MatchMetadataCandidate]:
        return self.candidates


def _candidate(
    match_id: str = "1144530",
    *,
    match_date: str = "2019-07-14",
    toss_winners: tuple[str, ...] = ("New Zealand",),
    winners: tuple[str, ...] = ("-",),
    missing_toss_rows: int = 0,
) -> MatchMetadataCandidate:
    return MatchMetadataCandidate(
        match_id=match_id,
        years=("2019",),
        dates=(match_date,),
        competitions=("ICC Cricket World Cup",),
        grounds=("Lord's, London",),
        winners=winners,
        toss_winners=toss_winners,
        teams=("England", "New Zealand"),
        missing_toss_rows=missing_toss_rows,
    )


def _resolve(candidates: list[MatchMetadataCandidate], **overrides: object):
    arguments: dict[str, object] = {
        "year": 2019,
        "competition": "ICC Cricket World Cup",
        "stage": "final",
        "fact_type": "toss",
    }
    arguments.update(overrides)
    return resolve_match_fact(StubMatchMetadataRepository(candidates), **arguments)


def test_inconsistent_toss_values_fail_closed() -> None:
    result = _resolve([_candidate(toss_winners=("New Zealand", "England"))])

    assert result.status == "data_limitation"
    assert "inconsistent toss winner" in result.detail.lower()
    assert result.fact_value is None


def test_missing_toss_value_returns_data_limitation() -> None:
    result = _resolve([_candidate(toss_winners=())])

    assert result.status == "data_limitation"
    assert "missing or inconsistent toss winner" in result.detail.lower()
    assert result.fact_value is None


def test_partially_missing_toss_rows_fail_closed() -> None:
    result = _resolve([_candidate(missing_toss_rows=3)])

    assert result.status == "data_limitation"
    assert result.fact_value is None


def test_no_winner_marker_is_never_a_toss_winner() -> None:
    result = _resolve([_candidate(toss_winners=("-",))])

    assert result.status == "data_limitation"
    assert result.fact_value is None


def test_duplicate_delivery_metadata_collapses_to_one_match_fact() -> None:
    result = _resolve([_candidate(toss_winners=("New Zealand", "New Zealand"))])

    assert result.status == "resolved"
    assert result.match_id == "1144530"
    assert result.fact_value == "New Zealand"


def test_tied_match_winner_does_not_replace_present_toss_winner() -> None:
    toss = _resolve([_candidate()])
    winner = _resolve([_candidate()], fact_type="winner")

    assert toss.status == "resolved"
    assert toss.fact_value == "New Zealand"
    assert winner.status == "data_limitation"
    assert winner.fact_value is None
    assert winner.toss == "New Zealand"
    assert "records no match winner" in winner.detail


def test_final_selection_fails_when_latest_match_date_is_not_unique() -> None:
    result = _resolve(
        [
            _candidate("1144530"),
            _candidate("another-final", toss_winners=("England",)),
        ]
    )

    assert result.status == "ambiguous"
    assert "more than one match" in result.detail.lower()
    assert result.match_id is None


def test_final_selection_is_not_applied_outside_single_final_tournaments() -> None:
    result = _resolve([_candidate()], competition="World Cup Super League", year=2023)

    assert result.status == "ambiguous"
    assert result.match_id is None


def test_non_final_stage_never_uses_latest_match_rule() -> None:
    result = _resolve([_candidate()], stage="semi-final")

    assert result.status == "ambiguous"
    assert result.match_id is None


@pytest.mark.parametrize(
    ("question", "missing_concept"),
    [
        ("Who won the toss in the 2019 final?", "competition"),
        ("Who won the toss in the World Cup final?", "year"),
        ("Who won the toss in the 2019 World Cup?", "stage"),
    ],
)
def test_missing_match_identity_requests_focused_clarification(
    semantic_service: SemanticAnalyticsService,
    question: str,
    missing_concept: str,
) -> None:
    response = semantic_service.answer_question(question)
    trace = _trace(response)

    assert response.status.value == "unsupported"
    assert response.failure_state == "planner_uncertainty"
    assert missing_concept in response.clarification_question.lower()
    assert trace["completeness_result"]["allows_execution"] is False
    missing_fact = next(
        fact
        for fact in trace["completeness_result"]["facts"]
        if fact["concept"] == missing_concept
    )
    assert missing_fact["disposition"] == "clarification_required"
