from __future__ import annotations

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from backend.app.db.repository import AnalyticsRepository


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / "venue.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE SCHEMA analytics")
        connection.execute(
            """CREATE TABLE analytics.deliveries_v1 (
                bowl VARCHAR, ground VARCHAR, p_match INTEGER, inns INTEGER,
                team_bowl VARCHAR, wide INTEGER, noball INTEGER,
                bowlruns INTEGER, dismissal VARCHAR, batruns INTEGER
            )"""
        )
        rows = []
        bowlers = [
            ("A", 30, [1], 5, 5, "The Oval"),
            ("B", 36, [2, 3], 4, 1, "The Oval"),
            ("C", 42, [4, 5], 3, 0, "The Oval"),
            ("D", 20, [6, 7], 6, 2, "The Oval"),
            ("E", 20, [9, 10], 0, 1, "The Oval"),
            ("Other venue", 30, [8], 30, 0, "Elsewhere"),
        ]
        for name, balls, matches, wickets, runs, ground in bowlers:
            for index in range(balls):
                rows.append(
                    (
                        name, ground, matches[index % len(matches)],
                        1 + index % 2 if name == "A" else 1,
                        "India", 1 if name == "E" else 0, 0, runs,
                        "bowled" if index < wickets else "", 0,
                    )
                )
        connection.executemany(
            "INSERT INTO analytics.deliveries_v1 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
    return AnalyticsRepository(path)


def test_venue_filter_qualifies_distinct_matches_before_limit(repository):
    default = repository.get_venue_bowling_leaderboard("The Oval", limit=2)
    assert [row["player_name"] for row in default] == ["A", "B"]
    assert default[0]["matches"] == 1  # A appeared in two innings of one ODI.

    qualified = repository.get_venue_bowling_leaderboard(
        "The Oval", limit=2, sample_unit="matches", minimum_sample=2
    )
    assert [row["player_name"] for row in qualified] == ["D", "B"]
    assert all(row["matches"] == 2 for row in qualified)

    by_balls = repository.get_venue_bowling_leaderboard(
        "The Oval", limit=2, minimum_sample=40
    )
    assert [row["player_name"] for row in by_balls] == ["C"]
    assert all(row["player_name"] != "Other venue" for row in default + qualified + by_balls)


@pytest.mark.parametrize(
    "controls",
    [
        {"sample_unit": "innings"},
        {"minimum_sample": -1},
        {"minimum_sample": 1.5},
        {"limit": 0},
    ],
)
def test_invalid_venue_controls_fail_clearly(repository, controls):
    with pytest.raises(ValueError):
        repository.get_venue_bowling_leaderboard("The Oval", **controls)


def test_streamlit_venue_filter_applies_before_top_ten_and_resets(repository):
    app = AppTest.from_string(
        """import streamlit as st
from streamlit_venue_explorer import render_venue_explorer
render_venue_explorer({"repository": st.session_state.repository})
"""
    )
    app.session_state.repository = repository
    app.run()
    app.selectbox[0].select("The Oval").run()
    next(button for button in app.button if button.label == "Explore venue").click().run()
    assert not app.exception
    assert [item.label for item in app.selectbox] == [
        "Venue", "Filter by", "Rank and chart by", "Phase"
    ]
    assert app.dataframe[0].value.iloc[0]["Bowler"] == "A"
    assert any("at least 24 legal balls" in item.value for item in app.caption)

    app.selectbox[1].select("matches")
    app.number_input[0].set_value(2)
    next(button for button in app.button if button.label == "Apply filter").click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Bowler"] == "D"
    assert any("at least 2 distinct odi matches" in item.value.lower() for item in app.caption)
    assert app.session_state["venue-filter"]["sample_unit"] == "matches"
    assert any(item.value == "### Top Wicket Takers" for item in app.markdown)

    next(button for button in app.button if button.label == "Reset filter").click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Bowler"] == "A"
    assert app.session_state["venue-filter"]["minimum_sample"] == 24

    app.number_input[0].set_value(999)
    next(button for button in app.button if button.label == "Apply filter").click().run()
    assert app.error
    assert not app.dataframe
