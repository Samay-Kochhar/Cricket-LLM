"""Independent intent and execution regressions; generated databases only."""
from datetime import date
from pathlib import Path
import duckdb
import pytest
from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.service import DeliveryFilter, MultiFormatService
from backend.app.multiformat import execution
from tests.backend.multiformat_fixture import build_fixture_db

@pytest.fixture
def service(tmp_path):
    path=build_fixture_db(tmp_path)
    c=duckdb.connect(str(path))
    for col,typ in [('over_no','INTEGER'),('legal_ball_in_over','INTEGER'),('non_striker_id','VARCHAR'),('venue','VARCHAR'),('is_super_over','BOOLEAN'),('bowler_style_code','VARCHAR'),('bowler_arm','VARCHAR'),('bowler_kind','VARCHAR'),('batting_team','VARCHAR'),('bowling_team','VARCHAR')]:
        c.execute(f'ALTER TABLE analytics.deliveries ADD COLUMN {col} {typ}')
    c.execute("UPDATE analytics.deliveries SET over_no=0,legal_ball_in_over=1,non_striker_id='bat2',venue='Sample Ground',is_super_over=false,bowler_style_code='LF',bowler_arm='left',bowler_kind='pace'")
    c.execute("INSERT INTO analytics.players VALUES ('bat2','S Partner','S Partner','RHB',NULL),('best','TL Best','TL Best',NULL,'pace'),('smith','SPD Smith','SPD Smith','RHB',NULL),('bumrah','JJ Bumrah','JJ Bumrah',NULL,'pace')")
    c.execute("INSERT INTO analytics.player_names VALUES ('s partner','S Partner','bat2'),('tl best','TL Best','best'),('spd smith','SPD Smith','smith'),('jj bumrah','JJ Bumrah','bumrah')")
    c.close()
    return MultiFormatService(path)

@pytest.fixture
def chat(service): return MultiFormatChat(service)

def rows(answer):
    return [dict(zip(t.columns,r)) for t in answer.query_response.tables for r in t.rows]

@pytest.mark.parametrize('question,role,styles',[
    ('Alpha Batter against left-arm fast bowling in the IPL','batting',['LF','LFM']),
    ('Alpha Batter against left-arm medium pace in the IPL','batting',['LM','LMF']),
    ('Alpha Batter against leg spinners in T20 cricket','batting',['LB','LBG']),
    ('B Bowler bowling strike rate in the IPL','bowling',[]),
])
def test_role_is_subject_not_opponent_style(chat,question,role,styles):
    p=chat.planner.read(question)
    assert p.role==role
    assert p.bowler_styles==styles

@pytest.mark.parametrize('question,name',[
    ('Steve Peter Devereux Smith Test average','smith'),
    ('Jasprit Bumra T20I economy','bumrah'),
])
def test_initials_and_fuzzy_name_resolution(chat,question,name):
    p=chat.planner.read(question)
    assert len(p.players)==1
    assert chat.planner.names.choose(p.players[0])[0]['player_id']==name


def test_best_is_not_player_best(chat):
    p=chat.planner.read('Best IPL strike rates (minimum 500 balls)')
    assert p.intent=='ranking' and p.players==[] and p.min_balls==500


def test_disjoint_year_union(chat):
    p=chat.planner.read('Alpha Batter IPL runs in 2018 and 2024')
    assert p.years==[2018,2024] and p.year_from is None and p.year_to is None
    a=chat.answer('Alpha Batter IPL runs in 2018 and 2024')
    assert sum(r['runs'] for r in rows(a))==4


def test_ranking_minimum_is_enforced(chat):
    a=chat.answer('Best IPL strike rates (minimum 500 balls)')
    assert not a.query_response.tables
    assert any('500' in n.detail for n in a.query_response.evidence_notes)

@pytest.mark.parametrize('fmt,phase,expected',[
    ('T20 domestic','powerplay',[0,5]),('T20 domestic','middle',[6,14]),('T20 domestic','death',[15,19]),
    ('ODI','powerplay',[0,5,6]),('ODI','middle',[14,15,19,39]),('ODI','death',[40,49]),
])
def test_zero_based_over_phase_boundaries(tmp_path,fmt,phase,expected):
    c=duckdb.connect()
    c.execute('CREATE SCHEMA analytics')
    c.execute('CREATE TABLE analytics.deliveries(format VARCHAR,over_no INTEGER,legal_ball_in_over INTEGER)')
    c.executemany('INSERT INTO analytics.deliveries VALUES (?, ?, 1)',[(fmt,n) for n in [0,5,6,14,15,19,39,40,49]])
    where,params=DeliveryFilter(phase=phase).sql()
    got=[r[0] for r in c.execute(f'SELECT over_no FROM analytics.deliveries d WHERE {where}',params).fetchall()]
    # Boundaries apply to valid scheduled overs of the chosen format.
    if fmt=='T20 domestic': got=[n for n in got if n<20]
    assert got==expected

@pytest.mark.parametrize('phase,expected',[('powerplay',[25]),('middle',[26,75]),('death',[76,100])])
def test_hundred_uses_five_ball_sets(phase,expected):
    c=duckdb.connect()
    c.execute('CREATE TABLE balls(format VARCHAR,over_no INTEGER,legal_ball_in_over INTEGER,n INTEGER)')
    c.executemany('INSERT INTO balls VALUES (?, ?, ?, ?)',[('The Hundred',(n-1)//5,(n-1)%5+1,n) for n in [25,26,75,76,100]])
    where,params=DeliveryFilter(phase=phase).sql()
    assert [r[0] for r in c.execute(f'SELECT n FROM balls d WHERE {where}',params).fetchall()]==expected


def test_repeated_pair_stands_and_runout_runs(service):
    with duckdb.connect(str(service.db_path)) as c:
        c.execute('DELETE FROM analytics.deliveries WHERE match_id != ?', ['m1'])
        c.execute("UPDATE analytics.deliveries SET non_striker_id='bat2'")
        # A/B stand (4+1 wide), A/C stand (2, non-striker run out), A/B return (3).
        c.execute("INSERT INTO analytics.deliveries SELECT * REPLACE (3 AS innings_delivery_seq,'bowl' AS non_striker_id,2 AS runs_total,2 AS runs_batter,NULL AS wides,true AS is_legal,true AS is_wicket,'bowl' AS player_out_id,'run out' AS wicket_kind,false AS is_bowler_wicket) FROM analytics.deliveries WHERE innings_delivery_seq=1")
        c.execute("INSERT INTO analytics.deliveries SELECT * REPLACE (4 AS innings_delivery_seq,3 AS runs_total,3 AS runs_batter) FROM analytics.deliveries WHERE innings_delivery_seq=1")
    result,_=execution.partnerships(service,DeliveryFilter(competition='Indian Premier League'),['bat','bat2'])
    assert result[0]['stands']==2
    assert result[0]['partnership_runs']==8 and result[0]['best_stand']==5
    stats=execution.aggregate(service,DeliveryFilter(competition='Indian Premier League'),'bowling','bowl')
    assert stats[0]['wickets']==0


def test_comparison_preserves_targets_and_explicit_gender(chat):
    p=chat.planner.read("Compare Alpha Batter and B Bowler in women's T20Is")
    assert p.intent=='comparison' and len(p.players)==2
    assert p.scopes[0].gender=='female'
    a=chat.answer("Compare Alpha Batter and B Bowler in women's T20Is")
    assert all(r.get('gender')=='female' for r in rows(a))


def test_coverage_first_dates_are_competition_specific(service):
    r=execution.coverage(service,DeliveryFilter(competition='Indian Premier League'))
    first=next(x for x in r if x['year']==2020)
    assert first['first_length']==date(2020,5,1)
    assert first['first_line']==date(2020,5,1)
    assert next(x for x in r if x['year']==2018)['first_length'] is None

@pytest.mark.parametrize('unsupported_request',['predict win probability','fielding catches','weather forecast','player salaries'])
def test_explicit_unsupported_never_substitutes_stats(chat,unsupported_request):
    a=chat.answer('Alpha Batter IPL '+unsupported_request)
    assert not a.query_response.tables
    assert a.query_response.status.value=='unsupported'


def test_evidence_is_source_free_and_general_note_last(chat):
    a=chat.answer('Alpha Batter IPL runs')
    assert a.query_response.evidence_notes[-1].title=='Afghanistan coverage'
    text=a.message.lower()
    assert not any(s in text for s in ['cricsheet','tigzig','aucb','espn'])


def test_every_venue_row_respects_requested_ground(service,chat):
    with duckdb.connect(str(service.db_path)) as c:
        c.execute("UPDATE analytics.deliveries SET venue='Other Ground' WHERE year=2018")
    answer=chat.answer('Average first-innings score at Sample Ground in the IPL')
    assert rows(answer) and all(r['venue']=='Sample Ground' for r in rows(answer))


def test_outside_off_includes_wide_category(chat):
    p=chat.planner.read('Alpha Batter against balls outside off stump in the IPL')
    assert set(p.lines)=={'OUTSIDE_OFFSTUMP','WIDE_OUTSIDE_OFFSTUMP'}


def test_six_runs_without_boundary_are_not_a_six(service):
    with duckdb.connect(str(service.db_path)) as c:
        c.execute('UPDATE analytics.deliveries SET non_boundary=true WHERE runs_batter=6')
    r=execution.aggregate(service,DeliveryFilter(competition='Indian Premier League'),'batting','bat')
    assert r[0]['runs']==10 and r[0]['sixes']==0


def test_hundred_wide_after_powerplay_is_not_in_powerplay():
    # Stored count is legal balls completed in this five-ball set: zero before
    # its first legal delivery. This wide belongs to ball 26, after the PP.
    c=duckdb.connect()
    c.execute("CREATE TABLE balls AS SELECT 'The Hundred' format,5 over_no,0 legal_ball_in_over")
    where,params=DeliveryFilter(phase='powerplay').sql()
    assert c.execute(f'SELECT count(*) FROM balls d WHERE {where}',params).fetchone()[0]==0


def test_afghan_player_limitation_is_prominent_and_also_last_evidence(service,chat):
    with duckdb.connect(str(service.db_path)) as c:
        c.execute("UPDATE analytics.deliveries SET batting_team='Afghanistan' WHERE format='T20I'")
    answer=chat.answer("Alpha Batter women's T20I runs")
    headline=answer.message.split('Evidence & limitations')[0]
    assert 'Data for Afghanistan players is limited' in headline
    assert answer.query_response.evidence_notes[-1].title=='Afghanistan coverage'


def test_validation_rejects_invalid_role_metric_without_rewriting_or_stats(chat):
    from backend.app.multiformat.answers import answer_plan
    from backend.app.multiformat.plans import UnderstandingPlan,ScopePlan
    plan=UnderstandingPlan(players=['A Batter'],role='batting',metrics=['economy'],scopes=[ScopePlan(label='IPL',competition='Indian Premier League')])
    before=plan.model_dump()
    _,response,_=answer_plan(chat,'A Batter IPL economy',plan)
    assert plan.model_dump()==before
    assert response.status.value=='unsupported' and not response.tables
