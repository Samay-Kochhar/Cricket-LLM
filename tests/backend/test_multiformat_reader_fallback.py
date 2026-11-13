from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.model_planner import GeminiPlanner
from backend.app.multiformat.plans import UnderstandingPlan
from backend.app.multiformat.service import MultiFormatService
from backend.app.services.gemini_client import GeminiStructuredResult
from tests.backend.multiformat_fixture import build_fixture_db


class Client:
    def __init__(self, text=None):
        self.text = text
        self.calls = 0

    def generate_structured(self, *args, **kwargs):
        self.calls += 1
        return GeminiStructuredResult(
            text=self.text,
            selected_model="fake",
            model_version=None,
            finish_reason="STOP" if self.text else None,
            latency_ms=1,
            error_kind=None if self.text else "request_failed",
        )


def test_timeout_uses_visible_standard_reading_without_repeated_calls(tmp_path):
    chat = MultiFormatChat(MultiFormatService(build_fixture_db(tmp_path)))
    client = Client()
    chat.reader = GeminiPlanner(client, "fake", chat.planner, tmp_path / "cache")
    for _ in range(2):
        answer = chat.answer("Alpha Batter IPL runs")
        assert answer.query_response.status.value == "supported"
        assert "standard question reader" in answer.reading_note
        assert "request_failed" not in answer.message
        assert (
            answer.query_response.tables[0].rows[0][
                answer.query_response.tables[0].columns.index("runs")
            ]
            == 10
        )
        assert answer.query_response.evidence_notes[-1].title == "Afghanistan coverage"
    assert client.calls == 1


def test_valid_model_unsupported_intent_is_never_replaced_by_fallback(tmp_path):
    chat = MultiFormatChat(MultiFormatService(build_fixture_db(tmp_path)))
    proposed = chat.planner.read("Alpha Batter IPL runs")
    proposed.unsupported = ["requested forecast"]
    chat.reader = GeminiPlanner(
        Client(proposed.model_dump_json()), "fake", chat.planner, tmp_path / "cache"
    )
    answer = chat.answer("Alpha Batter IPL runs")
    assert answer.plan == proposed.model_dump()
    assert answer.query_response.status.value == "unsupported"
    assert answer.reading_note is None
    assert not answer.query_response.tables
