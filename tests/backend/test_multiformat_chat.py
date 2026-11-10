from pathlib import Path

import pytest

from backend.app.multiformat.chat import MultiFormatChat, detect_scope
from backend.app.multiformat.service import MultiFormatService
from backend.app.services.chat_service import ChatService
from tests.backend.multiformat_fixture import build_fixture_db


@pytest.fixture()
def chat(tmp_path: Path) -> MultiFormatChat:
    return MultiFormatChat(MultiFormatService(build_fixture_db(tmp_path)))


@pytest.mark.parametrize(
    "question",
    [
        "What is Virat Kohli's strike rate?",
        "Kohli's ODI record in the World Cup",
        "Best economy in death overs",
        "How many runs did Rohit score in 2023?",
    ],
)
def test_odi_and_unscoped_questions_stay_on_the_odi_path(question) -> None:
    assert detect_scope(question) is None


def test_scope_detection() -> None:
    ipl = detect_scope("Kohli IPL runs since 2020")
    assert ipl.flt.competition == "Indian Premier League" and ipl.flt.year_from == 2020 and ipl.flt.gender == "male"
    assert detect_scope("Joe Root's Test average").flt.format == "Test"
    assert detect_scope("Root's test cricket average").flt.format == "Test"
    women = detect_scope("women's T20I strike rate")
    assert women.flt.format == "T20I" and women.flt.gender == "female" and women.gender_stated
    assert detect_scope("MS Dhoni IPL 2023 runs").flt.year_to == 2023
    assert detect_scope("T20 strike rate").flt.formats == ("T20I", "T20 domestic")


def test_player_stats_answer(chat) -> None:
    answer = chat.answer("How many runs did Alpha Batter score in the IPL?")
    assert "A Batter, batting in the IPL" in answer.message
    assert "10 runs off 3 balls" in answer.message and "strike rate 333.33" in answer.message


def test_line_length_answer_states_the_limit(chat) -> None:
    answer = chat.answer("How does A Batter bat against short balls in the IPL?")
    assert "by length in the IPL" in answer.message
    assert "Full: 1 balls" in answer.message
    assert "Data limit: Length is recorded for 2 of 4 deliveries (50.0%)" in answer.message
    assert "Coverage: Length is available from 2019." in answer.message


def test_line_length_without_data_returns_the_limitation(chat) -> None:
    answer = chat.answer("A Batter women's T20I batting by length")
    assert "not recorded for any of these" in answer.message
    assert "women's T20I in any source" in answer.message


def test_ranking_uses_the_minimum_sample(chat) -> None:
    # the fixture batter has only 3 balls, below the 60-ball ranking minimum
    assert "No batting rankings" in chat.answer("Which batter has the best strike rate in the IPL?").message


def test_coverage_question(chat) -> None:
    answer = chat.answer("What line and length data do you have for the IPL?")
    assert "What CricAtlas holds for the IPL" in answer.message
    assert "Length is available from 2019." in answer.message


class _NoOdi:
    def __call__(self, *_args, **_kwargs):
        raise AssertionError("IPL questions must not reach the ODI handler")


class _OfflineGemini:
    def is_configured(self) -> bool:
        return False


def test_chat_service_routes_named_formats_and_leaves_odi_alone(chat) -> None:
    service = ChatService(repository=None, query_handler=_NoOdi(), gemini_client=_OfflineGemini(), multiformat=chat)
    reply = service.reply("How many runs did A Batter score in the IPL?", [])
    assert reply.mode == "conversation" and reply.activity_trace == ["Multi-format database"]
    assert reply.query_response is None
    assert chat.answer("What is A Batter's ODI strike rate?") is None
