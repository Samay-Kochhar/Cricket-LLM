from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.domain.intent_models import CricketIntentPlan
from backend.app.domain.metric_models import QueryClass
from backend.app.services.player_resolution import ALIASES, normalize_name, resolve_player_name

TEAM_ADJECTIVES = {
    "afghan": "Afghanistan",
    "australian": "Australia",
    "bangladeshi": "Bangladesh",
    "english": "England",
    "indian": "India",
    "irish": "Ireland",
    "kiwi": "New Zealand",
    "new zealand": "New Zealand",
    "pakistani": "Pakistan",
    "south african": "South Africa",
    "sri lankan": "Sri Lanka",
    "west indian": "West Indies",
    "zimbabwean": "Zimbabwe",
}


@dataclass(frozen=True, slots=True)
class QueryRoute:
    query_class: QueryClass
    entities: tuple[str, ...]
    filters: dict[str, object]
    intent_plan: CricketIntentPlan | None = None


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
        entities = self._extract_entities(question)
        filters = self._extract_filters(question)
        if filters.get("external_fact"):
            return QueryClass.venue_context_leaderboard
        if entities and filters.get("group_by") in {"opponent", "venue"}:
            return QueryClass.role_comparison
        if entities and ("bowling figure" in lowered or "bowling figures" in lowered):
            return QueryClass.role_comparison
        if len(self._extract_position_groups(lowered)) >= 2:
            return QueryClass.role_comparison
        is_ranked_question = any(lowered.startswith(prefix) for prefix in ("which ", "who "))
        if not is_ranked_question and any(
            token in lowered
            for token in (
                "become more",
                "trend",
                "after ",
                "since ",
                "years",
                "year by year",
                "role changes",
                "over time",
                "starting years",
            )
        ):
            return QueryClass.trend_progression
        if any(token in lowered for token in (" vs ", " versus ", "matchup")):
            return QueryClass.head_to_head_matchup
        if len(entities) >= 2 and any(token in lowered for token in ("against", "to ", "versus", "record")):
            return QueryClass.head_to_head_matchup
        if not is_ranked_question and any(token in lowered for token in ("weakness", "weaknesses", "struggle", "struggles", "out the most", "shot")):
            return QueryClass.strengths_weaknesses
        if (
            any(token in lowered for token in ("best statistics", "best batsman", "best bowler", "stadium", "ground", "venue"))
            or (
                any(token in lowered for token in ("best", "worst", "lowest", "highest", "top", "most", "fewest", "fastest", "economical"))
                and any(token in lowered for token in ("economy", "wicket", "bowler", "bowling", "batter", "player", "yorker", "dot", "boundary", "strike rate", "runs", "false shot"))
            )
            or is_ranked_question
        ):
            return QueryClass.venue_context_leaderboard
        return QueryClass.role_comparison

    def _extract_entities(self, question: str) -> tuple[str, ...]:
        normalized_question = normalize_name(question)
        matched: list[tuple[int, str]] = []
        for player in self.available_players:
            normalized_player = normalize_name(player)
            position = normalized_question.find(normalized_player)
            if position >= 0:
                matched.append((position, player))
        for alias, canonical in ALIASES.items():
            alias_position = normalized_question.find(normalize_name(alias))
            if alias_position >= 0:
                result = resolve_player_name(canonical, self.available_players)
                if result.canonical_name:
                    matched.append((alias_position, result.canonical_name))

        if matched:
            deduped: list[str] = []
            for _, player in sorted(matched, key=lambda item: item[0]):
                if player not in deduped:
                    deduped.append(player)
            return tuple(deduped[:2])

        resolved: list[str] = []
        for ngram in re.findall(r"(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,})){0,3}", question):
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
        if "world cup" in lowered or "cricket world cup" in lowered:
            filters["competition"] = "World Cup 2023" if 2023 in year_matches else "ICC Cricket World Cup"
        if any(token in lowered for token in ("player of the match", "man of the match", "potm")):
            filters["external_fact"] = "player_of_match"
            filters["subject"] = "player"
            if "final" in lowered:
                filters["stage"] = "final"
        elif "final" in lowered:
            filters["stage"] = "final"
        if ("after " in lowered or "since " in lowered) and year_matches:
            filters["year_mode"] = "after"
        if "before " in lowered and year_matches:
            filters["year_mode"] = "before"
        if "powerplay" in lowered:
            filters["phase"] = "powerplay"
        elif "first six" in lowered or "first 6" in lowered:
            filters["phase"] = "first6"
        elif "middle" in lowered:
            filters["phase"] = "middle"
        elif "death" in lowered or "40-50" in lowered or "overs 40" in lowered:
            filters["phase"] = "death"
        over_match = re.search(r"\b(?:over|overs)\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?\b", lowered)
        if over_match:
            start = int(over_match.group(1))
            end = int(over_match.group(2) or start)
            filters["over_range"] = [start, end]
        position_groups = self._extract_position_groups(lowered)
        if position_groups:
            filters["position_groups"] = position_groups
        if "catch" in lowered or "catches" in lowered:
            filters["subject"] = "fielder"
            filters["skill"] = "fielding"
            filters["metric"] = "catches_taken"
        elif any(token in lowered for token in ("bowler", "bowling", "bowled", "concedes", "dismissed", "wicket", "yorker")):
            filters["subject"] = "bowler"
        elif any(token in lowered for token in ("batter", "batsman", "scores", "scored", "runs", "strike", "boundary percentage", "rotates")):
            filters["subject"] = "batter"
        asks_for_bowler_selection = bool(
            re.search(r"\bwhich\s+(?:spinner|bowler|seamer|pacer|player)\b", lowered)
            and any(token in lowered for token in ("should bowl", "bowl to", "held back for"))
        )
        if (
            any(token in lowered for token in ("bowling plan", "bowl to", "bowl against", "how should we bowl", "held back for"))
            and not asks_for_bowler_selection
        ):
            filters["plan_type"] = "bowling_to_batter"
            filters["subject"] = "batter"
            filters["skill"] = "bowling"
        if "against which batter" in lowered or "against which batters" in lowered or "which batter should be targeted" in lowered or "which batters should be targeted" in lowered:
            filters["subject"] = "batter"
        excluded_teams = self._extract_excluded_teams(lowered)
        if excluded_teams:
            filters["excluded_teams"] = excluded_teams
        bowling_terms = (
            "economy",
            "bowling",
            "bowled",
            "bowler",
            "wicket",
            "wickets",
            "balls per wicket",
            "balls/wicket",
            "balls per boundary",
            "balls/boundary",
            "runs conceded",
            "conceded",
            "yorker",
            "false shot",
            "false shots",
            "bowling figure",
            "bowling figures",
        )
        if any(term in lowered for term in bowling_terms):
            filters["skill"] = "bowling"
        if "spinner" in lowered or "spin" in lowered:
            filters["bowling_kind"] = "spin bowler"
            filters.setdefault("subject", "bowler")
            filters.setdefault("skill", "bowling")
        elif "pace" in lowered or "seam" in lowered or "fast bowler" in lowered or "fast bowling" in lowered:
            filters["bowling_kind"] = "pace bowler"
        if "left-hand" in lowered or "left hand" in lowered or "lhb" in lowered:
            filters["bat_hand"] = "LHB"
        elif "right-hand" in lowered or "right hand" in lowered or "rhb" in lowered:
            filters["bat_hand"] = "RHB"
        if "left-arm pace" in lowered:
            filters["bowling_style_group"] = "left_arm_pace"
        elif "leg spin" in lowered or "leg-spin" in lowered:
            filters["bowling_style_group"] = "leg_spin"
        elif "short ball" in lowered or "short balls" in lowered or "short-ball" in lowered or "short-balls" in lowered:
            filters["length"] = "SHORT"
        elif "full ball" in lowered or "full balls" in lowered or "full-ball" in lowered or "full-balls" in lowered:
            filters["length"] = "FULL"
        elif "yorker" in lowered or "yorkers" in lowered:
            filters["length"] = "YORKER"
        if "pitch" in lowered:
            filters["group_by"] = "length"
        if "line" in lowered:
            filters["group_by"] = "line"
        if "length" in lowered:
            filters["group_by"] = "length"
        if any(token in lowered for token in ("bowling type", "bowling types", "bowling style", "bowling styles", "type of bowling")):
            filters["group_by"] = "bowling_style"
        if any(token in lowered for token in ("opponent wise", "opponent-wise", "opposition wise", "opposition-wise", "by opponent", "by opposition", "against each team")):
            filters["group_by"] = "opponent"
        if any(token in lowered for token in ("venue wise", "venue-wise", "ground wise", "ground-wise", "by venue", "by ground", "at each venue", "at each ground")):
            filters["group_by"] = "venue"
        if "balls bowled" in lowered or "ball bowled" in lowered or "deliveries bowled" in lowered:
            filters["metric"] = "balls_bowled"
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
        elif "overs bowled" in lowered or ("how many overs" in lowered and any(token in lowered for token in ("bowled", "bowling", "bowl"))):
            filters["metric"] = "overs_bowled"
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
        elif "balls faced" in lowered or "ball faced" in lowered or "balls did" in lowered and "face" in lowered:
            filters["metric"] = "balls_faced"
            filters["subject"] = "batter"
            filters["skill"] = "batting"
        elif "bowling figure" in lowered or "bowling figures" in lowered:
            filters["metric"] = "best_bowling_figures"
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
        elif "economy" in lowered or "economical" in lowered:
            filters["metric"] = "economy_rate"
        elif "yorker success" in lowered:
            filters["metric"] = "yorker_success_rate"
        elif "yorker" in lowered:
            filters["metric"] = "yorker_count"
        elif "false shot" in lowered or "false shots" in lowered or "false-shot" in lowered or "false-shots" in lowered:
            filters["metric"] = "false_shot_percentage"
        elif "dot ball percentage" in lowered or "dot-ball percentage" in lowered or "dot percentage" in lowered:
            if filters.get("subject") == "bowler" or any(token in lowered for token in ("bowler", "bowling", "bowled")):
                filters["metric"] = "bowler_dot_percentage"
                filters["subject"] = "bowler"
                filters["skill"] = "bowling"
            else:
                filters["metric"] = "dot_percentage"
                filters["subject"] = "batter"
                filters["skill"] = "batting"
        elif "dot ball" in lowered or "dot balls" in lowered:
            if filters.get("subject") == "bowler" or any(token in lowered for token in ("bowler", "bowling", "bowled")):
                filters["metric"] = "bowler_dot_balls"
                filters["subject"] = "bowler"
                filters["skill"] = "bowling"
            else:
                filters["metric"] = "dot_balls"
                filters.setdefault("subject", "batter")
                filters.setdefault("skill", "batting")
        elif "boundary percentage" in lowered:
            filters["metric"] = "boundary_percentage"
        elif "boundaries per over" in lowered:
            filters["metric"] = "boundaries_per_over"
        elif "boundary" in lowered and filters.get("subject") == "bowler":
            filters["metric"] = "boundaries_per_over"
        elif "rotates strike" in lowered or "rotate strike" in lowered:
            filters["metric"] = "strike_rotation_percentage"
            filters.setdefault("subject", "batter")
        elif "struggles" in lowered or "struggle" in lowered:
            filters["metric"] = "batting_strike_rate"
            filters.setdefault("subject", "batter")
            filters["rank_intent"] = "worst"
        elif "strike rate" in lowered or "scores fastest" in lowered or "score fastest" in lowered or "fastest" in lowered:
            filters["metric"] = "batting_strike_rate"
            filters["subject"] = "batter" if filters.get("group_by") == "bowling_style" else filters.get("subject", "batter")
        elif "average" in lowered or "avg" in lowered:
            filters["metric"] = "batting_average"
            filters.setdefault("subject", "batter")
        elif "runs" in lowered or "scored" in lowered:
            filters["metric"] = "runs_scored"
            filters.setdefault("subject", "batter")
        elif "catch" in lowered or "catches" in lowered:
            filters["metric"] = "catches_taken"
            filters["subject"] = "fielder"
            filters["skill"] = "fielding"
        elif "balls per wicket" in lowered or "balls/wicket" in lowered:
            filters["metric"] = "balls_per_wicket"
        elif "balls per boundary" in lowered or "balls/boundary" in lowered:
            filters["metric"] = "balls_per_boundary"
        elif "wicket" in lowered:
            filters["metric"] = "wickets_taken"
        if "dismissed" in lowered or "dismisses" in lowered or "dismissals" in lowered or "delivery type" in lowered:
            filters["metric"] = "wickets_taken"
            filters["subject"] = "bowler"
            filters["matchup_role"] = "bowler_vs_batter"
            if "delivery type" in lowered:
                filters["group_by"] = "length"
        if "against" in lowered and self._extract_entities(question):
            filters.setdefault("matchup_role", "context_against_player")
        rank_intent = self._extract_rank_intent(lowered, filters.get("metric"))
        if rank_intent:
            filters["rank_intent"] = rank_intent
        if filters.get("subject") == "batter" and ("targeted" in lowered or "used most frequently" in lowered):
            filters["metric"] = "batting_strike_rate"
            filters["rank_intent"] = "worst"
        if filters.get("group_by") == "opponent" and any(token in lowered for token in ("successful", "success", "best", "most")):
            filters.setdefault("rank_intent", "best")
        self._apply_semantic_overrides(lowered, filters)
        return filters

    @staticmethod
    def _apply_semantic_overrides(lowered: str, filters: dict[str, object]) -> None:
        field_zone_aliases = {
            "midwicket": ("mid wicket", "mid-wicket", "midwicket"),
            "cover": ("cover", "covers"),
            "point": ("point", "deep point"),
            "third_man": ("third man", "third-man"),
            "fine_leg": ("fine leg", "fine-leg"),
            "square_leg": ("square leg", "square-leg"),
            "long_on": ("long on", "long-on"),
            "long_off": ("long off", "long-off"),
        }
        requested_field_zone = next(
            (
                zone
                for zone, aliases in field_zone_aliases.items()
                if any(alias in lowered for alias in aliases)
            ),
            None,
        )
        if requested_field_zone and any(token in lowered for token in ("batter", "score", "scores", "scored", "runs", "run")):
            filters["subject"] = "batter"
            filters["skill"] = "batting"
            filters["metric"] = "runs_scored"
            filters["field_zone"] = requested_field_zone
            filters["rank_intent"] = "best"

        asks_bowling_type = any(
            token in lowered
            for token in ("bowling type", "bowling types", "bowling style", "bowling styles", "type of bowling")
        )
        if asks_bowling_type:
            filters["group_by"] = "bowling_style"
            if any(token in lowered for token in ("score fastest", "scores fastest", "strike rate", "score most")):
                filters["subject"] = "batter"
                filters["metric"] = "batting_strike_rate"
                filters["rank_intent"] = "best"

        if "line" in lowered and "dot ball" in lowered:
            filters["group_by"] = "line"
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "bowler_dot_balls"
            filters["rank_intent"] = "best"

        if "length" in lowered and any(token in lowered for token in ("dismisses", "dismissed", "dismissals")):
            filters["group_by"] = "length"
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "wickets_taken"
            filters["rank_intent"] = "best"

        if "shot" in lowered and any(token in lowered for token in ("score most", "scores most", "most runs", "score the most")):
            filters["group_by"] = "shot"
            filters["subject"] = "batter"
            filters["skill"] = "batting"
            filters["metric"] = "runs_scored"
            filters["rank_intent"] = "best"

        if "phase" in lowered and any(token in lowered for token in ("productive", "contributes", "produces")):
            filters["group_by"] = "phase"
            filters.setdefault("metric", "runs_scored" if "wicket" not in lowered and "dot ball" not in lowered else filters.get("metric"))
            if "wicket" in lowered:
                filters["metric"] = "wickets_taken"
            elif "dot ball" in lowered:
                filters["metric"] = "dot_balls"
            filters.setdefault("subject", "batter")
            filters["rank_intent"] = "best"

        if "after facing 20 balls" in lowered or "after 20 balls" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "strike_rate_improvement_after_20"
            filters["split_after_balls"] = 20
            filters["rank_intent"] = "best"

        if "milestone" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "milestone_vulnerability_lift"
            filters["context_tag"] = "after_milestone"
            filters["post_milestone_balls"] = 12
            filters["rank_intent"] = "best"

        if "false-shot percentage against spin" in lowered or "false shot percentage against spin" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "false_shot_percentage"
            filters["bowling_kind"] = "spin bowler"
            filters["rank_intent"] = "best"

        if "hardest to bowl dot balls to" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "dot_percentage"
            filters["rank_intent"] = "best"

        if "scoring zones" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "runs_scored"
            filters["group_by"] = "field_zone"
            filters["rank_intent"] = "best"

        if "percentage of yorkers" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "yorker_percentage"
            filters.pop("length", None)
            filters["rank_intent"] = "best"

        if "false shots per over" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "false_shots_per_over"
            filters["rank_intent"] = "best"

        if "immediately after a wicket" in lowered or "after a wicket falls" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "economy_rate"
            filters["context_tag"] = "after_wicket"
            filters["rank_intent"] = "best"

        if "boundaries per 100 balls" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "boundaries_per_100_balls"
            filters["rank_intent"] = "best"

        if "wides and no-balls" in lowered or "wides and no balls" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "extras_rate"
            filters["rank_intent"] = "best"

        if "high-pressure" in lowered or "high pressure" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "economy_rate"
            filters["context_tag"] = "high_pressure"
            filters["rank_intent"] = "best"

        if "wicket opportunities" in lowered and "without taking wickets" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "false_shot_percentage"
            filters["context_tag"] = "wicket_opportunities_without_wickets"
            filters["rank_intent"] = "best"

        if "against set batters" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "economy_rate"
            filters["context_tag"] = "set_batters"
            filters["rank_intent"] = "best"

        if "finishers" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "wickets_taken"
            filters["context_tag"] = "finishers"
            filters["rank_intent"] = "best"

        if "one-sided" in lowered and "matchup" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "batting_strike_rate"
            filters["group_by"] = "matchup"
            filters["rank_intent"] = "best"

        if "matchup" in lowered and "false-shot" in lowered or "matchup" in lowered and "false shot" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "false_shot_percentage"
            filters["group_by"] = "matchup"
            filters["rank_intent"] = "best"

        if "elite bowlers" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "batting_strike_rate"
            filters["context_tag"] = "elite_bowlers"
            filters["rank_intent"] = "best"

        if "left-handers" in lowered and "right-handers" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "economy_rate"
            filters["group_by"] = "bat_hand"
            filters["rank_intent"] = "best"

        if "length changes" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "balls_bowled"
            filters["group_by"] = "length"
            filters["context_tag"] = "by_batter"
            filters["rank_intent"] = "best"

        if "adapts best" in lowered and "dismissed by the same bowler" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "batting_strike_rate"
            filters["context_tag"] = "repeat_bowler_dismissal"
            filters["rank_intent"] = "best"

        if "defending 10 runs" in lowered or "final over" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "economy_rate"
            filters["phase"] = "death"
            filters["context_tag"] = "defending_final_over"
            filters["rank_intent"] = "best"

        if "held back" in lowered and "death" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "economy_rate"
            filters["phase"] = "death"
            filters["rank_intent"] = "best"

        if "field placement" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "runs_scored"
            filters["plan_type"] = "bowling_to_batter"
            filters["group_by"] = "field_zone"

        if "optimal bowling plan" in lowered or "bowling plan" in lowered:
            filters["subject"] = "batter"
            filters["skill"] = "bowling"
            filters["metric"] = "batting_strike_rate"
            filters["plan_type"] = "bowling_to_batter"

        if "batting position" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "runs_scored"
            filters["group_by"] = "batting_position"
            filters["rank_intent"] = "best"

        if "introduce spin" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "batting_strike_rate"
            filters["bowling_kind"] = "spin bowler"
            filters["context_tag"] = "spin_introduction"

        if "bowling length" in lowered and "ground" in lowered:
            filters["subject"] = "bowler"
            filters["skill"] = "bowling"
            filters["metric"] = "wickets_taken"
            filters["group_by"] = "length"
            filters["context_tag"] = "ground_length_priority"

        if "partnership" in lowered:
            filters["subject"] = "batter"
            filters["metric"] = "runs_scored"
            filters["group_by"] = "partnership"
            filters["rank_intent"] = "best"

        if "team" in lowered or "teams" in lowered:
            if any(token in lowered for token in ("middle overs", "powerplay", "death overs", "chases", "victories", "winning", "losing")):
                filters["subject"] = "team"
                filters.setdefault("metric", "runs_scored")
                filters["rank_intent"] = "best"

        if "phase" in lowered and any(token in lowered for token in ("wickets", "dot balls", "match outcome", "winning", "losing")):
            filters["subject"] = "team"
            filters["group_by"] = "phase"
            filters["rank_intent"] = "best"
            if "wicket" in lowered:
                filters["metric"] = "wickets_taken"
            elif "dot ball" in lowered:
                filters["metric"] = "dot_balls"
            else:
                filters["metric"] = "runs_scored"

        if "overs 15 and 20" in lowered or "between overs 15 and 20" in lowered:
            filters["subject"] = "team"
            filters["metric"] = "batting_strike_rate"
            filters["over_range"] = [15, 20]
            filters["rank_intent"] = "best"

        if "strategic timeouts" in lowered:
            filters["subject"] = "team"
            filters["metric"] = "batting_strike_rate"
            filters["context_tag"] = "after_strategic_timeout"
            filters["rank_intent"] = "best"

        if "early wickets" in lowered and "recovers" in lowered:
            filters["subject"] = "team"
            filters["metric"] = "runs_scored"
            filters["context_tag"] = "after_early_wickets"
            filters["rank_intent"] = "best"

    @staticmethod
    def _extract_excluded_teams(lowered: str) -> list[str]:
        if not any(token in lowered for token in ("other than", "excluding", "except", "apart from", "non-")):
            return []
        excluded: list[str] = []
        for adjective, team in TEAM_ADJECTIVES.items():
            if adjective in lowered or f"non-{adjective}" in lowered:
                excluded.append(team)
        for team in {
            "Afghanistan",
            "Australia",
            "Bangladesh",
            "England",
            "India",
            "Ireland",
            "New Zealand",
            "Pakistan",
            "South Africa",
            "Sri Lanka",
            "West Indies",
            "Zimbabwe",
        }:
            if normalize_name(team) in normalize_name(lowered):
                excluded.append(team)
        deduped: list[str] = []
        for team in excluded:
            if team not in deduped:
                deduped.append(team)
        return deduped

    @staticmethod
    def _extract_rank_intent(lowered: str, metric: object) -> str | None:
        if metric == "economy_rate":
            if any(token in lowered for token in ("worst", "highest", "most expensive", "expensive", "poorest")):
                return "worst"
            if any(token in lowered for token in ("best", "lowest", "top", "most economical", "economical")):
                return "best"
        if metric == "wickets_taken":
            if any(token in lowered for token in ("worst", "lowest", "fewest", "least")):
                return "worst"
            if any(token in lowered for token in ("best", "highest", "most", "top")):
                return "best"
        if metric in {"yorker_count", "bowler_dot_balls", "runs_scored", "catches_taken"}:
            if any(token in lowered for token in ("fewest", "least", "lowest")):
                return "worst"
            if any(token in lowered for token in ("most", "highest", "best", "top")):
                return "best"
        if metric in {"batting_strike_rate", "batting_average", "boundary_percentage", "false_shot_percentage", "yorker_success_rate"}:
            if any(token in lowered for token in ("lowest", "worst", "struggles", "struggle")):
                return "worst"
            if any(token in lowered for token in ("highest", "best", "fastest", "most", "top")):
                return "best"
        if metric in {"boundaries_per_over", "dot_percentage"}:
            if any(token in lowered for token in ("fewest", "least", "lowest", "best")):
                return "best"
            if any(token in lowered for token in ("highest", "most", "worst")):
                return "worst"
        if any(token in lowered for token in ("worst", "poorest")):
            return "worst"
        if any(token in lowered for token in ("best", "top", "highest", "most")):
            return "best"
        return None

    @staticmethod
    def _extract_position_groups(lowered_question: str) -> list[dict[str, object]]:
        groups: list[tuple[int, dict[str, object]]] = []

        def add_group(index: int, label: str, positions: list[int]) -> None:
            if not any(group["label"] == label for _, group in groups):
                groups.append((index, {"label": label, "positions": positions}))

        opening_match = re.search(r"\b(opening|opener|openers|opened)\b", lowered_question)
        if opening_match:
            add_group(opening_match.start(), "Opening", [1, 2])

        for match in re.finditer(r"\b(?:number|no\.?|position|at)\s*#?\s*(\d{1,2})\b|#(\d{1,2})\b", lowered_question):
            raw_position = match.group(1) or match.group(2)
            if raw_position is None:
                continue
            position = int(raw_position)
            if 1 <= position <= 11:
                add_group(match.start(), f"No. {position}", [position])

        return [group for _, group in sorted(groups, key=lambda item: item[0])]
