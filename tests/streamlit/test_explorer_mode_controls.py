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
    app.selectbox[2].select('middle').run()
    app.selectbox[3].select('Arun Jaitley Stadium, Delhi').run()
    app.checkbox[0].check().run()
    app.number_input[0].set_value(2022).run()
    app.number_input[1].set_value(2023).run()
    app.selectbox[4].select('bowling_average').run()
    app.button[0].click().run()
    assert not app.exception
    profile = app.session_state['compare-profile']
    assert profile['filters'] == dict(phase='middle', venue='Arun Jaitley Stadium, Delhi', year_start=2022, year_end=2023)
    assert [p['deliveries'] for p in profile['players']] == [8, 8]
    assert app.dataframe[0].value.iloc[1]['Bowling average'] == '—'
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


def test_venue_batting_mode_preserves_filters_and_reset(repository):
    app = app_for(repository, 'venue')
    app.selectbox[0].select('Arun Jaitley Stadium, Delhi').run()
    app.button[0].click().run()
    app.number_input[0].set_value(1).run()
    app.selectbox[3].select('middle').run()
    app.checkbox[0].check().run()
    app.number_input[1].set_value(2023).run()
    app.number_input[2].set_value(2024).run()
    app.button[1].click().run()
    app.radio[0].set_value('batting').run()
    assert not app.exception
    profile = app.session_state['venue-profile']
    assert profile['mode'] == 'batting' and profile['filters']['phase'] == 'middle'
    assert profile['filters']['year_start'] == 2023 and profile['filters']['minimum_sample'] == 1
    assert profile['filters']['sample_unit'] == 'balls_faced'
    assert 'Balls faced' in app.dataframe[0].value
    app.selectbox[2].select('batter_dot_percentage').run()
    app.button[1].click().run()
    assert app.dataframe[0].value.iloc[0]['Batter'] == 'A'
    elements = list(app.main)
    assert next(i for i,e in enumerate(elements) if e.type == 'plotly_chart') < elements.index(app.dataframe[0])
    app.button[2].click().run()
    assert app.session_state['venue-profile']['mode'] == 'batting'
    assert app.session_state['venue-profile']['filters']['metric'] == 'runs_scored'
    assert app.session_state['venue-profile']['filters']['minimum_sample'] == 24
    assert 'Batting average' in app.dataframe[0].value
    app.radio[0].set_value('bowling').run()
    assert 'Bowling average' in app.dataframe[0].value
