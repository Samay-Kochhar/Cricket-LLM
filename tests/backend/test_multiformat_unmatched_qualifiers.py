"""Synthetic contracts for qualifiers and participant names, independent of evals.

Only this generated database extends the shared fixture. Distinct run signatures
make silently dropped over windows and incorrectly selected identities observable.
"""

import duckdb
import pytest

from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.service import MultiFormatService
from tests.backend.multiformat_fixture import build_fixture_db


IPL = "Indian Premier League"
BBL = "Big Bash League"


@pytest.fixture(scope="module")
def chat(tmp_path_factory):
    path = build_fixture_db(tmp_path_factory.mktemp("unmatched-qualifiers"))
    with duckdb.connect(str(path)) as conn:
        for column, kind in [
            ("over_no", "INTEGER"),
            ("legal_ball_in_over", "INTEGER"),
            ("non_striker_id", "VARCHAR"),
            ("venue", "VARCHAR"),
            ("is_super_over", "BOOLEAN"),
            ("batting_team", "VARCHAR"),
            ("bowling_team", "VARCHAR"),
        ]:
            conn.execute(f"ALTER TABLE analytics.deliveries ADD COLUMN {column} {kind}")
        people = [
            ("batter_synthetic", "N Calder", "Nolan Calder"),
            ("bowler_synthetic", "M Fenwick", "Marcellus Fenwick"),
            ("partner_synthetic", "T Venn", "Tobias Venn"),
            ("orton_ipl", "H Orton", "H Orton"),
            ("orton_bbl", "HV Orton", "HV Orton"),
            ("regional_marcellus", "Marcellus", "Marcellus"),
        ]
        for pid, canonical, alias in people:
            conn.execute(
                "INSERT INTO analytics.players VALUES (?, ?, ?, NULL, NULL)",
                [pid, canonical, canonical],
            )
            for name in dict.fromkeys([canonical, alias]):
                conn.execute(
                    "INSERT INTO analytics.player_names VALUES (?, ?, ?)",
                    [name.lower(), name, pid],
                )

        def add(match, fmt, competition, batter, bowler, overs, runs):
            for seq, over in enumerate(overs, 1):
                conn.execute(
                    """INSERT INTO analytics.deliveries BY NAME SELECT
                    ? AS match_id, ? AS format, 'male' AS gender, ? AS competition,
                    2023 AS year, DATE '2023-05-01' AS match_date,
                    1 AS innings_no, ? AS innings_delivery_seq,
                    ? AS batter_id, ? AS bowler_id, ? AS runs_batter, ? AS runs_total,
                    TRUE AS is_legal, FALSE AS is_wicket, FALSE AS is_bowler_wicket,
                    FALSE AS non_boundary, 'FULL' AS length,
                    'OUTSIDE_OFFSTUMP' AS line, 'aucb' AS ll_source,
                    ? AS over_no, 1 AS legal_ball_in_over,
                    'partner_synthetic' AS non_striker_id,
                    'Invented Oval' AS venue, FALSE AS is_super_over,
                    'Example XI' AS batting_team, 'Sample XI' AS bowling_team""",
                    [match, fmt, competition, seq, batter, bowler, runs, runs, over],
                )

        for fmt, competition, n in [
            ("T20 domestic", IPL, 20),
            ("ODI", "ODI", 50),
            ("Test", "Test", 20),
        ]:
            add(
                fmt,
                fmt,
                competition,
                "batter_synthetic",
                "bowler_synthetic",
                range(n),
                2,
            )
        # Global samples deliberately close: popularity cannot break this tie.
        add("h-ipl", "T20 domestic", IPL, "orton_ipl", "bowl", range(12), 1)
        add("hv-bbl", "T20 domestic", BBL, "orton_bbl", "bowl", range(14), 3)
        add("regional", "T20 domestic", BBL, "bat", "regional_marcellus", range(16), 4)
        conn.execute(
            "INSERT INTO analytics.coverage VALUES (?, 'male', ?, 1)",
            ["T20 domestic", BBL],
        )
        for fmt in ["ODI", "Test"]:
            conn.execute(
                "INSERT INTO analytics.coverage VALUES (?, 'male', ?, 1)", [fmt, fmt]
            )
    return MultiFormatChat(MultiFormatService(path))


def rows(answer):
    return [
        dict(zip(table.columns, row))
        for table in answer.query_response.tables
        for row in table.rows
    ]


@pytest.mark.parametrize("verb", ["bowl", "usually bowl"])
def test_bowler_location_reads_both_coordinates(chat, verb):
    question = f"Where does M Fenwick {verb} in Tests?"
    plan = chat.planner.read(question)
    assert plan.role == "bowling"
    assert set(plan.dimensions) == {"line", "length"}
    answer = chat.answer(question)
    assert answer.query_response.status.value == "supported", answer.message
    data = rows(answer)
    assert sum(row["balls"] for row in data if "line" in row) == 20
    assert sum(row["balls"] for row in data if "length" in row) == 20


def test_explicit_pitch_location_remains_length_only(chat):
    plan = chat.planner.read("Where does M Fenwick pitch the ball in Tests?")
    assert plan.role == "bowling"
    assert plan.dimensions == ["length"]


@pytest.mark.parametrize("scope,scheduled", [("IPL", 20), ("T20", 20), ("ODI", 50)])
@pytest.mark.parametrize("window,n", [("2", 2), ("five", 5), ("seven", 7)])
def test_last_overs_preserve_explicit_window_in_plan_and_totals(
    chat, scope, scheduled, window, n
):
    question = f"N Calder runs in the last {window} overs in {scope}"
    plan = chat.planner.read(question)
    if scope == "ODI":
        # This reader deliberately leaves standalone ODIs to the existing ODI
        # planner. The relative-over qualifier must not change route ownership.
        assert plan is None
        assert chat.answer(question) is None
        return
    assert (
        plan is not None
    ), "Explicit over qualifier was diverted from the multi-format reader"
    assert (plan.over_from, plan.over_to) == (scheduled - n + 1, scheduled)
    answer = chat.answer(question)
    assert answer.query_response.status.value == "supported"
    data = rows(answer)
    assert data, answer.message
    assert sum(row["runs"] for row in data) == 2 * n
    assert sum(row["balls"] for row in data) == n


@pytest.mark.parametrize("window", ["3", "five"])
@pytest.mark.parametrize("short_format", ["T20", "T20I", "IPL"])
def test_one_tail_window_across_incompatible_formats_is_explicitly_refused(
    chat, window, short_format
):
    question = (
        f"Compare N Calder runs in {short_format} and ODI in the last {window} overs"
    )
    plan = chat.planner.read(question)
    assert (
        plan is not None
    ), "Mixed-format window was diverted from the multi-format reader"
    assert plan.unsupported, plan.model_dump()
    answer = chat.answer(question)
    assert answer.query_response.status.value == "unsupported"
    assert not answer.query_response.tables
    assert any(word in answer.message.lower() for word in ("overs", "window"))


@pytest.mark.parametrize("ordinal", ["second", "third", "fourth", "2nd", "3rd", "7th"])
def test_wicket_ordinal_partnership_never_returns_unfiltered_stands(chat, ordinal):
    question = f"N Calder and T Venn partnership at the {ordinal} wicket in the IPL"
    plan = chat.planner.read(question)
    assert plan.unsupported, plan.model_dump()
    answer = chat.answer(question)
    assert answer.query_response.status.value == "unsupported"
    assert not answer.query_response.tables
    assert "wicket" in answer.message.lower()


@pytest.mark.parametrize(
    "phrase",
    [
        "N Calder against M Fenwic",
        "M Fenwic bowling against N Calder",
        "N Calder vs Fenwic",
        "How many times has M Fenwic dismissed N Calder?",
    ],
)
def test_exact_participant_does_not_stop_resolution_of_misspelled_opponent(
    chat, phrase
):
    question = phrase + " in the IPL"
    plan = chat.planner.read(question)
    answer = chat.answer(question)
    if answer.query_response.status.value == "unsupported":
        assert not answer.query_response.tables
        assert any(
            word in answer.message.lower()
            for word in ("unresolved", "participant", "player", "fenwic")
        )
    else:
        assert plan.intent == "matchup", plan.model_dump()
        assert len(plan.players) == 2, plan.model_dump()
        ids = {
            p["player_id"]
            for name in plan.players
            for p in chat.planner.names.choose(name, plan.scopes)
        }
        assert ids == {"batter_synthetic", "bowler_synthetic"}
        assert rows(answer), answer.message


@pytest.mark.parametrize(
    "scope,pid,total", [("IPL", "orton_ipl", 12), ("BBL", "orton_bbl", 42)]
)
def test_full_name_initials_choose_identity_from_requested_competition(
    chat, scope, pid, total
):
    question = f"Harold Orton runs in the {scope}"
    plan = chat.planner.read(question)
    assert len(plan.players) == 1
    candidates = chat.planner.names.choose(plan.players[0], plan.scopes)
    assert [p["player_id"] for p in candidates] == [pid]
    answer = chat.answer(question)
    assert answer.query_response.status.value == "supported", answer.message
    assert sum(row["runs"] for row in rows(answer)) == total


@pytest.mark.parametrize("name", ["Marcellus", "Marcellus Fenwick"])
def test_given_name_from_full_alias_competes_with_regional_canonical_name(chat, name):
    question = f"{name} bowling economy in the IPL"
    plan = chat.planner.read(question)
    assert len(plan.players) == 1
    candidates = chat.planner.names.choose(plan.players[0], plan.scopes)
    assert [p["player_id"] for p in candidates] == ["bowler_synthetic"]
    answer = chat.answer(question)
    assert answer.query_response.status.value == "supported", answer.message
    assert rows(answer), answer.message
    assert sum(row["balls"] for row in rows(answer)) == 20
    assert all(row["economy"] == 12 for row in rows(answer))
