from __future__ import annotations

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes.explore import router
from backend.app.bootstrap import get_services
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.venue_leaderboard import BATTING_METRICS, METRICS
from backend.app.services.explorer_service import build_player_comparison, build_venue_profile


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / 'modes.duckdb'
    with duckdb.connect(str(path)) as conn:
        conn.execute('CREATE SCHEMA analytics')
        conn.execute('''CREATE TABLE analytics.deliveries_v1 (
            bat VARCHAR, bowl VARCHAR, ground VARCHAR, p_match INTEGER, team_bowl VARCHAR,
            wide INTEGER, noball INTEGER, batruns INTEGER, bowlruns INTEGER,
            dismissal VARCHAR, year INTEGER, over DOUBLE, ballfaced INTEGER,
            out BOOLEAN, control DOUBLE)''')
        rows = []
        for ground in ('Feroz Shah Kotla, Delhi', 'Arun Jaitley Stadium, Delhi'):
            for year in (2022, 2023, 2024):
                for over in (6, 10, 10.1, 40, 40.1):
                    rows.extend([
                        ('A', 'X', ground, year, 'India', 0, 0, 4, 4, 'bowled', year, over, 1, True, 1),
                        ('B', 'Y', ground, year, 'India', 0, 0, 0, 0, 'run out', year, over, 1, True, None),
                        ('C', 'Z', ground, year, 'India', 0, 0, 1, 1, '', year, over, 1, False, 0),
                    ])
        rows.extend([
            ('Extras', 'Extra bowler', 'Feroz Shah Kotla, Delhi', 1, 'India', 0, 0, 0, 1, '', 2023, 10, 1, False, 1),
            ('Extras', 'Extra bowler', 'Arun Jaitley Stadium, Delhi', 1, 'India', 0, 0, 0, 0, '', 2023, 10, 1, False, None),
            ('Extras', 'Extra bowler', 'Arun Jaitley Stadium, Delhi', 1, 'India', 1, 0, 0, 1, '', 2023, 10, 0, False, None),
            ('Extras', 'Extra bowler', 'Arun Jaitley Stadium, Delhi', 1, 'India', 0, 1, 4, 5, '', 2023, 10, 0, False, 0),
            ('Other', 'Other bowler', 'Wankhede Stadium, Mumbai', 2, 'India', 0, 0, 6, 6, 'bowled', 2023, 10, 1, True, 1),
        ])
        conn.executemany('INSERT INTO analytics.deliveries_v1 VALUES (' + ','.join('?' * 15) + ')', rows)
        conn.execute("CREATE VIEW analytics.player_lookup AS SELECT bat AS player_name FROM analytics.deliveries_v1 UNION SELECT bowl FROM analytics.deliveries_v1")
    return AnalyticsRepository(path)


def compare(repository, mode='bowling', **filters):
    return build_player_comparison(repository, ['X', 'Y'] if mode == 'bowling' else ['A', 'B'], mode=mode, **filters)


def test_batting_alias_aggregation_and_missing_averages(repository):
    profile = build_venue_profile(repository, 'in-delhi-kotla', mode='batting')
    assert profile['venue_name'] == 'Arun Jaitley Stadium, Delhi'
    assert profile['filters']['sample_unit'] == 'balls_faced'
    assert profile['leaderboard'] == profile['batting_leaderboard']
    assert profile['bowling_leaderboard'] == []
    a, c, b = profile['leaderboard']
    assert a['runs_scored'] == 120 and a['balls_faced'] == 30
    assert a['dismissals'] == 30 and a['matches'] == 3
    assert a['average'] == 4 and a['strike_rate'] == 400
    assert a['boundary_percentage'] == 100 and a['dot_percentage'] == 0
    assert a['control_percentage'] == 100 and a['control_balls'] == 30
    assert b['control_percentage'] is None and b['control_balls'] == 0
    assert c['average'] is None
    rows = build_venue_profile(repository, 'Feroz Shah Kotla, Delhi', mode='batting', metric='batting_average')['leaderboard']
    assert [r['player_name'] for r in rows] == ['A', 'B']


@pytest.mark.parametrize('phase,balls', [('first6', 2), ('powerplay', 4), ('middle', 4), ('death', 2)])
@pytest.mark.parametrize('mode', ['batting', 'bowling'])
def test_compare_identical_context_and_inclusive_years(repository, phase, balls, mode):
    profile = compare(repository, mode, phase=phase, year_start=2022, year_end=2023, venue='Feroz Shah Kotla, Delhi')
    field = 'balls_faced' if mode == 'batting' else 'deliveries'
    assert [p[field] for p in profile['players']] == [balls * 2, balls * 2]
    assert all(p['matches'] == 2 for p in profile['players'])
    assert profile['filters']['venue'] == 'Arun Jaitley Stadium, Delhi'
    assert all(p['small_sample'] for p in profile['players'])


def test_bowling_calculations_and_missing_values(repository):
    profile = compare(repository)
    x, y = profile['players']
    assert x['deliveries'] == 30 and x['runs_conceded'] == 120 and x['wickets'] == 30
    assert x['bowling_average'] == 4 and x['bowling_strike_rate'] == 1 and x['economy_rate'] == 24
    assert x['boundary_percentage'] == 100 and x['dot_percentage'] == 0
    assert y['bowling_average'] is None and y['bowling_strike_rate'] is None
    assert y['economy_rate'] == 0 and y['dot_percentage'] == 100
    assert profile['ranking']['preference'] == 'Lower is preferable'
    assert not x['small_sample']
    missing = compare(repository, phase='death', year_start=1800, year_end=1800)
    assert len(missing['players']) == 2
    assert all(p['deliveries'] == 0 and p['small_sample'] for p in missing['players'])
    assert all(p.get('economy_rate') is None for p in missing['players'])


def test_extras_use_independent_batting_and_bowling_denominators(repository):
    batting = repository.get_explorer_player_summary('Extras', 'batting')
    assert batting['balls_faced'] == 2 and batting['runs_scored'] == 4
    assert batting['strike_rate'] == 200 and batting['dot_percentage'] == 100
    assert batting['control_balls'] == 1 and batting['control_percentage'] == 100
    assert batting['average'] is None
    bowling = repository.get_explorer_player_summary('Extra bowler', 'bowling')
    assert bowling['deliveries'] == 2 and bowling['runs_conceded'] == 7
    assert bowling['economy_rate'] == 21 and bowling['dot_percentage'] == 50
    assert bowling['boundary_percentage'] == 0


@pytest.mark.parametrize('metric', BATTING_METRICS)
def test_batting_rank_direction_and_sample_before_limit(repository, metric):
    profile = build_venue_profile(repository, 'in-delhi-kotla', mode='batting', metric=metric, minimum_sample=0)
    field = profile['ranking']['field']
    values = [row[field] for row in profile['leaderboard']]
    assert all(v is not None for v in values)
    assert values == sorted(values, reverse=profile['ranking']['direction'] == 'desc')
    limited = build_venue_profile(repository, 'in-delhi-kotla', mode='batting', metric=metric,
                                  sample_unit='matches', minimum_sample=2, limit=1)
    assert limited['leaderboard'] == [r for r in profile['leaderboard'] if r['matches'] >= 2][:1]
    assert build_venue_profile(repository, 'in-delhi-kotla', mode='batting', metric=metric,
                              minimum_sample=24, phase='death')['leaderboard'] == []


@pytest.mark.parametrize('mode,catalog', [('batting', BATTING_METRICS), ('bowling', METRICS)])
def test_comparison_metric_metadata(repository, mode, catalog):
    for metric, (_, field, direction) in catalog.items():
        profile = compare(repository, mode, metric=metric)
        assert profile['ranking']['field'] == field and profile['ranking']['direction'] == direction
        assert len(profile['players']) == 2


def test_api_shared_contract_validation_and_switching(repository):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_services] = lambda: {'repository': repository}
    with TestClient(app) as client:
        context = dict(phase='middle', year_start=2022, year_end=2023)
        for mode in ('batting', 'bowling'):
            response = client.get('/api/compare', params={**context, 'mode': mode, 'player': ['A', 'B']})
            assert response.status_code == 200
            assert response.json() == build_player_comparison(repository, ['A', 'B'], mode=mode, **context)
            response = client.get('/api/venues/in-delhi-kotla', params={**context, 'mode': mode})
            assert response.status_code == 200
            assert response.json() == build_venue_profile(repository, 'in-delhi-kotla', mode=mode, **context)
        for bad in ({'mode': 'other'}, {'phase': 'typo'}, {'year_start': 2023},
                    {'year_start': 2024, 'year_end': 2023}, {'metric': 'typo'}):
            assert client.get('/api/compare', params={'player': ['X', 'Y'], **bad}).status_code == 422
            assert client.get('/api/venues/in-delhi-kotla', params=bad).status_code == 422
        assert client.get('/api/compare', params={'player': ['X', 'X']}).status_code == 422
        assert client.get('/api/compare', params={'player': ['X']}).status_code == 422
        assert client.get('/api/venues/in-delhi-kotla', params={'mode': 'batting', 'sample_unit': 'legal_balls'}).status_code == 422
