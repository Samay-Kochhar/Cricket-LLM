from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, UTC
from uuid import uuid4

from backend.app.domain.evidence_models import EvidenceStatus, QueryResponse
from backend.app.services.chat_service import standalone_metric_clarification
from backend.app.services.player_resolution import ALIASES, normalize_name


YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
# Words that may accompany an exact team name in a structured squad lookup,
# such as "India squad 2019". They never carry analytical meaning.
TEAM_LOOKUP_WORDS = frozenset({"squad", "team", "side", "odi", "odis", "in"})
# A structured player lookup is a name, not a sentence.
MAX_PLAYER_LOOKUP_TOKENS = 4


def _trace_event(message: str) -> str:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    return f"{timestamp} | {message}"


@dataclass(slots=True)
class WorkbenchService:
    """Route a Workbench search to a structured lookup or shared analytics meaning.

    Exact player names/aliases and exact team names (with an optional year) keep
    their structured result modes; an exact player keeps the approved profile
    response. Everything else is a natural-language analytics question and is
    answered by the same query handler as Atlas chat, so entity resolution
    happens on extracted mentions, never on token overlap between the whole
    sentence and player names.
    """

    repository: object
    query_handler: object
    profile_handler: object

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

        selection = self._structured_lookup(query)
        if selection is None:
            trace.append(_trace_event(f"{trace_id} | selected mode=analytics"))
            return self._analytics_result(query, trace_id, trace)
        trace.append(_trace_event(f"{trace_id} | selected mode={selection['kind']}"))

        if selection["kind"] == "player":
            player_name = str(selection["player_name"])
            query_text = f"show me some stats of {player_name}"
            return self._player_result(player_name, query_text, self.profile_handler(query_text), trace_id, trace)

        if selection["kind"] == "player_choice":
            options = list(selection["options"])
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | requesting player choice among {len(options)}")],
                "kind": "clarification",
                "query": query,
                "message": "Which player do you mean?",
                "options": [{"label": name, "query": name} for name in options],
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

    def _structured_lookup(self, query: str) -> dict[str, object] | None:
        """Return a structured lookup only when the whole input names a team or player."""
        years = [int(match) for match in YEAR_PATTERN.findall(query)]
        tokens = normalize_name(YEAR_PATTERN.sub(" ", query)).split()
        if not tokens:
            return None

        team_tokens = [token for token in tokens if token not in TEAM_LOOKUP_WORDS]
        teams = {normalize_name(team): team for team in self.repository.list_teams()}
        team_name = teams.get(" ".join(team_tokens))
        if team_name is not None:
            if years:
                return {"kind": "team_squad", "team_name": team_name, "year": years[0]}
            return {"kind": "team_year_required", "team_name": team_name}

        if years or len(tokens) > MAX_PLAYER_LOOKUP_TOKENS:
            return None
        normalized = " ".join(tokens)
        players = self.repository.list_player_names()
        by_name = {normalize_name(player): player for player in players}
        if normalized in by_name:
            return {"kind": "player", "player_name": by_name[normalized]}
        alias_target = ALIASES.get(normalized)
        if alias_target is not None and normalize_name(alias_target) in by_name:
            return {"kind": "player", "player_name": by_name[normalize_name(alias_target)]}

        # Every typed word must be a whole word of the player's name ("Sharma",
        # "Virat"). Partial overlap with a sentence never selects a player.
        requested = set(tokens)
        matches = sorted(
            player for normalized_player, player in by_name.items()
            if requested <= set(normalized_player.split())
        )
        if len(matches) == 1:
            return {"kind": "player", "player_name": matches[0]}
        if matches:
            return {"kind": "player_choice", "options": matches}
        return None

    def _analytics_result(self, query: str, trace_id: str, trace: list[str]) -> dict[str, object]:
        metric_clarification = standalone_metric_clarification(query)
        if metric_clarification is not None:
            message, options = metric_clarification
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | requesting metric choice")],
                "kind": "clarification",
                "query": query,
                "message": message,
                "options": [{"label": option.label, "query": option.message} for option in options],
            }

        query_response: QueryResponse = self.query_handler(query)
        if query_response.clarification_question:
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | analytics requested clarification")],
                "kind": "clarification",
                "query": query,
                "message": query_response.clarification_question,
                "options": [
                    {"label": option, "query": f"{query} Use {option}."}
                    for option in query_response.clarification_options
                ],
            }
        if query_response.status != EvidenceStatus.supported:
            details = [item.detail for item in query_response.insufficiencies]
            return {
                "trace_id": trace_id,
                "trace": trace + [_trace_event(f"{trace_id} | analytics status={query_response.status.value}")],
                "kind": "unsupported",
                "message": " ".join(details)
                or "Atlas Workbench could not answer that ODI question from the database.",
            }

        players = set(self.repository.list_player_names())
        entities = query_response.interpretation.entities
        if len(entities) == 1 and entities[0] in players:
            return self._player_result(entities[0], query, query_response, trace_id, trace)
        summary = query_response.summaries[0].body if query_response.summaries else ""
        return {
            "trace_id": trace_id,
            "trace": trace + [_trace_event(f"{trace_id} | returning analytics result")],
            "kind": "analytics_result",
            "query": query,
            "summary": summary,
            "query_response": query_response.model_dump(),
        }

    def _player_result(
        self,
        player_name: str,
        query_text: str,
        query_response: QueryResponse,
        trace_id: str,
        trace: list[str],
    ) -> dict[str, object]:
        return {
            "trace_id": trace_id,
            "trace": trace + [_trace_event(f"{trace_id} | returning player result for {player_name}")],
            "kind": "player_result",
            "query": query_text,
            "player_name": player_name,
            "role_summary": self._build_role_summary(player_name),
            "query_response": query_response.model_dump(),
        }

    def _build_role_summary(self, player_name: str) -> str:
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
