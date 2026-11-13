"""A tiny multi-format database for backend tests (no dependency on the real build)."""

from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa


def _ball(match, fmt, gender, competition, year, seq, batter, bowler, runs=0, wides=None,
          wicket=False, bowler_wicket=False, length=None, line=None, ll_source=None, player_out=None, kind=None):
    return {
        "match_id": match, "format": fmt, "gender": gender, "competition": competition,
        "year": year, "match_date": date(year, 5, 1), "innings_no": 1, "innings_delivery_seq": seq,
        "batter_id": batter, "bowler_id": bowler, "runs_batter": runs, "runs_total": runs + (wides or 0),
        "wides": wides, "noballs": None, "non_boundary": False, "is_legal": wides is None,
        "is_wicket": wicket, "is_bowler_wicket": bowler_wicket,
        "player_out_id": (player_out or batter) if wicket else None,
        "wicket_kind": (kind or ("run out" if player_out else "bowled")) if wicket else None,
        "length": length, "line": line, "ll_source": ll_source,
    }



def build_fixture_db(tmp_path: Path) -> Path:
    db = tmp_path / "multi.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE SCHEMA analytics")
    balls = [
        # IPL 2018: no line/length; IPL 2020: line/length present
        _ball("m1", "T20 domestic", "male", "Indian Premier League", 2018, 1, "bat", "bowl", runs=4),
        _ball("m1", "T20 domestic", "male", "Indian Premier League", 2018, 2, "bat", "bowl", wides=1),
        _ball("m2", "T20 domestic", "male", "Indian Premier League", 2020, 1, "bat", "bowl", runs=6,
              length="FULL", line="OUTSIDE_OFFSTUMP", ll_source="aucb"),
        _ball("m2", "T20 domestic", "male", "Indian Premier League", 2020, 2, "bat", "bowl", wicket=True,
              bowler_wicket=True, length="GOOD_LENGTH", line="ON_THE_STUMPS", ll_source="aucb"),
        _ball("m3", "T20I", "female", "World Cup", 2024, 1, "bat", "bowl", runs=1),
        # "bat" run out at the non-striker's end off a ball "bat2" faced
        _ball("m2", "T20 domestic", "male", "Indian Premier League", 2020, 3, "bat2", "bowl2", runs=1,
              wicket=True, player_out="bat"),
    ]
    conn.register("b", pa.Table.from_pylist(balls))
    conn.execute("CREATE TABLE analytics.deliveries AS SELECT * FROM b")
    conn.execute(
        "CREATE TABLE analytics.players AS SELECT * FROM (VALUES "
        "('bat', 'A Batter', 'A Batter', 'RHB', NULL), ('bowl', 'B Bowler', 'B Bowler', NULL, 'Right-arm pace')) "
        "t(player_id, name, unique_name, batting_hand, bowling_style_group)"
    )
    conn.execute(
        "CREATE TABLE analytics.data_limitations AS SELECT * FROM (VALUES "
        "('T20 domestic', 'male', 'Length is available from 2019.'), "
        "('T20I', 'female', 'Line and length are not recorded for women''s T20I in any source.')) "
        "t(format, gender, statement)"
    )
    conn.execute("CREATE TABLE analytics.build_info AS SELECT DATE '2026-11-03' AS cricsheet_latest_match")
    conn.execute("CREATE TABLE analytics.coverage_summary AS SELECT 'T20 domestic' AS format, 'male' AS gender, 2 AS matches")
    conn.execute(
        "CREATE TABLE analytics.coverage AS SELECT * FROM (VALUES "
        "('T20 domestic', 'male', 'Indian Premier League', 2), ('T20I', 'female', 'World Cup', 1)) "
        "t(format, gender, competition, matches)"
    )
    conn.execute(
        "CREATE TABLE analytics.player_names AS SELECT * FROM (VALUES "
        "('a batter', 'A Batter', 'bat'), ('alpha batter', 'Alpha Batter', 'bat'), ('b bowler', 'B Bowler', 'bowl')) "
        "t(name_key, name, player_id)"
    )
    conn.close()

    return db
