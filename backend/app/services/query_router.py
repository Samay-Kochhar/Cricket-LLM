from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.domain.metric_models import QueryClass
from backend.app.services.player_resolution import normalize_name, resolve_player_name


@dataclass(frozen=True, slots=True)
class QueryRoute:
    query_class: QueryClass
    entities: tuple[str, ...]
    filters: dict[str, object]


class QueryRouter:
    def __init__(self, available_players: list[str]) -> None:
        self.available_players = available_players

    def route(self, question: str) -> QueryRoute:
        return QueryRoute(
            query_class=self._classify(question),
            entities=self._extract_entities(question),
            filters=self._extract_filters(question),
        )

    def _classify(self, question: str) -> QueryClass:
        lowered = question.lower()
        if any(token in lowered for token in (" vs ", " versus ", "matchup")):
            return QueryClass.head_to_head_matchup
        if any(token in lowered for token in ("weakness", "weaknesses", "struggle", "struggles", "out the most", "shot")):
            return QueryClass.strengths_weaknesses
        if any(token in lowered for token in ("best statistics", "best batsman", "best bowler", "stadium", "ground", "venue")):
            return QueryClass.venue_context_leaderboard
        if any(token in lowered for token in ("become more", "trend", "after ", "since ", "years", "starting years")):
            return QueryClass.trend_progression
        return QueryClass.role_comparison

    def _extract_entities(self, question: str) -> tuple[str, ...]:
        normalized_question = normalize_name(question)
        matched: list[tuple[int, str]] = []
        for player in self.available_players:
            normalized_player = normalize_name(player)
            position = normalized_question.find(normalized_player)
            if position >= 0:
                matched.append((position, player))
        if matched:
            deduped: list[str] = []
            for _, player in sorted(matched, key=lambda item: item[0]):
                if player not in deduped:
                    deduped.append(player)
            return tuple(deduped[:2])

        resolved: list[str] = []
        for ngram in re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}", question):
            result = resolve_player_name(ngram, self.available_players)
            if result.canonical_name and result.canonical_name not in resolved:
                resolved.append(result.canonical_name)
            if len(resolved) >= 2:
                break
        return tuple(resolved)

    def _extract_filters(self, question: str) -> dict[str, object]:
        lowered = question.lower()
        filters: dict[str, object] = {}
        year_matches = [int(match) for match in re.findall(r"\b(20\d{2})\b", lowered)]
        if year_matches:
            filters["years"] = year_matches
        if "after " in lowered and year_matches:
            filters["year_mode"] = "after"
        if "before " in lowered and year_matches:
            filters["year_mode"] = "before"
        if "powerplay" in lowered:
            filters["phase"] = "powerplay"
        elif "middle" in lowered:
            filters["phase"] = "middle"
        elif "death" in lowered:
            filters["phase"] = "death"
        return filters
