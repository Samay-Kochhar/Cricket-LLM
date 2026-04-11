from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend.app.domain.metric_models import QueryClass
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.player_resolution import resolve_player_name
from backend.app.services.query_router import QueryRoute, QueryRouter


@dataclass(frozen=True, slots=True)
class InterpretedQuestion:
    route: QueryRoute
    used_ai: bool


@dataclass(slots=True)
class QueryInterpreter:
    repository: object
    gemini_client: GeminiClient
    fallback_router: QueryRouter

    def interpret(self, question: str) -> InterpretedQuestion:
        question = question.strip()
        if not question:
            return InterpretedQuestion(
                route=QueryRoute(query_class=QueryClass.role_comparison, entities=(), filters={}),
                used_ai=False,
            )

        ai_route = self._interpret_with_ai(question)
        if ai_route is not None:
            return InterpretedQuestion(route=ai_route, used_ai=True)

        return InterpretedQuestion(route=self.fallback_router.route(question), used_ai=False)

    def _interpret_with_ai(self, question: str) -> QueryRoute | None:
        if not self.gemini_client.is_configured():
            return None

        prompt = (
            "You are an ODI cricket query interpreter.\n"
            "Convert the user's request into strict JSON only.\n"
            "Do not explain anything.\n"
            "Schema:\n"
            "{\n"
            '  "query_class": "role_comparison" | "strengths_weaknesses" | "head_to_head_matchup" | "venue_context_leaderboard" | "trend_progression",\n'
            '  "player_mentions": ["raw player mentions from the user"],\n'
            '  "filters": {\n'
            '    "phase": "powerplay" | "middle" | "death",\n'
            '    "years": [2023],\n'
            '    "year_mode": "after" | "before" | "exact",\n'
            '    "venue_name": "venue name if the user asked about a venue"\n'
            "  }\n"
            "}\n"
            "Rules:\n"
            "- Extract only genuine cricket entities.\n"
            "- Never treat filler words or conjunctions as player mentions.\n"
            "- Use player_mentions only for players actually referenced or strongly implied.\n"
            "- If the question is just normal conversation, still return the best query_class and leave player_mentions empty.\n"
            "- Return valid JSON only.\n\n"
            f"User question: {question}"
        )
        generated = self.gemini_client.generate_text(prompt, prefer_complex=False)
        if not generated:
            return None

        payload = self._parse_json_object(generated)
        if not isinstance(payload, dict):
            return None

        raw_query_class = payload.get("query_class")
        if not isinstance(raw_query_class, str):
            return None
        try:
            ai_query_class = QueryClass(raw_query_class)
        except ValueError:
            return None
        fallback_class = self.fallback_router.route(question).query_class
        query_class = self._reconcile_query_class(question, ai_query_class, fallback_class)

        raw_mentions = payload.get("player_mentions")
        mentions = [item.strip() for item in raw_mentions if isinstance(item, str) and item.strip()] if isinstance(raw_mentions, list) else []
        resolved_entities = self._resolve_player_mentions(question, mentions)

        raw_filters = payload.get("filters")
        filters = self._normalize_filters(raw_filters if isinstance(raw_filters, dict) else {})

        return QueryRoute(
            query_class=query_class,
            entities=tuple(resolved_entities[:2]),
            filters=filters,
        )

    @staticmethod
    def _reconcile_query_class(
        question: str,
        ai_query_class: QueryClass,
        fallback_class: QueryClass,
    ) -> QueryClass:
        lowered = question.lower()
        if any(token in lowered for token in (" vs ", " versus ", "matchup")):
            return QueryClass.head_to_head_matchup
        if any(
            token in lowered
            for token in (
                "weakness",
                "weaknesses",
                "struggle",
                "struggles",
                "out the most",
                "on which shots",
                "which shots",
                "where does",
            )
        ):
            return QueryClass.strengths_weaknesses
        if any(token in lowered for token in ("best statistics", "best batsman", "best bowler", "stadium", "ground", "venue")):
            return QueryClass.venue_context_leaderboard
        if any(token in lowered for token in ("become more", "trend", "after ", "since ", "years", "starting years")):
            return QueryClass.trend_progression
        if any(token in lowered for token in ("strike rate", "stats", "average", "runs", "show me some stats", "what are")):
            return QueryClass.role_comparison
        return ai_query_class if ai_query_class != QueryClass.strengths_weaknesses else fallback_class

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, object] | None:
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    def _resolve_player_mentions(self, question: str, mentions: list[str]) -> list[str]:
        available_names = self.repository.list_player_names()
        resolved: list[str] = []
        for mention in mentions:
            resolution = resolve_player_name(mention, available_names)
            if resolution.canonical_name:
                if resolution.canonical_name not in resolved:
                    resolved.append(resolution.canonical_name)
                continue

            candidates = self.repository.search_players(mention, limit=5)
            if not candidates:
                continue
            if len(candidates) == 1:
                candidate = candidates[0]
            else:
                candidate = self._choose_candidate(question, mention, candidates)
            if candidate and candidate not in resolved:
                resolved.append(candidate)
        return resolved

    def _choose_candidate(self, question: str, mention: str, candidates: list[str]) -> str | None:
        if self.gemini_client.is_configured():
            prompt = (
                "Pick the most likely ODI player referenced by the user.\n"
                "Return only one candidate exactly as written, or NONE.\n"
                f"User message: {question}\n"
                f"Ambiguous mention: {mention}\n"
                f"Candidates: {', '.join(candidates)}"
            )
            generated = self.gemini_client.generate_text(prompt, prefer_complex=False)
            if generated:
                cleaned = generated.strip()
                for candidate in candidates:
                    if cleaned.lower() == candidate.lower():
                        return candidate
        return candidates[0]

    @staticmethod
    def _normalize_filters(raw_filters: dict[str, object]) -> dict[str, object]:
        filters: dict[str, object] = {}

        phase = raw_filters.get("phase")
        if isinstance(phase, str) and phase in {"powerplay", "middle", "death"}:
            filters["phase"] = phase

        years = raw_filters.get("years")
        if isinstance(years, list):
            normalized_years = [int(item) for item in years if isinstance(item, int) or (isinstance(item, str) and item.isdigit())]
            if normalized_years:
                filters["years"] = normalized_years

        year_mode = raw_filters.get("year_mode")
        if isinstance(year_mode, str) and year_mode in {"after", "before", "exact"}:
            filters["year_mode"] = year_mode

        venue_name = raw_filters.get("venue_name")
        if isinstance(venue_name, str) and venue_name.strip():
            filters["venue_name"] = venue_name.strip()

        return filters
