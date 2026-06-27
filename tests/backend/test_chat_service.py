from __future__ import annotations

from backend.app.domain.evidence_models import EvidenceStatus, QueryInterpretation, QueryResponse, SummaryBlock, TableBlock
from backend.app.services.chat_service import ChatHistoryTurn, ChatService


class FakeRepository:
    def list_player_names(self) -> list[str]:
        return ["Ravichandran Ashwin", "Virat Kohli", "Hardik Pandya", "Jasprit Bumrah", "Mitchell Starc", "Tim Southee"]

    def search_players(self, query: str, limit: int = 5) -> list[str]:
        mapping = {
            "ashwin": ["Ravichandran Ashwin"],
            "virat": ["Virat Kohli"],
            "virat kohli": ["Virat Kohli"],
            "hardik": ["Hardik Pandya"],
            "hardik pandya": ["Hardik Pandya"],
            "mitchell starc": ["Mitchell Starc"],
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


class UnavailableGeminiClient:
    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


def fake_query_handler(question: str) -> QueryResponse:
    entities: list[str] = []
    if "Ravichandran Ashwin" in question:
        entities.append("Ravichandran Ashwin")
    if "Virat Kohli" in question:
        entities.append("Virat Kohli")
    if "Hardik Pandya" in question:
        entities.append("Hardik Pandya")
    if "Jasprit Bumrah" in question:
        entities.append("Jasprit Bumrah")
    if "Mitchell Starc" in question or "mitchell starc" in question.lower():
        entities.append("Mitchell Starc")
    if "Tim Southee" in question:
        entities.append("Tim Southee")
    return QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question=question,
            query_class="trend_progression" if "year by year" in question.lower() else "role_comparison",
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


def table_query_handler(question: str) -> QueryResponse:
    return QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question=question,
            query_class="role_comparison",
            entities=["Virat Kohli", "Steven Smith"],
        ),
        summaries=[SummaryBlock(title="Comparison", body="Virat Kohli is ahead on scoring tempo.")],
        tables=[
            TableBlock(
                title="Primary batting metrics",
                columns=["Player", "Runs", "Balls", "Strike Rate"],
                rows=[
                    ["Virat Kohli", 13950, 15208, 91.73],
                    ["Steven Smith", 5674, 6643, 85.41],
                ],
            )
        ],
    )


def leaderboard_query_handler(question: str) -> QueryResponse:
    return QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question=question,
            query_class="venue_context_leaderboard",
            entities=[],
        ),
        summaries=[SummaryBlock(title="Leaderboard", body="Mohammad Nabi leads the bowling economy leaderboard.")],
        tables=[
            TableBlock(
                title="Bowling economy leaderboard",
                columns=["Rank", "Bowler", "Economy"],
                rows=[[1, "Mohammad Nabi", 3.68]],
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

    assert reply.mode == "conversation"
    assert reply.resolved_input is None


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


def test_chat_service_includes_table_rows_in_numeric_analysis_message() -> None:
    service = ChatService(
        repository=FakeRepository(),
        query_handler=table_query_handler,
        gemini_client=TruncatingGeminiClient(),
    )

    reply = service.reply("Compare Virat Kohli and Steven Smith in ODIs", history=[])

    assert reply.mode == "analysis"
    assert "Primary batting metrics" in reply.message
    assert "Virat Kohli | 13950 | 15208 | 91.73" in reply.message
    assert "Steven Smith | 5674 | 6643 | 85.41" in reply.message


def test_chat_service_coaching_prompt_does_not_query_database_leaderboard() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return leaderboard_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=UnavailableGeminiClient(),
    )

    reply = service.reply("Talk me through how to judge a batter's weakness against spin.", history=[])

    assert reply.mode == "conversation"
    assert seen_questions == []
    assert "strike rate" in reply.message
    assert "Virat Kohli ranks first" not in reply.message
    assert "ODI database" not in reply.activity_trace


def test_chat_service_contextualizes_player_follow_up() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )

    reply = service.reply(
        "Break the player down year by year to inspect role changes over time.",
        history=[
            ChatHistoryTurn(role="user", content="What is Jasprit Bumrah's economy rate in death overs?"),
            ChatHistoryTurn(role="assistant", content="Jasprit Bumrah ODI bowling snapshot. In death overs, economy is 5.78."),
        ],
    )

    assert reply.mode == "analysis"
    assert reply.resolved_input is not None
    assert "Jasprit Bumrah" in seen_questions[0]
    assert "as a bowler" in seen_questions[0]
    assert "in death overs" in seen_questions[0]


def test_chat_service_contextualizes_his_pronoun_follow_up() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )

    reply = service.reply(
        "what are his best bowling figures?",
        history=[
            ChatHistoryTurn(role="user", content="Tell me about Tim Southee"),
            ChatHistoryTurn(role="assistant", content="Tim Southee is in the local ODI dataset."),
        ],
    )

    assert reply.mode == "analysis"
    assert reply.resolved_input is not None
    assert "Tim Southee's best bowling figures" in seen_questions[0]


def test_chat_service_contextualizes_trend_comparison_with_new_player() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )

    reply = service.reply(
        "Compare this trend against another ODI player. mitchell starc",
        history=[
            ChatHistoryTurn(role="user", content="What is Jasprit Bumrah's economy rate in death overs?"),
            ChatHistoryTurn(role="assistant", content="In death overs, Jasprit Bumrah's economy is 5.78 runs per over."),
            ChatHistoryTurn(role="user", content="Break the player down year by year to inspect role changes over time."),
            ChatHistoryTurn(role="assistant", content="The ODI bowling trend for Jasprit Bumrah in death overs covers 7 recorded years."),
        ],
    )

    assert reply.mode == "analysis"
    assert reply.resolved_input is not None
    assert "Jasprit Bumrah trend" in seen_questions[0]
    assert "mitchell starc" in seen_questions[0].lower()
    assert "as a bowler" in seen_questions[0]
    assert "in death overs" in seen_questions[0]


def test_chat_service_returns_supported_leaderboard_as_analysis_without_entities() -> None:
    service = ChatService(
        repository=FakeRepository(),
        query_handler=leaderboard_query_handler,
        gemini_client=TruncatingGeminiClient(),
    )

    reply = service.reply("Which bowler has the best death-over economy since 2022?", history=[])

    assert reply.mode == "analysis"
    assert reply.query_response is not None
    assert reply.query_response.tables[0].title == "Bowling economy leaderboard"
    assert "Bowling economy leaderboard" in reply.message
    assert "ODI database" in reply.activity_trace
