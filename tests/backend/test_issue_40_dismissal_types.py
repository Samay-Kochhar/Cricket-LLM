from __future__ import annotations

import json

import duckdb
import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.canonical_meaning import CanonicalMeaningResolver
from backend.app.cricket_analytics.cricket_definitions import (
    BOWLER_WICKET_PREDICATE,
    is_bowler_credit_wicket,
)
from backend.app.cricket_analytics.dismissal_types import (
    DISMISSAL_TYPE_REGISTRY,
    NON_DISMISSAL_OUT_VALUES,
    canonical_dismissal_type,
    requested_dismissal_types,
)
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.ontology import DIMENSIONS
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.services.chat_service import ChatService
from backend.app.services.gemini_client import GeminiStructuredResult

TRACER = "How often was Kohli dismissed caught versus bowled?"

# The saved production Flash extraction for the tracer (priority-8 capture).
SAVED_TRACER_EXTRACTION = {
    "version": 1,
    "family": "comparison",
    "entities": [{"name": "Kohli", "kind": "player", "relationship": "subject"}],
    "metric_concept": "dismissals",
    "role": None,
    "breakdown_dimensions": [],
    "split_dimensions": [],
    "filters": [
        {"concept": "dismissal type", "values": ["caught"], "evidence": "caught"},
        {"concept": "dismissal type", "values": ["bowled"], "evidence": "bowled"},
    ],
    "intent": "value",
    "ordering": None,
    "limit": None,
    "sample_threshold": None,
    "ambiguity_candidates": [],
}


class _Client:
    """Offline stand-in: either unconfigured or replaying one saved extraction."""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload
        self.calls = 0

    def is_configured(self) -> bool:
        return self.payload is not None

    def generate_structured(self, prompt: str, **kwargs: object) -> GeminiStructuredResult:
        self.calls += 1
        return GeminiStructuredResult(
            text=json.dumps(self.payload),
            selected_model="saved-test-flash",
            model_version="saved-response",
            finish_reason="STOP",
            latency_ms=0,
        )

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> None:
        return None

    def ground_with_google_search(self, *args: object, **kwargs: object) -> None:
        return None


@pytest.fixture(scope="module")
def repository() -> AnalyticsRepository:
    return AnalyticsRepository(AppConfig.from_env().duckdb_path)


@pytest.fixture(scope="module")
def db() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(AppConfig.from_env().duckdb_path), read_only=True)


def _chat(repository: AnalyticsRepository, payload: dict | None = None) -> tuple[ChatService, _Client]:
    client = _Client(payload)
    semantic = SemanticAnalyticsService(
        repository=repository,
        gemini_client=client,  # type: ignore[arg-type]
        app_env="production",
        allow_dev_fallback=False,
    )
    chat = ChatService(
        repository=repository,
        query_handler=semantic.answer_question,
        gemini_client=client,  # type: ignore[arg-type]
    )
    return chat, client


def _trace(response) -> dict:
    return json.loads(
        next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace")
    )


def _rows(response) -> dict[str, list]:
    table = response.tables[0]
    return {row[1]: row for row in table.rows}


def _independent_counts(db: duckdb.DuckDBPyConnection, batter: str, extra: str = "", params: list | None = None) -> dict[str, int]:
    """Read-only check independent of the application query builder."""
    rows = db.execute(
        "SELECT dismissal, COUNT(*) FROM analytics.deliveries_v1 "
        "WHERE out = 'True' AND p_out IN (SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat = ?) "
        + extra
        + " GROUP BY dismissal",
        [batter, *(params or [])],
    ).fetchall()
    return {str(dismissal): int(count) for dismissal, count in rows if dismissal is not None}


# --- tracer ---------------------------------------------------------------------


def test_tracer_returns_caught_170_and_bowled_34_from_saved_extraction(repository, db) -> None:
    chat, client = _chat(repository, SAVED_TRACER_EXTRACTION)
    reply = chat.reply(TRACER, history=[])

    assert client.calls == 1  # no refinement call for a resolved meaning
    response = reply.query_response
    assert reply.mode == "analysis"
    assert response.status.value == "supported"
    rows = _rows(response)
    assert rows["Caught"][2] == 170
    assert rows["Bowled"][2] == 34
    assert list(rows) == ["Caught", "Bowled"]
    independent = _independent_counts(db, "Virat Kohli")
    assert (independent["caught"], independent["bowled"]) == (170, 34)

    trace = _trace(response)
    plan = trace["normalized_plan"]
    assert plan["operation"] == "aggregate"
    assert plan["entity"] == "batter"
    assert plan["metric"] == "dismissals"
    assert plan["group_by"] == ["dismissal_type"]
    assert plan["filters"] == {"batter": "Virat Kohli", "dismissal_type": ["caught", "bowled"]}
    assert trace["selected_executor"] == "query_builders.dismissal_type_builder.build_dismissal_type_query"


def test_tracer_completeness_accounts_for_both_requested_categories(repository) -> None:
    chat, _ = _chat(repository, SAVED_TRACER_EXTRACTION)
    trace = _trace(chat.reply(TRACER, history=[]).query_response)
    facts = trace["meaning_resolution"]["completeness"]["facts"]

    values = {
        fact["requested"]: fact
        for fact in facts
        if fact["fact_type"] == "value" and fact["concept"] == "dismissal type"
    }
    assert set(values) == {"caught", "bowled"}
    assert all(fact["disposition"] == "compiled" for fact in values.values())
    assert all(fact["canonical_target"] == "filter.dismissal_type" for fact in values.values())
    assert trace["meaning_resolution"]["completeness"]["allows_execution"] is True


def test_tracer_without_a_model_uses_the_same_registered_path(repository) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(TRACER, history=[]).query_response

    rows = _rows(response)
    assert (rows["Caught"][2], rows["Bowled"][2]) == (170, 34)
    assert _trace(response)["normalized_plan"]["group_by"] == ["dismissal_type"]


# --- registered dimension ----------------------------------------------------------


def test_dismissal_type_is_a_registered_dimension_with_literal_categories(db) -> None:
    assert "dismissal_type" in DIMENSIONS
    stored = {
        row[0]
        for row in db.execute(
            "SELECT DISTINCT LOWER(TRIM(dismissal)) FROM analytics.deliveries_v1 "
            "WHERE out = 'True' AND dismissal IS NOT NULL"
        ).fetchall()
    }
    assert set(DISMISSAL_TYPE_REGISTRY) == stored - set(NON_DISMISSAL_OUT_VALUES)
    assert "caught and bowled" not in stored
    assert {definition.label for definition in DISMISSAL_TYPE_REGISTRY.values()} >= {
        "Caught",
        "Bowled",
        "Leg before wicket",
        "Run out",
        "Stumped",
        "Hit wicket",
    }
    for metric in ("dismissals", "dismissal_type_percentage"):
        rule = get_metric(metric)
        assert "dismissal_type" in rule.allowed_groupings
        assert "dismissal_type" in rule.allowed_filters
    assert "dismissal_type" not in get_metric("runs_scored").allowed_groupings


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        ("caught", "caught"),
        ("Caught", "caught"),
        ("bowled", "bowled"),
        ("lbw", "leg before wicket"),
        ("LBW", "leg before wicket"),
        ("leg before wicket", "leg before wicket"),
        ("leg-before", "leg before wicket"),
        ("run out", "run out"),
        ("run-out", "run out"),
        ("stumped", "stumped"),
        ("hit wicket", "hit wicket"),
        ("caught and bowled", None),
        ("caught behind", None),
        ("retired hurt", None),
        ("dismissed", None),
    ],
)
def test_extracted_category_values_map_only_to_literal_categories(value, stored) -> None:
    assert canonical_dismissal_type(value) == stored


# --- literal category behaviour ----------------------------------------------------


@pytest.mark.parametrize(
    ("question", "label", "stored"),
    [
        ("How many times was Virat Kohli caught?", "Caught", "caught"),
        ("How many times has Kohli been bowled?", "Bowled", "bowled"),
        ("How many times has Kohli been out lbw?", "Leg before wicket", "leg before wicket"),
        ("How often was Kohli dismissed leg before wicket?", "Leg before wicket", "leg before wicket"),
        ("How many times has Kohli been stumped?", "Stumped", "stumped"),
        ("How many times has Kohli been run out?", "Run out", "run out"),
        ("How often was Kohli out hit wicket?", "Hit wicket", "hit wicket"),
    ],
)
def test_each_literal_category_is_counted_separately(repository, db, question, label, stored) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(question, history=[]).query_response

    assert response.status.value == "supported"
    rows = _rows(response)
    assert list(rows) == [label]
    assert rows[label][2] == _independent_counts(db, "Virat Kohli").get(stored, 0)
    assert rows[label][-1] == 241
    assert _trace(response)["normalized_plan"]["filters"]["dismissal_type"] == [stored]


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("How often was Kohli caught and bowled?", "caught-and-bowled"),
        ("How often was Kohli caught behind?", "catcher"),
    ],
)
def test_unrecorded_catch_detail_is_a_targeted_data_limitation(repository, question, fragment) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(question, history=[]).query_response

    assert response.status.value == "insufficient_evidence"
    assert response.failure_state == "data_limitation"
    assert fragment in response.summaries[0].body
    assert not response.tables


def test_caught_does_not_silently_merge_caught_and_bowled() -> None:
    request = requested_dismissal_types("How often was Kohli caught and bowled?")
    assert request is not None
    assert request.categories == ()
    assert request.unrecorded == ("caught and bowled",)
    # Explicit comparison wording lists the two literal categories instead.
    compared = requested_dismissal_types("Compare how often Kohli was caught and bowled")
    assert compared is not None and compared.categories == ("caught", "bowled")


# --- attribution --------------------------------------------------------------------


def test_run_outs_use_dismissed_batter_attribution_including_non_striker(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply("How many times has Kohli been run out?", history=[]).query_response

    assert _rows(response)["Run out"][2] == 12
    non_striker = db.execute(
        "SELECT COUNT(*) FROM analytics.deliveries_v1 WHERE out = 'True' AND dismissal = 'run out' "
        "AND p_out IN (SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat = 'Virat Kohli') "
        "AND bat <> 'Virat Kohli'"
    ).fetchone()[0]
    partner_on_strike = db.execute(
        "SELECT COUNT(*) FROM analytics.deliveries_v1 WHERE out = 'True' AND dismissal = 'run out' "
        "AND bat = 'Virat Kohli' AND p_out NOT IN "
        "(SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat = 'Virat Kohli')"
    ).fetchone()[0]
    assert (non_striker, partner_on_strike) == (4, 11)
    assert "run out" in response.evidence_notes[-1].detail


def test_bowler_wicket_rules_still_exclude_run_outs() -> None:
    assert not is_bowler_credit_wicket("run out")
    assert "run out" not in BOWLER_WICKET_PREDICATE
    assert not DISMISSAL_TYPE_REGISTRY["run out"].bowler_credit
    assert DISMISSAL_TYPE_REGISTRY["caught"].bowler_credit


def test_named_player_stays_the_dismissed_batter_in_any_voice(repository) -> None:
    chat, _ = _chat(repository)
    for question in (
        "How many times was Bumrah caught?",
        "Bumrah caught how many times?",
        "How often did Bumrah get caught?",
    ):
        plan = _trace(chat.reply(question, history=[]).query_response)["normalized_plan"]
        assert plan["entity"] == "batter", question
        assert plan["filters"]["batter"] == "Jasprit Bumrah", question
        assert "bowler" not in plan["filters"], question


def test_bowler_named_after_by_is_a_delivery_filter(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply("How often was Kohli bowled by Starc?", history=[]).query_response

    plan = _trace(response)["normalized_plan"]
    assert plan["filters"] == {
        "batter": "Virat Kohli",
        "bowler": "Mitchell Starc",
        "dismissal_type": ["bowled"],
    }
    independent = _independent_counts(db, "Virat Kohli", "AND bowl = ?", ["Mitchell Starc"])
    rows = _rows(response)
    assert rows["Bowled"][2] == independent.get("bowled", 0) == 0
    assert rows["Bowled"][-1] == sum(independent.values()) == 1
    assert "on deliveries from Mitchell Starc" in response.summaries[0].body


# --- counts, shares and forms -----------------------------------------------------


def test_percentage_share_has_an_explicit_denominator(repository) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(
        "What share of Kohli's dismissals were caught versus bowled?", history=[]
    ).query_response

    plan = _trace(response)["normalized_plan"]
    assert plan["metric"] == "dismissal_type_percentage"
    assert response.tables[0].columns == [
        "Batter",
        "Dismissal Type",
        "Dismissals",
        "Share of Dismissals (%)",
        "All Recorded Dismissals",
    ]
    rows = _rows(response)
    assert rows["Caught"][2:] == [170, 70.54, 241]
    assert rows["Bowled"][2:] == [34, 14.11, 241]
    assert "70.54% (170 of 241)" in response.summaries[0].body
    assert "all recorded dismissals" in response.evidence_notes[-1].detail


def test_counts_and_shares_are_distinct_meanings(repository) -> None:
    chat, _ = _chat(repository)
    counts = _trace(chat.reply(TRACER, history=[]).query_response)["normalized_plan"]
    shares = _trace(
        chat.reply("What percentage of Kohli's dismissals were caught?", history=[]).query_response
    )["normalized_plan"]
    assert counts["metric"] == "dismissals"
    assert shares["metric"] == "dismissal_type_percentage"


@pytest.mark.parametrize(
    "question",
    [
        "Compare how often Kohli was caught and bowled",
        "Kohli: caught vs bowled dismissals?",
        "Kohli caught or bowled more?",
    ],
)
def test_one_player_categorical_comparison_is_not_a_two_player_comparison(repository, question) -> None:
    chat, _ = _chat(repository)
    reply = chat.reply(question, history=[])

    assert reply.mode == "analysis"
    assert reply.query_response.status.value == "supported"
    rows = _rows(reply.query_response)
    assert (rows["Caught"][2], rows["Bowled"][2]) == (170, 34)


def test_breakdown_filtered_and_requested_forms_share_the_dimension_path(repository, db) -> None:
    chat, _ = _chat(repository)
    independent = _independent_counts(db, "Virat Kohli")
    registered = {key: value for key, value in independent.items() if key in DISMISSAL_TYPE_REGISTRY}
    forms = {
        "Break down Kohli's dismissals by dismissal type": None,
        "How was Kohli usually dismissed?": None,
        "How many times was Virat Kohli caught?": ["caught"],
        TRACER: ["caught", "bowled"],
    }
    for question, categories in forms.items():
        response = chat.reply(question, history=[]).query_response
        trace = _trace(response)
        plan = trace["normalized_plan"]
        assert plan["group_by"] == ["dismissal_type"], question
        assert plan["filters"].get("dismissal_type") == categories, question
        assert trace["selected_executor"].endswith("build_dismissal_type_query"), question
    breakdown = chat.reply(
        "Break down Kohli's dismissals by dismissal type", history=[]
    ).query_response
    table_counts = {row[1]: row[2] for row in breakdown.tables[0].rows}
    assert table_counts == {
        DISMISSAL_TYPE_REGISTRY[key].label: value for key, value in registered.items()
    }
    assert sum(table_counts.values()) == 241


def test_table_and_narrative_keep_dismissal_language_and_scope(repository) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(TRACER, history=[]).query_response

    body = response.summaries[0].body
    assert body.startswith("Within the ODI database")
    assert "caught 170 times" in body and "bowled 34 times" in body
    assert "241 recorded dismissals" in body
    assert "wicket" not in body.lower()
    assert response.tables[0].columns == [
        "Batter",
        "Dismissal Type",
        "Dismissals",
        "All Recorded Dismissals",
    ]
    assert not response.charts


def test_requested_scope_filters_are_preserved(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(
        "How often was Kohli dismissed caught against Australia in 2019?", history=[]
    ).query_response

    plan = _trace(response)["normalized_plan"]
    assert plan["filters"] == {
        "batter": "Virat Kohli",
        "dismissal_type": ["caught"],
        "years": [2019],
        "opposition": "Australia",
    }
    independent = _independent_counts(
        db, "Virat Kohli", "AND year = ? AND team_bowl = ?", ["2019", "Australia"]
    )
    rows = _rows(response)
    assert rows["Caught"][2] == independent["caught"] == 7
    assert rows["Caught"][-1] == sum(independent.values()) == 9
    assert "in 2019 against Australia" in response.summaries[0].body


def test_innings_wording_is_a_filter_not_a_single_match(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply("How often was Kohli caught while chasing?", history=[]).query_response

    assert _trace(response)["normalized_plan"]["filters"]["innings"] == 2
    independent = _independent_counts(db, "Virat Kohli", "AND inns = '2'")
    assert _rows(response)["Caught"][2] == independent["caught"] == 88
    first = chat.reply("How often was Kohli caught in the first innings?", history=[]).query_response
    assert _rows(first)["Caught"][2] == 82


# --- completeness ---------------------------------------------------------------


def _resolver(repository: AnalyticsRepository) -> CanonicalMeaningResolver:
    return CanonicalMeaningResolver(
        available_players=repository.list_player_names(),
        available_venues=repository.list_venues(),
        available_teams=repository.list_teams(),
        player_participation=repository.player_participation(),
    )


def test_an_extracted_category_the_plan_omits_blocks_execution(repository) -> None:
    candidate = dict(SAVED_TRACER_EXTRACTION)
    candidate["filters"] = [
        *SAVED_TRACER_EXTRACTION["filters"],
        {"concept": "dismissal type", "values": ["stumped"], "evidence": "caught"},
    ]
    resolution = _resolver(repository).resolve_candidate(
        TRACER, None, LanguageMeaningCandidate.model_validate(candidate)
    )
    assert resolution.status.value == "unsupported"
    assert resolution.completeness is not None
    assert resolution.completeness.allows_execution is False
    blocked = [fact for fact in resolution.completeness.facts if fact.disposition == "unsupported"]
    assert any(fact.requested == "stumped" for fact in blocked)


def test_an_unregistered_category_value_blocks_execution(repository) -> None:
    candidate = dict(SAVED_TRACER_EXTRACTION)
    candidate["filters"] = [
        {"concept": "dismissal type", "values": ["caught", "timed out"], "evidence": "caught"},
    ]
    resolution = _resolver(repository).resolve_candidate(
        TRACER, None, LanguageMeaningCandidate.model_validate(candidate)
    )
    assert resolution.status.value == "unsupported"


def test_validator_rejects_plans_that_drop_or_misuse_dismissal_types() -> None:
    dropped = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="dismissals",
        group_by=["batter"],
        filters={"batter": "Virat Kohli"},
        sort=SortSpec(by="dismissals", direction="desc"),
    )
    assert any("dismissal types" in error for error in validate_plan(dropped, TRACER).errors)

    partial = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="dismissals",
        group_by=["dismissal_type"],
        filters={"batter": "Virat Kohli", "dismissal_type": ["caught"]},
        sort=SortSpec(by="dismissals", direction="desc"),
        limit=None,
    )
    assert any("every requested dismissal type" in error for error in validate_plan(partial, TRACER).errors)

    wrong_metric = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="runs_scored",
        group_by=["dismissal_type"],
        filters={"batter": "Virat Kohli"},
        sort=SortSpec(by="runs_scored", direction="desc"),
        limit=None,
    )
    assert not validate_plan(wrong_metric, "Kohli runs by dismissal type").valid


# --- targeted limitations --------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Who has been stumped the most?", "one named dismissed batter"),
        ("Kohli strike rate by dismissal type", "Only dismissal counts and dismissal shares"),
        ("How often was Kohli caught against short balls?", "length filter"),
        ("Kohli caught to bowled ratio", "ratio"),
        ("How was Kohli out in the 2011 final?", "single match"),
        # Registered chase/result conditions compile (issue 42); unread result
        # wording is still a named limitation.
        ("How often was Kohli bowled in matches India lost?", "match-result condition"),
    ],
)
def test_unsupported_dismissal_type_requests_name_the_missing_capability(repository, question, fragment) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(question, history=[]).query_response

    assert response.status.value == "unsupported"
    assert response.failure_state == "unsupported_capability"
    assert fragment in response.summaries[0].body
    assert not response.tables


# --- follow-ups -----------------------------------------------------------------


def test_follow_ups_change_scope_categories_and_counts_versus_shares(repository, db) -> None:
    chat, _ = _chat(repository)
    state = None
    answers = {}
    for question in (
        TRACER,
        "And in 2019?",
        "What about stumped?",
        "As a percentage?",
        "all dismissal types",
    ):
        reply = chat.reply(question, history=[], conversation_state=state)
        answers[question] = reply.query_response
        state = reply.conversation_state or state

    in_2019 = _independent_counts(db, "Virat Kohli", "AND year = ?", ["2019"])
    assert _rows(answers["And in 2019?"])["Caught"][2] == in_2019["caught"] == 18
    assert _rows(answers["And in 2019?"])["Bowled"][2] == in_2019["bowled"] == 3
    assert _rows(answers["What about stumped?"])["Stumped"][2] == 0
    share_plan = _trace(answers["As a percentage?"])["normalized_plan"]
    assert share_plan["metric"] == "dismissal_type_percentage"
    assert share_plan["filters"]["dismissal_type"] == ["stumped"]
    final = _trace(answers["all dismissal types"])["normalized_plan"]
    assert "dismissal_type" not in final["filters"]
    assert final["filters"]["years"] == [2019]
    assert sum(row[2] for row in answers["all dismissal types"].tables[0].rows) == sum(in_2019.values()) == 23


# --- compatibility -----------------------------------------------------------------


def test_existing_dismissal_wicket_and_fielding_answers_are_unchanged(repository) -> None:
    chat, _ = _chat(repository)

    total = chat.reply("How many times has Kohli been dismissed?", history=[]).query_response
    assert _trace(total)["normalized_plan"]["group_by"] == ["batter"]
    assert total.tables[0].rows[0][1] == 248

    matchup = _trace(
        chat.reply("Which bowler gets David Warner out most?", history=[]).query_response
    )["normalized_plan"]
    assert matchup["entity"] == "bowler"
    assert matchup["group_by"] == ["bowler"]
    assert "dismissal_type" not in matchup["filters"]

    for question in (
        "How many run outs has Jadeja effected?",
        "Who took the most catches in the 2019 World Cup?",
    ):
        response = chat.reply(question, history=[]).query_response
        assert response.failure_state == "data_limitation", question

    for question in (
        "How many overs has Bumrah bowled?",
        "Who has bowled the most dot balls?",
        "Which bowler has bowled Kohli the most?",
    ):
        assert requested_dismissal_types(question) is None, question
