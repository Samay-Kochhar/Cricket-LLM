from __future__ import annotations

import json

import duckdb
import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
)
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.match_state_filters import (
    MATCH_STATE_FIELDS,
    REQUIRED_RUN_RATE,
    match_state_mentions,
    predicate_from_filter,
    predicate_from_language_values,
    registered_predicates,
    strip_match_state_phrases,
)
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.query_builders.aggregate_builder import (
    build_aggregate_query,
)
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.services.chat_service import ChatService
from backend.app.services.gemini_client import GeminiStructuredResult

TRACER = "Rohit's strike rate when required rate was above 8?"

# The saved production Flash extraction for the tracer (priority-8 capture): the
# threshold arrives as the string ">8" with no structured operator.
SAVED_TRACER_EXTRACTION = {
    "version": 1,
    "family": "direct",
    "entities": [{"name": "Rohit", "kind": "player", "relationship": "subject"}],
    "metric_concept": "strike rate",
    "role": None,
    "breakdown_dimensions": [],
    "split_dimensions": [],
    "filters": [
        {
            "concept": "required rate",
            "values": [">8"],
            "evidence": "when required rate was above 8",
        }
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


@pytest.fixture(scope="module")
def resolver(repository) -> CanonicalMeaningResolver:
    return CanonicalMeaningResolver(
        available_players=repository.list_player_names(),
        available_venues=repository.list_venues(),
        available_teams=repository.list_teams(),
        player_participation=repository.player_participation(),
    )


def _chat(
    repository: AnalyticsRepository,
    payload: dict | None = None,
    *,
    dev_fallback: bool = False,
) -> tuple[ChatService, _Client]:
    client = _Client(payload)
    semantic = SemanticAnalyticsService(
        repository=repository,
        gemini_client=client,  # type: ignore[arg-type]
        app_env="production",
        allow_dev_fallback=dev_fallback,
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


def _row(response) -> dict[str, object]:
    table = response.tables[0]
    return dict(zip(table.columns, table.rows[0]))


def _note(response, title: str = "Required run rate filter") -> str:
    return next(note.detail for note in response.evidence_notes if note.title == title)


def _independent(
    db: duckdb.DuckDBPyConnection,
    condition: str,
    params: list | None = None,
    *,
    batter: str = "Rohit Sharma",
    extra: str = "",
) -> tuple[int, int]:
    """Read-only runs/balls-faced check independent of the application builder."""
    runs, balls = db.execute(
        "SELECT SUM(CASE WHEN ballfaced = '1' THEN CAST(batruns AS INTEGER) ELSE 0 END), "
        "SUM(CASE WHEN ballfaced = '1' THEN 1 ELSE 0 END) "
        "FROM analytics.deliveries_v1 WHERE bat = ? AND " + condition + extra,
        [batter, *(params or [])],
    ).fetchone()
    return int(runs or 0), int(balls or 0)


def _plan(filters: dict[str, object], metric: str = "batting_strike_rate", entity: str = "batter") -> CricketQueryPlan:
    return CricketQueryPlan(
        operation="aggregate",
        entity=entity,
        metric=metric,
        group_by=[entity],
        filters=filters,
        sort=SortSpec(by=metric, direction="desc"),
    )


# --- tracer ---------------------------------------------------------------------


def test_tracer_returns_118_79_from_354_runs_and_298_balls_from_saved_extraction(repository, db) -> None:
    chat, client = _chat(repository, SAVED_TRACER_EXTRACTION)
    reply = chat.reply(TRACER, history=[])

    assert client.calls == 1
    response = reply.query_response
    assert reply.mode == "analysis"
    assert response.status.value == "supported"
    row = _row(response)
    assert row["Batting Strike Rate"] == 118.79
    assert row["Runs Scored"] == 354
    assert row["Balls Faced"] == 298
    assert _independent(db, "TRY_CAST(inns_rrr AS DOUBLE) > 8") == (354, 298)
    assert "required run rate above 8" in response.summaries[0].body

    trace = _trace(response)
    plan = trace["normalized_plan"]
    assert plan["operation"] == "aggregate"
    assert plan["entity"] == "batter"
    assert plan["metric"] == "batting_strike_rate"
    assert plan["filters"] == {
        "batter": "Rohit Sharma",
        "required_run_rate": {"operator": "gt", "value": 8},
    }
    query = response.evidence_queries[0]
    assert "TRY_CAST(inns_rrr AS DOUBLE) > ?" in query.sql
    assert "TRY_CAST(inns_balls_rem AS DOUBLE) > 0" in query.sql
    assert 8.0 in query.parameters


def test_tracer_completeness_accounts_for_field_operator_and_value(repository) -> None:
    chat, _ = _chat(repository, SAVED_TRACER_EXTRACTION)
    trace = _trace(chat.reply(TRACER, history=[]).query_response)
    completeness = trace["meaning_resolution"]["completeness"]
    facts = {
        fact["fact_type"]: fact
        for fact in completeness["facts"]
        if fact["fact_type"] in {"filter", "operator", "value"}
    }

    assert completeness["allows_execution"] is True
    assert facts["filter"]["disposition"] == "compiled"
    assert facts["filter"]["canonical_target"] == "filter.required_run_rate"
    assert facts["operator"]["requested"] == "gt"
    assert facts["operator"]["disposition"] == "compiled"
    assert facts["operator"]["canonical_target"] == "filter.required_run_rate.operator"
    assert facts["value"]["requested"] == 8
    assert facts["value"]["disposition"] == "compiled"
    assert facts["value"]["canonical_target"] == "filter.required_run_rate.value"


@pytest.mark.parametrize("dev_fallback", [False, True])
def test_tracer_without_a_model_uses_the_same_registered_predicate(repository, dev_fallback) -> None:
    chat, _ = _chat(repository, dev_fallback=dev_fallback)
    response = chat.reply(TRACER, history=[]).query_response

    row = _row(response)
    assert (row["Batting Strike Rate"], row["Runs Scored"], row["Balls Faced"]) == (118.79, 354, 298)
    assert _trace(response)["normalized_plan"]["filters"]["required_run_rate"] == {
        "operator": "gt",
        "value": 8,
    }


# --- stored-field audit -----------------------------------------------------------


def test_inns_rrr_is_the_state_after_the_recorded_delivery(db) -> None:
    first, recorded_first = db.execute(
        "SELECT COUNT(*), COUNT(inns_rrr) FROM analytics.deliveries_v1 WHERE inns = '1'"
    ).fetchone()
    assert first > 0 and recorded_first == 0

    total, after_match, no_balls_left, before_match = db.execute(
        """
        WITH d AS (
          SELECT CAST(inns_rrr AS DOUBLE) AS rrr,
                 CAST(inns_runs_rem AS DOUBLE) AS runs_rem,
                 CAST(inns_balls_rem AS DOUBLE) AS balls_rem,
                 CAST(score AS DOUBLE) AS score,
                 wide, noball
          FROM analytics.deliveries_v1 WHERE inns = '2'
        )
        SELECT COUNT(*),
               SUM(CASE WHEN balls_rem > 0 AND ABS(rrr - ROUND(runs_rem * 6 / balls_rem, 2)) <= 0.011 THEN 1 ELSE 0 END),
               SUM(CASE WHEN balls_rem <= 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN ABS(rrr - ROUND((runs_rem + score) * 6
                   / NULLIF(balls_rem + CASE WHEN wide = '0' AND noball = '0' THEN 1 ELSE 0 END, 0), 2)) <= 0.011
                   THEN 1 ELSE 0 END)
        FROM d
        """
    ).fetchone()
    # Every row with balls remaining matches the after-delivery formula; the
    # before-delivery reading does not describe the stored value.
    assert after_match + no_balls_left == total
    assert before_match < total / 2
    assert db.execute(
        "SELECT COUNT(*) FROM analytics.deliveries_v1 WHERE inns = '2' "
        "AND CAST(inns_balls_rem AS DOUBLE) <= 0 AND CAST(inns_rrr AS DOUBLE) <> 0"
    ).fetchone()[0] == 0


def test_required_run_rate_is_a_registered_filter_not_an_arbitrary_expression() -> None:
    assert set(MATCH_STATE_FIELDS) == {"required_run_rate"}
    assert REQUIRED_RUN_RATE.column == "inns_rrr"
    for metric in ("batting_strike_rate", "runs_scored", "economy_rate", "dismissals"):
        assert "required_run_rate" in get_metric(metric).allowed_filters
    assert "required_run_rate" not in get_metric("batting_strike_rate").allowed_groupings


# --- typed predicates ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (TRACER, {"operator": "gt", "value": 8}),
        ("Rohit's SR when RRR > 8", {"operator": "gt", "value": 8}),
        ("Rohit's strike rate when the required rate exceeded 8", {"operator": "gt", "value": 8}),
        ("Rohit's strike rate with required run rate >= 8", {"operator": "gte", "value": 8}),
        ("Rohit's strike rate when the required rate was at least 8", {"operator": "gte", "value": 8}),
        ("Rohit's strike rate when the asking rate was 8 or more", {"operator": "gte", "value": 8}),
        ("Rohit's strike rate in 8+ RRR chases", {"operator": "gte", "value": 8}),
        ("Rohit's strike rate when RRR was below 4", {"operator": "lt", "value": 4}),
        ("Rohit's strike rate when the required rate was under 4", {"operator": "lt", "value": 4}),
        ("Rohit's strike rate when the RRR was at most 7.25", {"operator": "lte", "value": 7.25}),
        ("Rohit's strike rate when the required rate was 6 or less", {"operator": "lte", "value": 6}),
        ("Rohit's strike rate when the required rate was between 6 and 8", {"operator": "between", "lower": 6, "upper": 8}),
        ("Rohit's strike rate when the RRR was 6-8", {"operator": "between", "lower": 6, "upper": 8}),
        ("Rohit's strike rate with the required rate above 8.5 an over", {"operator": "gt", "value": 8.5}),
        ("Rohit's strike rate when required rate was above eight?", {"operator": "gt", "value": 8}),
    ],
)
def test_language_resolves_one_typed_predicate(question, expected) -> None:
    assert registered_predicates(question) == {"required_run_rate": expected}


def test_decimals_are_preserved_without_integer_coercion() -> None:
    predicate = registered_predicates("RRR above 8.5")["required_run_rate"]
    assert predicate == {"operator": "gt", "value": 8.5}
    assert isinstance(predicate["value"], float)
    assert registered_predicates("RRR above 8")["required_run_rate"]["value"] == 8
    for values, operator in (([">8.5"], None), (["8.5"], "gt"), ([8.5], "gt")):
        parsed = predicate_from_language_values(operator, values, "required rate above 8.5", REQUIRED_RUN_RATE)
        assert parsed is not None and parsed.as_filter() == {"operator": "gt", "value": 8.5}


def test_gt_and_gte_stay_distinct_meanings_predicates_and_answers(repository, db, resolver) -> None:
    strict = resolver.resolve("Rohit's strike rate when required rate was above 8", None).meaning
    inclusive = resolver.resolve("Rohit's strike rate when required rate was at least 8", None).meaning
    assert strict.filters["required_run_rate"] == {"operator": "gt", "value": 8}
    assert inclusive.filters["required_run_rate"] == {"operator": "gte", "value": 8}

    assert "TRY_CAST(inns_rrr AS DOUBLE) > ?" in build_aggregate_query(_plan(strict.filters)).sql
    assert "TRY_CAST(inns_rrr AS DOUBLE) >= ?" in build_aggregate_query(_plan(inclusive.filters)).sql

    chat, _ = _chat(repository)
    row = _row(chat.reply("Rohit's strike rate when required rate was at least 8", history=[]).query_response)
    assert (row["Runs Scored"], row["Balls Faced"], row["Batting Strike Rate"]) == (354, 301, 117.61)
    assert _independent(db, "TRY_CAST(inns_rrr AS DOUBLE) >= 8") == (354, 301)


@pytest.mark.parametrize(
    ("question", "condition", "params", "expected_rate"),
    [
        ("Rohit's strike rate when the RRR was above 8.5", "TRY_CAST(inns_rrr AS DOUBLE) > ?", [8.5], 121.47),
        (
            "Rohit's strike rate when the required rate was between 6 and 8",
            "TRY_CAST(inns_rrr AS DOUBLE) BETWEEN ? AND ?",
            [6, 8],
            89.06,
        ),
    ],
)
def test_decimal_and_bounded_range_answers_match_independent_queries(
    repository, db, question, condition, params, expected_rate
) -> None:
    chat, _ = _chat(repository)
    row = _row(chat.reply(question, history=[]).query_response)
    runs, balls = _independent(db, condition, params)
    assert (row["Runs Scored"], row["Balls Faced"]) == (runs, balls)
    assert row["Batting Strike Rate"] == expected_rate == round(runs * 100 / balls, 2)


# --- aliases ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Rohit's strike rate when RRR was above 8",
        "Rohit's strike rate when the required run rate was above 8",
        "Rohit's strike rate when the asking rate was above 8",
        "Rohit's strike rate when the required rate was above 8",
    ],
)
def test_required_rate_aliases_resolve_to_the_registered_concept(resolver, question) -> None:
    meaning = resolver.resolve(question, None).meaning
    assert meaning.metric == "batting_strike_rate"
    assert meaning.role == "batter"
    assert meaning.filters == {
        "batter": "Rohit Sharma",
        "required_run_rate": {"operator": "gt", "value": 8},
    }


def test_required_rate_wording_is_not_a_run_rate_runs_or_sample_request(resolver) -> None:
    runs = resolver.resolve("How many runs has Rohit scored when the required run rate was at least 8?", None)
    assert runs.meaning.metric == "runs_scored"
    assert runs.meaning.minimum_sample is None
    average = resolver.resolve("Rohit's batting average when the asking rate was 8 or more", None)
    assert average.meaning.metric == "batting_average"
    # "at least 8" belongs to the predicate, not to a minimum sample or ranking direction.
    assert strip_match_state_phrases("Rohit's SR when required rate at least 8") == "rohit's sr when"
    assert validate_plan(
        _plan({"batter": "Rohit Sharma", "required_run_rate": {"operator": "gte", "value": 8}}),
        "Rohit's strike rate when required rate was at least 8",
    ).valid


@pytest.mark.parametrize(
    ("question", "concept"),
    [
        ("Rohit's strike rate when the current run rate was above 6", "current run rate"),
        ("Rohit's strike rate when the run rate was above 6", "run rate"),
        ("Rohit's strike rate when the target was above 300", "target"),
        ("Rohit's strike rate chasing over 300", "target"),
        ("Rohit's strike rate with more than 50 runs needed", "runs needed"),
        ("Rohit's strike rate with fewer than 3 wickets in hand", "wickets in hand"),
    ],
)
def test_unsupported_numeric_fields_fail_closed_with_the_concept_retained(repository, question, concept) -> None:
    chat, _ = _chat(repository)
    reply = chat.reply(question, history=[])
    response = reply.query_response

    assert response.status.value == "unsupported"
    assert not response.evidence_queries
    assert f"Filtering by {concept} is not a registered match-state filter" in response.summaries[0].body


def test_an_extracted_unregistered_numeric_concept_blocks_execution(resolver) -> None:
    candidate = LanguageMeaningCandidate.model_validate(
        {
            **SAVED_TRACER_EXTRACTION,
            "filters": [
                {"concept": "target", "operator": "gt", "values": [300], "evidence": "strike rate"}
            ],
        }
    )
    resolution = resolver.resolve_candidate("Rohit's strike rate", None, candidate)
    assert resolution.status == MeaningStatus.unsupported
    assert "Filtering by target" in resolution.reason
    blocked = [
        fact
        for fact in resolution.completeness.facts
        if fact.fact_type == "filter" and fact.concept == "target"
    ]
    assert blocked and blocked[0].disposition == "unsupported"
    assert resolution.completeness.allows_execution is False


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Rohit's strike rate by required rate", "Which required run rate threshold"),
        ("Rohit's strike rate when the required rate was high", "Which required run rate threshold"),
        ("Rohit's strike rate when required rate was 8", "Which required run rate comparison"),
        ("Rohit's strike rate when required rate was above 8 vs below 8", "Only one required run rate condition"),
        ("Rohit's strike rate when required rate was above 8 and below 12", "Only one required run rate condition"),
        ("Rohit's strike rate when required rate was above 150", "threshold must be between 0 and 100"),
    ],
)
def test_unreadable_required_rate_conditions_ask_instead_of_disappearing(repository, question, fragment) -> None:
    chat, _ = _chat(repository)
    reply = chat.reply(question, history=[])
    assert reply.mode == "clarification"
    assert fragment in reply.message
    assert not reply.query_response.evidence_queries


# --- unavailable values ----------------------------------------------------------


def test_unavailable_required_rate_is_excluded_never_zero(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply("Rohit's strike rate when RRR was below 4", history=[]).query_response
    row = _row(response)

    available = "TRY_CAST(inns_rrr AS DOUBLE) IS NOT NULL AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0"
    assert (row["Runs Scored"], row["Balls Faced"]) == _independent(
        db, available + " AND TRY_CAST(inns_rrr AS DOUBLE) < 4"
    ) == (1441, 1474)
    # The stored 0 on a ball with no balls remaining is not a real required rate.
    assert _independent(db, "TRY_CAST(inns_rrr AS DOUBLE) < 4")[1] == 1475

    note = _note(response)
    assert "never treated as zero" in note
    assert "recorded after each delivery" in note
    first_innings = _independent(db, "inns = '1'")[1]
    no_balls_left = _independent(db, "inns = '2' AND TRY_CAST(inns_balls_rem AS DOUBLE) <= 0")[1]
    assert f"{first_innings + no_balls_left:,} had no recorded required run rate" in note
    assert "1,474 met the condition" in note


def test_malformed_or_unregistered_predicates_never_compile() -> None:
    for bad in (
        ">8",
        {"operator": "gt", "value": "8"},
        {"operator": "gt", "value": True},
        {"operator": "eq", "value": 8},
        {"operator": "gt", "value": 8, "sql": "1=1"},
        {"operator": "between", "lower": 8, "upper": 6},
        {"operator": "gt", "value": float("nan")},
        {"operator": "gt", "value": 500},
    ):
        assert predicate_from_filter(bad, REQUIRED_RUN_RATE) is None
        result = validate_plan(_plan({"batter": "Rohit Sharma", "required_run_rate": bad}), "Rohit's strike rate")
        assert not result.valid
        assert build_aggregate_query(
            _plan({"batter": "Rohit Sharma", "required_run_rate": bad})
        ).sql.count("1 = 0") == 1
    unregistered = validate_plan(
        _plan({"batter": "Rohit Sharma", "inns_rr": {"operator": "gt", "value": 6}}), "Rohit's strike rate"
    )
    assert not unregistered.valid


def test_validator_rejects_a_plan_that_drops_or_changes_the_predicate() -> None:
    dropped = validate_plan(_plan({"batter": "Rohit Sharma"}), TRACER)
    assert not dropped.valid
    assert any("required run rate" in error for error in dropped.errors)
    changed = validate_plan(
        _plan({"batter": "Rohit Sharma", "required_run_rate": {"operator": "gte", "value": 8}}), TRACER
    )
    assert not changed.valid
    assert validate_plan(
        _plan({"batter": "Rohit Sharma", "required_run_rate": {"operator": "gt", "value": 8}}), TRACER
    ).valid


def test_a_model_reading_that_contradicts_the_wording_asks_for_clarification(resolver) -> None:
    candidate = LanguageMeaningCandidate.model_validate(
        {
            **SAVED_TRACER_EXTRACTION,
            "filters": [
                {"concept": "required rate", "operator": "gte", "values": [8], "evidence": "required rate"}
            ],
        }
    )
    resolution = resolver.resolve_candidate(TRACER, None, candidate)
    assert resolution.status == MeaningStatus.clarification
    assert resolution.clarification_options == ["required run rate > 8", "required run rate >= 8"]


def test_a_model_that_omits_the_condition_cannot_drop_it(resolver) -> None:
    candidate = LanguageMeaningCandidate.model_validate({**SAVED_TRACER_EXTRACTION, "filters": []})
    resolution = resolver.resolve_candidate(TRACER, None, candidate)
    assert resolution.status == MeaningStatus.resolved
    assert resolution.meaning.filters["required_run_rate"] == {"operator": "gt", "value": 8}


# --- composition -----------------------------------------------------------------


def test_predicate_composes_with_phase_opposition_year_and_venue(repository, db) -> None:
    chat, _ = _chat(repository)
    rrr = "TRY_CAST(inns_rrr AS DOUBLE) > 8 AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0"

    death = _row(chat.reply("Rohit's strike rate in the death overs when required rate above 8", history=[]).query_response)
    assert (death["Runs Scored"], death["Balls Faced"]) == _independent(
        db, rrr, extra=" AND TRY_CAST(over AS DOUBLE) > 40"
    )

    response = chat.reply(
        "Rohit's strike rate when the required rate was above 8 against Australia in 2019", history=[]
    ).query_response
    scoped = _row(response)
    assert _trace(response)["normalized_plan"]["filters"] == {
        "batter": "Rohit Sharma",
        "opposition": "Australia",
        "years": [2019],
        "required_run_rate": {"operator": "gt", "value": 8},
    }
    assert (scoped["Runs Scored"], scoped["Balls Faced"]) == _independent(
        db, rrr, extra=" AND team_bowl = 'Australia' AND year = '2019'"
    )

    venue = _row(chat.reply("Rohit's strike rate at Wankhede when RRR above 8", history=[]).query_response)
    assert (venue["Runs Scored"], venue["Balls Faced"]) == _independent(
        db, rrr, extra=" AND ground = 'Wankhede Stadium, Mumbai'"
    )


def test_predicate_applies_to_bowlers_rankings_and_comparisons(repository, db) -> None:
    chat, _ = _chat(repository)
    economy = _row(chat.reply("Bumrah's economy when the required rate was above 8", history=[]).query_response)
    runs, legal = db.execute(
        "SELECT SUM(CAST(bowlruns AS INTEGER)), SUM(CASE WHEN wide = '0' AND noball = '0' THEN 1 ELSE 0 END) "
        "FROM analytics.deliveries_v1 WHERE bowl = 'Jasprit Bumrah' "
        "AND TRY_CAST(inns_rrr AS DOUBLE) > 8 AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0"
    ).fetchone()
    assert (economy["Runs Conceded"], economy["Legal Balls"]) == (runs, legal)

    ranking = chat.reply("Who scored the most runs when the RRR was above 10?", history=[]).query_response
    leader, leader_runs = db.execute(
        "SELECT bat, SUM(CASE WHEN ballfaced = '1' THEN CAST(batruns AS INTEGER) ELSE 0 END) AS r "
        "FROM analytics.deliveries_v1 WHERE TRY_CAST(inns_rrr AS DOUBLE) > 10 "
        "AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0 GROUP BY bat ORDER BY r DESC LIMIT 1"
    ).fetchone()
    top = _row(ranking)
    assert (top["Batter"], top["Runs Scored"]) == (leader, leader_runs)

    compare = chat.reply(
        "Compare Rohit and Kohli's strike rate when the required rate was above 8", history=[]
    ).query_response
    rates = {row[0]: row[1] for row in compare.tables[0].rows}
    assert rates["Rohit Sharma"] == 118.79
    kohli_runs, kohli_balls = _independent(db, "TRY_CAST(inns_rrr AS DOUBLE) > 8", batter="Virat Kohli")
    assert rates["Virat Kohli"] == round(kohli_runs * 100 / kohli_balls, 2)


def test_predicate_applies_inside_matchups_and_splits(repository, db) -> None:
    chat, _ = _chat(repository)
    rrr = "TRY_CAST(inns_rrr AS DOUBLE) > 7 AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0"
    matchup = chat.reply("Kohli strike rate vs Starc when required rate above 7", history=[]).query_response
    row = _row(matchup)
    runs, balls = _independent(db, rrr, batter="Virat Kohli", extra=" AND bowl = 'Mitchell Starc'")
    assert (row["Runs"], row["Balls"]) == (runs, balls)

    split = chat.reply(
        "Bumrah's economy in the powerplay vs death when the rrr was above 7", history=[]
    ).query_response
    assert _trace(split)["normalized_plan"]["filters"]["required_run_rate"] == {"operator": "gt", "value": 7}
    samples = dict(zip(split.tables[0].columns, split.tables[0].rows[0]))
    powerplay_legal = db.execute(
        "SELECT SUM(CASE WHEN wide = '0' AND noball = '0' THEN 1 ELSE 0 END) FROM analytics.deliveries_v1 "
        "WHERE bowl = 'Jasprit Bumrah' AND TRY_CAST(over AS DOUBLE) <= 10 AND " + rrr
    ).fetchone()[0]
    assert samples["Powerplay Sample"] == powerplay_legal


# --- follow-ups --------------------------------------------------------------------


def test_follow_ups_replace_tighten_and_remove_the_threshold(repository, db) -> None:
    chat, _ = _chat(repository, SAVED_TRACER_EXTRACTION)
    first = chat.reply(TRACER, history=[])
    follow_chat, client = _chat(repository)

    replaced = follow_chat.reply("What about above 10?", history=[], conversation_state=first.conversation_state)
    plan = _trace(replaced.query_response)["normalized_plan"]
    assert plan["metric"] == "batting_strike_rate"
    assert plan["filters"] == {"batter": "Rohit Sharma", "required_run_rate": {"operator": "gt", "value": 10}}
    row = _row(replaced.query_response)
    assert (row["Runs Scored"], row["Balls Faced"]) == _independent(db, "TRY_CAST(inns_rrr AS DOUBLE) > 10")

    tightened = follow_chat.reply("And at least 9?", history=[], conversation_state=replaced.conversation_state)
    plan = _trace(tightened.query_response)["normalized_plan"]
    assert plan["filters"]["required_run_rate"] == {"operator": "gte", "value": 9}
    # "at least 9" restates the threshold; it is not a 9-ball minimum sample.
    assert plan["minimum_sample_explicit"] is False

    scoped = follow_chat.reply("And in 2019?", history=[], conversation_state=tightened.conversation_state)
    assert _trace(scoped.query_response)["normalized_plan"]["filters"] == {
        "batter": "Rohit Sharma",
        "required_run_rate": {"operator": "gte", "value": 9},
        "years": [2019],
    }

    named = follow_chat.reply(
        "What about when the RRR was below 6?", history=[], conversation_state=scoped.conversation_state
    )
    assert _trace(named.query_response)["normalized_plan"]["filters"]["required_run_rate"] == {
        "operator": "lt",
        "value": 6,
    }

    removed = follow_chat.reply(
        "Without the required rate filter?", history=[], conversation_state=named.conversation_state
    )
    plan = _trace(removed.query_response)["normalized_plan"]
    assert plan["filters"] == {"batter": "Rohit Sharma", "years": [2019]}
    assert plan["metric"] == "batting_strike_rate"
    assert not any(note.title == "Required run rate filter" for note in removed.query_response.evidence_notes)
    assert client.calls == 0


def test_unregistered_follow_up_condition_is_not_silently_ignored(repository) -> None:
    chat, _ = _chat(repository, SAVED_TRACER_EXTRACTION)
    first = chat.reply(TRACER, history=[])
    follow_chat, _ = _chat(repository)
    reply = follow_chat.reply(
        "And when the target was above 300?", history=[], conversation_state=first.conversation_state
    )
    assert reply.mode == "clarification"
    assert "Filtering by target" in reply.message


# --- compatibility ----------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Rank teams by the gap between powerplay and death-over run rate.",
        "Which team changes run rate most from powerplay to death?",
        "Give six highest strike rates after over 40, 90-ball floor.",
        "Four most economical bowlers in overs 11-40 with at least 300 legal deliveries?",
        "How expensive is Bumrah from over 41 onwards?",
        "Who scored most runs in successful ODI chases?",
    ],
)
def test_questions_without_a_match_state_condition_are_untouched(question) -> None:
    assert match_state_mentions(question) == []
    assert strip_match_state_phrases(question) == question.lower()
