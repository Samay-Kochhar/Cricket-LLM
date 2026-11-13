"""General contracts for ranking defaults, eligibility and absent annotations."""

from pathlib import Path

import duckdb
import pytest

from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.service import MultiFormatService
from tests.backend.multiformat_fixture import build_fixture_db


@pytest.fixture
def chat(tmp_path: Path):
    path = build_fixture_db(tmp_path)
    with duckdb.connect(str(path)) as conn:
        conn.execute("ALTER TABLE analytics.deliveries ADD COLUMN venue VARCHAR")
        conn.execute("UPDATE analytics.deliveries SET venue = 'Example Park'")
    return MultiFormatChat(MultiFormatService(path))


@pytest.mark.parametrize(
    "subject,role,metric",
    [
        ("bowlers", "bowling", "wickets"),
        ("batters", "batting", "runs"),
    ],
)
def test_unqualified_player_ranking_uses_one_count_metric(chat, subject, role, metric):
    plan = chat.planner.read(f"Best {subject} at Example Park in the IPL")
    assert plan.intent == "ranking"
    assert plan.role == role
    assert plan.metrics == [metric]
    assert (
        chat.answer(
            f"Best {subject} at Example Park in the IPL"
        ).query_response.status.value
        != "unsupported"
    )


def test_explicit_ranking_metric_is_preserved(chat):
    assert chat.planner.read("Best bowling averages in the IPL").metrics == ["average"]


def test_category_ranking_does_not_present_ineligible_rows_as_ranked(chat):
    answer = chat.answer(
        "Which length does Alpha Batter score fastest against in the IPL?"
    )
    assert not answer.query_response.tables
    assert "60-ball minimum" in answer.message
    assert "No length data" not in answer.message


def test_absent_annotation_explains_stored_limitation(chat):
    answer = chat.answer("Alpha Batter women's T20I record by length")
    assert (
        "not recorded for women's T20I"
        in answer.message.split("Evidence & limitations")[0]
    )
    assert any("not recorded" in n.detail for n in answer.query_response.evidence_notes)
    assert answer.query_response.evidence_notes[-1].title == "Afghanistan coverage"


def test_filtered_length_ranking_uses_only_the_batters_own_deliveries(chat):
    with duckdb.connect(str(chat.service.db_path)) as conn:
        conn.execute(
            "UPDATE analytics.deliveries SET length='FULL' WHERE batter_id='bat2' AND player_out_id='bat'"
        )
    answer = chat.answer(
        "Which batter scores fastest against full deliveries in the IPL (minimum 1 balls)?"
    )
    assert answer.query_response.status.value == "supported", answer.message
    table = answer.query_response.tables[0]
    row = dict(zip(table.columns, table.rows[0]))
    assert row["name"] == "A Batter"
    assert row["runs"] == 6 and row["balls"] == 1
    assert row["dismissals"] == 0
    assert any(
        n.title == "Length coverage" for n in answer.query_response.evidence_notes
    )


def test_gender_is_visible_in_the_interpretation(chat):
    answer = chat.answer("Alpha Batter women's T20I runs")
    assert "women" in answer.message.splitlines()[0]


def test_one_player_compared_across_formats_keeps_both_scopes(chat):
    answer = chat.answer("Compare Alpha Batter IPL strike rate versus T20I strike rate")
    assert answer.query_response.status.value == "supported", answer.message
    assert len(answer.plan["players"]) == 1 and len(answer.plan["scopes"]) == 2
    assert len(answer.query_response.tables) == 2


def test_competition_coverage_keeps_its_conventional_gender(chat):
    assert chat.planner.read("IPL line and length data").scopes[0].gender == "male"
    assert chat.planner.read("Women's Premier League data").scopes[0].gender == "female"


@pytest.mark.parametrize(
    "gender_word,expected",
    [("", {"male", "female"}), ("men's ", {"male"}), ("women's ", {"female"})],
)
def test_general_format_coverage_respects_only_explicit_gender(
    chat, gender_word, expected
):
    with duckdb.connect(str(chat.service.db_path)) as conn:
        for gender in ("male", "female"):
            conn.execute(
                "INSERT INTO analytics.deliveries SELECT * REPLACE ('The Hundred' AS format, ? AS gender, ? AS match_id) FROM analytics.deliveries LIMIT 1",
                [gender, gender + "-hundred"],
            )
    answer = chat.answer(f"Is {gender_word}The Hundred covered?")
    assert answer.query_response.status.value == "supported", answer.message
    table = answer.query_response.tables[0]
    assert {r[table.columns.index("gender")] for r in table.rows} == expected
