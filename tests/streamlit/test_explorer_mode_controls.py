import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from tests.backend.test_explorer_modes import repository  # noqa: F401


def app_for(repository, surface):
    app = AppTest.from_string(f'''import streamlit as st
from streamlit_{surface}_explorer import render_{surface}_explorer
render_{surface}_explorer({{'repository': st.session_state.repository}})
''')
    app.session_state.repository = repository
    return app.run()


def test_compare_mode_context_and_unavailable_chart(repository):
    app = app_for(repository, 'compare')
    app.selectbox[0].select('X').run()
    app.selectbox[1].select('Y').run()
    app.radio[0].set_value('bowling').run()
    app.selectbox[2].select('middle')
    app.selectbox[3].select('Arun Jaitley Stadium, Delhi')
    app.number_input[0].set_value(2022)
    app.number_input[1].set_value(2023)
    app.selectbox[4].select('bowling_average')
    app.button[0].click().run()
    assert not app.exception
    profile = app.session_state['compare-profile']
    assert profile['filters'] == dict(phase='middle', venue='Arun Jaitley Stadium, Delhi', year_start=2022, year_end=2023)
    assert [p['deliveries'] for p in profile['players']] == [8, 8]
    assert pd.isna(app.dataframe[0].value.iloc[1]['Bowling average'])
    assert any('Lower is preferable' in c.value for c in app.caption)
    assert len(app.warning) == 2
    figure = app.get('plotly_chart')[0].proto.spec
    assert 'null' in figure  # Missing average retained as a missing bar, never zero.
    app.radio[0].set_value('batting').run()
    assert not app.dataframe  # Mode changes cannot display the previous mode's evidence.
    app.selectbox[0].select('A').run()
    app.selectbox[1].select('B').run()
    app.button[0].click().run()
    assert not app.exception
    assert 'Batting average' in app.dataframe[0].value
    assert app.session_state['compare-profile']['filters']['phase'] == 'middle'


@pytest.mark.parametrize('mode,players,field', [
    ('batting', ('A', 'B'), 'Balls'),
    ('bowling', ('X', 'Y'), 'Legal balls'),
])
def test_compare_repeated_submits_update_year_evidence(repository, mode, players, field):
    app = app_for(repository, 'compare')
    app.radio[0].set_value(mode).run()
    app.selectbox[0].select(players[0]).run()
    app.selectbox[1].select(players[1]).run()
    app.selectbox[4].select('balls_faced' if mode == 'batting' else 'balls_bowled')
    for start, end, balls in [(2023, 2023, 10), (2022, 2023, 20), (2024, 2024, 10), (1800, 1800, 0)]:
        app.number_input[0].set_value(start)
        app.number_input[1].set_value(end)
        app.button[0].click().run()
        assert not app.exception
        assert not app.error
        assert app.session_state['compare-profile']['filters']['year_start'] == start
        assert app.session_state['compare-profile']['filters']['year_end'] == end
        assert app.dataframe[0].value[field].tolist() == [balls, balls]
        assert json.loads(app.get('plotly_chart')[0].proto.spec)['data'][0]['x'] == [balls, balls]
        assert any(f'{start}–{end}' in caption.value for caption in app.caption)
        app.button[0].click().run()
        assert not app.exception
        assert app.dataframe[0].value[field].tolist() == [balls, balls]

    # A reversed range must explain the validation error and allow the next
    # submission to recover, rather than retaining an old result or error.
    app.number_input[0].set_value(2024)
    app.number_input[1].set_value(2023)
    app.button[0].click().run()
    assert 'start year' in app.error[0].value
    assert not app.dataframe
    app.number_input[1].set_value(2024)
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert app.dataframe[0].value[field].tolist() == [10, 10]
    app.number_input[0].set_value(None)
    app.number_input[1].set_value(None)
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert app.dataframe[0].value[field].tolist() == [30, 30]
    assert app.session_state['compare-profile']['filters']['year_start'] is None


def test_compare_phase_labels_explain_odi_slices(repository):
    app = app_for(repository, 'compare')
    assert app.selectbox[2].options == [
        'All overs',
        'ODI powerplay (overs 1–10)', 'Middle overs (11–40)',
        'Death overs (after 40)',
    ]


def test_compare_year_edits_apply_without_separate_opt_in(repository):
    app = app_for(repository, 'compare')
    app.selectbox[0].select('A').run()
    app.selectbox[1].select('B').run()
    app.button[0].click().run()
    assert app.dataframe[0].value['Balls'].tolist() == [30, 30]
    for year in (2022, 2023):
        app.number_input[0].set_value(year)
        app.number_input[1].set_value(year)
        app.button[0].click().run()
        assert not app.exception and not app.error
        assert app.session_state['compare-profile']['filters']['year_start'] == year
        assert app.dataframe[0].value['Balls'].tolist() == [10, 10]


@pytest.mark.parametrize('endpoint', [0, 1])
def test_compare_single_year_endpoint(repository, endpoint):
    app = app_for(repository, 'compare')
    app.selectbox[0].select('A').run()
    app.selectbox[1].select('B').run()
    app.number_input[endpoint].set_value(2022)
    app.button[0].click().run()
    assert not app.exception and not app.error
    assert app.session_state['compare-profile']['filters']['year_start'] == 2022
    assert app.session_state['compare-profile']['filters']['year_end'] == 2022
    assert app.dataframe[0].value['Balls'].tolist() == [10, 10]


@pytest.mark.parametrize('mode', ['batting', 'bowling'])
def test_venue_filters_apply_on_first_explore_and_later_explores(repository, mode):
    app = app_for(repository, 'venue')
    assert app.expander[0].label == 'Filter bowlers'
    assert not app.dataframe
    app.radio[0].set_value(mode).run()
    app.selectbox[0].select('Arun Jaitley Stadium, Delhi').run()
    app.number_input[0].set_value(0)
    app.number_input[1].set_value(2022)
    app.number_input[2].set_value(2022)
    app.selectbox[3].select('middle')
    app.button[2].click().run()
    assert not app.exception and not app.error
    profile = app.session_state['venue-profile']
    assert profile['filters']['year_start'] == 2022
    assert profile['filters']['phase'] == 'middle'
    assert profile['filters']['minimum_sample'] == 0
    field, player = ('balls_faced', 'A') if mode == 'batting' else ('deliveries', 'X')
    assert next(row[field] for row in profile['leaderboard'] if row['player_name'] == player) == 4
    app.number_input[2].set_value(2023)
    app.button[2].click().run()
    profile = app.session_state['venue-profile']
    assert profile['filters']['year_end'] == 2023
    assert profile['filters']['phase'] == 'middle'
    assert next(row[field] for row in profile['leaderboard'] if row['player_name'] == player) == 8


@pytest.mark.parametrize('mode', ['batting', 'bowling'])
def test_venue_year_edits_apply_without_separate_opt_in(repository, mode):
    app = app_for(repository, 'venue')
    app.radio[0].set_value(mode).run()
    app.selectbox[0].select('Arun Jaitley Stadium, Delhi').run()
    app.button[2].click().run()
    app.number_input[0].set_value(0)
    app.button[0].click().run()
    for year in (2022, 2023, 2024):
        app.number_input[1].set_value(year)
        app.number_input[2].set_value(year)
        app.button[0].click().run()
        assert not app.exception and not app.error
        profile = app.session_state['venue-profile']
        assert profile['filters']['year_start'] == year
        assert profile['filters']['year_end'] == year
        field = 'balls_faced' if mode == 'batting' else 'deliveries'
        player = 'A' if mode == 'batting' else 'X'
        assert next(row[field] for row in profile['leaderboard'] if row['player_name'] == player) == 10
    app.number_input[1].set_value(None)
    app.number_input[2].set_value(None)
    app.button[0].click().run()
    assert app.session_state['venue-profile']['filters']['year_start'] is None
    assert next(row[field] for row in app.session_state['venue-profile']['leaderboard'] if row['player_name'] == player) == 30
    app.number_input[1].set_value(2022)
    app.button[0].click().run()
    assert app.session_state['venue-profile']['filters']['year_end'] == 2022

    # An empty year must remain the applied context on later reruns, rather
    # than resurrecting the previous year's leaderboard.
    app.number_input[1].set_value(1800)
    app.number_input[2].set_value(1800)
    app.button[0].click().run()
    assert app.error and not app.dataframe
    assert app.session_state['venue-profile']['filters']['year_start'] == 1800
    app.run()
    assert app.error and not app.dataframe


def test_venue_batting_mode_preserves_filters_and_reset(repository):
    app = app_for(repository, 'venue')
    app.selectbox[0].select('Arun Jaitley Stadium, Delhi').run()
    app.button[2].click().run()
    assert 'First 6 overs' not in app.selectbox[3].options
    app.number_input[0].set_value(1)
    app.selectbox[3].select('middle')
    app.number_input[1].set_value(2023)
    app.number_input[2].set_value(2024)
    app.button[0].click().run()
    app.radio[0].set_value('batting').run()
    assert not app.exception
    profile = app.session_state['venue-profile']
    assert profile['mode'] == 'batting' and profile['filters']['phase'] == 'middle'
    assert profile['filters']['year_start'] == 2023 and profile['filters']['minimum_sample'] == 1
    assert profile['filters']['sample_unit'] == 'balls_faced'
    assert 'Balls faced' in app.dataframe[0].value
    app.selectbox[2].select('batter_dot_percentage')
    app.button[0].click().run()
    assert app.dataframe[0].value.iloc[0]['Batter'] == 'A'
    elements = list(app.main)
    assert next(i for i,e in enumerate(elements) if e.type == 'plotly_chart') < elements.index(app.dataframe[0])
    app.button[1].click().run()
    assert app.session_state['venue-profile']['mode'] == 'batting'
    assert app.session_state['venue-profile']['filters']['metric'] == 'runs_scored'
    assert app.session_state['venue-profile']['filters']['minimum_sample'] == 24
    assert 'Batting average' in app.dataframe[0].value
    app.radio[0].set_value('bowling').run()
    assert 'Bowling average' in app.dataframe[0].value
