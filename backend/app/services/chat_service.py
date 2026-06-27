from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from backend.app.domain.evidence_models import CitationSource, EvidenceStatus, QueryInterpretation, QueryResponse
from backend.app.services.follow_up_suggester import suggest_follow_ups
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.query_classes import QueryClass

STOPWORDS = {
    "about",
    "against",
    "analyst",
    "analysis",
    "around",
    "batsman",
    "bowler",
    "breakdown",
    "compare",
    "conversation",
    "cricket",
    "explain",
    "from",
    "just",
    "match",
    "middle",
    "overs",
    "over",
    "please",
    "powerplay",
    "query",
    "recent",
    "rate",
    "show",
    "some",
    "stats",
    "strike",
    "tell",
    "their",
    "them",
    "there",
    "these",
    "this",
    "through",
    "venue",
    "what",
    "where",
    "which",
    "with",
}

CHAT_TABLE_VISIBLE_ROWS = 5


class ChatHistoryTurn(BaseModel):
    role: str
    content: str


class ChatReply(BaseModel):
    mode: str
    message: str
    query_response: QueryResponse | None = None
    suggestions: list[str] = Field(default_factory=list)
    resolved_input: str | None = None
    resolution_note: str | None = None
    activity_trace: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class ChatService:
    repository: object
    query_handler: object
    gemini_client: GeminiClient

    def reply(self, message: str, history: list[ChatHistoryTurn]) -> ChatReply:
        normalized_message = message.strip()
        contextual_message = self._contextualize_follow_up(normalized_message, history)
        resolution_note = None
        if self._looks_like_coaching_prompt(normalized_message):
            coaching_response = QueryResponse(
                status=EvidenceStatus.unsupported,
                interpretation=QueryInterpretation(
                    original_question=normalized_message,
                    query_class=QueryClass.strengths_weaknesses.value,
                    entities=[],
                    filters={"intent": "coaching_explanation"},
                ),
            )
            conversational = (
                self._general_conversation_reply(
                    message=normalized_message,
                    history=history,
                    resolution_note=resolution_note,
                    query_response=coaching_response,
                )
                if self.gemini_client.is_configured()
                else self._offline_coaching_reply(normalized_message)
            )
            used_gemini = self.gemini_client.is_configured()
            if conversational.startswith("I could not get the conversational model response"):
                conversational = self._offline_coaching_reply(normalized_message)
                used_gemini = False
            return ChatReply(
                mode="conversation",
                message=conversational,
                suggestions=[
                    "Check a named batter's strike rate and false-shot percentage against spin.",
                    "Compare the batter's spin numbers with their pace baseline.",
                    "Inspect dismissal rate, dot percentage, and control percentage by bowling style.",
                ],
                activity_trace=["Gemini reasoning"] if used_gemini else [],
            )
        query_response = self.query_handler(contextual_message)
        entities = query_response.interpretation.entities
        query_class = QueryClass(query_response.interpretation.query_class)
        resolved_input = contextual_message if contextual_message != normalized_message else None
        is_semantic_v2 = "semantic_operation" in query_response.interpretation.filters

        if query_response.status.value == "supported" and (entities or query_response.tables or is_semantic_v2):
            reply_text, used_gemini = self._analysis_reply(
                message=contextual_message,
                query_response=query_response,
                resolution_note=resolution_note,
            )
            return ChatReply(
                mode="analysis",
                message=reply_text,
                query_response=query_response,
                suggestions=self._suggest_follow_ups(query_class, query_response),
                resolved_input=resolved_input,
                resolution_note=resolution_note,
                activity_trace=self._build_activity_trace(query_response, used_gemini=used_gemini),
            )

        if query_response.status.value != "supported" and (query_response.tables or query_response.evidence_queries or is_semantic_v2):
            reply_text, used_gemini = self._analysis_reply(
                message=contextual_message,
                query_response=query_response,
                resolution_note=resolution_note,
            )
            return ChatReply(
                mode="analysis",
                message=reply_text,
                query_response=query_response,
                suggestions=self._suggest_follow_ups(query_class, query_response),
                resolved_input=resolved_input,
                resolution_note=resolution_note,
                activity_trace=self._build_activity_trace(query_response, used_gemini=used_gemini),
            )

        if self._looks_like_general_chat(message) or not entities:
            conversational = self._general_conversation_reply(
                message=normalized_message,
                history=history,
                resolution_note=resolution_note,
                query_response=query_response,
            )
            return ChatReply(
                mode="conversation",
                message=conversational,
                query_response=query_response if entities else None,
                suggestions=self._suggest_follow_ups(query_class, query_response) if entities else [],
                resolved_input=None,
                resolution_note=resolution_note,
                activity_trace=self._build_activity_trace(query_response, used_gemini=self.gemini_client.is_configured()),
            )

        fallback, used_gemini = self._analysis_reply(
            message=contextual_message,
            query_response=query_response,
            resolution_note=resolution_note,
        )
        return ChatReply(
            mode="analysis",
            message=fallback,
            query_response=query_response,
            suggestions=self._suggest_follow_ups(query_class, query_response),
            resolved_input=resolved_input,
            resolution_note=resolution_note,
            activity_trace=self._build_activity_trace(query_response, used_gemini=used_gemini),
        )

    def _contextualize_follow_up(self, message: str, history: list[ChatHistoryTurn]) -> str:
        if not history:
            return message

        lowered = message.lower()
        context_markers = (
            "the player",
            "this player",
            "same player",
            "his",
            "him",
            "year by year",
            "role changes",
            "over time",
            "this trend",
        )
        if not any(marker in lowered for marker in context_markers):
            return message

        player = self._last_player_from_history(history)
        if not player:
            return message

        contextual = re.sub(r"\b(?:the|this|same) player\b", player, message, flags=re.IGNORECASE)
        contextual = re.sub(r"\bthis trend\b", f"{player} trend", contextual, flags=re.IGNORECASE)
        contextual = re.sub(r"\bhis\b", f"{player}'s", contextual, flags=re.IGNORECASE)
        contextual = re.sub(r"\bhim\b", player, contextual, flags=re.IGNORECASE)
        if contextual == message:
            contextual = self._append_context(contextual, f"for {player}")

        history_text = " ".join(turn.content for turn in history[-6:]).lower()
        contextual_lower = contextual.lower()
        if not any(token in contextual_lower for token in ("batting", "batter", "bowling", "bowler", "economy", "wicket")):
            if any(token in history_text for token in ("bowling", "bowler", "economy", "wicket", "bowl AS player", "where bowl")):
                contextual = self._append_context(contextual, "as a bowler")
            elif any(token in history_text for token in ("batting", "batter", "strike rate", "runs scored")):
                contextual = self._append_context(contextual, "as a batter")

        contextual_lower = contextual.lower()
        if not any(token in contextual_lower for token in ("death", "powerplay", "middle overs")):
            if "death overs" in history_text or "death-over" in history_text:
                contextual = self._append_context(contextual, "in death overs")
            elif "powerplay" in history_text:
                contextual = self._append_context(contextual, "in powerplay")
            elif "middle overs" in history_text:
                contextual = self._append_context(contextual, "in middle overs")

        return contextual

    @staticmethod
    def _append_context(message: str, suffix: str) -> str:
        return f"{message.rstrip(' .?!,;:')} {suffix}"

    def _message_mentions_player(self, message: str) -> bool:
        lowered = message.lower()
        return any(player.lower() in lowered for player in self.repository.list_player_names())

    def _last_player_from_history(self, history: list[ChatHistoryTurn]) -> str | None:
        players = self.repository.list_player_names()
        for turn in reversed(history[-8:]):
            lowered = turn.content.lower()
            for player in players:
                if player.lower() in lowered:
                    return player
        return None

    def _analysis_reply(
        self,
        message: str,
        query_response: QueryResponse,
        resolution_note: str | None,
    ) -> tuple[str, bool]:
        fallback = self._analysis_text(query_response, resolution_note)
        if not self.gemini_client.is_configured():
            return fallback, False
        if self._requires_exact_numeric_response(query_response):
            return fallback, False

        prompt = (
            "You are Atlas, an ODI cricket analyst assistant.\n"
            "You are given a database-backed result. Rewrite it as a concise, sharp analyst answer.\n"
            "Rules:\n"
            "- Respect the database result exactly.\n"
            "- Copy every statistic exactly if any statistics are present.\n"
            "- Do not invent statistics or entities.\n"
            "- If external context exists, treat it as secondary.\n"
            "- If a name was resolved, mention it naturally once.\n"
            "- Keep the answer short and useful.\n\n"
            f"User question: {message}\n"
            f"Resolution note: {resolution_note or 'none'}\n"
            f"Database status: {query_response.status.value}\n"
            f"Entities: {', '.join(query_response.interpretation.entities) or 'none'}\n"
            f"Summaries: {' | '.join(block.body for block in query_response.summaries[:2]) or 'none'}\n"
            f"Insufficiencies: {' | '.join(block.detail for block in query_response.insufficiencies[:2]) or 'none'}\n"
            f"Citations: {' | '.join(citation.label for citation in query_response.citations[:4]) or 'none'}\n\n"
            "Reply as Atlas."
        )
        generated = self.gemini_client.generate_text(prompt, prefer_complex=False)
        if not generated:
            return fallback, False
        if not self._preserves_numeric_tokens(fallback, generated):
            return fallback, False
        return generated, True

    def _general_conversation_reply(
        self,
        message: str,
        history: list[ChatHistoryTurn],
        resolution_note: str | None,
        query_response: QueryResponse,
    ) -> str:
        if not self.gemini_client.is_configured():
            if resolution_note:
                return f"{resolution_note} I can analyze ODI data once you ask a more specific cricket question."
            return (
                "I can talk generally about ODI cricket and analyze database-backed questions, "
                "but Gemini is not configured right now. Ask a more specific player, venue, or matchup question."
            )

        history_text = "\n".join(
            f"{turn.role}: {turn.content}" for turn in history[-8:] if turn.content.strip()
        )
        prompt = (
            "You are Atlas, an ODI cricket analyst assistant.\n"
            "Rules:\n"
            "- You may talk conversationally about cricket.\n"
            "- If the local database already answered something, do not contradict it.\n"
            "- If the database is insufficient, say that clearly.\n"
            "- Keep answers concise and useful.\n"
            "- If a name was auto-resolved, mention that naturally once.\n\n"
            f"Resolution note: {resolution_note or 'none'}\n"
            f"Database status: {query_response.status.value}\n"
            f"Database summaries: {' | '.join(block.body for block in query_response.summaries[:2]) or 'none'}\n"
            f"Database insufficiencies: {' | '.join(block.detail for block in query_response.insufficiencies[:2]) or 'none'}\n"
            f"Conversation history:\n{history_text or 'none'}\n\n"
            f"User message: {message}\n\n"
            "Reply as Atlas."
        )
        generated = self.gemini_client.generate_text(prompt, prefer_complex=False)
        if generated:
            return generated
        if resolution_note:
            return f"{resolution_note} I could not get the conversational model response, but I can still analyze ODI questions."
        return "I could not get the conversational model response right now, but I can still analyze ODI questions."

    @staticmethod
    def _analysis_text(query_response: QueryResponse, resolution_note: str | None) -> str:
        summary_text = "\n\n".join(block.body for block in query_response.summaries[:2]).strip()
        if not summary_text and query_response.insufficiencies:
            summary_text = query_response.insufficiencies[0].detail
        evidence_text = ChatService._table_text_sections(query_response)
        if evidence_text:
            summary_text = f"{summary_text}\n\n{evidence_text}".strip()
        if resolution_note:
            return f"{resolution_note}\n\n{summary_text}".strip()
        return summary_text or "I analyzed the ODI data and attached the structured evidence below."

    @staticmethod
    def _table_text_sections(query_response: QueryResponse) -> str:
        if not query_response.tables:
            return ""

        sections = []
        for table in query_response.tables[:4]:
            if not table.rows:
                continue
            header = " | ".join(table.columns)
            rows = [
                " | ".join(str(cell) if cell is not None else "-" for cell in row)
                for row in table.rows[:CHAT_TABLE_VISIBLE_ROWS]
            ]
            extra = (
                ""
                if len(table.rows) <= CHAT_TABLE_VISIBLE_ROWS
                else f"\n... {len(table.rows) - CHAT_TABLE_VISIBLE_ROWS} more rows in the evidence panel"
            )
            sections.append(f"{table.title}\n{header}\n" + "\n".join(rows) + extra)
        return "\n\n".join(sections)

    @staticmethod
    def _requires_exact_numeric_response(query_response: QueryResponse) -> bool:
        summary_text = " ".join(block.body for block in query_response.summaries)
        table_values = " ".join(
            str(cell)
            for table in query_response.tables
            for row in table.rows
            for cell in row
            if cell is not None
        )
        source = f"{summary_text} {table_values}".strip()
        return bool(re.search(r"\d", source))

    @staticmethod
    def _preserves_numeric_tokens(fallback: str, generated: str) -> bool:
        fallback_tokens = re.findall(r"\d+(?:\.\d+)?", fallback)
        if not fallback_tokens:
            return True
        generated_tokens = set(re.findall(r"\d+(?:\.\d+)?", generated))
        return all(token in generated_tokens for token in fallback_tokens)

    @staticmethod
    def _looks_like_general_chat(message: str) -> bool:
        lowered = message.lower()
        conversational_markers = (
            "hello",
            "hi",
            "hey",
            "what do you think",
            "can we talk",
            "explain",
            "why",
            "help me think",
            "brainstorm",
        )
        return any(token in lowered for token in conversational_markers)

    @staticmethod
    def _looks_like_coaching_prompt(message: str) -> bool:
        lowered = message.lower()
        coaching_markers = (
            "talk me through",
            "how to judge",
            "how do i judge",
            "how should i judge",
            "help me judge",
            "teach me",
            "what should i look for",
            "walk me through",
        )
        return any(marker in lowered for marker in coaching_markers)

    @staticmethod
    def _offline_coaching_reply(message: str) -> str:
        lowered = message.lower()
        if "spin" in lowered:
            return (
                "To judge a batter's weakness against spin, compare their spin sample with their own pace baseline: "
                "strike rate, dot-ball percentage, false-shot percentage, dismissal rate, and boundary percentage. "
                "Then split by spin type if possible, because wrist spin and finger spin can expose different problems. "
                "A real weakness usually shows up across more than one signal, not just one low-scoring innings."
            )
        return (
            "Judge a batting weakness by comparing the filtered sample with the batter's normal baseline: scoring rate, "
            "dot pressure, false shots, dismissals, boundary rate, and sample size. One metric can mislead; a good read "
            "needs the same pattern across several signals."
        )

    def _build_activity_trace(self, query_response: QueryResponse, used_gemini: bool) -> list[str]:
        trace = []
        if used_gemini:
            trace.append("Gemini reasoning")
        if query_response.interpretation.entities or query_response.tables or query_response.visuals:
            trace.append("ODI database")
        if any(citation.source_type == CitationSource.external_web for citation in query_response.citations):
            trace.append("Web context")
        return trace

    @staticmethod
    def _suggest_follow_ups(query_class: QueryClass, query_response: QueryResponse) -> list[str]:
        filters = query_response.interpretation.filters
        operation = filters.get("semantic_operation")
        if operation == "player_compare":
            return [
                "Compare the same players in powerplay, middle, and death overs.",
                "Compare the same players against a specific team or bowling style.",
            ]
        if isinstance(filters.get("bowling_style"), str):
            return [
                "Compare this result with the player's overall ODI baseline.",
                "Compare the player against pace, off spin, leg spin, and left-arm spin.",
                "Break the result down by powerplay, middle, and death overs.",
            ]
        if "length" in filters.get("semantic_group_by", []):
            return [
                "Compare every length on strike rate, dot-ball percentage, and dismissals.",
                "Break the length results down by powerplay, middle, and death overs.",
            ]
        if operation == "aggregate" and "venue" not in filters:
            return [
                "Adjust the minimum ball threshold and re-sort this result.",
                "Break this result down by powerplay, middle, and death overs.",
            ]
        return suggest_follow_ups(query_class)
