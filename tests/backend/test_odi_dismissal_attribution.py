"""Regression coverage for dismissed-player attribution through actual app queries."""

from pathlib import Path

import duckdb
import pytest

from backend.app.cricket_analytics.dismissal_sql import CONTEXT_COLUMNS, OWN_DISMISSAL
from backend.app.cricket_analytics.schemas import CricketQueryPlan
from backend.app.cricket_analytics.query_builders.aggregate_builder import (
    build_aggregate_query,
)
from backend.app.cricket_analytics.executors.matchup_executor import build_matchup_query
from backend.app.cricket_analytics.executors.split_compare_executor import (
    build_split_compare_query,
)
from backend.app.db.connection import get_connection
from backend.app.db.repository import AnalyticsRepository


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / "attribution.duckdb"
    columns = list(
        dict.fromkeys(
            [
                *CONTEXT_COLUMNS,
                "bat",
                "p_bat",
                "bowl",
                "p_bowl",
                "p_out",
                "out",
                "dismissal",
                "ballfaced",
                "batruns",
                "control",
                "bowlruns",
                "wide",
                "noball",
                "line",
                "length",
                "bowl_kind",
                "bowl_style",
                "bat_hand",
                "shot",
                "wagonZone",
            ]
        )
    )
    with duckdb.connect(str(path)) as c:
        c.execute("CREATE SCHEMA analytics")
        c.execute(
            "CREATE TABLE analytics.deliveries_v1 ("
            + ",".join('"' + x + '" VARCHAR' for x in columns)
            + ")"
        )
        events = [
            ("A", "1", "2", "run out", "1", "1", "0"),
            ("B", "2", "1", "run out", "1", "3", "0"),
            ("A", "1", "1", "retired hurt", "1", "2", "0"),
            ("A", "1", "1", "stumped", "0", "0", "1"),
            ("A", "1", "1", "caught", "1", "4", "0"),
            ("A", "1", None, "caught", "1", "1", "0"),
        ]
        for i, (bat, p_bat, p_out, kind, faced, runs, wide) in enumerate(events):
            row = dict.fromkeys(columns)
            row.update(
                p_match="m",
                inns="1",
                team_bat="India",
                team_bowl="Other",
                over="45",
                ball_id=str(i),
                year="2011",
                ground="Test Ground",
                competition="ODI",
                bat=bat,
                p_bat=p_bat,
                p_out=p_out,
                out="true",
                dismissal=kind,
                ballfaced=faced,
                batruns=runs,
                bowl="Bowler",
                p_bowl="9",
                bowlruns=runs,
                wide=wide,
                noball="0",
                control="1",
                line="OUTSIDE_OFFSTUMP",
                length="GOOD_LENGTH",
                bowl_kind="pace bowler",
                bowl_style="RF",
                bat_hand="RHB",
            )
            c.execute(
                "INSERT INTO analytics.deliveries_v1 VALUES ("
                + ",".join("?" for _ in columns)
                + ")",
                [row[x] for x in columns],
            )
    return AnalyticsRepository(path)


def query_rows(repository, built):
    q = getattr(built, "query", built)
    with get_connection(repository.db_path) as c:
        result = c.execute(q.sql, q.params)
        return [
            dict(zip([x[0] for x in result.description], row))
            for row in result.fetchall()
        ]


def test_career_and_explorer_include_own_nonstriker_and_wide_only(repository):
    for summary in [
        repository.get_player_batting_summary("A"),
        repository.get_explorer_player_summary("A", "batting"),
        repository.get_player_batting_summary("A", "death"),
    ]:
        assert summary["dismissals"] == 3
        assert summary["balls_faced"] == 4
        assert summary["runs_scored"] == 8
        assert summary["dot_balls"] == 0
        assert summary["control_percentage"] == 100
    b = repository.get_player_batting_summary("B")
    assert b["dismissals"] == 1  # dismissed on A's ball, not on B's own delivery
    assert b["runs_scored"] == 3
    assert b["balls_faced"] == 1
    assert repository.get_explorer_player_summary("A", "batting")["delivery_rows"] == 5


@pytest.mark.parametrize("builder", [build_aggregate_query, build_matchup_query])
def test_generated_career_queries(repository, builder):
    p = CricketQueryPlan(
        operation="aggregate" if builder == build_aggregate_query else "matchup",
        entity="batter",
        metric="batting_average",
        filters={"batter": "A"},
    )
    row = query_rows(repository, builder(p))[0]
    assert row["dismissals"] == 3
    assert row["balls"] == 4
    assert row["legal_balls"] == 4  # no extra legal delivery for synthetic dismissal


def test_context_totals_and_ball_dimensions(repository):
    phases = repository.get_player_phase_summary("A")
    assert sum(x["dismissals"] for x in phases) == 3
    venue = repository.get_player_batting_venue_summary("A")[0]
    assert venue["dismissals"] == 3 and venue["balls_faced"] == 4
    for builder in [build_aggregate_query, build_matchup_query]:
        plan = CricketQueryPlan(
            operation="aggregate" if builder == build_aggregate_query else "matchup",
            entity="batter",
            metric="dismissals",
            filters={"batter": "A", "bowler": "Bowler"},
        )
        assert query_rows(repository, builder(plan))[0]["dismissals"] == 2
    assert repository.get_matchup_summary("A", "Bowler")["dismissals"] == 2
    assert repository.get_player_bowling_style_summary("A")[0]["dismissals"] == 2
    assert repository.get_player_bowling_kind_summary("A")[0]["dismissals"] == 2


def test_bowling_uses_raw_deliveries(repository):
    summary = repository.get_explorer_player_summary("Bowler", "bowling")
    assert summary["delivery_rows"] == 6
    assert summary["deliveries"] == 5
    assert summary["runs_conceded"] == 11
    # Bowling-credit semantics are unchanged, even for malformed missing p_out.
    assert summary["wickets"] == 3
    with get_connection(repository.db_path) as c:
        assert (
            c.execute("SELECT count(*) FROM analytics.deliveries_v1").fetchone()[0] == 6
        )
        synthetic = c.execute(
            "SELECT bowl,line,length,control,ballfaced,batruns FROM batting_events_v1 WHERE synthetic_dismissal"
        ).fetchall()
        assert synthetic == [
            (None, None, None, None, "0", "0"),
            (None, None, None, None, "0", "0"),
        ]


def test_unknown_dismissed_id_does_not_fall_back_to_striker(repository):
    with get_connection(repository.db_path) as c:
        assert (
            c.execute(
                f"SELECT count(*) FROM analytics.deliveries_v1 WHERE p_out IS NULL AND {OWN_DISMISSAL}"
            ).fetchone()[0]
            == 0
        )


def test_real_dhoni_if_local_data_available():
    path = Path(__file__).resolve().parents[2] / "data/odi_analytics.duckdb"
    if not path.exists():
        pytest.skip("local ODI dataset absent")
    repository = AnalyticsRepository(path)
    for summary in [
        repository.get_player_batting_summary("MS Dhoni"),
        repository.get_explorer_player_summary("MS Dhoni", "batting"),
    ]:
        assert summary["dismissals"] == 210
        assert summary["runs_scored"] == 10738
        assert summary["balls_faced"] == 12277


def test_phase_split_and_year_group_preserve_dismissal_only_context(repository):
    plan = CricketQueryPlan(
        operation="split_compare",
        entity="batter",
        metric="dismissal_rate",
        filters={"batter": "A"},
        split_by="phase",
        compare_values=["death", "powerplay"],
    )
    built = build_split_compare_query(plan)
    row = query_rows(repository, built)[0]
    assert row[built.value_a_column] == 75  # three dismissals / four faced balls
    plan = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="dismissals",
        filters={"batter": "A"},
        group_by=["year"],
    )
    assert query_rows(repository, build_aggregate_query(plan))[0]["dismissals"] == 3


@pytest.mark.parametrize(
    "kind", ["retired hurt", "retired not out", "retired not out (hurt)", "not out"]
)
def test_all_retirement_spellings_excluded(repository, kind):
    # Mutate only this test's disposable database; production data stays read-only.
    with duckdb.connect(str(repository.db_path)) as c:
        c.execute(
            "UPDATE analytics.deliveries_v1 SET dismissal=? WHERE dismissal='retired hurt'",
            [kind],
        )
    assert repository.get_player_batting_summary("A")["dismissals"] == 3


def test_generated_sql_is_self_contained_for_read_only_clients(repository):
    plan = CricketQueryPlan(
        operation="aggregate",
        entity="batter",
        metric="dismissals",
        filters={"batter": "A"},
    )
    built = build_aggregate_query(plan)
    with duckdb.connect(str(repository.db_path), read_only=True) as c:
        result = c.execute(built.sql, built.params)
        fields = [x[0] for x in result.description]
        assert dict(zip(fields, result.fetchone()))["dismissals"] == 3


def test_ingestion_bowling_view_uses_credit_types(repository):
    sql_path = Path(__file__).resolve().parents[2] / "ingestion/sql/derived_views.sql"
    with duckdb.connect(str(repository.db_path)) as c:
        c.execute(sql_path.read_text())
        assert (
            c.execute(
                "SELECT wickets_on_ball FROM analytics.player_year_bowling"
            ).fetchone()[0]
            == 3
        )


def test_connection_without_delivery_relation(tmp_path):
    path = tmp_path / "unrelated.duckdb"
    with duckdb.connect(str(path)) as c:
        c.execute("CREATE TABLE unrelated (id INTEGER)")
    with get_connection(path) as c:
        assert c.execute("SELECT COUNT(*) FROM unrelated").fetchone()[0] == 0


def test_missing_attribution_blocks_batting_but_not_other_queries(tmp_path):
    # Without p_out the database cannot say who was dismissed, so the batting
    # events view is never built and any batting query fails loudly instead of
    # guessing from the striker's out flag. Bowling/venue queries still run.
    path = tmp_path / "missing-attribution.duckdb"
    with duckdb.connect(str(path)) as c:
        c.execute("CREATE SCHEMA analytics")
        c.execute("CREATE TABLE analytics.deliveries_v1 (p_bat VARCHAR, bowl VARCHAR, bowlruns INTEGER)")
        c.execute("INSERT INTO analytics.deliveries_v1 VALUES ('a', 'b', 4)")
    with get_connection(path) as conn:
        assert conn.execute("SELECT sum(bowlruns) FROM analytics.deliveries_v1 WHERE bowl = 'b'").fetchone() == (4,)
        with pytest.raises(duckdb.CatalogException, match="batting_events_v1"):
            conn.execute("SELECT count(*) FROM batting_events_v1").fetchone()


@pytest.mark.parametrize(
    "builder", [build_aggregate_query, build_matchup_query, build_split_compare_query]
)
def test_synthetic_caught_never_adds_bowling_projections(repository, builder):
    # A malformed caught event dismisses the nonstriker. Preserve the raw
    # bowling credit once, never count its batting-only duplicate as a wicket.
    with duckdb.connect(str(repository.db_path)) as c:
        c.execute("UPDATE analytics.deliveries_v1 SET dismissal='caught' WHERE bat='B'")
    operation = {
        build_aggregate_query: "aggregate",
        build_matchup_query: "matchup",
        build_split_compare_query: "split_compare",
    }[builder]
    plan = CricketQueryPlan(
        operation=operation,
        entity="batter",
        metric="dismissal_rate" if operation == "split_compare" else "dismissals",
        filters={"batter": "A"},
        split_by="phase" if operation == "split_compare" else None,
        compare_values=["death", "powerplay"] if operation == "split_compare" else [],
    )
    result = builder(plan)
    built = getattr(result, "query", result)
    # Inspect the actual generated CTE, since wickets are an intermediate
    # projection for batting plans rather than a public batting output field.
    import re

    from backend.app.cricket_analytics.query_builders.aggregate_builder import (
        BOWLER_WICKET,
    )

    cte = "bucketed" if operation == "split_compare" else "aggregate_rows"
    # Terminate after the first CTE, preserving the generated projections and
    # filters. Only the first CTE's parameters apply to this diagnostic SELECT.
    prefix = re.split(
        r"\n\s*\)(?:,)?\n\s*(?:SELECT|split_rows AS)", built.sql, maxsplit=1
    )[0]
    projection = (
        prefix
        + f") SELECT SUM(wickets), SUM(runs_conceded), SUM(legal_balls) FROM {cte}"
    )
    with get_connection(repository.db_path) as c:
        actual = c.execute(projection, built.params[: projection.count("?")]).fetchone()
        assert actual == (3, 8, 4)
        assert (
            c.execute(
                f"SELECT SUM(CASE WHEN {BOWLER_WICKET} THEN 1 ELSE 0 END) FROM analytics.deliveries_v1"
            ).fetchone()[0]
            == 4
        )


def test_ball_context_split_includes_wide_stumping(repository):
    plan = CricketQueryPlan(
        operation="split_compare",
        entity="batter",
        metric="dismissal_rate",
        filters={"batter": "A", "bowler": "Bowler"},
        split_by="phase",
        compare_values=["death", "powerplay"],
    )
    built = build_split_compare_query(plan)
    assert query_rows(repository, built)[0][built.value_a_column] == 50


@pytest.mark.parametrize(
    "dimension,value",
    [("line", "OUTSIDE_OFFSTUMP"), ("length", "GOOD_LENGTH"), ("bowling_style", "RF")],
)
@pytest.mark.parametrize("builder", [build_aggregate_query, build_matchup_query])
def test_delivery_dimensions_include_zero_faced_own_dismissal(
    repository, dimension, value, builder
):
    plan = CricketQueryPlan(
        operation="aggregate" if builder == build_aggregate_query else "matchup",
        entity="batter",
        metric="dismissals",
        filters={"batter": "A", dimension: value},
    )
    row = query_rows(repository, builder(plan))[0]
    assert row["dismissals"] == 2
    assert row["balls"] == 4
    assert row["runs_scored" if builder == build_aggregate_query else "runs"] == 8
