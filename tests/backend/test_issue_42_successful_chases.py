"""Issue 42: batter statistics and rankings in successful ODI chases.

Every expected number is recomputed with independent read-only SQL written
separately from the application builder (plain ``inns = '2'`` and
``winner = team_bat`` comparisons over ``analytics.deliveries_v1``).
"""

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
from backend.app.cricket_analytics.match_result_conditions import (
    BATTING_RESULT_FILTER,
    batting_result_clause,
    removes_result_condition,
    requested_result_filters,
    result_condition_problem,
)
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.query_builders.aggregate_builder import (
    build_aggregate_query,
)
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec
from backend.app.db.repository import AnalyticsRepository
from tests.backend.test_issue_41_required_run_rate import _chat

TRACER = "Who scored most runs in successful ODI chases?"

# The saved production Flash extraction for the tracer (priority-8 capture).
SAVED_TRACER_EXTRACTION = {
    "version": 1,
    "family": "ranking",
    "entities": [],
    "metric_concept": "runs",
    "role": "batter",
    "breakdown_dimensions": [],
    "split_dimensions": [],
    "filters": [
        {"concept": "match_type", "evidence": "odi", "values": ["odi"]},
        {"concept": "innings_outcome", "evidence": "successful", "values": ["win"]},
        {"concept": "innings_type", "evidence": "chases", "values": ["chase"]},
    ],
    "intent": "ranking",
    "ordering": "highest",
    "limit": None,
    "sample_threshold": None,
    "ambiguity_candidates": [],
}

WON = "inns = '2' AND winner = team_bat"
LOST = "inns = '2' AND winner = team_bowl"


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


def _trace(response) -> dict:
    return json.loads(
        next(note.detail for note in response.evidence_notes if note.title == "Semantic V2 trace")
    )


def _plan(response) -> dict:
    return _trace(response)["normalized_plan"]


def _rows(response) -> list[dict[str, object]]:
    table = response.tables[0]
    return [dict(zip(table.columns, row)) for row in table.rows]


def _note(response, prefix: str = "Successful chase condition") -> str:
    return next(note.detail for note in response.evidence_notes if note.title == prefix)


def _batter_runs(db, where: str, params: list | None = None, limit: int = 5) -> list[tuple]:
    return db.execute(
        f"""
        SELECT bat,
               SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END) AS runs,
               SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) AS balls
        FROM analytics.deliveries_v1
        WHERE {where}
        GROUP BY bat
        ORDER BY runs DESC, balls DESC, bat
        LIMIT {limit}
        """,
        params or [],
    ).fetchall()


def _team_innings(db, where: str, params: list | None = None) -> int:
    return int(
        db.execute(
            "SELECT COUNT(DISTINCT p_match || ':' || inns) FROM analytics.deliveries_v1 "
            f"WHERE {where}",
            params or [],
        ).fetchone()[0]
    )


# --- tracer --------------------------------------------------------------------


def test_tracer_ranks_kohli_first_with_5791_from_the_saved_flash_extraction(repository, db) -> None:
    chat, client = _chat(repository, SAVED_TRACER_EXTRACTION)
    response = chat.reply(TRACER, history=[]).query_response

    expected = _batter_runs(db, WON)
    assert expected[0][:2] == ("Virat Kohli", 5791)
    assert expected[1][:2] == ("Rohit Sharma", 4415)
    rows = _rows(response)
    assert [(row["Batter"], row["Runs Scored"]) for row in rows[:5]] == [
        (name, runs) for name, runs, _ in expected
    ]
    plan = _plan(response)
    assert plan["operation"] == "aggregate"
    assert plan["entity"] == "batter"
    assert plan["metric"] == "runs_scored"
    assert plan["group_by"] == ["batter"]
    assert plan["filters"] == {"innings": 2, "batting_result": "won"}
    assert plan["sort"] == {"by": "runs_scored", "direction": "desc"}
    assert plan["limit"] == 10
    assert client.calls == 1
    summary = response.summaries[0].body
    assert summary.startswith("In successful chases (second innings won by the batting side)")
    assert "Virat Kohli ranks first" in summary and "5791" in summary


def test_tracer_without_a_model_compiles_the_same_meaning(repository) -> None:
    chat, client = _chat(repository)
    response = chat.reply(TRACER, history=[]).query_response
    assert _plan(response)["filters"] == {"innings": 2, "batting_result": "won"}
    assert _rows(response)[0]["Runs Scored"] == 5791
    assert client.calls == 0


def test_completeness_accounts_for_chase_innings_and_winning_outcome_separately(repository) -> None:
    chat, _ = _chat(repository, SAVED_TRACER_EXTRACTION)
    trace = _trace(chat.reply(TRACER, history=[]).query_response)
    completeness = trace["completeness_result"]
    assert completeness["allows_execution"] is True
    targets = {
        (fact["fact_type"], fact["concept"]): (fact["disposition"], fact["canonical_target"])
        for fact in completeness["facts"]
    }
    assert targets[("filter", "innings_outcome")] == ("compiled", "filter.batting_result")
    assert targets[("value", "innings_outcome")] == ("compiled", "filter.batting_result")
    assert targets[("filter", "innings_type")] == ("compiled", "filter.innings")
    assert targets[("value", "innings_type")] == ("compiled", "filter.innings")
    assert all(fact["disposition"] == "compiled" for fact in completeness["facts"])


def test_a_combined_chase_outcome_fact_is_split_into_two_accounted_conditions(resolver) -> None:
    candidate = LanguageMeaningCandidate.model_validate(
        {
            **SAVED_TRACER_EXTRACTION,
            "filters": [
                {
                    "concept": "chase_outcome",
                    "evidence": "successful ODI chases",
                    "values": ["successful"],
                }
            ],
        }
    )
    resolution = resolver.resolve_candidate(TRACER, None, candidate)
    assert resolution.status == MeaningStatus.resolved
    facts = [
        (fact.fact_type, fact.canonical_target, fact.disposition)
        for fact in resolution.completeness.facts
        if fact.fact_type == "filter"
    ]
    assert ("filter", "filter.innings", "compiled") in facts
    assert ("filter", "filter.batting_result", "compiled") in facts


def test_evidence_note_states_condition_policy_and_sample_scope(repository, db) -> None:
    chat, _ = _chat(repository)
    note = _note(chat.reply(TRACER, history=[]).query_response)
    won = _team_innings(db, WON)
    total = _team_innings(db, "inns = '2'")
    no_winner = _team_innings(db, "inns = '2' AND winner = '-'")
    unmatched = _team_innings(
        db, "inns = '2' AND winner <> '-' AND winner <> team_bat AND winner <> team_bowl"
    )
    rain = _team_innings(db, f"{WON} AND rain IN ('1', '9')")
    lost = _team_innings(db, LOST)
    assert (won, lost, no_winner, unmatched, total) == (1280, 1164, 60, 1, 2505)
    assert won + lost + no_winner + unmatched == total
    assert "second-innings deliveries in which the batting team equals the stored match winner" in note
    assert "Ties and no-results (stored winner '-')" in note
    assert (
        f"{won:,} successful chases out of {total:,} in-scope chases" in note
        and f"{no_winner:,} had no stored winner" in note
        and f"{unmatched:,} had a stored winner matching neither team" in note
        and f"{rain:,} of the included were rain-affected" in note
    )


# --- distinct canonical meanings ----------------------------------------------


@pytest.mark.parametrize(
    ("question", "filters", "where"),
    [
        ("Who scored most runs in ODI chases?", {"innings": 2}, "inns = '2'"),
        ("Most runs chasing", {"innings": 2}, "inns = '2'"),
        (TRACER, {"innings": 2, "batting_result": "won"}, WON),
        (
            "Who scored most runs in unsuccessful chases?",
            {"innings": 2, "batting_result": "lost"},
            LOST,
        ),
        ("Who scored most runs in ODI wins?", {"batting_result": "won"}, "winner = team_bat"),
        ("Who scored most runs in ODIs?", {}, "1 = 1"),
    ],
)
def test_chasing_successful_unsuccessful_and_unfiltered_stay_distinct(
    repository, db, question, filters, where
) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(question, history=[]).query_response
    assert _plan(response)["filters"] == filters
    expected = _batter_runs(db, where, limit=2)
    assert [(row["Batter"], row["Runs Scored"]) for row in _rows(response)[:2]] == [
        (name, runs) for name, runs, _ in expected
    ]


@pytest.mark.parametrize(
    "question",
    [
        "Who scored most runs in successful chases?",
        "Most runs in successful run chases",
        "Who has the most runs in winning chases?",
        "Most runs in chases that were won",
        "Most runs in chases they won",
        "Most runs in wins while chasing",
        "Who scored the most runs while successfully chasing?",
        "Most runs in targets chased down",
        "Leading run scorers in completed ODI chases",
    ],
)
def test_equivalent_successful_chase_phrasings_share_one_meaning(repository, question) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(question, history=[]).query_response
    plan = _plan(response)
    assert plan["filters"] == {"innings": 2, "batting_result": "won"}
    assert plan["metric"] == "runs_scored"
    assert _rows(response)[0]["Runs Scored"] == 5791


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("most runs in failed chases", {"innings": 2, "batting_result": "lost"}),
        ("runs in chases that ended in defeat", {"innings": 2, "batting_result": "lost"}),
        ("runs lost while chasing", {"innings": 2, "batting_result": "lost"}),
        ("Kohli runs in winning causes", {"batting_result": "won"}),
        ("Kohli runs when his team lost", {"batting_result": "lost"}),
        ("Kohli runs chasing", {}),
        ("Who has been the most successful batter in ODIs?", {}),
        ("Who won the toss in the 2019 World Cup final?", {}),
    ],
)
def test_result_language_is_parsed_deterministically(question, expected) -> None:
    assert requested_result_filters(question) == expected


# --- result policy ---------------------------------------------------------------


def test_ties_no_results_placeholder_winners_and_nonstandard_innings_policy(db) -> None:
    # Only innings 1 and 2 are stored; no super-over rows exist.
    assert {row[0] for row in db.execute("SELECT DISTINCT inns FROM analytics.deliveries_v1").fetchall()} == {"1", "2"}
    # 122 matches have no stored winner; 1 match stores a winner matching neither team.
    assert _team_innings(db, "winner = '-' AND inns = '1'") == 122
    placeholder = db.execute(
        "SELECT DISTINCT p_match, winner FROM analytics.deliveries_v1 "
        "WHERE winner <> '-' AND winner <> team_bat AND winner <> team_bowl"
    ).fetchall()
    assert placeholder == [("66387", "ICC World XI")]

    def scoped(result: str) -> int:
        clause, params = batting_result_clause(result)
        return int(
            db.execute(
                "SELECT COUNT(DISTINCT p_match) FROM analytics.deliveries_v1 "
                f"WHERE inns = '2' AND {clause}",
                params,
            ).fetchone()[0]
        )

    # Neither successful nor unsuccessful chases include a match with no stored
    # winner or with the unmatched placeholder winner.
    for result in ("won", "lost"):
        clause, params = batting_result_clause(result)
        assert db.execute(
            f"SELECT COUNT(*) FROM analytics.deliveries_v1 WHERE {clause} "
            "AND (winner = '-' OR p_match = '66387')",
            params,
        ).fetchone()[0] == 0
    assert scoped("won") == _team_innings(db, WON) == 1280
    assert scoped("lost") == _team_innings(db, LOST) == 1164
    # Rain-affected matches keep their stored result: 127 successful chases.
    rain_won = db.execute(
        f"SELECT COUNT(DISTINCT p_match) FROM analytics.deliveries_v1 WHERE {WON} AND rain IN ('1', '9')"
    ).fetchone()[0]
    assert rain_won == 127


@pytest.mark.parametrize("value", ["win", "WON", "", None, 1, ["won"], {"value": "won"}])
def test_malformed_result_values_never_widen_scope(value) -> None:
    assert batting_result_clause(value) == ("1 = 0", [])
    plan = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="runs_scored",
        group_by=["batter"],
        filters={"innings": 2, "batting_result": value},
        sort=SortSpec(by="runs_scored", direction="desc"),
    )
    assert not validate_plan(plan, "Most runs in chases").valid


def test_sql_is_registered_and_parameterised(db) -> None:
    plan = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="runs_scored",
        group_by=["batter"],
        filters={"innings": 2, "batting_result": "won"},
        sort=SortSpec(by="runs_scored", direction="desc"),
        limit=2,
    )
    build = build_aggregate_query(plan)
    assert "CAST(winner AS VARCHAR) = CAST(team_bat AS VARCHAR)" in build.sql
    assert "inns = ?" in build.sql
    rows = db.execute(build.sql, build.params).fetchall()
    assert [(row[0], row[6]) for row in rows] == [("Virat Kohli", 5791), ("Rohit Sharma", 4415)]


# --- composition ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "extra_filters", "where", "params"),
    [
        ("Kohli runs in successful chases", {"batter": "Virat Kohli"}, "bat = ?", ["Virat Kohli"]),
        (
            "Most runs in successful chases against Australia in 2019",
            {"opposition": "Australia", "years": [2019]},
            "team_bowl = ? AND year = ?",
            ["Australia", "2019"],
        ),
        (
            "Most runs in successful chases at Wankhede",
            {"venue": "Wankhede Stadium, Mumbai"},
            "ground = ?",
            ["Wankhede Stadium, Mumbai"],
        ),
        (
            "Most runs in successful chases in the death overs",
            {"phase": "death"},
            "TRY_CAST(over AS DOUBLE) > 40",
            [],
        ),
        (
            "Most runs in successful chases when required rate was above 8",
            {"required_run_rate": {"operator": "gt", "value": 8}},
            "TRY_CAST(inns_rrr AS DOUBLE) > 8 AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0",
            [],
        ),
    ],
)
def test_filters_compose_without_losing_the_chase_result_meaning(
    repository, db, question, extra_filters, where, params
) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(question, history=[]).query_response
    plan = _plan(response)
    assert plan["filters"] == {"innings": 2, "batting_result": "won", **extra_filters}
    expected = _batter_runs(db, f"{WON} AND {where}", params, limit=1)
    top = _rows(response)[0]
    assert (top["Batter"], top["Runs Scored"]) == expected[0][:2]
    assert "successful chases" in response.summaries[0].body


def test_batting_team_and_competition_compose_at_plan_level(db) -> None:
    plan = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="runs_scored",
        group_by=["batter"],
        filters={
            "innings": 2,
            "batting_result": "won",
            "batting_team": "India",
            "competition": "ICC Cricket World Cup",
        },
        sort=SortSpec(by="runs_scored", direction="desc"),
        limit=1,
    )
    assert validate_plan(plan, "Most runs in successful chases").valid
    build = build_aggregate_query(plan)
    row = db.execute(build.sql, build.params).fetchone()
    expected = _batter_runs(
        db, f"{WON} AND team_bat = 'India' AND competition = 'ICC Cricket World Cup'", limit=1
    )[0]
    assert (row[0], row[6]) == expected[:2]


@pytest.mark.parametrize(
    ("question", "expected_filter", "where"),
    [
        (
            "Most runs for India in successful chases",
            {"player_team": "India"},
            "team_bat = 'India'",
        ),
        (
            "Most runs by India's batters in successful chases",
            {"player_team": "India"},
            "team_bat = 'India'",
        ),
        (
            "Most runs against India in successful chases",
            {"opposition": "India"},
            "team_bowl = 'India'",
        ),
        (
            "Most runs for Australia against India in successful chases",
            {"player_team": "Australia", "opposition": "India"},
            "team_bat = 'Australia' AND team_bowl = 'India'",
        ),
    ],
)
def test_own_team_and_opposition_stay_distinct_under_the_condition(
    repository, db, question, expected_filter, where
) -> None:
    chat, _ = _chat(repository)
    response = chat.reply(question, history=[]).query_response
    plan = _plan(response)
    assert plan["filters"] == {"innings": 2, "batting_result": "won", **expected_filter}
    expected = _batter_runs(db, f"{WON} AND {where}", limit=1)[0]
    top = _rows(response)[0]
    assert (top["Batter"], top["Runs Scored"]) == expected[:2]
    summary = response.summaries[0].body
    for key, team in expected_filter.items():
        assert (f"for {team}" if key == "player_team" else f"against {team}") in summary


def test_own_team_for_bowling_statistics_uses_the_bowling_side(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply("Most wickets for India", history=[]).query_response
    assert _plan(response)["filters"] == {"player_team": "India"}
    expected = db.execute(
        "SELECT bowl, COUNT(*) AS wickets FROM analytics.deliveries_v1 "
        "WHERE team_bowl = 'India' AND LOWER(CAST(dismissal AS VARCHAR)) IN "
        "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled') "
        "GROUP BY bowl ORDER BY wickets DESC LIMIT 1"
    ).fetchone()
    top = _rows(response)[0]
    assert (top["Bowler"], top["Wickets Taken"]) == expected
    assert response.summaries[0].body.startswith("For India")


def test_player_comparison_and_dismissal_types_keep_the_condition(repository, db) -> None:
    chat, _ = _chat(repository)
    comparison = chat.reply(
        "Compare Kohli and Rohit runs in successful chases", history=[]
    ).query_response
    assert _plan(comparison)["filters"]["batting_result"] == "won"
    assert _plan(comparison)["filters"]["innings"] == 2
    runs = {row["Player"]: row["Runs Scored"] for row in _rows(comparison)}
    assert runs == {"Virat Kohli": 5791, "Rohit Sharma": 4415}
    assert "successful chases" in _note(comparison)

    dismissals = chat.reply(
        "How often was Kohli bowled in successful run chases?", history=[]
    ).query_response
    plan = _plan(dismissals)
    assert plan["filters"]["batting_result"] == "won" and plan["filters"]["innings"] == 2
    bowled, total = db.execute(
        f"""
        SELECT SUM(CASE WHEN dismissal = 'bowled' THEN 1 ELSE 0 END), COUNT(*)
        FROM analytics.deliveries_v1
        WHERE {WON} AND out = 'True'
          AND p_out IN (SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat = 'Virat Kohli')
          AND dismissal IN ('caught', 'bowled', 'leg before wicket', 'run out', 'stumped',
                            'hit wicket', 'obstructing the field', 'handled the ball')
        """
    ).fetchone()
    row = _rows(dismissals)[0]
    assert (row["Dismissals"], row["All Recorded Dismissals"]) == (bowled, total) == (10, 65)


def test_batting_average_in_wins_uses_the_result_without_an_innings_condition(repository, db) -> None:
    chat, _ = _chat(repository)
    response = chat.reply("Kohli's batting average in wins", history=[]).query_response
    assert _plan(response)["filters"] == {"batter": "Virat Kohli", "batting_result": "won"}
    runs, outs = db.execute(
        """
        SELECT SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END),
               SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND out = 'True' THEN 1 ELSE 0 END)
        FROM analytics.deliveries_v1 WHERE bat = 'Virat Kohli' AND winner = team_bat
        """
    ).fetchone()
    row = _rows(response)[0]
    assert (row["Runs Scored"], row["Dismissals"]) == (runs, outs)
    assert row["Batting Average"] == round(runs / outs, 2)
    assert "Match result condition" in [note.title for note in response.evidence_notes]


# --- rankings retain metric, direction, limit and threshold ----------------------


def test_rankings_retain_metric_direction_limit_and_explicit_sample(repository, db) -> None:
    chat, _ = _chat(repository)
    top_five = chat.reply("Top 5 run scorers in successful chases", history=[]).query_response
    assert _plan(top_five)["limit"] == 5
    assert len(_rows(top_five)) == 5

    fastest = chat.reply(
        "Highest batting strike rate in successful chases, minimum 500 balls", history=[]
    ).query_response
    slowest = chat.reply(
        "Lowest batting strike rate in successful chases, minimum 500 balls", history=[]
    ).query_response
    for response, direction in ((fastest, "desc"), (slowest, "asc")):
        plan = _plan(response)
        assert plan["metric"] == "batting_strike_rate"
        assert plan["sort"]["direction"] == direction
        assert plan["minimum_sample"]["balls"] == 500
        assert plan["minimum_sample_explicit"] is True
        assert plan["filters"] == {"innings": 2, "batting_result": "won"}
    expected = db.execute(
        f"""
        SELECT bat, ROUND(100.0 * SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END)
                     / SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END), 2) AS sr
        FROM analytics.deliveries_v1 WHERE {WON}
        GROUP BY bat HAVING SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) >= 500
        ORDER BY sr DESC LIMIT 1
        """
    ).fetchone()
    top = _rows(fastest)[0]
    assert (top["Batter"], top["Batting Strike Rate"]) == expected
    assert all(row["Balls Faced"] >= 500 for row in _rows(slowest))


# --- follow-ups -----------------------------------------------------------------


def test_follow_up_broadens_to_all_chases_by_removing_only_the_result(repository, db) -> None:
    chat, _ = _chat(repository)
    first = chat.reply(TRACER, history=[])
    state = first.conversation_state
    broadened = chat.reply("What about all chases now?", history=[], conversation_state=state)
    plan = _plan(broadened.query_response)
    assert plan["filters"] == {"innings": 2}
    assert plan["metric"] == "runs_scored" and plan["limit"] == 10
    assert plan["sort"] == {"by": "runs_scored", "direction": "desc"}
    expected = _batter_runs(db, "inns = '2'", limit=1)[0]
    assert _rows(broadened.query_response)[0]["Runs Scored"] == expected[1] == 7844
    patch = _trace(broadened.query_response)["meaning_patch"]
    assert patch["operations"] == [{"action": "remove", "target": "filter.batting_result", "value": None}]

    unsuccessful = chat.reply(
        "And unsuccessful chases?", history=[], conversation_state=broadened.conversation_state
    )
    assert _plan(unsuccessful.query_response)["filters"] == {"innings": 2, "batting_result": "lost"}
    australia = chat.reply(
        "And against Australia?", history=[], conversation_state=unsuccessful.conversation_state
    )
    assert _plan(australia.query_response)["filters"] == {
        "innings": 2,
        "batting_result": "lost",
        "opposition": "Australia",
    }
    expected = _batter_runs(db, f"{LOST} AND team_bowl = 'Australia'", limit=1)[0]
    assert _rows(australia.query_response)[0]["Runs Scored"] == expected[1]


@pytest.mark.parametrize(
    "follow_up",
    ["Regardless of the result?", "Including unsuccessful chases?", "Win or lose?"],
)
def test_other_broadening_wording_removes_only_the_result(repository, follow_up) -> None:
    chat, _ = _chat(repository)
    first = chat.reply(TRACER, history=[])
    reply = chat.reply(follow_up, history=[], conversation_state=first.conversation_state)
    assert _plan(reply.query_response)["filters"] == {"innings": 2}


def test_follow_up_adding_the_result_to_a_chasing_answer(repository) -> None:
    chat, _ = _chat(repository)
    first = chat.reply("Most runs chasing", history=[])
    reply = chat.reply(
        "And in successful chases?", history=[], conversation_state=first.conversation_state
    )
    assert _plan(reply.query_response)["filters"] == {"innings": 2, "batting_result": "won"}
    assert _rows(reply.query_response)[0]["Runs Scored"] == 5791


def test_changing_the_innings_under_a_result_condition_asks(repository) -> None:
    chat, _ = _chat(repository)
    first = chat.reply(TRACER, history=[])
    reply = chat.reply(
        "What about batting first?", history=[], conversation_state=first.conversation_state
    )
    assert reply.mode == "clarification"
    assert "result condition" in reply.message


# --- fail closed ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "fragment"),
    [
        ("Most runs in tied matches", "Ties and no-results are not a registered result filter"),
        ("Most runs in no-result matches", "Ties and no-results"),
        ("Most runs in successful and unsuccessful chases", "Comparing successful and unsuccessful"),
        ("Kohli runs in successful vs unsuccessful chases", "Comparing successful and unsuccessful"),
        ("Most runs in India's wins", "could not be read as a registered result filter"),
        ("Bumrah economy in successful chases", "registered for batting statistics"),
        ("Most wickets in successful chases", "registered for batting statistics"),
        ("Most runs batting first in successful chases", "cannot be combined with batting first"),
        ("Most runs in successful chases of targets above 300", "Filtering by target"),
        ("Most runs in successful World Cup chases", "competition (world cup)"),
    ],
)
def test_unsupported_result_requests_fail_closed_with_the_condition_named(
    repository, question, fragment
) -> None:
    chat, _ = _chat(repository)
    reply = chat.reply(question, history=[])
    response = reply.query_response
    assert response is None or not response.tables
    assert fragment in reply.message


def test_model_readings_cannot_add_or_contradict_the_result_condition(resolver) -> None:
    contradicting = LanguageMeaningCandidate.model_validate(
        {
            **SAVED_TRACER_EXTRACTION,
            "filters": [
                {"concept": "innings_outcome", "evidence": "successful", "values": ["loss"]},
                {"concept": "innings_type", "evidence": "chases", "values": ["chase"]},
            ],
        }
    )
    assert resolver.resolve_candidate(TRACER, None, contradicting).status != MeaningStatus.resolved

    added = LanguageMeaningCandidate.model_validate(
        {
            **SAVED_TRACER_EXTRACTION,
            "filters": [
                {"concept": "innings_outcome", "evidence": "chases", "values": ["win"]},
                {"concept": "innings_type", "evidence": "chases", "values": ["chase"]},
            ],
        }
    )
    question = "Who scored most runs in ODI chases?"
    assert resolver.resolve_candidate(question, None, added).status != MeaningStatus.resolved

    omitted = LanguageMeaningCandidate.model_validate(
        {**SAVED_TRACER_EXTRACTION, "filters": [SAVED_TRACER_EXTRACTION["filters"][2]]}
    )
    resolution = resolver.resolve_candidate(TRACER, None, omitted)
    assert resolution.status == MeaningStatus.resolved
    assert resolution.meaning.filters == {"innings": 2, "batting_result": "won"}


def test_validator_rejects_plans_that_drop_change_or_keep_a_removed_condition() -> None:
    def plan(filters: dict, entity: str = "batter", metric: str = "runs_scored") -> CricketQueryPlan:
        return CricketQueryPlan(
            operation="aggregate",
            entity=entity,
            metric=metric,
            group_by=[entity],
            filters=filters,
            sort=SortSpec(by=metric, direction="desc"),
            limit=10,
        )

    assert validate_plan(plan({"innings": 2, "batting_result": "won"}), TRACER).valid
    assert not validate_plan(plan({"innings": 2}), TRACER).valid
    assert not validate_plan(plan({"batting_result": "won"}), TRACER).valid
    assert not validate_plan(plan({}), TRACER).valid
    assert not validate_plan(plan({"innings": 2, "batting_result": "lost"}), TRACER).valid
    assert not validate_plan(
        plan({"innings": 2, "batting_result": "won"}), "What about all chases now?"
    ).valid
    assert not validate_plan(
        plan({"innings": 2, "batting_result": "won"}, "bowler", "economy_rate"),
        "Bumrah economy in successful chases",
    ).valid
    assert removes_result_condition("What about all chases now?")
    assert result_condition_problem(TRACER) is None
    assert BATTING_RESULT_FILTER == "batting_result"


# --- compatibility ------------------------------------------------------------------


def test_existing_questions_are_unchanged(repository) -> None:
    chat, _ = _chat(repository)
    toss = chat.reply("Who won the toss in the 2019 World Cup final?", history=[]).query_response
    assert _plan(toss)["operation"] == "match_fact"
    assert "New Zealand won the toss" in toss.summaries[0].body
    chasing = chat.reply("Most runs chasing", history=[]).query_response
    assert _plan(chasing)["filters"] == {"innings": 2}
    assert "successful" not in chasing.summaries[0].body
    assert all(note.title != "Successful chase condition" for note in chasing.evidence_notes)
    rohit = chat.reply("Rohit's strike rate when required rate was above 8?", history=[]).query_response
    assert _rows(rohit)[0]["Batting Strike Rate"] == 118.79
