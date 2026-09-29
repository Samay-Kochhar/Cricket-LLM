"""Issue 43: one-player splits by the recorded match-lighting category.

Every expected number is recomputed with independent read-only SQL over
``analytics.deliveries_v1`` (plain ``daynight = ...`` comparisons), written
separately from the application builders.
"""

from __future__ import annotations

import json

import duckdb
import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.match_lighting import (
    LIGHTING_VALUES,
    casual_night_used,
    lighting_clause,
    lighting_problem,
    requested_lighting_values,
)
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.evidence_models import EvidenceStatus
from tests.backend.test_issue_41_required_run_rate import _chat

TRACER = "Compare Bumrah's economy in day versus night matches."

# The saved production Flash extraction for the tracer (priority-8 capture).
SAVED_TRACER_EXTRACTION = {
    "version": 1,
    "family": "comparison",
    "entities": [{"kind": "player", "name": "Bumrah", "relationship": "subject", "role": "bowler"}],
    "metric_concept": "economy",
    "role": None,
    "breakdown_dimensions": [],
    "split_dimensions": ["day_night_condition"],
    "filters": [
        {
            "concept": "day_night_condition",
            "evidence": "day versus night matches",
            "values": ["day", "night"],
        }
    ],
    "intent": "comparison",
    "ordering": None,
    "limit": None,
    "sample_threshold": None,
    "ambiguity_candidates": [],
}

LEGAL = "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"


@pytest.fixture(scope="module")
def repository() -> AnalyticsRepository:
    return AnalyticsRepository(AppConfig.from_env().duckdb_path)


@pytest.fixture(scope="module")
def db() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(AppConfig.from_env().duckdb_path), read_only=True)


def _trace(response) -> dict:
    return json.loads(
        next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace")
    )


def _plan(response) -> dict:
    return _trace(response)["normalized_plan"]


def _table(response, title: str) -> list[dict[str, object]]:
    table = next(table for table in response.tables if table.title == title)
    return [dict(zip(table.columns, row)) for row in table.rows]


def _note(response) -> str:
    return next(note.detail for note in response.evidence_notes if note.title == "Match lighting")


def _bowler_economy(db, bowler: str, lighting: str, extra: str = "") -> tuple[int, int]:
    runs, balls = db.execute(
        f"""
        SELECT COALESCE(SUM(TRY_CAST(bowlruns AS INTEGER)), 0),
               COALESCE(SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END), 0)
        FROM analytics.deliveries_v1
        WHERE bowl = ? AND daynight = ? {extra}
        """,
        [bowler, lighting],
    ).fetchone()
    return int(runs), int(balls)


def _batter_runs_balls(db, batter: str, where: str) -> tuple[int, int]:
    runs, balls = db.execute(
        f"""
        SELECT SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END),
               SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END)
        FROM analytics.deliveries_v1 WHERE bat = ? AND {where}
        """,
        [batter],
    ).fetchone()
    return int(runs), int(balls)


# --- tracer --------------------------------------------------------------------


def _assert_tracer(response, db) -> None:
    day = _bowler_economy(db, "Jasprit Bumrah", "day match")
    day_night = _bowler_economy(db, "Jasprit Bumrah", "day/night match")
    assert day == (1055, 1487)
    assert day_night == (2454, 3093)
    assert round(6 * day[0] / day[1], 2) == 4.26
    assert round(6 * day_night[0] / day_night[1], 2) == 4.76

    plan = _plan(response)
    assert plan["operation"] == "split_compare"
    assert plan["entity"] == "bowler"
    assert plan["metric"] == "economy_rate"
    assert plan["filters"] == {"bowler": "Jasprit Bumrah"}
    assert plan["split_by"] == "match_lighting"
    assert plan["compare_values"] == ["day match", "day/night match"]
    assert response.status == EvidenceStatus.supported

    evidence = _table(response, "Recorded match-lighting evidence")
    assert [
        (row["Match Lighting"], row["Economy Rate"], row["Runs Conceded"], row["Legal Balls"])
        for row in evidence
    ] == [("day match", 4.26, 1055, 1487), ("day/night match", 4.76, 2454, 3093)]
    summary = response.summaries[0].body
    assert "Day Match 4.26" in summary and "Day/Night Match 4.76" in summary
    note = _note(response)
    assert "'day/night match'" in note
    assert "not evidence that every delivery was bowled at night" in note
    assert "Casual 'night' wording" in note


def test_tracer_from_the_saved_flash_extraction(repository, db) -> None:
    chat, client = _chat(repository, SAVED_TRACER_EXTRACTION)
    response = chat.reply(TRACER, history=[]).query_response
    _assert_tracer(response, db)
    assert client.calls == 1
    completeness = _trace(response)["completeness_result"]
    assert completeness["complete"] is True
    lighting_facts = [
        fact for fact in completeness["facts"] if fact["concept"] == "day_night_condition"
    ]
    assert {fact["fact_type"] for fact in lighting_facts} == {"dimension", "filter", "value"}
    assert all(fact["disposition"] == "compiled" for fact in lighting_facts)
    assert all(fact["canonical_target"] == "dimension.match_lighting" for fact in lighting_facts)


def test_tracer_without_a_model_compiles_the_same_meaning(repository, db) -> None:
    chat, _ = _chat(repository)
    _assert_tracer(chat.reply(TRACER, history=[]).query_response, db)


def test_registered_values_are_the_literal_stored_labels(db) -> None:
    stored = {
        row[0]
        for row in db.execute(
            "SELECT DISTINCT CAST(daynight AS VARCHAR) FROM analytics.deliveries_v1"
        ).fetchall()
    }
    assert stored == set(LIGHTING_VALUES)
    # One value per match; no null or conflicting categories.
    assert db.execute(
        "SELECT COUNT(*) FROM (SELECT p_match FROM analytics.deliveries_v1 "
        "GROUP BY p_match HAVING COUNT(DISTINCT COALESCE(CAST(daynight AS VARCHAR), '<null>')) > 1)"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM analytics.deliveries_v1 WHERE daynight IS NULL"
    ).fetchone()[0] == 0


# --- language ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "values", "casual"),
    [
        (TRACER, ["day match", "day/night match"], True),
        ("Bumrah economy in night vs day games", ["day/night match", "day match"], True),
        ("Bumrah economy in day/night matches", ["day/night match"], False),
        ("Bumrah economy in day-night ODIs", ["day/night match"], False),
        ("Bumrah day/night vs night matches", ["day/night match", "night match"], False),
        ("Bumrah economy in pure night matches versus day matches", ["night match", "day match"], False),
        ("Bumrah economy in night-only matches", ["night match"], False),
        ("Kohli strike rate at night", ["day/night match"], True),
        ("Kohli runs in daytime matches", ["day match"], False),
        ("Kohli one-day runs", [], False),
        ("Kohli runs in one day internationals", [], False),
        ("Kohli's runs on the first day of the tour", [], False),
    ],
)
def test_lighting_language_is_parsed_deterministically(question, values, casual) -> None:
    assert requested_lighting_values(question) == values
    assert casual_night_used(question) is casual


@pytest.mark.parametrize(
    "question",
    [
        TRACER,
        "Compare Bumrah's economy in night versus day matches.",
        "How does Bumrah's economy in night games compare with day games?",
        "Bumrah economy: day matches vs night matches",
        "Bumrah's economy rate in day compared with night ODIs",
    ],
)
def test_one_player_split_never_asks_for_a_second_player(repository, question) -> None:
    chat, _ = _chat(repository)
    reply = chat.reply(question, history=[])
    assert reply.mode == "analysis"
    plan = _plan(reply.query_response)
    assert plan["operation"] == "split_compare"
    assert plan["split_by"] == "match_lighting"
    assert set(plan["compare_values"]) == {"day match", "day/night match"}
    evidence = {
        row["Match Lighting"]: row["Economy Rate"]
        for row in _table(reply.query_response, "Recorded match-lighting evidence")
    }
    assert evidence == {"day match": 4.26, "day/night match": 4.76}


def test_explicit_pure_night_returns_insufficient_evidence_without_substitution(repository, db) -> None:
    assert _bowler_economy(db, "Jasprit Bumrah", "night match") == (0, 0)
    chat, _ = _chat(repository)
    response = chat.reply(
        "Compare Bumrah's economy in pure night matches versus day matches", history=[]
    ).query_response
    plan = _plan(response)
    assert plan["compare_values"] == ["night match", "day match"]
    assert response.status == EvidenceStatus.insufficient_evidence
    assert "Night Match has 0 balls" in response.summaries[0].body
    evidence = {row["Match Lighting"]: row for row in _table(response, "Recorded match-lighting evidence")}
    assert evidence["night match"]["Legal Balls"] == 0
    assert evidence["day match"]["Legal Balls"] == 1487
    note = _note(response)
    assert "'night match'" in note and "Casual" not in note


def test_explicit_day_night_wording_has_no_casual_disclosure(repository) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(
        "Compare Bumrah's economy in day matches versus day/night matches", history=[]
    ).query_response
    assert _plan(response)["compare_values"] == ["day match", "day/night match"]
    note = _note(response)
    assert "Casual" not in note
    assert "not evidence that every delivery was bowled at night" in note


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Compare Bumrah's economy in day matches versus floodlit matches", "'floodlit' is not a recorded category"),
        ("Bumrah's economy under lights", "'under lights' is not a recorded category"),
        ("Compare Bumrah's economy in day, day/night and pure night matches", "more than two"),
    ],
)
def test_unrecorded_or_too_many_categories_fail_closed(repository, question, fragment) -> None:
    assert lighting_problem(question) is not None
    chat, _ = _chat(repository)
    reply = chat.reply(question, history=[])
    text = reply.message if reply.query_response is None else reply.query_response.summaries[0].body
    assert fragment in text


def test_malformed_values_never_widen_scope() -> None:
    assert lighting_clause("night") == ("1 = 0", [])
    assert lighting_clause(None) == ("1 = 0", [])
    assert lighting_clause("day match") == ("CAST(daynight AS VARCHAR) = ?", ["day match"])


# --- composition -----------------------------------------------------------------


def test_filter_form_uses_the_same_economy_definition(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply("Bumrah's economy in day/night matches", history=[]).query_response
    plan = _plan(response)
    assert plan["operation"] == "aggregate"
    assert plan["filters"] == {"bowler": "Jasprit Bumrah", "match_lighting": "day/night match"}
    row = _table(response, "Semantic aggregate result")[0]
    assert (row["Runs Conceded"], row["Legal Balls"], row["Economy Rate"]) == (2454, 3093, 4.76)
    assert response.summaries[0].body.startswith("In recorded day/night matches")


def test_batter_metrics_split_by_lighting(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(
        "Kohli's strike rate in day matches versus day/night matches", history=[]
    ).query_response
    assert _plan(response)["entity"] == "batter"
    evidence = {row["Match Lighting"]: row for row in _table(response, "Recorded match-lighting evidence")}
    for label in ("day match", "day/night match"):
        runs, balls = _batter_runs_balls(db, "Virat Kohli", f"daynight = '{label}'")
        assert (evidence[label]["Runs Scored"], evidence[label]["Balls Faced"]) == (runs, balls)
        assert evidence[label]["Batting Strike Rate"] == round(100 * runs / balls, 2)


def test_other_families_keep_the_lighting_filter(repository, db) -> None:
    chat, _ = _chat(repository)
    matchup = chat.reply("Kohli vs Starc in day/night matches", history=[]).query_response
    assert _plan(matchup)["filters"]["match_lighting"] == "day/night match"
    runs, balls = db.execute(
        "SELECT SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END), "
        "SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) FROM analytics.deliveries_v1 "
        "WHERE bat = 'Virat Kohli' AND bowl = 'Mitchell Starc' AND daynight = 'day/night match'"
    ).fetchone()
    assert f"{runs} runs from {balls} balls" in matchup.summaries[0].body

    comparison = chat.reply(
        "Compare Kohli and Rohit strike rate in day/night matches", history=[]
    ).query_response
    assert _plan(comparison)["filters"]["match_lighting"] == "day/night match"
    rohit = _batter_runs_balls(db, "Rohit Sharma", "daynight = 'day/night match'")
    assert f"{round(100 * rohit[0] / rohit[1], 2)}" in comparison.summaries[0].body

    dismissals = chat.reply(
        "How often was Kohli dismissed caught versus bowled in day/night matches?", history=[]
    ).query_response
    assert _plan(dismissals)["filters"]["match_lighting"] == "day/night match"
    counts = dict(
        db.execute(
            "SELECT dismissal, COUNT(*) FROM analytics.deliveries_v1 WHERE p_out = "
            "(SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat = 'Virat Kohli') "
            "AND daynight = 'day/night match' AND dismissal IN ('caught', 'bowled') GROUP BY 1"
        ).fetchall()
    )
    body = dismissals.summaries[0].body
    assert f"caught {counts['caught']} times" in body and f"bowled {counts['bowled']} times" in body


def test_opposition_composes_with_the_split(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(
        "Compare Bumrah's economy in day versus night matches against Australia", history=[]
    ).query_response
    plan = _plan(response)
    assert plan["filters"] == {"bowler": "Jasprit Bumrah", "opposition": "Australia"}
    assert plan["split_by"] == "match_lighting"
    evidence = {row["Match Lighting"]: row for row in _table(response, "Recorded match-lighting evidence")}
    for label in ("day match", "day/night match"):
        runs, balls = _bowler_economy(db, "Jasprit Bumrah", label, "AND team_bat = 'Australia'")
        assert (evidence[label]["Runs Conceded"], evidence[label]["Legal Balls"]) == (runs, balls)


# --- follow-ups --------------------------------------------------------------------


def test_follow_ups_replace_add_and_remove_the_lighting_filter(repository, db) -> None:
    chat, _ = _chat(repository)
    first = chat.reply("Bumrah's economy in day/night matches", history=[])
    day = chat.reply("What about day matches?", history=[], conversation_state=first.conversation_state)
    assert _plan(day.query_response)["filters"] == {
        "bowler": "Jasprit Bumrah",
        "match_lighting": "day match",
    }
    removed = chat.reply(
        "Remove the lighting filter", history=[], conversation_state=day.conversation_state
    )
    assert _plan(removed.query_response)["filters"] == {"bowler": "Jasprit Bumrah"}
    assert _table(removed.query_response, "Semantic aggregate result")[0]["Legal Balls"] == 1487 + 3093

    phase = chat.reply("Compare Bumrah's economy in powerplay versus death overs", history=[])
    narrowed = chat.reply(
        "Only in day/night matches", history=[], conversation_state=phase.conversation_state
    )
    plan = _plan(narrowed.query_response)
    assert plan["split_by"] == "phase"
    assert plan["filters"] == {"bowler": "Jasprit Bumrah", "match_lighting": "day/night match"}


def test_split_follow_up_changes_metric_and_keeps_the_categories(repository) -> None:
    chat, _ = _chat(repository)
    first = chat.reply(TRACER, history=[])
    dots = chat.reply(
        "What about his dot ball percentage?", history=[], conversation_state=first.conversation_state
    )
    plan = _plan(dots.query_response)
    assert plan["metric"] == "bowler_dot_ball_percentage"
    assert plan["split_by"] == "match_lighting"
    assert plan["compare_values"] == ["day match", "day/night match"]


# --- validation ----------------------------------------------------------------------


def _split_plan(**updates) -> CricketQueryPlan:
    base = dict(
        operation="split_compare",
        entity="bowler",
        metric="economy_rate",
        group_by=["bowler"],
        filters={"bowler": "Jasprit Bumrah"},
        split_by="match_lighting",
        compare_values=["day match", "day/night match"],
        sort=SortSpec(by="economy_rate", direction="asc"),
    )
    base.update(updates)
    return CricketQueryPlan(**base)


def test_validator_rejects_plans_that_drop_or_change_categories() -> None:
    assert validate_plan(_split_plan(), TRACER).valid
    changed = validate_plan(_split_plan(compare_values=["day match", "night match"]), TRACER)
    assert not changed.valid
    dropped = validate_plan(
        _split_plan(split_by="phase", compare_values=["powerplay", "death"]), TRACER
    )
    assert not dropped.valid
    aggregate = CricketQueryPlan(
        operation="aggregate",
        entity="bowler",
        metric="economy_rate",
        group_by=["bowler"],
        filters={"bowler": "Jasprit Bumrah"},
        sort=SortSpec(by="economy_rate", direction="asc"),
    )
    missing_filter = validate_plan(aggregate, "Bumrah's economy in day/night matches")
    assert not missing_filter.valid
    malformed = validate_plan(
        aggregate.model_copy(update={"filters": {"bowler": "Jasprit Bumrah", "match_lighting": "night"}}),
        "Bumrah's economy",
    )
    assert not malformed.valid


def test_existing_split_answers_are_unchanged(repository) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(
        "Compare Bumrah's economy in powerplay versus death overs", history=[]
    ).query_response
    plan = _plan(response)
    assert plan["split_by"] == "phase" and plan["compare_values"] == ["powerplay", "death"]
    assert "Powerplay 3.96" in response.summaries[0].body
    assert all(table.title != "Recorded match-lighting evidence" for table in response.tables)
    assert all(note.title != "Match lighting" for note in response.evidence_notes)
