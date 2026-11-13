import duckdb

from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.service import MultiFormatService
from tests.backend.multiformat_fixture import build_fixture_db


def test_fuzzy_names_do_not_consume_cricket_vocabulary(tmp_path):
    path = build_fixture_db(tmp_path)
    with duckdb.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO analytics.players VALUES ('decoy1','ND Pinner','ND Pinner',NULL,NULL), ('decoy2','XA Scorin','XA Scorin',NULL,NULL)"
        )
    chat = MultiFormatChat(MultiFormatService(path))
    for question in [
        "Most scoring rates in franchise leagues",
        "Compare batters against leg spinners in the IPL",
    ]:
        assert not chat.planner.names.spot(question)


def test_existing_surname_precedes_derived_given_name_in_the_same_scope(tmp_path):
    path = build_fixture_db(tmp_path)
    with duckdb.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO analytics.players VALUES ('family','M Fenwick','M Fenwick',NULL,NULL), ('given','P Hales','P Hales',NULL,NULL)"
        )
        conn.execute(
            "INSERT INTO analytics.player_names VALUES ('m fenwick','M Fenwick','family'), ('fenwick hales','Fenwick Hales','given')"
        )
        conn.execute(
            "UPDATE analytics.deliveries SET bowler_id='family' WHERE bowler_id='bowl'"
        )
        conn.execute(
            "INSERT INTO analytics.deliveries SELECT * REPLACE ('given' AS bowler_id) FROM analytics.deliveries WHERE bowler_id='family'"
        )
    chat = MultiFormatChat(MultiFormatService(path))
    plan = chat.planner.read("Fenwick IPL economy")
    assert [
        p["player_id"] for p in chat.planner.names.choose(plan.players[0], plan.scopes)
    ] == ["family"]


def test_scope_can_choose_a_plausible_spelling_over_a_closer_inactive_name(tmp_path):
    path = build_fixture_db(tmp_path)
    with duckdb.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO analytics.players VALUES ('active','A Meriden','A Meriden',NULL,NULL), ('other','C Meridenns','C Meridenns',NULL,NULL)"
        )
        conn.execute(
            "INSERT INTO analytics.player_names VALUES ('a meriden','A Meriden','active'), ('c meridenns','C Meridenns','other')"
        )
        conn.execute(
            "UPDATE analytics.deliveries SET batter_id='active' WHERE batter_id='bat'"
        )
        conn.execute(
            "INSERT INTO analytics.deliveries SELECT * REPLACE ('other' AS batter_id, 'Big Bash League' AS competition) FROM analytics.deliveries WHERE batter_id='active'"
        )
    chat = MultiFormatChat(MultiFormatService(path))
    answer = chat.answer("Meridenn vs B Bowler in the IPL")
    assert answer.query_response.status.value == "supported", answer.message
    assert answer.query_response.interpretation.entities == ["A Meriden", "B Bowler"]
