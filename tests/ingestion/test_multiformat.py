from ingestion.app.multiformat.align import Ball, align_innings, align_sequences, name_key
from ingestion.app.multiformat.commentary import parse
from ingestion.app.multiformat.cricsheet import classify_format, parse_match


def ball(key, over, batter="A Batter", bowler="B Bowler", runs=0, extras=0, wide=False, noball=False, wicket=False):
    return Ball(key, over, name_key(batter), name_key(bowler), runs, extras, wide, noball, wicket)


def test_name_key_folds_initials_accents_and_hyphens() -> None:
    assert name_key("V Kohli") == ("kohli", "v")
    assert name_key("Virat Kohli") == ("kohli", "v")
    assert name_key("Naveen-ul-Haq") == name_key("Naveen ul-Haq") == ("haq", "n")
    assert name_key("Pathum Nissanka")[0] == name_key("P Nissanka")[0]
    assert name_key(None) is None


def test_alignment_skips_a_ball_missing_from_the_source() -> None:
    cs = [ball(1, 0, runs=0), ball(2, 0, runs=4), ball(3, 0, runs=1), ball(4, 0, runs=0)]
    src = [ball(11, 0, runs=0), ball(13, 0, runs=1), ball(14, 0, runs=0)]  # the four is missing
    pairs = align_sequences(src, cs)
    assert [(src[i].key, cs[j].key) for i, j, _ in pairs] == [(11, 1), (13, 3), (14, 4)]


def test_alignment_rejects_a_different_bowler() -> None:
    cs = [ball(1, 0, bowler="JJ Bumrah")]
    src = [ball(1, 0, bowler="Mitchell Starc")]
    assert align_sequences(src, cs) == []


def test_unknown_runs_are_neutral_not_a_mismatch() -> None:
    cs = [ball(1, 0, runs=4)]
    src = [Ball(1, 0, name_key("A Batter"), name_key("B Bowler"), None, None, False, False, False)]
    assert len(align_sequences(src, cs)) == 1


def test_innings_alignment_detects_shifted_over_numbers() -> None:
    # odata's older fixtures number overs from 0; after the usual 1-based shift
    # their over k lands on Cricsheet over k + 1.
    cs = [ball(o * 10 + b, o, bowler=f"Bowler{'AB'[o % 2]}", runs=b % 3) for o in range(4) for b in range(6)]
    src = [ball(o * 10 + b, o - 1, bowler=f"Bowler{'AB'[o % 2]}", runs=b % 3) for o in range(1, 4) for b in range(6)]
    result = align_innings(src, cs)
    assert len(result.pairs) == 18
    assert all(s == c for s, c, _ in result.pairs)


def test_commentary_parser_reads_names_runs_length_line_footwork() -> None:
    p = parse(
        "FOUR! Blessing Muzarabani to Kusal Perera. Back of a length, outside off stump on the front foot "
        "pulling, well timed in the air under control past deep mid wicket for 4 runs."
    )
    assert (p.bowler, p.batter, p.runs) == ("Blessing Muzarabani", "Kusal Perera", 4)
    assert (p.length, p.line, p.footwork) == ("BackOfALength", "OutsideOff", "FrontFoot")


def test_commentary_parser_handles_wides_and_dismissal_prefixes() -> None:
    wide = parse("Wide Kagiso Rabada to Virat Kohli. Short, outside off stump down the track Leave, Left for 1 run.")
    assert wide.is_wide and wide.bowler == "Kagiso Rabada" and wide.runs == 1
    out = parse("OUT! Caught. Akeal Hosein to Hassan Nawaz. Arm length ball, wide outside off stump on the back foot cutting, caught by Charles.")
    assert (out.bowler, out.batter, out.length, out.line) == ("Akeal Hosein", "Hassan Nawaz", "LengthBall", "Wide")


def test_commentary_parser_refuses_free_text_without_names() -> None:
    assert parse("Round the wicket. Full, middle stump, front foot, worked along the ground to Imam-ul-Haq at square leg. 1 run.") is None


def test_classify_format() -> None:
    assert classify_format("T20", "international", 6, "ICC Men's T20 World Cup") == "T20I"
    assert classify_format("T20", "club", 6, "Indian Premier League") == "T20 domestic"
    assert classify_format("T20", "club", 5, "The Hundred Men's Competition") == "The Hundred"
    assert classify_format("MDM", "club", 6, "County Championship") == "First-class domestic"
    assert classify_format("ODM", "club", 6, "Royal London One-Day Cup") == "List A domestic"


def test_parse_match_counts_legal_balls_and_bowler_wickets() -> None:
    payload = {
        "meta": {"data_version": "1.1.0", "revision": 1},
        "info": {
            "match_type": "T20", "gender": "male", "team_type": "international", "balls_per_over": 6,
            "dates": ["2024-06-29"], "teams": ["India", "South Africa"], "event": {"name": "World Cup"},
            "registry": {"people": {"A": "id-a", "B": "id-b", "C": "id-c"}},
            "players": {"India": ["A", "C"], "South Africa": ["B"]},
            "outcome": {"winner": "India", "by": {"runs": 7}}, "toss": {"winner": "India", "decision": "bat"},
            "venue": "Kensington Oval",
        },
        "innings": [{
            "team": "India",
            "overs": [{"over": 0, "deliveries": [
                {"batter": "A", "bowler": "B", "non_striker": "C", "runs": {"batter": 0, "extras": 1, "total": 1}, "extras": {"wides": 1}},
                {"batter": "A", "bowler": "B", "non_striker": "C", "runs": {"batter": 4, "extras": 0, "total": 4}},
                {"batter": "A", "bowler": "B", "non_striker": "C", "runs": {"batter": 0, "extras": 0, "total": 0},
                 "wickets": [{"kind": "run out", "player_out": "C"}]},
            ]}],
        }],
    }
    match, players, deliveries = parse_match("1", payload)
    assert match["format"] == "T20I" and match["win_by_runs"] == 7
    assert len(players) == 3 and players[0]["player_id"] == "id-a"
    assert [d["legal_ball_in_over"] for d in deliveries] == [0, 1, 2]
    assert deliveries[2]["player_out_id"] == "id-c"
    assert deliveries[2]["is_bowler_wicket"] is False  # run outs are not the bowler's
