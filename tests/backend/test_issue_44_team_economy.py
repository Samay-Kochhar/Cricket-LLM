"""Issue 44: bowling-team economy rankings with explicit team roles.

Expected numbers are recomputed with independent read-only SQL over
``analytics.deliveries_v1`` (plain ``team_bowl``/``team_bat`` grouping), written
separately from the application builders.
"""

from __future__ import annotations

import json

import duckdb
import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, SortSpec
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.evidence_models import EvidenceStatus
from tests.backend.test_issue_41_required_run_rate import _chat

TRACER = "Which bowling team has the lowest economy against India?"
EXPLICIT_600 = "Which bowling team has the lowest economy against India, with at least 600 balls?"
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


def _rows(response) -> list[dict[str, object]]:
    table = response.tables[0]
    return [dict(zip(table.columns, row)) for row in table.rows]


def _note(response) -> str:
    return next(note.detail for note in response.evidence_notes if note.title == "Team metric definition")


def _team_economy(db, where: str = "1 = 1", minimum: int = 60, order: str = "ASC", limit: int = 3):
    return db.execute(
        f"""
        SELECT team_bowl,
               SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs,
               SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) AS legal_balls
        FROM analytics.deliveries_v1
        WHERE {where}
        GROUP BY team_bowl
        HAVING SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) >= {minimum}
        ORDER BY 6.0 * SUM(TRY_CAST(bowlruns AS INTEGER)) / SUM(CASE WHEN {LEGAL} THEN 1 ELSE 0 END) {order}
        LIMIT {limit}
        """
    ).fetchall()


def _ask(repository, question: str):
    chat, client = _chat(repository)
    reply = chat.reply(question, history=[])
    return reply, client


# --- tracer --------------------------------------------------------------------


def test_tracer_returns_zimbabwe_with_the_displayed_default_qualification(repository, db) -> None:
    expected = _team_economy(db, "team_bat = 'India'")
    assert expected[0] == ("Zimbabwe", 4099, 4743)
    reply, client = _ask(repository, TRACER)
    response = reply.query_response
    assert client.calls == 0, "registered team metrics never call the model"
    plan = _plan(response)
    assert plan["operation"] == "aggregate"
    assert plan["entity"] == "team"
    assert plan["metric"] == "economy_rate"
    assert plan["group_by"] == ["bowling_team"]
    assert plan["filters"] == {"batting_team": "India"}
    assert plan["sort"] == {"by": "economy_rate", "direction": "asc"}
    assert plan["minimum_sample"]["legal_balls"] == 60
    assert plan["minimum_sample_explicit"] is False
    top = _rows(response)[0]
    assert (top["Bowling Team"], top["Economy Rate"], top["Runs Conceded"], top["Legal Balls"]) == (
        "Zimbabwe",
        5.19,
        4099,
        4743,
    )
    summary = response.summaries[0].body
    assert "Against India batting" in summary
    assert "default minimum of 60 legal balls" in summary
    assert "Zimbabwe ranks first" in summary and "5.19" in summary
    note = _note(response)
    assert "documented default" in note and "not a user-provided threshold" in note
    assert "Batting opposition: India" in note


def test_explicit_600_ball_threshold_is_applied_and_shown(repository, db) -> None:
    expected = _team_economy(db, "team_bat = 'India'", minimum=600)
    assert expected[0] == ("Zimbabwe", 4099, 4743)
    reply, _ = _ask(repository, EXPLICIT_600)
    response = reply.query_response
    plan = _plan(response)
    assert plan["minimum_sample"]["legal_balls"] == 600
    assert plan["minimum_sample_explicit"] is True
    rows = _rows(response)
    assert [(row["Bowling Team"], row["Runs Conceded"], row["Legal Balls"]) for row in rows[:3]] == expected
    assert all(row["Legal Balls"] >= 600 for row in rows)
    assert "minimum sample of 600 legal balls" in response.summaries[0].body
    assert "default" not in response.summaries[0].body
    assert "as requested" in _note(response)


def test_completeness_accounts_for_team_role_opposition_direction_and_threshold(repository) -> None:
    reply, _ = _ask(repository, EXPLICIT_600)
    completeness = _trace(reply.query_response)["completeness_result"]
    assert completeness["complete"] is True
    targets = {fact["canonical_target"]: fact for fact in completeness["facts"]}
    assert targets["group_by.bowling_team"]["disposition"] == "compiled"
    assert targets["filter.batting_team"]["requested"] == "India"
    assert targets["sort.direction"]["requested"] == "asc"
    assert targets["minimum_sample.legal_balls"]["requested"] == {"legal_balls": 600}
    assert targets["minimum_sample.legal_balls"]["disposition"] == "compiled"

    default = _trace(_ask(repository, TRACER)[0].query_response)["completeness_result"]
    threshold = next(fact for fact in default["facts"] if fact["concept"] == "minimum_sample")
    assert threshold["disposition"] == "default_applied"


# --- direction, forms and composition --------------------------------------------------


@pytest.mark.parametrize(
    ("question", "order"),
    [
        (TRACER, "ASC"),
        ("Which bowling team has the best economy against India?", "ASC"),
        ("Which bowling side is most economical against India?", "ASC"),
        ("Which bowling team has the highest economy against India?", "DESC"),
        ("Which bowling team has the worst economy against India?", "DESC"),
        ("Which bowling attack is most expensive against India?", "DESC"),
    ],
)
def test_direction_follows_lowest_best_and_highest_worst(repository, db, question, order) -> None:
    reply, _ = _ask(repository, question)
    plan = _plan(reply.query_response)
    assert plan["sort"]["direction"] == order.lower()
    expected = _team_economy(db, "team_bat = 'India'", order=order, limit=1)[0]
    assert _rows(reply.query_response)[0]["Bowling Team"] == expected[0]


def test_global_and_opposition_forms_share_the_capability(repository, db) -> None:
    reply, _ = _ask(repository, "Which bowling team has the lowest economy?")
    plan = _plan(reply.query_response)
    assert plan["group_by"] == ["bowling_team"] and plan["filters"] == {}
    expected = _team_economy(db, limit=1)[0]
    top = _rows(reply.query_response)[0]
    assert (top["Bowling Team"], top["Runs Conceded"], top["Legal Balls"]) == expected


@pytest.mark.parametrize(
    ("question", "filters", "where"),
    [
        (
            "Which bowling side is most economical against India in 2019?",
            {"batting_team": "India", "years": [2019]},
            "team_bat = 'India' AND year = '2019'",
        ),
        (
            "Top 3 bowling teams by economy against India in the powerplay",
            {"batting_team": "India", "phase": "powerplay"},
            "team_bat = 'India' AND TRY_CAST(over AS DOUBLE) <= 10",
        ),
        (
            "Rank bowling teams by economy against Australia at Lord's",
            {"batting_team": "Australia", "venue": "Lord's, London"},
            "team_bat = 'Australia' AND ground = 'Lord''s, London'",
        ),
    ],
)
def test_filters_compose_with_the_team_roles(repository, db, question, filters, where) -> None:
    reply, _ = _ask(repository, question)
    assert _plan(reply.query_response)["filters"] == filters
    expected = _team_economy(db, where, limit=1)[0]
    top = _rows(reply.query_response)[0]
    assert (top["Bowling Team"], top["Runs Conceded"], top["Legal Balls"]) == expected


def test_limit_is_retained(repository) -> None:
    reply, _ = _ask(repository, "Top 3 bowling teams by economy against India in the powerplay")
    assert _plan(reply.query_response)["limit"] == 3
    assert len(_rows(reply.query_response)) == 3


def test_team_names_resolve_as_roles_not_players(repository) -> None:
    reply, _ = _ask(repository, "Which bowling attack concedes the fewest runs per over against India?")
    plan = _plan(reply.query_response)
    assert plan["entity"] == "team"
    assert plan["filters"] == {"batting_team": "India"}
    assert "bowler" not in plan["filters"] and "batter" not in plan["filters"]


# --- fail-closed and evidence states ------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        (
            "Which team concedes the lowest innings run rate against India?",
            "Opposition innings run rate",
        ),
        ("Which team has the highest run rate in death overs?", "Team run rate is not a registered team metric"),
        (
            "Which bowling team has the lowest economy against India and Australia?",
            "More than one opposition",
        ),
    ],
)
def test_unregistered_team_requests_fail_closed_with_the_reason(repository, question, fragment) -> None:
    reply, client = _ask(repository, question)
    assert client.calls == 0
    assert reply.query_response.status != EvidenceStatus.supported
    assert fragment in reply.query_response.summaries[0].body


def test_batting_team_with_a_bowling_metric_asks_which_role(repository) -> None:
    reply, _ = _ask(repository, "Which batting team has the lowest economy?")
    assert reply.mode == "clarification"
    assert "bowling side" in reply.message


def test_insufficient_sample_returns_insufficient_evidence(repository) -> None:
    reply, _ = _ask(repository, "Which bowling team has the lowest economy against India, at least 99999 balls?")
    assert reply.query_response.status == EvidenceStatus.insufficient_evidence


def test_other_policy_outcomes_keep_precedence(repository) -> None:
    reply, _ = _ask(repository, "Which team will win the next world cup?")
    assert "prediction" in reply.message.lower()


# --- validation and regression ----------------------------------------------------------


def _team_plan(**updates) -> CricketQueryPlan:
    base = dict(
        operation="aggregate",
        entity="team",
        metric="economy_rate",
        group_by=["bowling_team"],
        filters={"batting_team": "India"},
        sort=SortSpec(by="economy_rate", direction="asc"),
        limit=10,
        minimum_sample=MinimumSampleSpec(legal_balls=60),
        question_subject="team_ranking",
    )
    base.update(updates)
    return CricketQueryPlan(**base)


def test_validator_enforces_registered_team_roles() -> None:
    assert validate_plan(_team_plan(), TRACER).valid
    assert not validate_plan(_team_plan(group_by=["batting_team"]), TRACER).valid
    assert not validate_plan(_team_plan(filters={"opposition": "India"}), TRACER).valid
    assert not validate_plan(_team_plan(minimum_sample=None), TRACER).valid
    assert not validate_plan(_team_plan(filters={"batting_team": "India", "bowler": "Jasprit Bumrah"}), TRACER).valid
    # A bowler-owned metric on a team entity is only valid through its registered role.
    assert not validate_plan(_team_plan(metric="bowling_average"), TRACER).valid


def test_player_economy_answers_are_unchanged(repository) -> None:
    reply, _ = _ask(repository, "Lowest economy against India, top 5 bowlers")
    plan = _plan(reply.query_response)
    assert plan["entity"] == "bowler"
    assert plan["group_by"] == ["bowler"]
    assert plan["filters"] == {"opposition": "India"}
    assert all(note.title != "Team metric definition" for note in reply.query_response.evidence_notes)


def test_team_run_rate_split_is_unchanged(repository) -> None:
    reply, _ = _ask(repository, "Compare team run rates in powerplay versus death overs")
    plan = _plan(reply.query_response)
    assert plan["operation"] == "split_compare" and plan["entity"] == "team"
