from __future__ import annotations

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes.explore import router
from backend.app.bootstrap import get_services
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.venue_leaderboard import METRICS, VenueBowlingOptions
from backend.app.services.explorer_service import build_venue_profile


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / "venue.duckdb"
    with duckdb.connect(str(path)) as conn:
        conn.execute("CREATE SCHEMA analytics")
        conn.execute('''CREATE TABLE analytics.deliveries_v1 (
            bowl VARCHAR, ground VARCHAR, p_match INTEGER, team_bowl VARCHAR,
            wide INTEGER, noball INTEGER, batruns INTEGER, bowlruns INTEGER,
            dismissal VARCHAR, year INTEGER, over DOUBLE)''')
        rows = []
        # Same ODI across two historical labels; filter first, then distinct matches.
        for alias in ("Feroz Shah Kotla, Delhi", "Arun Jaitley Stadium, Delhi"):
            for name, runs, dismissal in (("A", 2, "bowled"), ("B", 1, "run out"), ("C", 4, "caught")):
                for year in (2022, 2023, 2024):
                    for over in (6, 10, 10.1, 40, 40.1):
                        rows.append((name, alias, year, "India", 0, 0, runs, runs, dismissal, year, over))
        # Extras: batruns=0 is not a dot when charged to bowler. Illegal balls
        # contribute runs but neither legal-ball denominator nor legal boundaries.
        rows += [
            ("Extras", "Feroz Shah Kotla, Delhi", 1, "India", 0, 0, 0, 1, "", 2023, 10),
            ("Extras", "Arun Jaitley Stadium, Delhi", 1, "India", 0, 0, 0, 0, "", 2023, 10),
            ("Extras", "Arun Jaitley Stadium, Delhi", 1, "India", 1, 0, 0, 1, "", 2023, 10),
            ("Extras", "Arun Jaitley Stadium, Delhi", 1, "India", 0, 1, 4, 5, "", 2023, 10),
            ("Illegal", "Feroz Shah Kotla, Delhi", 2, "India", 1, 0, 0, 1, "", 2023, 10),
            ("Other", "Wankhede Stadium, Mumbai", 3, "India", 0, 0, 6, 6, "bowled", 2023, 10),
        ]
        conn.executemany("INSERT INTO analytics.deliveries_v1 VALUES (" + ",".join("?" * 11) + ")", rows)
    return AnalyticsRepository(path)


def test_alias_union_and_default_minimum(repository):
    profile = build_venue_profile(repository, "Feroz Shah Kotla, Delhi")
    assert profile["venue_name"] == "Arun Jaitley Stadium, Delhi"
    assert profile["filters"]["minimum_sample"] == 24
    rows = profile["bowling_leaderboard"]
    assert [row["player_name"] for row in rows] == ["A", "C", "B"]
    assert rows[0]["deliveries"] == 30
    assert rows[0]["matches"] == 3
    assert repository.get_venue_bowling_leaderboard("in-delhi-kotla") == rows


@pytest.mark.parametrize("phase,balls", [("first6", 2), ("powerplay", 4), ("middle", 4), ("death", 2)])
def test_phase_boundaries_and_inclusive_years(repository, phase, balls):
    rows = repository.get_venue_bowling_leaderboard("in-delhi-kotla", phase=phase,
        year_start=2023, year_end=2023, minimum_sample=0)
    row = next(row for row in rows if row["player_name"] == "A")
    assert row["deliveries"] == balls
    assert row["matches"] == 1
    rows = repository.get_venue_bowling_leaderboard("in-delhi-kotla", phase=phase,
        year_start=2022, year_end=2023, minimum_sample=0)
    assert next(row for row in rows if row["player_name"] == "A")["deliveries"] == balls * 2


def test_bowling_calculations_extras_and_unavailable_rates(repository):
    rows = repository.get_venue_bowling_leaderboard("in-delhi-kotla", minimum_sample=0)
    extras = next(row for row in rows if row["player_name"] == "Extras")
    assert extras["deliveries"] == 2 and extras["delivery_rows"] == 4
    assert extras["matches"] == 1 and extras["runs_conceded"] == 7
    assert extras["economy_rate"] == 21
    assert extras["dot_percentage"] == 50
    assert extras["boundary_percentage"] == 0
    assert extras["bowling_average"] is None and extras["bowling_strike_rate"] is None
    illegal = next(row for row in rows if row["player_name"] == "Illegal")
    assert illegal["economy_rate"] is None and illegal["dot_percentage"] is None
    a = rows[0]
    assert a["bowling_average"] == 2 and a["bowling_strike_rate"] == 1
    assert a["economy_rate"] == 12 and a["wickets"] == 30
    c = next(row for row in rows if row["player_name"] == "C")
    assert c["boundary_percentage"] == 100
    assert next(row for row in rows if row["player_name"] == "B")["wickets"] == 0


@pytest.mark.parametrize("metric", METRICS)
def test_selected_metric_direction_and_eligibility_before_limit(repository, metric):
    options = VenueBowlingOptions(metric=metric, minimum_sample=0)
    all_rows = repository.get_venue_bowling_leaderboard("in-delhi-kotla", **options.as_dict())
    values = [row[options.ranking["field"]] for row in all_rows]
    assert all(v is not None for v in values)
    assert values == sorted(values, reverse=options.ranking["direction"] == "desc")
    limited = repository.get_venue_bowling_leaderboard("in-delhi-kotla", metric=metric, limit=1,
        sample_unit="matches", minimum_sample=2)
    qualified = [row for row in all_rows if row["matches"] >= 2]
    assert limited == qualified[:1]
    assert repository.get_venue_bowling_leaderboard("in-delhi-kotla", metric=metric,
        phase="death", minimum_sample=24) == []


def test_deterministic_ties(repository):
    with duckdb.connect(str(repository.db_path)) as conn:
        conn.execute("INSERT INTO analytics.deliveries_v1 SELECT 'AA', ground, p_match, team_bowl, wide, noball, batruns, bowlruns, dismissal, year, over FROM analytics.deliveries_v1 WHERE bowl = 'A'")
    assert [r["player_name"] for r in repository.get_venue_bowling_leaderboard("in-delhi-kotla", limit=2)] == ["A", "AA"]


@pytest.mark.parametrize("filters", [
    {"phase": "typo"}, {"phase": ""}, {"metric": "typo"}, {"sample_unit": "innings"},
    {"minimum_sample": -1}, {"minimum_sample": True}, {"minimum_sample": 1.5},
    {"limit": 0}, {"limit": 101}, {"year_start": 2023}, {"year_end": 2023},
    {"year_start": 2024, "year_end": 2023}, {"year_start": 2023.5, "year_end": 2024},
])
def test_validates_controls_before_query(repository, filters):
    with pytest.raises(ValueError):
        repository.get_venue_bowling_leaderboard("in-delhi-kotla", **filters)


def test_api_contract_and_validation(repository):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_services] = lambda: {"repository": repository}
    with TestClient(app) as client:
        filters = dict(metric="economy_rate", phase="middle", year_start=2022, year_end=2023,
                       sample_unit="matches", minimum_sample=2)
        response = client.get("/api/venues/in-delhi-kotla", params=filters)
        assert response.status_code == 200
        assert response.json() == build_venue_profile(repository, "in-delhi-kotla", **filters)
        assert response.json()["ranking"]["direction"] == "asc"
        assert response.json()["bowling_leaderboard"][0]["player_name"] == "B"
        for bad in ({"metric": "bogus"}, {"phase": "typo"}, {"year_start": 2023}, {"minimum_sample": "1.5"}):
            assert client.get("/api/venues/in-delhi-kotla", params=bad).status_code == 422
