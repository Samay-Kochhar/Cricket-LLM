"""Dismissal-only batting appearances never become deliveries faced."""

import duckdb

from backend.app.multiformat.execution import aggregate
from backend.app.multiformat.service import DeliveryFilter, MultiFormatService
from tests.backend.multiformat_fixture import build_fixture_db


def test_nonstriker_dismissal_without_facing_counts_appearance_not_delivery(tmp_path):
    path = build_fixture_db(tmp_path)
    with duckdb.connect(str(path)) as conn:
        conn.execute(
            """INSERT INTO analytics.deliveries
            SELECT * REPLACE ('m4' AS match_id, 2021 AS year,
                              DATE '2021-05-01' AS match_date)
            FROM analytics.deliveries WHERE player_out_id='bat' AND batter_id <> 'bat'"""
        )
    result = aggregate(
        MultiFormatService(path),
        DeliveryFilter(competition="Indian Premier League"),
        "batting",
        "bat",
    )[0]
    assert result["runs"] == 10
    assert result["balls"] == 3
    assert result["delivery_rows"] == 4
    assert result["dismissals"] == 3
    assert result["matches"] == 3
