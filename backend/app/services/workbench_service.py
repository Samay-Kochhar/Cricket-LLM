from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, UTC
from uuid import uuid4

from backend.app.services.gemini_client import GeminiClient
from backend.app.services.player_resolution import normalize_name


def _trace_event(message: str) -> str:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    return f"{timestamp} | {message}"


@dataclass(slots=True)
class WorkbenchService:
    repository: object
    query_handler: object
    gemini_client: GeminiClient

    def search(self, raw_query: str) -> dict[str, object]:
        trace_id = str(uuid4())
        trace = [_trace_event(f"{trace_id} | received search query")]
        query = raw_query.strip()
        if not query:
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | empty query rejected")],
                "kind": "empty",
            }

        player_candidates = self.repository.search_players(query, limit=5)
        team_candidates = self.repository.search_teams(query, limit=5)
        trace.append(_trace_event(f"{trace_id} | player candidates={len(player_candidates)} team candidates={len(team_candidates)}"))

        selection = self._select_mode(query, player_candidates, team_candidates)
        trace.append(_trace_event(f"{trace_id} | selected mode={selection['kind']}"))

        if selection["kind"] == "player":
            player_name = selection["player_name"]
            query_text = self._workbench_query_text(query, player_name)
            query_response = self.query_handler(query_text)
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | returning player result for {player_name}")],
                "kind": "player_result",
                "query": query_text,
                "player_name": player_name,
                "role_summary": self._build_role_summary(player_name),
                "query_response": query_response.model_dump(),
            }

        if selection["kind"] == "team_year_required":
            team_name = selection["team_name"]
            years = self.repository.get_team_available_years(team_name)
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | requesting year for team={team_name}")],
                "kind": "team_year_required",
                "team_name": team_name,
                "available_years": years[:12],
            }

        if selection["kind"] == "team_squad":
            team_name = selection["team_name"]
            year = selection["year"]
            squad = self.repository.get_team_year_squad(team_name, year)
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | returning squad for {team_name} {year}")],
                "kind": "team_squad",
                "team_name": team_name,
                "year": year,
                "players": squad,
            }

        return {
            "trace_id": trace_id,
            "trace": trace + [_trace_event(f"{trace_id} | unsupported search result")],
            "kind": "unsupported",
            "message": "Atlas Workbench could not resolve that search yet. Try a player name or a team and year.",
        }

    def _select_mode(
        self,
        query: str,
        player_candidates: list[str],
        team_candidates: list[str],
    ) -> dict[str, object]:
        lowered = query.lower()
        year_matches = [int(match) for match in re.findall(r"\b(20\d{2})\b", lowered)]
        if player_candidates and not team_candidates:
            return {"kind": "player", "player_name": player_candidates[0]}
        if team_candidates and not player_candidates:
            team_name = team_candidates[0]
            if year_matches:
                return {"kind": "team_squad", "team_name": team_name, "year": year_matches[0]}
            return {"kind": "team_year_required", "team_name": team_name}
        if player_candidates and team_candidates:
            return self._choose_with_ai(query, player_candidates, team_candidates, year_matches)
        return {"kind": "unsupported"}

    def _choose_with_ai(
        self,
        query: str,
        player_candidates: list[str],
        team_candidates: list[str],
        year_matches: list[int],
    ) -> dict[str, object]:
        if self.gemini_client.is_configured():
            prompt = (
                "Classify the user's workbench search.\n"
                "Return exactly one line in one of these forms:\n"
                "PLAYER|<name>\n"
                "TEAM|<name>\n"
                f"User query: {query}\n"
                f"Player candidates: {', '.join(player_candidates) or 'none'}\n"
                f"Team candidates: {', '.join(team_candidates) or 'none'}"
            )
            generated = self.gemini_client.generate_text(prompt, prefer_complex=False)
            if generated:
                cleaned = generated.strip().splitlines()[0]
                if cleaned.startswith("PLAYER|"):
                    candidate = cleaned.split("|", maxsplit=1)[1].strip()
                    if candidate in player_candidates:
                        return {"kind": "player", "player_name": candidate}
                if cleaned.startswith("TEAM|"):
                    candidate = cleaned.split("|", maxsplit=1)[1].strip()
                    if candidate in team_candidates:
                        if year_matches:
                            return {"kind": "team_squad", "team_name": candidate, "year": year_matches[0]}
                        return {"kind": "team_year_required", "team_name": candidate}

        if year_matches and team_candidates:
            return {"kind": "team_squad", "team_name": team_candidates[0], "year": year_matches[0]}
        return {"kind": "player", "player_name": player_candidates[0]}

    @staticmethod
    def _workbench_query_text(query: str, player_name: str) -> str:
        normalized_query = normalize_name(query)
        normalized_player = normalize_name(player_name)
        if normalized_query == normalized_player:
            return f"show me some stats of {player_name}"
        return query

    def _build_role_summary(self, player_name: str) -> str:
        squad = self.repository.get_team_year_squad
        del squad
        summary = self.repository.get_player_batting_summary(player_name)
        hand = self.repository.get_primary_batting_hand(player_name)
        split = self.repository.get_player_split_summary(player_name)
        pieces = []
        if hand == "RHB":
            pieces.append("Right-hand bat")
        elif hand == "LHB":
            pieces.append("Left-hand bat")
        if split.get("pace_strike_rate") is not None or split.get("spin_strike_rate") is not None:
            pieces.append("ODI batter profile")
        if summary and summary.get("balls_faced", 0) > 0:
            pieces.append(f"{summary['runs_scored']} ODI runs")
        return " | ".join(pieces) if pieces else "ODI player profile"
