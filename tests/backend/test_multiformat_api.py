from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes.multiformat import get_multiformat_service, router
from backend.app.multiformat.service import MultiFormatService
from tests.backend.multiformat_fixture import build_fixture_db


@pytest.fixture()
def client(tmp_path: Path):
    db = build_fixture_db(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_multiformat_service] = lambda: MultiFormatService(db)
    return TestClient(app)


def test_batting_stats_follow_the_metric_definitions(client) -> None:
    body = client.get("/api/v2/data/players/bat/stats", params={"gender": "male"}).json()
    [row] = body["by_format"]
    # wides are not balls faced: 3 balls faced, 10 runs; dismissals include the
    # run-out at the non-striker's end
    assert (row["balls"], row["runs"], row["dismissals"]) == (3, 10, 2)
    assert row["strike_rate"] == pytest.approx(333.33)
    assert row["average"] == 5.0


def test_bowling_stats_charge_wides_and_count_bowler_wickets(client) -> None:
    [row] = client.get("/api/v2/data/players/bowl/stats", params={"role": "bowling", "gender": "male"}).json()["by_format"]
    assert (row["balls"], row["runs_conceded"], row["wickets"]) == (3, 11, 1)
    assert row["economy"] == 22.0


def test_line_length_reports_partial_coverage(client) -> None:
    body = client.get("/api/v2/data/players/bat/line-length", params={"competition": "Indian Premier League"}).json()
    assert body["coverage"]["deliveries"] == 4 and body["coverage"]["with_length"] == 2
    assert body["complete"] is False
    assert "2 of 4 deliveries" in body["note"]
    assert {r["length"] for r in body["rows"]} == {"FULL", "GOOD_LENGTH"}
    assert body["limitations"][0]["statement"] == "Length is available from 2019."


def test_line_length_without_any_data_returns_the_limitation(client) -> None:
    body = client.get("/api/v2/data/players/bat/line-length", params={"gender": "female"}).json()
    assert body["rows"] == []
    assert "not recorded for any" in body["note"]
    assert "women's T20I" in body["limitations"][0]["statement"]


def test_unknown_player_is_404(client) -> None:
    assert client.get("/api/v2/data/players/nobody/stats").status_code == 404


def test_missing_database_is_503(tmp_path) -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_multiformat_service] = lambda: MultiFormatService(tmp_path / "absent.duckdb")
    response = TestClient(app).get("/api/v2/data/coverage")
    assert response.status_code == 503 and "ingestion.app.multiformat.build" in response.json()["detail"]
