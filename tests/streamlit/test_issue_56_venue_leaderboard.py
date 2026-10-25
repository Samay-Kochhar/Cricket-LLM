from __future__ import annotations

from streamlit.testing.v1 import AppTest

from tests.backend.test_venue_bowling_leaderboard import repository  # noqa: F401
from streamlit_venue_explorer import build_wickets_figure


def app_for(repository):
    app = AppTest.from_string('''import streamlit as st
from streamlit_venue_explorer import render_venue_explorer
render_venue_explorer({'repository': st.session_state.repository})
''')
    app.session_state.repository = repository
    app.run()
    app.selectbox[0].select("Arun Jaitley Stadium, Delhi").run()
    app.button[2].click().run()
    assert not app.exception
    return app


def test_controls_apply_independently_and_reset(repository):
    app = app_for(repository)
    assert app.dataframe[0].value.iloc[0]["Bowler"] == "A"
    assert "Bowling average" in app.dataframe[0].value
    app.selectbox[1].select("matches")
    app.number_input[0].set_value(1)
    app.selectbox[2].select("economy_rate")
    app.selectbox[3].select("middle")
    app.number_input[1].set_value(2023)
    app.number_input[2].set_value(2024)
    # Form edits stay in the browser until submission; batch them before run().
    # Draft controls do not mutate applied evidence.
    assert app.session_state["venue-profile"]["filters"]["metric"] == "wickets_taken"
    app.button[0].click().run()
    assert not app.exception
    profile = app.session_state["venue-profile"]
    assert profile["filters"]["phase"] == "middle"
    assert profile["filters"]["year_start"] == 2023
    assert profile["filters"]["year_end"] == 2024
    assert profile["filters"]["sample_unit"] == "matches"
    assert app.dataframe[0].value.iloc[0]["Bowler"] == "B"
    assert any("Middle; 2023–2024" in caption.value for caption in app.caption)
    app.number_input[1].set_value(None)
    app.number_input[2].set_value(None)
    app.button[0].click().run()
    filters = app.session_state["venue-profile"]["filters"]
    assert filters["year_start"] is None
    assert filters["metric"] == "economy_rate" and filters["phase"] == "middle"
    app.button[1].click().run()
    assert app.session_state["venue-profile"]["filters"]["metric"] == "wickets_taken"
    assert app.session_state["venue-profile"]["filters"]["minimum_sample"] == 24
    assert app.selectbox[2].value == "wickets_taken"


def test_invalid_and_empty_filters_do_not_show_misleading_results(repository):
    app = app_for(repository)
    app.number_input[1].set_value(2024)
    app.number_input[2].set_value(2023)
    app.button[0].click().run()
    assert app.error and not app.dataframe
    app.number_input[2].set_value(2024)
    app.number_input[0].set_value(999)
    app.button[0].click().run()
    assert app.error and not app.dataframe


def test_metric_chart_and_layout_order(repository):
    app = app_for(repository)
    # AppTest exposes protocol tree order, including Plotly elements.
    elements = list(app.main)
    chart_index = next(i for i, item in enumerate(elements) if item.type == "plotly_chart")
    table_index = elements.index(app.dataframe[0])
    assert chart_index < table_index
    profile = app.session_state["venue-profile"]
    rows = profile["bowling_leaderboard"]
    figure = build_wickets_figure(rows, "economy_rate")
    assert list(figure.data[0].x) == [row["economy_rate"] for row in rows[:6]]
    assert figure.layout.xaxis.title.text == "Economy"
