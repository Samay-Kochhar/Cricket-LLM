from __future__ import annotations

import json
import re
from dataclasses import dataclass

from backend.app.domain.intent_models import (
    AnswerShape,
    ContextScope,
    CricketIntentPlan,
    CricketMetric,
    IntentAmbiguity,
    IntentSubject,
    MatchContext,
    QueryType,
    SubjectRole,
)
from backend.app.domain.metric_models import QueryClass
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.player_resolution import resolve_player_name
from backend.app.services.query_router import TEAM_ADJECTIVES, QueryRoute, QueryRouter


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

        fallback_route = self.fallback_router.route(question)
        return InterpretedQuestion(
            route=self._route_with_intent(question, fallback_route, self._intent_from_route(fallback_route)),
            used_ai=False,
        )

    def _interpret_with_ai(self, question: str) -> QueryRoute | None:
        if not self.gemini_client.is_configured():
            return None

        prompt = (
            "You are an ODI cricket query interpreter.\n"
            "Convert the user's request into a cricket intent plan as strict JSON only.\n"
            "Do not explain anything.\n"
            "Schema:\n"
            "{\n"
            '  "query_type": "single_metric" | "leaderboard" | "comparison" | "trend" | "match_fact" | "tactical_plan" | "strengths_weaknesses" | "conversation",\n'
            '  "answer_shape": "single_number" | "short_fact" | "leaderboard" | "comparison_table" | "trend_chart" | "scouting_report" | "tactical_plan" | "insufficient_data",\n'
            '  "query_class": "role_comparison" | "strengths_weaknesses" | "head_to_head_matchup" | "venue_context_leaderboard" | "trend_progression",\n'
            '  "metric": "balls_bowled" | "overs_bowled" | "balls_faced" | "runs_scored" | "runs_conceded" | "wickets_taken" | "economy_rate" | "best_bowling_figures" | "balls_per_wicket" | "balls_per_boundary" | "dot_balls" | "bowler_dot_balls" | "dot_percentage" | "bowler_dot_percentage" | "boundaries" | "boundaries_conceded" | "boundaries_per_over" | "boundaries_per_100_balls" | "catches_taken" | "dismissals" | "batting_strike_rate" | "strike_rate_improvement_after_20" | "milestone_vulnerability_lift" | "batting_average" | "boundary_percentage" | "strike_rotation_percentage" | "false_shot_percentage" | "false_shots_per_over" | "yorker_count" | "yorker_percentage" | "yorker_success_rate" | "extras_rate" | "player_of_match",\n'
            '  "subjects": [{"player": "canonical or raw player name", "team": "team if relevant", "role": "batter" | "bowler" | "fielder" | "player" | "team"}],\n'
            '  "context": {\n'
            '    "scope": "career" | "season" | "competition" | "single_match" | "phase" | "venue" | "matchup",\n'
            '    "competition": "ICC Cricket World Cup",\n'
            '    "year": 2011,\n'
            '    "years": [2011],\n'
            '    "year_mode": "after" | "before" | "exact",\n'
            '    "stage": "final",\n'
            '    "teams": ["India", "Sri Lanka"],\n'
            '    "venue_name": "venue name",\n'
            '    "phase": "powerplay" | "middle" | "death",\n'
            '    "group_by": "line" | "length" | "bowling_style" | "phase" | "shot" | "field_zone" | "bat_hand" | "batting_position" | "partnership" | "matchup" | "opponent" | "venue",\n'
            '    "length": "YORKER" | "FULL" | "GOOD_LENGTH" | "SHORT_OF_A_GOOD_LENGTH" | "SHORT" | "FULL_TOSS",\n'
            '    "line": "OUTSIDE_OFFSTUMP" | "ON_THE_STUMPS" | "WIDE_OUTSIDE_OFFSTUMP" | "DOWN_LEG" | "WIDE_DOWN_LEG",\n'
            '    "bowling_kind": "pace bowler" | "spin bowler",\n'
            '    "bowling_style_group": "left_arm_pace" | "leg_spin",\n'
            '    "bat_hand": "LHB" | "RHB",\n'
            '    "over_range": [41, 50]\n'
            '  },\n'
            '  "rank_intent": "best" | "worst",\n'
            '  "ambiguity": {"possible_alternate_metric": "balls_faced", "reason": "why alternate may be intended"},\n'
            '  "player_mentions": ["raw player mentions from the user"],\n'
            '  "filters": {\n'
            '    "phase": "powerplay" | "middle" | "death",\n'
            '    "years": [2023],\n'
            '    "year_mode": "after" | "before" | "exact",\n'
            '    "competition": "ICC Cricket World Cup",\n'
            '    "venue_name": "venue name if the user asked about a venue",\n'
            '    "excluded_teams": ["team names to exclude, e.g. England"],\n'
            '    "external_fact": "player_of_match",\n'
            '    "stage": "final",\n'
            '    "position_groups": [{"label": "Opening", "positions": [1, 2]}, {"label": "No. 3", "positions": [3]}],\n'
            '    "subject": "bowler" | "batter" | "fielder" | "player" | "team",\n'
            '    "skill": "batting" | "bowling" | "fielding",\n'
            '    "metric": "balls_bowled" | "overs_bowled" | "balls_faced" | "economy_rate" | "wickets_taken" | "best_bowling_figures" | "balls_per_wicket" | "balls_per_boundary" | "catches_taken" | "yorker_count" | "yorker_percentage" | "yorker_success_rate" | "bowler_dot_balls" | "boundaries_per_over" | "boundaries_per_100_balls" | "false_shot_percentage" | "false_shots_per_over" | "extras_rate" | "batting_strike_rate" | "strike_rate_improvement_after_20" | "milestone_vulnerability_lift" | "batting_average" | "boundary_percentage" | "runs_scored" | "dot_percentage" | "strike_rotation_percentage",\n'
            '    "length": "YORKER" | "FULL" | "GOOD_LENGTH" | "SHORT_OF_A_GOOD_LENGTH" | "SHORT" | "FULL_TOSS",\n'
            '    "line": "OUTSIDE_OFFSTUMP" | "ON_THE_STUMPS" | "WIDE_OUTSIDE_OFFSTUMP" | "DOWN_LEG" | "WIDE_DOWN_LEG",\n'
            '    "field_zone": "midwicket" | "cover" | "point" | "third_man" | "fine_leg" | "square_leg" | "long_on" | "long_off",\n'
            '    "group_by": "line" | "length" | "bowling_style" | "phase" | "shot" | "field_zone" | "bat_hand" | "batting_position" | "partnership" | "matchup" | "opponent" | "venue",\n'
            '    "bowling_kind": "pace bowler" | "spin bowler",\n'
            '    "bowling_style_group": "left_arm_pace" | "leg_spin",\n'
            '    "bat_hand": "LHB" | "RHB",\n'
            '    "rank_intent": "best" | "worst"\n'
            "  }\n"
            "}\n"
            "Rules:\n"
            "- Extract only genuine cricket entities.\n"
            "- Never treat filler words or conjunctions as player mentions.\n"
            "- Use player_mentions only for players actually referenced or strongly implied.\n"
            "- For economy rate, best/lowest/most economical means rank_intent best; worst/highest/most expensive means rank_intent worst.\n"
            "- For wickets taken, best/highest/most/top means rank_intent best; worst/lowest/fewest/least means rank_intent worst.\n"
            "- Phrases like other than, excluding, except, apart from, or non-English should populate excluded_teams.\n"
            "- For global which/who leaderboard questions, set subject to bowler or batter and leave player_mentions empty unless a specific opponent is named.\n"
            "- For yorker questions, use length YORKER. For short-ball/full-ball questions, use length SHORT or FULL.\n"
            "- For opponent-wise, opposition-wise, against each team, or by opponent questions, set group_by to opponent.\n"
            "- For bowling type/style questions, set group_by to bowling_style. Do not answer with individual bowlers.\n"
            "- For scoring-area questions such as mid-wicket, cover, point, third man, fine leg, square leg, long on, or long off, set subject batter, metric runs_scored, and filters.field_zone to the requested area. Do not treat mid-wicket as wicket-taking.\n"
            "- For questions asking who improves after facing 20 balls, use metric strike_rate_improvement_after_20 and filters.split_after_balls = 20.\n"
            "- For milestone vulnerability questions, use metric milestone_vulnerability_lift, context_tag after_milestone, and post_milestone_balls 12.\n"
            "- For venue-wise, ground-wise, by venue, or by ground questions about a named player, set group_by to venue.\n"
            "- For Player of the Match, Man of the Match, or POTM questions, set external_fact to player_of_match and stage to final when final is mentioned.\n"
            "- Preserve the literal metric asked by the user. If they ask balls bowled, metric must be balls_bowled, not economy_rate.\n"
            "- If they ask balls faced, metric must be balls_faced and role batter.\n"
            "- If they ask a named batter's dot-ball percentage, use metric dot_percentage and role batter; do not turn it into a bowler leaderboard.\n"
            "- If they ask about a final, semi-final, or named match, use context.scope single_match and preserve stage/teams/year/competition when present.\n"
            "- If a literal interpretation may be cricket-ambiguous, keep the literal metric and add ambiguity.possible_alternate_metric.\n"
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

        fallback_route = self.fallback_router.route(question)
        raw_query_class = payload.get("query_class")
        ai_query_class = self._query_class_from_payload(raw_query_class, payload.get("query_type"))
        if ai_query_class is None:
            return None
        if fallback_route.entities and fallback_route.filters.get("group_by") in {"opponent", "venue"}:
            query_class = QueryClass.role_comparison
        elif "position_groups" in fallback_route.filters:
            query_class = QueryClass.role_comparison
        elif fallback_route.filters.get("metric") == "best_bowling_figures" and fallback_route.entities:
            query_class = QueryClass.role_comparison
        else:
            query_class = self._reconcile_query_class(question, ai_query_class, fallback_route.query_class)

        raw_mentions = payload.get("player_mentions")
        mentions = [item.strip() for item in raw_mentions if isinstance(item, str) and item.strip()] if isinstance(raw_mentions, list) else []
        subjects = payload.get("subjects")
        if isinstance(subjects, list):
            for subject in subjects:
                if not isinstance(subject, dict):
                    continue
                player = subject.get("player")
                if isinstance(player, str) and player.strip():
                    mentions.append(player.strip())
        resolved_entities = self._resolve_player_mentions(question, mentions)
        if not resolved_entities:
            resolved_entities = list(fallback_route.entities)

        raw_filters = payload.get("filters")
        filters = self._normalize_filters(raw_filters if isinstance(raw_filters, dict) else {})
        if "position_groups" in fallback_route.filters and "position_groups" not in filters:
            filters["position_groups"] = fallback_route.filters["position_groups"]
        for deterministic_key in (
            "phase",
            "skill",
            "metric",
            "years",
            "year_mode",
            "competition",
            "rank_intent",
            "subject",
            "length",
            "line",
            "group_by",
            "bowling_kind",
            "bowling_style_group",
            "bat_hand",
            "over_range",
            "matchup_role",
            "plan_type",
            "excluded_teams",
            "external_fact",
            "stage",
        ):
            if deterministic_key in fallback_route.filters and deterministic_key not in filters:
                filters[deterministic_key] = fallback_route.filters[deterministic_key]
        if "rank_intent" in fallback_route.filters:
            filters["rank_intent"] = fallback_route.filters["rank_intent"]
        if "competition" in fallback_route.filters:
            filters["competition"] = fallback_route.filters["competition"]
        if "excluded_teams" in fallback_route.filters:
            filters["excluded_teams"] = fallback_route.filters["excluded_teams"]
        self._apply_question_level_overrides(question, filters)

        intent_plan = self._normalize_intent_plan(payload, resolved_entities, filters, fallback_route)

        return QueryRoute(
            query_class=query_class,
            entities=tuple(resolved_entities[:2]),
            filters=filters,
            intent_plan=intent_plan,
        )

    @staticmethod
    def _apply_question_level_overrides(question: str, filters: dict[str, object]) -> None:
        lowered = question.lower()
        QueryRouter._apply_semantic_overrides(lowered, filters)
        asks_bowling_type = any(
            token in lowered
            for token in ("bowling type", "bowling types", "bowling style", "bowling styles", "type of bowling")
        )
        asks_batter_scoring = any(token in lowered for token in ("score fastest", "scores fastest", "strike rate", "score most"))
        if asks_bowling_type:
            filters["group_by"] = "bowling_style"
            if asks_batter_scoring:
                filters["subject"] = "batter"
                filters["metric"] = "batting_strike_rate"
                filters["rank_intent"] = "best"

    @staticmethod
    def _route_with_intent(question: str, route: QueryRoute, plan: CricketIntentPlan | None) -> QueryRoute:
        if plan is None:
            return route
        return QueryRoute(
            query_class=route.query_class,
            entities=route.entities,
            filters=route.filters,
            intent_plan=plan,
        )

    @staticmethod
    def _query_class_from_payload(raw_query_class: object, raw_query_type: object) -> QueryClass | None:
        if isinstance(raw_query_class, str):
            try:
                return QueryClass(raw_query_class)
            except ValueError:
                pass
        if raw_query_type == "leaderboard":
            return QueryClass.venue_context_leaderboard
        if raw_query_type == "trend":
            return QueryClass.trend_progression
        if raw_query_type == "match_fact":
            return QueryClass.venue_context_leaderboard
        if raw_query_type == "strengths_weaknesses":
            return QueryClass.strengths_weaknesses
        if raw_query_type == "comparison":
            return QueryClass.head_to_head_matchup
        if raw_query_type in {"single_metric", "tactical_plan", "conversation"}:
            return QueryClass.role_comparison
        return None

    @staticmethod
    def _intent_from_route(route: QueryRoute) -> CricketIntentPlan | None:
        metric = QueryInterpreter._metric_from_value(route.filters.get("metric"))
        subject_role = QueryInterpreter._role_from_value(route.filters.get("subject"))
        query_type = QueryType.comparison
        answer_shape = AnswerShape.comparison_table
        if metric and route.entities and not route.filters.get("rank_intent") and not route.filters.get("group_by"):
            query_type = QueryType.single_metric
            answer_shape = AnswerShape.single_number
        if route.query_class == QueryClass.venue_context_leaderboard:
            query_type = QueryType.leaderboard
            answer_shape = AnswerShape.leaderboard
        elif route.query_class == QueryClass.trend_progression:
            query_type = QueryType.trend
            answer_shape = AnswerShape.trend_chart
        elif route.query_class == QueryClass.strengths_weaknesses:
            query_type = QueryType.strengths_weaknesses
            answer_shape = AnswerShape.scouting_report
        elif route.query_class == QueryClass.head_to_head_matchup:
            query_type = QueryType.comparison
            answer_shape = AnswerShape.comparison_table

        if route.filters.get("external_fact") == "player_of_match":
            metric = CricketMetric.player_of_match
            query_type = QueryType.match_fact
            answer_shape = AnswerShape.short_fact

        years = route.filters.get("years")
        normalized_years = [int(year) for year in years] if isinstance(years, list) else []
        scope = ContextScope.career
        if route.filters.get("stage") or route.filters.get("match_id"):
            scope = ContextScope.single_match
        elif route.filters.get("competition"):
            scope = ContextScope.competition
        elif route.filters.get("phase"):
            scope = ContextScope.phase
        elif route.filters.get("venue_name"):
            scope = ContextScope.venue

        subjects = [
            IntentSubject(player=entity, role=subject_role or SubjectRole.player)
            for entity in route.entities
        ]
        return CricketIntentPlan(
            query_type=query_type,
            answer_shape=answer_shape,
            metric=metric,
            subjects=subjects,
            context=MatchContext(
                scope=scope,
                competition=str(route.filters["competition"]) if route.filters.get("competition") else None,
                year=normalized_years[0] if len(normalized_years) == 1 else None,
                years=normalized_years,
                year_mode=str(route.filters["year_mode"]) if route.filters.get("year_mode") else None,
                stage=str(route.filters["stage"]) if route.filters.get("stage") else None,
                venue_name=str(route.filters["venue_name"]) if route.filters.get("venue_name") else None,
                phase=str(route.filters["phase"]) if route.filters.get("phase") else None,
                group_by=str(route.filters["group_by"]) if route.filters.get("group_by") else None,
                length=str(route.filters["length"]) if route.filters.get("length") else None,
                line=str(route.filters["line"]) if route.filters.get("line") else None,
                bowling_kind=str(route.filters["bowling_kind"]) if route.filters.get("bowling_kind") else None,
                bowling_style_group=str(route.filters["bowling_style_group"]) if route.filters.get("bowling_style_group") else None,
                bat_hand=str(route.filters["bat_hand"]) if route.filters.get("bat_hand") else None,
                over_range=[int(value) for value in route.filters.get("over_range", [])]
                if isinstance(route.filters.get("over_range"), list)
                else [],
            ),
            rank_intent=str(route.filters["rank_intent"]) if route.filters.get("rank_intent") else None,
        )

    @staticmethod
    def _normalize_intent_plan(
        payload: dict[str, object],
        resolved_entities: list[str],
        filters: dict[str, object],
        fallback_route: QueryRoute,
    ) -> CricketIntentPlan:
        base_route = QueryRoute(
            query_class=fallback_route.query_class,
            entities=tuple(resolved_entities[:2]) or fallback_route.entities,
            filters={**fallback_route.filters, **filters},
        )
        base_plan = QueryInterpreter._intent_from_route(base_route) or CricketIntentPlan()

        query_type = QueryInterpreter._enum_value(QueryType, payload.get("query_type")) or base_plan.query_type
        answer_shape = QueryInterpreter._enum_value(AnswerShape, payload.get("answer_shape")) or base_plan.answer_shape
        metric = QueryInterpreter._metric_from_value(payload.get("metric")) or QueryInterpreter._metric_from_value(filters.get("metric")) or base_plan.metric

        raw_context = payload.get("context")
        context_payload = raw_context if isinstance(raw_context, dict) else {}
        context = base_plan.context.model_copy(
            update={
                "scope": QueryInterpreter._enum_value(ContextScope, context_payload.get("scope")) or base_plan.context.scope,
                "competition": QueryInterpreter._string_or_none(context_payload.get("competition")) or base_plan.context.competition,
                "year": QueryInterpreter._int_or_none(context_payload.get("year")) or base_plan.context.year,
                "years": QueryInterpreter._int_list(context_payload.get("years")) or base_plan.context.years,
                "year_mode": QueryInterpreter._string_or_none(context_payload.get("year_mode")) or base_plan.context.year_mode,
                "stage": QueryInterpreter._string_or_none(context_payload.get("stage")) or base_plan.context.stage,
                "teams": QueryInterpreter._string_list(context_payload.get("teams")) or base_plan.context.teams,
                "venue_name": QueryInterpreter._string_or_none(context_payload.get("venue_name")) or base_plan.context.venue_name,
                "phase": QueryInterpreter._string_or_none(context_payload.get("phase")) or base_plan.context.phase,
                "match_id": QueryInterpreter._string_or_none(context_payload.get("match_id")) or base_plan.context.match_id,
                "group_by": QueryInterpreter._string_or_none(context_payload.get("group_by")) or base_plan.context.group_by,
                "length": QueryInterpreter._string_or_none(context_payload.get("length")) or base_plan.context.length,
                "line": QueryInterpreter._string_or_none(context_payload.get("line")) or base_plan.context.line,
                "bowling_kind": QueryInterpreter._string_or_none(context_payload.get("bowling_kind")) or base_plan.context.bowling_kind,
                "bowling_style_group": QueryInterpreter._string_or_none(context_payload.get("bowling_style_group"))
                or base_plan.context.bowling_style_group,
                "bat_hand": QueryInterpreter._string_or_none(context_payload.get("bat_hand")) or base_plan.context.bat_hand,
                "over_range": QueryInterpreter._int_list(context_payload.get("over_range")) or base_plan.context.over_range,
            }
        )
        if context.year and context.year not in context.years:
            context = context.model_copy(update={"years": [context.year, *context.years]})
        if context.stage and context.scope == ContextScope.career:
            context = context.model_copy(update={"scope": ContextScope.single_match})

        role = QueryInterpreter._role_from_value(filters.get("subject")) or base_plan.primary_role() or SubjectRole.player
        subjects = [IntentSubject(player=entity, role=role) for entity in (resolved_entities[:2] or list(fallback_route.entities))]
        if not subjects:
            raw_subjects = payload.get("subjects")
            if isinstance(raw_subjects, list):
                for subject in raw_subjects:
                    if not isinstance(subject, dict):
                        continue
                    team = QueryInterpreter._string_or_none(subject.get("team"))
                    if team:
                        subjects.append(
                            IntentSubject(
                                team=team,
                                role=QueryInterpreter._role_from_value(subject.get("role")) or SubjectRole.team,
                            )
                        )

        ambiguity = None
        raw_ambiguity = payload.get("ambiguity")
        if isinstance(raw_ambiguity, dict):
            possible_alternate = QueryInterpreter._metric_from_value(raw_ambiguity.get("possible_alternate_metric"))
            reason = QueryInterpreter._string_or_none(raw_ambiguity.get("reason"))
            if possible_alternate or reason:
                ambiguity = IntentAmbiguity(possible_alternate_metric=possible_alternate, reason=reason)

        return CricketIntentPlan(
            query_type=query_type,
            answer_shape=answer_shape,
            metric=metric,
            subjects=subjects,
            context=context,
            rank_intent=QueryInterpreter._string_or_none(payload.get("rank_intent"))
            or QueryInterpreter._string_or_none(filters.get("rank_intent"))
            or base_plan.rank_intent,
            ambiguity=ambiguity,
        )

    @staticmethod
    def _metric_from_value(value: object) -> CricketMetric | None:
        if isinstance(value, str):
            try:
                return CricketMetric(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _role_from_value(value: object) -> SubjectRole | None:
        if isinstance(value, str):
            try:
                return SubjectRole(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _enum_value(enum_class, value: object):
        if isinstance(value, str):
            try:
                return enum_class(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _string_or_none(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    @staticmethod
    def _int_list(value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        return [int(item) for item in value if isinstance(item, int) or (isinstance(item, str) and item.isdigit())]

    @staticmethod
    def _reconcile_query_class(
        question: str,
        ai_query_class: QueryClass,
        fallback_class: QueryClass,
    ) -> QueryClass:
        lowered = question.lower()
        is_ranked_question = any(lowered.startswith(prefix) for prefix in ("which ", "who "))
        if is_ranked_question and fallback_class == QueryClass.venue_context_leaderboard:
            return QueryClass.venue_context_leaderboard
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
        if (
            any(token in lowered for token in ("best statistics", "best batsman", "best bowler", "stadium", "ground", "venue"))
            or (
                any(token in lowered for token in ("best", "worst", "lowest", "highest", "top", "most", "fewest", "fastest", "economical"))
                and any(token in lowered for token in ("economy", "wicket", "bowler", "bowling", "batter", "player", "yorker", "dot", "boundary", "strike rate", "runs", "false shot"))
            )
            or is_ranked_question
        ):
            return QueryClass.venue_context_leaderboard
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

        competition = raw_filters.get("competition")
        if isinstance(competition, str) and competition.strip():
            filters["competition"] = competition.strip()

        venue_name = raw_filters.get("venue_name")
        if isinstance(venue_name, str) and venue_name.strip():
            filters["venue_name"] = venue_name.strip()

        external_fact = raw_filters.get("external_fact")
        if isinstance(external_fact, str) and external_fact in {"player_of_match"}:
            filters["external_fact"] = external_fact

        stage = raw_filters.get("stage")
        if isinstance(stage, str) and stage in {"final"}:
            filters["stage"] = stage

        excluded_teams = raw_filters.get("excluded_teams")
        if isinstance(excluded_teams, list):
            normalized_exclusions = [
                QueryInterpreter._normalize_team_name(team)
                for team in excluded_teams
                if isinstance(team, str) and team.strip()
            ]
            if normalized_exclusions:
                filters["excluded_teams"] = list(dict.fromkeys(normalized_exclusions))

        skill = raw_filters.get("skill")
        if isinstance(skill, str) and skill in {"batting", "bowling", "fielding"}:
            filters["skill"] = skill

        subject = raw_filters.get("subject")
        if isinstance(subject, str) and subject in {"bowler", "batter", "fielder", "player", "team"}:
            filters["subject"] = subject

        metric = raw_filters.get("metric")
        if isinstance(metric, str) and metric in {
            "balls_bowled",
            "overs_bowled",
            "balls_faced",
            "economy_rate",
            "runs_conceded",
            "wickets_taken",
            "best_bowling_figures",
            "balls_per_wicket",
            "balls_per_boundary",
            "dot_balls",
            "catches_taken",
            "yorker_count",
            "yorker_success_rate",
            "bowler_dot_balls",
            "bowler_dot_percentage",
            "boundaries",
            "boundaries_conceded",
            "boundaries_per_over",
            "boundaries_per_100_balls",
            "false_shot_percentage",
            "false_shots_per_over",
            "extras_rate",
            "batting_strike_rate",
            "strike_rate_improvement_after_20",
            "milestone_vulnerability_lift",
            "batting_average",
            "boundary_percentage",
            "runs_scored",
            "dot_percentage",
            "strike_rotation_percentage",
            "yorker_percentage",
        }:
            filters["metric"] = metric

        rank_intent = raw_filters.get("rank_intent")
        if isinstance(rank_intent, str) and rank_intent in {"best", "worst"}:
            filters["rank_intent"] = rank_intent

        for key, allowed_values in {
            "length": {"YORKER", "FULL", "GOOD_LENGTH", "SHORT_OF_A_GOOD_LENGTH", "SHORT", "FULL_TOSS"},
            "line": {"OUTSIDE_OFFSTUMP", "ON_THE_STUMPS", "WIDE_OUTSIDE_OFFSTUMP", "DOWN_LEG", "WIDE_DOWN_LEG"},
            "field_zone": {"midwicket", "cover", "point", "third_man", "fine_leg", "square_leg", "long_on", "long_off"},
            "group_by": {"line", "length", "bowling_style", "phase", "shot", "field_zone", "bat_hand", "batting_position", "partnership", "matchup", "opponent", "venue"},
            "bowling_kind": {"pace bowler", "spin bowler"},
            "bowling_style_group": {"left_arm_pace", "leg_spin"},
            "bat_hand": {"LHB", "RHB"},
        }.items():
            value = raw_filters.get(key)
            if isinstance(value, str) and value in allowed_values:
                filters[key] = value

        position_groups = raw_filters.get("position_groups")
        if isinstance(position_groups, list):
            normalized_groups: list[dict[str, object]] = []
            for group in position_groups:
                if not isinstance(group, dict):
                    continue
                label = group.get("label")
                positions = group.get("positions")
                if not isinstance(label, str) or not isinstance(positions, list):
                    continue
                normalized_positions = [
                    int(position)
                    for position in positions
                    if isinstance(position, int) or (isinstance(position, str) and position.isdigit())
                ]
                normalized_positions = [position for position in normalized_positions if 1 <= position <= 11]
                if normalized_positions:
                    normalized_groups.append({"label": label.strip(), "positions": normalized_positions})
            if normalized_groups:
                filters["position_groups"] = normalized_groups

        return filters

    @staticmethod
    def _normalize_team_name(value: str) -> str:
        lowered = value.strip().lower()
        return TEAM_ADJECTIVES.get(lowered, value.strip())
