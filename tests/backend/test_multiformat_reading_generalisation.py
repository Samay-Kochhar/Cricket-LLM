"""Reading rules found by the 2026-11-13 holdout run, tested as general patterns.

Each test uses invented players and grounds in a generated database, so it pins
the rule (two specialist batters are compared, "at the death" is a phase, a
ground can be named by its initials or a registry nickname, ...) rather than any
one evaluation question.
"""

from datetime import date

import duckdb
import pytest

from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.service import MultiFormatService
from tests.backend.multiformat_fixture import build_fixture_db

IPL = "Indian Premier League"
# id, display name, balls faced, balls bowled
PLAYERS = [
    ("bat_a", "P Anchor", 900, 0),
    ("bat_b", "Q Opener", 800, 12),
    ("bowl_c", "R Quick", 40, 900),
    ("bowl_d", "S Spinner", 30, 700),
    ("ar_e", "T Allround", 500, 800),  # 1.6x: an all-rounder, not a specialist
]
GROUNDS = [  # name, matches
    ("Melbourne Cricket Ground", 30),
    ("Marrara Cricket Ground, Darwin", 2),
    ("Sydney Cricket Ground", 20),
    ("Southend Cricket Ground", 18),  # shares SCG initials, not dominated
    ("Brisbane Cricket Ground", 10),  # the registry knows it as "The Gabba"
    ("Feroz Shah Kotla, Delhi", 6),   # registry: same ground as Arun Jaitley Stadium
    ("Arun Jaitley Stadium", 4),
]


@pytest.fixture
def chat(tmp_path):
    db = build_fixture_db(tmp_path)
    c = duckdb.connect(str(db))
    for col, typ in [
        ("over_no", "INTEGER"), ("legal_ball_in_over", "INTEGER"), ("non_striker_id", "VARCHAR"),
        ("venue", "VARCHAR"), ("is_super_over", "BOOLEAN"), ("bowler_style_code", "VARCHAR"),
        ("bowler_arm", "VARCHAR"), ("bowler_kind", "VARCHAR"), ("batting_team", "VARCHAR"),
        ("bowling_team", "VARCHAR"),
    ]:
        c.execute(f"ALTER TABLE analytics.deliveries ADD COLUMN {col} {typ}")
    for pid, name, _, _ in PLAYERS:
        c.execute("INSERT INTO analytics.players VALUES (?, ?, ?, NULL, NULL)", [pid, name, name])
        c.execute("INSERT INTO analytics.player_names VALUES (?, ?, ?)", [name.lower(), name, pid])
    seq = 0

    def balls(batter, bowler, n, match, venue, length=None):
        nonlocal seq
        for i in range(n):
            seq += 1
            c.execute(
                """INSERT INTO analytics.deliveries BY NAME SELECT
                   ? AS match_id, 'T20 domestic' AS format, 'male' AS gender, ? AS competition,
                   2023 AS year, ?::DATE AS match_date, 1 AS innings_no, ? AS innings_delivery_seq,
                   ? AS batter_id, ? AS bowler_id, ? AS runs_batter, ? AS runs_total,
                   NULL::INTEGER AS wides, NULL::INTEGER AS noballs, FALSE AS non_boundary,
                   TRUE AS is_legal, FALSE AS is_wicket, FALSE AS is_bowler_wicket,
                   ? AS length, 'OUTSIDE_OFFSTUMP' AS line, 'aucb' AS ll_source,
                   ? AS over_no, 'x' AS non_striker_id, ? AS venue, FALSE AS is_super_over,
                   'India' AS batting_team, 'Australia' AS bowling_team""",
                [match, IPL, date(2023, 5, 1), seq, batter, bowler, i % 4, i % 4, length, i % 20, venue],
            )

    ground_cycle = [g for g, n in GROUNDS for _ in range(n)]
    m = 0
    for pid, _, faced, bowled in PLAYERS:
        for chunk in range(0, faced, 50):
            m += 1
            balls(pid, "x", min(50, faced - chunk), f"f{m}", ground_cycle[m % len(ground_cycle)],
                  length=["FULL", "YORKER", "SHORT", "GOOD_LENGTH"][m % 4])
        for chunk in range(0, bowled, 50):
            m += 1
            balls("x", pid, min(50, bowled - chunk), f"b{m}", ground_cycle[m % len(ground_cycle)])
    # One match per listed ground so match counts reflect GROUNDS exactly.
    for g, n in GROUNDS:
        for k in range(n):
            balls("x", "x", 1, f"{g}-{k}", g)
    c.close()
    return MultiFormatChat(MultiFormatService(db))


def read(chat, q):
    return chat.planner.read(q)


@pytest.mark.parametrize(
    "q,intent",
    [
        ("P Anchor vs Q Opener in the IPL", "comparison"),      # two specialist batters
        ("R Quick vs S Spinner in the IPL", "comparison"),      # two specialist bowlers
        ("P Anchor vs R Quick in the IPL", "matchup"),          # batter v bowler
        ("P Anchor vs T Allround in the IPL", "matchup"),       # batter v all-rounder
        ("How many times has R Quick dismissed Q Opener in the IPL?", "matchup"),
    ],
)
def test_vs_is_a_head_to_head_only_between_different_kinds_of_player(chat, q, intent):
    assert read(chat, q).intent == intent


@pytest.mark.parametrize(
    "q,role",
    [
        ("Who has the better IPL strike rate, T Allround or P Anchor?", "batting"),
        ("T Allround IPL strike rate", "batting"),   # all-rounder: never guessed as bowling
        ("R Quick IPL strike rate", "bowling"),      # clear specialist bowler
        ("R Quick or S Spinner: better IPL average?", "bowling"),
        ("R Quick or P Anchor: better IPL average?", "batting"),  # not all bowlers
    ],
)
def test_unqualified_metric_role_follows_clear_specialists_only(chat, q, role):
    assert read(chat, q).role == role


@pytest.mark.parametrize(
    "q",
    [
        "How does P Anchor handle short-pitched bowling in the IPL?",
        "P Anchor facing spin bowling in the IPL",
        "How does P Anchor play pace bowling in the IPL?",
    ],
)
def test_bowling_words_describing_the_opposition_keep_the_batter_role(chat, q):
    assert read(chat, q).role == "batting"


def test_length_words_cover_their_family_but_named_categories_stay_exact(chat):
    assert read(chat, "P Anchor against short balls in the IPL").lengths == ["SHORT", "SHORT_OF_A_GOOD_LENGTH"]
    assert read(chat, "P Anchor against full deliveries in the IPL").lengths == ["FULL", "YORKER"]
    assert read(chat, "P Anchor against bouncers in the IPL").lengths == ["SHORT"]
    assert read(chat, "P Anchor against yorkers in the IPL").lengths == ["YORKER"]
    assert read(chat, "P Anchor against balls short of a good length in the IPL").lengths == ["SHORT_OF_A_GOOD_LENGTH"]


def test_where_a_bowler_pitches_is_length(chat):
    p = read(chat, "Where does R Quick pitch the ball in the IPL?")
    assert p.role == "bowling" and p.dimensions == ["length"]


@pytest.mark.parametrize("phrase", ["at the death", "at the start", "at the end", "at number 4"])
def test_at_phrases_that_are_not_grounds_are_not_venues(chat, phrase):
    p = read(chat, f"P Anchor batting {phrase} in the IPL")
    assert p.venue is None
    assert not any("venue" in u for u in p.unsupported)


def test_death_is_still_read_as_the_phase(chat):
    assert read(chat, "P Anchor batting at the death in the IPL").phase == "death"


@pytest.mark.parametrize("suffix", ["", "?", "!"])
def test_ground_initials_pick_the_clearly_dominant_ground(chat, suffix):
    p = read(chat, f"Most runs at the MCG in the IPL{suffix}")
    assert p.venue == "Melbourne Cricket Ground"


def test_ambiguous_initials_are_reported_not_guessed(chat):
    p = read(chat, "Most runs at the SCG in the IPL")  # Sydney 20 v Southend 18
    assert p.venue is None
    assert any("unresolved venue" in u for u in p.unsupported)


def test_registry_nickname_maps_to_this_databases_spelling(chat):
    assert read(chat, "Most runs at the Gabba in the IPL?").venue == "Brisbane Cricket Ground"


def test_a_ground_includes_all_its_recorded_names(chat):
    venue = read(chat, "Most wickets at Kotla in the IPL").venue
    assert set(venue.split("|")) == {"Feroz Shah Kotla, Delhi", "Arun Jaitley Stadium"}


@pytest.mark.parametrize("q", ["Is the IPL covered?", "How far back does your IPL data go?"])
def test_coverage_wording(chat, q):
    assert read(chat, q).intent == "coverage"


def test_fastest_category_is_named_with_the_minimum_sample(chat):
    a = chat.answer("Which length does P Anchor score fastest against in the IPL?")
    first = a.message.split("\n\n")[0]
    assert "Highest strike rate by length" in first and "minimum 60 balls" in first
    assert a.query_response.status.value == "supported"


def test_two_players_by_length_name_each_players_best_category(chat):
    a = chat.answer("Which length do P Anchor and Q Opener score fastest against in the IPL?")
    first = a.message.split("\n\n")[0]
    assert first.count("Highest strike rate by length") == 2


def test_category_leaderboards_across_all_players_stay_unsupported(chat):
    a = chat.answer("Which batter scores fastest by length in the IPL?")
    assert "can't answer" in a.message


@pytest.mark.parametrize("word", ["batter", "bowler", "batsman", "keeper", "opener", "finisher"])
def test_role_nouns_are_never_player_names(chat, word):
    # A player surnamed like a role noun (the fixture's "A Batter"/"B Bowler",
    # or a real "PD Bowler") must not be matched from the role word itself.
    assert read(chat, f"Which {word} has the most runs in the IPL?").players == []
