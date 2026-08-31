from __future__ import annotations

from backend.app.domain.evidence_models import EvidenceStatus, QueryInterpretation, QueryResponse, SummaryBlock, TableBlock
from backend.app.services.chat_service import ChatHistoryTurn, ChatService, ConversationState


class FakeRepository:
    def list_player_names(self) -> list[str]:
        return ["Ravichandran Ashwin", "Virat Kohli", "Glenn Maxwell", "Hardik Pandya", "Jasprit Bumrah", "Mitchell Starc", "Shimron Hetmyer", "Tim Southee"]

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
        return "Hardik Pandya's death over batting strike rate is 1"


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
    if "Glenn Maxwell" in question:
        entities.append("Glenn Maxwell")
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
                body="In death overs, Hardik Pandya has 691 runs from 507 balls with a Batting Strike Rate of 136.29.",
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


def test_chat_service_asks_user_to_disambiguate_strike_rate_before_querying() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )

    reply = service.reply("What is Jasprit Bumrah's strike rate?", history=[])

    assert reply.mode == "clarification"
    assert reply.message == "Do you mean batting strike rate or bowling strike rate?"
    assert [option.label for option in reply.clarification_options] == [
        "Batting strike rate",
        "Bowling strike rate",
    ]
    assert [option.message for option in reply.clarification_options] == [
        "What is Jasprit Bumrah's batting strike rate?",
        "What is Jasprit Bumrah's bowling strike rate?",
    ]
    assert seen_questions == []


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
        "death over batting strike rate of hardik pandya",
        history=[],
    )

    assert reply.mode == "analysis"
    assert reply.message == "In death overs, Hardik Pandya has 691 runs from 507 balls with a Batting Strike Rate of 136.29."
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


def test_complete_named_trend_question_does_not_inherit_stale_bowling_context() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    question = "Has Shimron Hetmyer become more destructive after 2020?"

    reply = service.reply(
        question,
        history=[
            ChatHistoryTurn(role="user", content="What is Jasprit Bumrah's economy rate in death overs?"),
            ChatHistoryTurn(role="assistant", content="Jasprit Bumrah's death-over economy is 5.78."),
        ],
    )

    assert seen_questions == [question]
    assert reply.resolved_input is None


def test_complete_named_novel_question_keeps_its_own_pronoun_context() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    question = "How has Virat Kohli adapted his batting approach under pressure?"

    service.reply(
        question,
        history=[
            ChatHistoryTurn(role="user", content="What is Jasprit Bumrah's economy in death overs?"),
            ChatHistoryTurn(role="assistant", content="Jasprit Bumrah's death-over economy is 5.78."),
        ],
    )

    assert seen_questions == [question]


def test_successful_comparison_returns_structured_conversation_state() -> None:
    def query_handler(question: str) -> QueryResponse:
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=QueryInterpretation(
                original_question=question,
                query_class="venue_context_leaderboard",
                entities=["Jasprit Bumrah", "Mitchell Starc"],
                filters={
                    "phase": "death",
                    "compare_players": ["Jasprit Bumrah", "Mitchell Starc"],
                    "comparison_metrics": ["economy_rate", "bowling_strike_rate"],
                    "semantic_operation": "player_compare",
                    "semantic_metric": "economy_rate",
                    "semantic_group_by": ["bowler"],
                },
            ),
            summaries=[SummaryBlock(title="Comparison", body="Comparison complete.")],
        )

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )

    reply = service.reply("Compare Bumrah and Starc in death overs", history=[])

    assert reply.conversation_state is not None
    assert reply.conversation_state.players == ["Jasprit Bumrah", "Mitchell Starc"]
    assert reply.conversation_state.metric == "economy_rate"
    assert reply.conversation_state.comparison_participants == ["Jasprit Bumrah", "Mitchell Starc"]
    assert reply.conversation_state.comparison_metrics == ["economy_rate", "bowling_strike_rate"]
    assert reply.conversation_state.filters == {"phase": "death"}


def test_short_phase_follow_up_preserves_structured_comparison_context() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    state = ConversationState(
        players=["Jasprit Bumrah", "Mitchell Starc"],
        metric="economy_rate",
        comparison_participants=["Jasprit Bumrah", "Mitchell Starc"],
        comparison_metrics=["economy_rate", "bowling_strike_rate"],
        filters={"phase": "death"},
    )

    reply = service.reply(
        "What about powerplay?",
        history=[],
        conversation_state=state,
    )

    assert reply.resolved_input is not None
    assert "Compare Jasprit Bumrah and Mitchell Starc" in seen_questions[0]
    assert "economy rate" in seen_questions[0]
    assert "bowling strike rate" in seen_questions[0]
    assert "powerplay" in seen_questions[0]
    assert "death" not in seen_questions[0]


def test_short_style_follow_up_replaces_only_structured_bowling_style() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    state = ConversationState(
        players=["Glenn Maxwell"],
        metric="batting_strike_rate",
        filters={"bowling_style": "off_spin"},
    )

    reply = service.reply(
        "What about leg-spin?",
        history=[],
        conversation_state=state,
    )

    assert reply.resolved_input is not None
    assert "Glenn Maxwell's batting strike rate" in seen_questions[0]
    assert "against leg spin" in seen_questions[0]
    assert "off spin" not in seen_questions[0]


def test_short_matchup_follow_up_preserves_batter_bowler_and_metric() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    state = ConversationState(
        players=["Virat Kohli", "Mitchell Starc"],
        operation="matchup",
        metric="batting_strike_rate",
        filters={"batter": "Virat Kohli", "bowler": "Mitchell Starc"},
    )

    service.reply(
        "What about death overs?",
        history=[],
        conversation_state=state,
    )

    assert "Virat Kohli's batting strike rate against Mitchell Starc" in seen_questions[0]
    assert "in death overs" in seen_questions[0]


def test_structured_state_prevents_canonical_inference_from_prose_history() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    state = ConversationState(
        players=["Virat Kohli"],
        operation="aggregate",
        metric="batting_strike_rate",
        group_by=["year"],
        filters={"batter": "Virat Kohli"},
    )

    service.reply(
        "Break it down year by year.",
        history=[
            ChatHistoryTurn(role="user", content="What is Jasprit Bumrah's economy rate?"),
            ChatHistoryTurn(role="assistant", content="Jasprit Bumrah's economy rate is 4.6."),
        ],
        conversation_state=state,
    )

    assert seen_questions == [
        "Show Virat Kohli's batting strike rate trend year by year"
    ]


def test_unsupported_turn_returns_last_successful_structured_state() -> None:
    def unsupported_query_handler(question: str) -> QueryResponse:
        return QueryResponse(
            status=EvidenceStatus.unsupported,
            interpretation=QueryInterpretation(
                original_question=question,
                query_class="role_comparison",
                entities=["Virat Kohli"],
            ),
        )

    service = ChatService(
        repository=FakeRepository(),
        query_handler=unsupported_query_handler,
        gemini_client=FakeGeminiClient(),
    )
    state = ConversationState(
        players=["Virat Kohli"],
        operation="aggregate",
        metric="batting_strike_rate",
        filters={"batter": "Virat Kohli", "phase": "death"},
    )

    reply = service.reply(
        "What about an unsupported situation?",
        history=[],
        conversation_state=state,
    )

    assert reply.query_response is not None
    assert reply.query_response.status == EvidenceStatus.unsupported
    assert reply.conversation_state == state


def test_explicit_dimension_only_follow_up_uses_structured_state() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    state = ConversationState(
        players=["Virat Kohli"],
        operation="aggregate",
        metric="batting_strike_rate",
        filters={"batter": "Virat Kohli", "phase": "death"},
    )

    service.reply("Powerplay?", history=[], conversation_state=state)

    assert seen_questions == [
        "What is Virat Kohli's batting strike rate in powerplay?"
    ]


def test_phase_split_follow_up_preserves_other_comparison_filters() -> None:
    seen_questions: list[str] = []

    def query_handler(question: str) -> QueryResponse:
        seen_questions.append(question)
        return fake_query_handler(question)

    service = ChatService(
        repository=FakeRepository(),
        query_handler=query_handler,
        gemini_client=FakeGeminiClient(),
    )
    state = ConversationState(
        players=["Virat Kohli", "Glenn Maxwell"],
        operation="player_compare",
        metric="batting_strike_rate",
        group_by=["batter"],
        comparison_participants=["Virat Kohli", "Glenn Maxwell"],
        comparison_metrics=["batting_strike_rate"],
        filters={
            "phase": "death",
            "bowling_style": "spin",
            "venue": "Sydney Cricket Ground",
        },
    )

    service.reply(
        "Compare the same players in powerplay, middle, and death overs.",
        history=[],
        conversation_state=state,
    )

    assert seen_questions == [
        "Compare Virat Kohli and Glenn Maxwell by batting strike rate "
        "against spin at Sydney Cricket Ground across powerplay, middle overs, and death overs"
    ]


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
