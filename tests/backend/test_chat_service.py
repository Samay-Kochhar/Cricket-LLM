from __future__ import annotations

from backend.app.domain.evidence_models import EvidenceStatus, QueryInterpretation, QueryResponse, SummaryBlock
from backend.app.services.chat_service import ChatHistoryTurn, ChatService


class FakeRepository:
    def search_players(self, query: str, limit: int = 5) -> list[str]:
        mapping = {
            "ashwin": ["Ravichandran Ashwin"],
            "virat": ["Virat Kohli"],
            "virat kohli": ["Virat Kohli"],
            "hardik": ["Hardik Pandya"],
            "hardik pandya": ["Hardik Pandya"],
        }
        return mapping.get(query.lower(), [])


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        if "Pick the most likely ODI player" in prompt:
            return "Ravichandran Ashwin"
        return "Database-backed analyst answer."


class TruncatingGeminiClient:
    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        if "Pick the most likely ODI player" in prompt:
            return "Hardik Pandya"
        return "Hardik Pandya's death over strike rate is 1"


def fake_query_handler(question: str) -> QueryResponse:
    entities: list[str] = []
    if "Ravichandran Ashwin" in question:
        entities.append("Ravichandran Ashwin")
    if "Virat Kohli" in question:
        entities.append("Virat Kohli")
    if "Hardik Pandya" in question:
        entities.append("Hardik Pandya")
    return QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question=question,
            query_class="role_comparison",
            entities=entities,
        ),
        summaries=[SummaryBlock(title="Snapshot", body="Player snapshot.")],
    )


def numeric_query_handler(question: str) -> QueryResponse:
    entities = ["Hardik Pandya"] if "hardik pandya" in question.lower() else []
    return QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question=question,
            query_class="role_comparison",
            entities=entities,
            filters={"phase": "death"},
        ),
        summaries=[
            SummaryBlock(
                title="Snapshot",
                body="In death overs, Hardik Pandya has 691 runs from 507 balls with a strike rate of 136.29.",
            )
        ],
    )


def test_chat_service_resolves_broad_player_prompt_and_returns_analysis() -> None:
    service = ChatService(
        repository=FakeRepository(),
        query_handler=fake_query_handler,
        gemini_client=FakeGeminiClient(),
    )

    reply = service.reply(
        "can you just show me some stats of ashwin or virat kohli",
        history=[ChatHistoryTurn(role="user", content="hi")],
    )

    assert reply.mode == "analysis"
    assert reply.resolved_input is not None
    assert "Ravichandran Ashwin" in reply.resolved_input
    assert "ODI database" in reply.activity_trace


def test_chat_service_does_not_turn_over_into_a_player_name() -> None:
    service = ChatService(
        repository=FakeRepository(),
        query_handler=fake_query_handler,
        gemini_client=FakeGeminiClient(),
    )

    reply = service.reply(
        "death over strike rate of hardik pandya",
        history=[],
    )

    assert reply.resolved_input is None or "Brandon Glover" not in reply.resolved_input


def test_chat_service_prefers_database_text_when_gemini_damages_numeric_reply() -> None:
    service = ChatService(
        repository=FakeRepository(),
        query_handler=numeric_query_handler,
        gemini_client=TruncatingGeminiClient(),
    )

    reply = service.reply(
        "death over strike rate of hardik pandya",
        history=[],
    )

    assert reply.mode == "analysis"
    assert reply.message == "In death overs, Hardik Pandya has 691 runs from 507 balls with a strike rate of 136.29."
    assert "Gemini reasoning" not in reply.activity_trace
    assert "ODI database" in reply.activity_trace
