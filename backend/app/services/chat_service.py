from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from backend.app.domain.evidence_models import CitationSource, QueryResponse
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
        resolved_message, resolution_note = self._resolve_entities(message)
        query_response = self.query_handler(resolved_message)
        entities = query_response.interpretation.entities
        query_class = QueryClass(query_response.interpretation.query_class)
        activity_trace = self._build_activity_trace(query_response)

        if query_response.status.value == "supported" and entities:
            reply_text = self._analysis_reply_with_gemini(
                message=message,
                query_response=query_response,
                resolution_note=resolution_note,
            )
            return ChatReply(
                mode="analysis",
                message=reply_text,
                query_response=query_response,
                suggestions=suggest_follow_ups(query_class),
                resolved_input=resolved_message if resolved_message != message else None,
                resolution_note=resolution_note,
                activity_trace=activity_trace,
            )

        if self._looks_like_general_chat(message) or not entities:
            conversational = self._general_conversation_reply(
                message=message,
                history=history,
                resolution_note=resolution_note,
                query_response=query_response,
            )
            return ChatReply(
                mode="conversation",
                message=conversational,
                query_response=query_response if entities else None,
                suggestions=suggest_follow_ups(query_class) if entities else [],
                resolved_input=resolved_message if resolved_message != message else None,
                resolution_note=resolution_note,
                activity_trace=activity_trace,
            )

        fallback = self._analysis_reply_with_gemini(
            message=message,
            query_response=query_response,
            resolution_note=resolution_note,
        )
        return ChatReply(
            mode="analysis",
            message=fallback,
            query_response=query_response,
            suggestions=suggest_follow_ups(query_class),
            resolved_input=resolved_message if resolved_message != message else None,
            resolution_note=resolution_note,
            activity_trace=activity_trace,
        )

    def _analysis_reply_with_gemini(
        self,
        message: str,
        query_response: QueryResponse,
        resolution_note: str | None,
    ) -> str:
        fallback = self._analysis_text(query_response, resolution_note)
        if not self.gemini_client.is_configured():
            return fallback

        prompt = (
            "You are Atlas, an ODI cricket analyst assistant.\n"
            "You are given a database-backed result. Rewrite it as a concise, sharp analyst answer.\n"
            "Rules:\n"
            "- Respect the database result exactly.\n"
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
        return generated or fallback

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
        if resolution_note:
            return f"{resolution_note}\n\n{summary_text}".strip()
        return summary_text or "I analyzed the ODI data and attached the structured evidence below."

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

    def _resolve_entities(self, message: str) -> tuple[str, str | None]:
        tokens = re.findall(r"[A-Za-z][A-Za-z'.-]+", message)
        phrases = self._candidate_phrases(tokens)
        replacements: dict[str, str] = {}
        resolution_notes: list[str] = []

        for phrase in phrases:
            normalized_phrase = phrase.strip()
            if len(normalized_phrase) < 4 or normalized_phrase.lower() in STOPWORDS:
                continue
            if normalized_phrase in replacements:
                continue
            candidates = self.repository.search_players(normalized_phrase, limit=5)
            if not candidates:
                continue
            selected = candidates[0] if len(candidates) == 1 else self._choose_candidate_with_ai(message, normalized_phrase, candidates)
            if not selected:
                continue
            if selected.lower() == normalized_phrase.lower():
                continue
            if selected.lower() in message.lower():
                continue
            replacements[normalized_phrase] = selected
            resolution_notes.append(f"{normalized_phrase} -> {selected}")

        if not replacements:
            return message.strip(), None

        resolved_message = message
        for phrase, candidate in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            resolved_message = re.sub(
                rf"\b{re.escape(phrase)}\b",
                candidate,
                resolved_message,
                flags=re.IGNORECASE,
            )

        if not resolution_notes:
            return resolved_message.strip(), None
        if len(resolution_notes) == 1:
            source, target = resolution_notes[0].split(" -> ", maxsplit=1)
            return resolved_message.strip(), f"Interpreting {source} as {target}."
        note = "; ".join(resolution_notes)
        return resolved_message.strip(), f"Resolved player names: {note}."

    @staticmethod
    def _candidate_phrases(tokens: list[str]) -> list[str]:
        phrases: list[str] = []
        total = len(tokens)
        for size in range(3, 0, -1):
            for start in range(total - size + 1):
                phrase = " ".join(tokens[start : start + size])
                if phrase not in phrases:
                    phrases.append(phrase)
        return phrases

    def _choose_candidate_with_ai(self, message: str, phrase: str, candidates: list[str]) -> str | None:
        if self.gemini_client.is_configured():
            prompt = (
                "Pick the most likely ODI player referenced by the user.\n"
                "Return only one candidate exactly as written, or NONE.\n"
                f"User message: {message}\n"
                f"Ambiguous phrase: {phrase}\n"
                f"Candidates: {', '.join(candidates)}"
            )
            generated = self.gemini_client.generate_text(prompt, prefer_complex=False)
            if generated:
                cleaned = generated.strip()
                for candidate in candidates:
                    if cleaned.lower() == candidate.lower():
                        return candidate
        return candidates[0]

    def _build_activity_trace(self, query_response: QueryResponse) -> list[str]:
        trace = []
        if self.gemini_client.is_configured():
            trace.append("Gemini reasoning")
        if query_response.interpretation.entities or query_response.tables or query_response.visuals:
            trace.append("ODI database")
        if any(citation.source_type == CitationSource.external_web for citation in query_response.citations):
            trace.append("Web context")
        return trace
