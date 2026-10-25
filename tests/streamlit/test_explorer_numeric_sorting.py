from copy import deepcopy

import pandas as pd
import pytest

from tests.backend.test_explorer_modes import repository  # noqa: F401
from tests.streamlit.test_explorer_mode_controls import app_for


@pytest.mark.parametrize('surface', ['venue', 'compare'])
@pytest.mark.parametrize('mode', ['batting', 'bowling'])
def test_explorer_rates_remain_numeric_for_table_sorting(repository, surface, mode):
    app = app_for(repository, surface)
    app.radio[0].set_value(mode).run()
    if surface == 'venue':
        app.selectbox[0].select('Arun Jaitley Stadium, Delhi').run()
        next(button for button in app.button if button.label == 'Explore venue').click().run()
    else:
        first, second = ('A', 'B') if mode == 'batting' else ('X', 'Y')
        app.selectbox[0].select(first).run()
        app.selectbox[1].select(second).run()
        app.button[0].click().run()
    assert not app.exception
    table = app.dataframe[0].value
    columns = ['Batting average', 'Strike Rate', 'Control %', 'Dot %', 'Boundary %'] if mode == 'batting' else [
        'Bowling average', 'Economy', 'Bowling strike rate', 'Dot %', 'Boundary % conceded',
    ]
    for column in columns:
        assert pd.api.types.is_numeric_dtype(table[column]), (surface, mode, column, table[column].tolist())


def test_venue_average_sorts_reported_values_numerically(repository, monkeypatch):
    import streamlit_venue_explorer as module
    original = module.load_venue_profile
    values = [None, 101.0, 26.0, 27.0, 32.0, 35.5, 37.25, 40.0, 45.0, 82.0]

    def load(*args, **kwargs):
        profile = original(*args, **kwargs)
        if profile['mode'] == 'batting':
            template = profile['leaderboard'][0]
            profile['leaderboard'] = [dict(deepcopy(template), player_name=f'Batter {i}', average=value)
                                      for i, value in enumerate(values)]
        return profile

    monkeypatch.setattr(module, 'load_venue_profile', load)
    app = app_for(repository, 'venue')
    app.radio[0].set_value('batting').run()
    app.selectbox[0].select('Arun Jaitley Stadium, Delhi').run()
    next(button for button in app.button if button.label == 'Explore venue').click().run()
    table = app.dataframe[0].value
    averages = table['Batting average']
    assert pd.api.types.is_numeric_dtype(averages)
    assert pd.isna(averages.iloc[0])  # Undefined average stays missing, never zero or text.
    expected = [26.0, 27.0, 32.0, 35.5, 37.25, 40.0, 45.0, 82.0, 101.0]
    assert averages.sort_values().dropna().tolist() == expected
    assert averages.sort_values(ascending=False).dropna().tolist() == expected[::-1]
