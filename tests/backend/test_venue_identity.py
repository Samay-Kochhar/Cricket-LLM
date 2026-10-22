from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.schemas import CricketQueryPlan
from backend.app.cricket_analytics.venue_resolution import same_venue_family, venue_alias_matches
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.venues import REGISTRY, VENUES, resolve_venue, venue_filter
from backend.app.services.explorer_service import build_venue_profile


KNOWN_IDS = [
    'in-ahmedabad-motera', 'in-delhi-kotla', 'lc-gros-islet-beausejour',
    'za-bloemfontein-oval', 'in-bengaluru-chinnaswamy', 'za-gqeberha-st-georges',
    'bd-chattogram-divisional', 'ae-sharjah-stadium', 'ae-abu-dhabi-zayed',
    'gb-southampton-bowl', 'nz-wellington-regional',
]
GROUPS = [v for v in VENUES if v.id in KNOWN_IDS]
ADDITIONAL_GROUPS = [v for v in VENUES if v.id not in KNOWN_IDS and len(v.aliases) > 1]
ALL_GROUPS = GROUPS + ADDITIONAL_GROUPS


@pytest.fixture(scope="module")
def repository(tmp_path_factory) -> AnalyticsRepository:
    # Every test only reads this synthetic dataset. Share its construction.
    path = tmp_path_factory.mktemp("venue-identities") / "venues.duckdb"
    with duckdb.connect(str(path)) as conn:
        conn.execute('CREATE SCHEMA analytics')
        conn.execute('''CREATE TABLE analytics.deliveries_v1 (
            ground VARCHAR, p_match INTEGER, inns INTEGER, team_bat VARCHAR,
            team_bowl VARCHAR, bat VARCHAR, bowl VARCHAR, ballfaced INTEGER,
            wide INTEGER, noball INTEGER, batruns INTEGER, bowlruns INTEGER,
            dismissal VARCHAR, out BOOLEAN, control INTEGER, length VARCHAR
        )''')
        rows = []
        for group_index, venue in enumerate(ALL_GROUPS):
            for alias_index, alias in enumerate(venue.aliases):
                # Same match can use two source names: distinct matches MUST use
                # the union, not a sum of per-alias distinct-match counts.
                for match in (group_index * 10, group_index * 10 + alias_index + 1):
                    rows.extend([(alias, match, 1, 'India', 'Australia', 'Batter', 'Bowler',
                                 1, 0, 0, 2, 2, 'bowled', True, 1, 'YORKER')] * 24)
        rows.append(('Other ground, Delhi', 9999, 1, 'India', 'Australia', 'Batter', 'Bowler',
                     1, 0, 0, 1000, 1000, 'bowled', True, 1, 'YORKER'))
        conn.executemany('INSERT INTO analytics.deliveries_v1 VALUES (' + ','.join('?' * 16) + ')', rows)
    return AnalyticsRepository(path)


@pytest.mark.parametrize('venue', ALL_GROUPS, ids=lambda v: v.id)
def test_aliases_ids_and_current_names_share_statistics(repository, venue):
    expected_rows = len(venue.aliases) * 48
    expected_matches = len(venue.aliases) + 1
    for name in (*venue.aliases, venue.id):
        result = repository.get_venue_bowling_leaderboard(name)
        assert len(result) == 1
        assert result[0]['delivery_rows'] == expected_rows
        assert result[0]['deliveries'] == expected_rows
        assert result[0]['runs_conceded'] == expected_rows * 2
        where, params = repository._batter_where_clause('Batter', venue=name)
        assert repository._fetchone('SELECT count(*), count(DISTINCT p_match) FROM analytics.deliveries_v1' + where, params) == (expected_rows, expected_matches)
        if name != venue.id:
            assert repository.search_venues(name)[0] == venue.display_name
    assert venue.display_name in repository.list_venues()
    assert all(a not in repository.list_venues() for a in venue.aliases if a != venue.display_name)
    assert build_venue_profile(repository, venue.aliases[-1])['venue_id'] == venue.id
    assert build_venue_profile(repository, venue.aliases[-1])['venue_name'] == venue.display_name


@pytest.mark.parametrize('venue', ALL_GROUPS, ids=lambda v: v.id)
def test_old_multi_alias_state_and_grouped_aggregates_do_not_duplicate(repository, venue):
    filters = {'venues': [*venue.aliases, venue.display_name, venue.id]}
    plan = CricketQueryPlan(operation='aggregate', entity='venue', metric='runs_scored',
                            group_by=['venue'], filters=filters)
    query = build_aggregate_query(plan)
    rows = repository._fetchall(query.sql, query.params)
    assert len(rows) == 1
    assert rows[0][0] == venue.display_name
    assert rows[0][1] == len(venue.aliases) + 1  # distinct matches
    assert rows[0][3] == len(venue.aliases) * 48  # balls faced
    # A single historical filter is equivalent to old plural conversation state.
    single = build_aggregate_query(plan.model_copy(update={'filters': {'venue': venue.aliases[-1]}}))
    assert repository._fetchall(single.sql, single.params) == rows


@pytest.mark.parametrize('left,right', [
    ('Basin Reserve, Wellington', 'Westpac Stadium, Wellington'),
    ('Brabourne Stadium, Mumbai', 'Wankhede Stadium, Mumbai'),
    ('MA Aziz Stadium, Chittagong', 'Chittagong Divisional Stadium'),
    ('Vidarbha Cricket Association Ground, Nagpur', 'Vidarbha Cricket Association Stadium, Jamtha, Nagpur'),
    ('Madhavrao Scindia Cricket Ground, Rajkot', 'Saurashtra Cricket Association Stadium, Rajkot'),
    ('Sector 16 Stadium, Chandigarh', 'Punjab Cricket Association Stadium, Mohali, Chandigarh'),
    ('Hagley Oval, Christchurch', 'AMI Stadium, Christchurch'),
    ('Melbourne Cricket Ground', 'Docklands Stadium, Melbourne'),
    ('Perth Stadium', 'Western Australia Cricket Association Ground, Perth'),
    ('Maple Leaf North-West Ground, Toronto', 'Toronto Cricket, Skating and Curling Club'),
    ('Sportpark Westvliet, Voorburg', 'Sportpark Duivesteijn, Voorburg'),
    ('Khan Shaheb Osman Ali Stadium, Fatullah', 'Khan Shaheb Osman Ali Stadium Outer Ground, Fatullah'),
    ('ICC Academy Ground 1, Dubai', 'ICC Academy Ground No 2, Dubai'),
    ('Mulpani Cricket Ground', 'Lower Mulpani Cricket Stadium'),
    ('Reliance Stadium, Vadodara', 'Kotambi Stadium, Vadodara'),
    ('Kinrara Academy Oval, Kuala Lumpur', 'Bayuemas Oval, Kuala Lumpur'),
    ('Al Amerat Cricket Ground Oman Cricket (Ministry Turf 1)', 'Al Amerat Cricket Ground Oman Cricket (Ministry Turf 2)'),
    ('The Oval, Unknown City', 'The Oval, Another City'),
])
def test_unrelated_grounds_never_merge_by_city_or_similar_name(left, right):
    assert not same_venue_family([left, right])
    assert resolve_venue(left).id != resolve_venue(right).id
    assert right not in venue_filter([left])[1]


def test_alias_recognition_obeys_availability_and_deduplicates():
    names = [v.display_name for v in GROUPS]
    assert venue_alias_matches('Compare at Feroz Shah Kotla and Arun Jaitley', names) == ['Arun Jaitley Stadium, Delhi']
    assert venue_alias_matches('At Goodyear Park', names) == ['Mangaung Oval, Bloemfontein']
    assert venue_alias_matches('At Goodyear Park', ['Lord\'s, London']) == []
    assert venue_alias_matches('At Rose Bowl and Sky Stadium', names) == ['Utilita Bowl, Southampton', 'Hnry Stadium, Wellington']
    assert venue_alias_matches('At chinnaswamy', names) == ['M Chinnaswamy Stadium, Bengaluru']


def test_registry_integrity_and_provenance():
    assert len({v.id for v in VENUES}) == len(VENUES)
    assert len(GROUPS) == 11
    for row in REGISTRY:
        assert row['notes']
        if row['status'] == 'verified':
            assert row['sources']
            assert date.fromisoformat(row['verified_on']).isoformat() == row['verified_on']
        else:
            assert len(row['aliases']) == 1


def test_upper_mulpani_odi_uses_current_board_name_not_suspended_rename():
    venue = resolve_venue('Mulpani Cricket Ground')
    assert resolve_venue('Upper Mulpani Cricket Ground') == venue
    assert resolve_venue('Mulpani International Cricket Ground') == venue
    assert venue.display_name == 'Mulpani International Cricket Ground, Kathmandu'
    metadata = next(row for row in REGISTRY if row['id'] == venue.id)
    assert 'Jayakumar Shah International Cricket Ground' in metadata['suspended_name_proposals']
    assert all('Shah' not in name for name in venue.aliases)
    assert resolve_venue('Lower Mulpani Cricket Stadium').id != venue.id


def test_former_kinrara_ground_keeps_historical_links_without_replacement_merge():
    venue = resolve_venue('Kinrara Academy Oval, Kuala Lumpur')
    assert resolve_venue('Kinrara Academy Oval, Puchong') == venue
    metadata = next(row for row in REGISTRY if row['id'] == venue.id)
    assert metadata['lifecycle'] == 'former_cricket_venue'
    assert metadata['verification_scope'] == 'verified_historical_name'
    assert resolve_venue('Bayuemas Oval, Kuala Lumpur').id != venue.id


@pytest.mark.parametrize('row', [row for row in REGISTRY if row.get('legacy_ids')], ids=lambda r: r['id'])
def test_consolidation_preserves_old_ids_and_filters(repository, row):
    venue = resolve_venue(row['id'])
    assert venue.display_name in repository.list_venues()
    for old_id in row['legacy_ids']:
        assert resolve_venue(old_id) == venue
        assert venue_filter([old_id]) == venue_filter([venue.id])
        assert build_venue_profile(repository, old_id)['venue_id'] == venue.id
    assert repository._fetchone('SELECT count(*) FROM analytics.deliveries_v1 WHERE ' +
        venue_filter([*row['legacy_ids'], venue.id])[0],
        venue_filter([*row['legacy_ids'], venue.id])[1])[0] == len(venue.aliases) * 48


def test_new_unreviewed_names_have_the_same_identity_in_python_and_sql(repository):
    from backend.app.domain.venues import venue_id_sql, venue_display_sql

    name = 'Other ground, Delhi'
    identity, display, count = repository._fetchone(
        f'SELECT {venue_id_sql()}, {venue_display_sql(venue_id_sql())}, count(*) '
        f'FROM analytics.deliveries_v1 WHERE ground = ? GROUP BY {venue_id_sql()}', [name]
    )
    assert identity == resolve_venue(name).id
    assert display == name
    assert count == 1


def test_match_fact_identity_accepts_historical_aliases_but_rejects_other_grounds():
    from backend.app.cricket_analytics.match_facts import MatchMetadataCandidate, resolve_match_fact

    class Metadata:
        def match_metadata_candidates(self, **kwargs):
            return [MatchMetadataCandidate(
                match_id='123', years=('2023',), dates=('2023-11-19',),
                competitions=('ICC Cricket World Cup',),
                grounds=('Narendra Modi Stadium, Ahmedabad', 'Sardar Patel Stadium, Motera, Ahmedabad'),
                winners=('Australia',), toss_winners=('Australia',), teams=('India', 'Australia'),
            )]

    arguments = dict(year=2023, competition='ICC Cricket World Cup', stage='final', fact_type='toss')
    result = resolve_match_fact(Metadata(), venue='Sardar Patel Stadium, Motera, Ahmedabad', **arguments)
    assert result.status == 'resolved'
    assert result.ground == 'Narendra Modi Stadium, Ahmedabad'
    wrong = resolve_match_fact(Metadata(), venue='Wankhede Stadium, Mumbai', **arguments)
    assert wrong.status == 'data_limitation'


def test_venue_explorer_selector_hides_historical_names(repository):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''import streamlit as st
from streamlit_venue_explorer import render_venue_explorer
render_venue_explorer({'repository': st.session_state.repository})
''')
    app.session_state.repository = repository
    app.run()
    assert not app.exception
    options = app.selectbox[0].options
    assert 'Arun Jaitley Stadium, Delhi' in options
    assert 'Feroz Shah Kotla, Delhi' not in options
    assert 'Utilita Bowl, Southampton' in options
    assert 'The Rose Bowl, Southampton' not in options
    app.selectbox[0].select('Arun Jaitley Stadium, Delhi').run()
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state['venue-profile']['venue_id'] == 'in-delhi-kotla'
    assert app.session_state['venue-profile']['venue_name'] == 'Arun Jaitley Stadium, Delhi'
