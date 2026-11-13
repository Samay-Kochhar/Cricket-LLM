from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.service import MultiFormatService
from backend.app.services.chat_service import ChatService
from tests.backend.multiformat_fixture import build_fixture_db


def test_general_data_request_with_unsupported_qualifier_retains_failure_class(
    tmp_path,
):
    chat = MultiFormatChat(MultiFormatService(build_fixture_db(tmp_path)))
    service = ChatService(
        repository=None, query_handler=None, gemini_client=None, multiformat=chat
    )
    reply = service.reply("Forecast future trophies using the available data.", [])
    assert reply.mode == "analysis"
    assert reply.query_response.status.value == "unsupported"
    assert reply.query_response.failure_state == "unsupported_capability"
    assert not reply.query_response.tables
    assert reply.query_response.evidence_notes[-1].title == "Afghanistan coverage"
