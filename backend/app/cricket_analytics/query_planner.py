from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.app.cricket_analytics.ontology import METRICS, ontology_context
from backend.app.cricket_analytics.plan_normalizer import normalize_plan
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, SortSpec, ValidationResult
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.services.gemini_client import GeminiClient, GeminiStructuredResult
from backend.app.services.player_resolution import ALIASES, normalize_name, resolve_player_name


@dataclass(slots=True)
class PlannerResult:
    plan: CricketQueryPlan | None
    validation: ValidationResult
    used_gemini: bool


class SemanticQueryPlanner:
    def __init__(
        self,
        gemini_client: GeminiClient,
        available_players: list[str],
        available_venues: list[str] | None = None,
        available_teams: list[str] | None = None,
        *,
        allow_dev_fallback: bool = True,
    ) -> None:
        self.gemini_client = gemini_client
        self.available_players = available_players
        self.available_venues = available_venues or []
        self.available_teams = available_teams or []
        self.allow_dev_fallback = allow_dev_fallback

    def plan(self, question: str, trace: QueryTrace) -> PlannerResult:
        if self.gemini_client.is_configured():
            planned = self._plan_with_gemini(question, trace, prefer_complex=self._needs_complex_model(question))
            if planned.plan is not None and planned.validation.valid:
                self._finalize_planner_trace(trace, repair_outcome="not_needed")
                return planned
            repaired = self._repair_with_gemini(question, planned.plan, planned.validation, trace)
            self._finalize_planner_trace(
                trace,
                repair_outcome=(
                    "succeeded" if repaired.plan is not None and repaired.validation.valid else "failed"
                ),
            )
            if repaired.plan is not None and repaired.validation.valid:
                return repaired

        if not self.allow_dev_fallback:
            validation = ValidationResult(
                valid=False,
                errors=["Semantic V2 planner could not produce a validated LLM plan."],
            )
            trace.validation_result = validation.model_dump(mode="json")
            trace.final_answer_metadata = {"planner_fallback": "disabled"}
            if not trace.planner_outcome:
                trace.planner_outcome = {
                    "attempt_count": 0,
                    "selected_model": None,
                    "finish_reason": None,
                    "parse_outcome": "not_attempted",
                    "validation_outcome": "not_run",
                    "repair_outcome": "not_attempted",
                    "latency_ms": 0.0,
                }
            return PlannerResult(plan=None, validation=validation, used_gemini=self.gemini_client.is_configured())

        fallback = self._fallback_plan(question)
        normalized = self._normalize_and_resolve_players(fallback, question, infer_meaning=True)
        validation = validate_plan(normalized, question)
        trace.parsed_json_plan = fallback.model_dump(mode="json")
        trace.normalized_plan = normalized.model_dump(mode="json")
        trace.validation_result = validation.model_dump(mode="json")
        trace.operation_type = normalized.operation
        return PlannerResult(plan=normalized, validation=validation, used_gemini=False)

    def _plan_with_gemini(self, question: str, trace: QueryTrace, prefer_complex: bool) -> PlannerResult:
        prompt = self._planner_prompt(question)
        return self._run_gemini_attempt(
            question,
            prompt,
            trace,
            attempt="initial",
            prefer_complex=prefer_complex,
        )

    def _repair_with_gemini(
        self,
        question: str,
        invalid_plan: CricketQueryPlan | None,
        validation: ValidationResult,
        trace: QueryTrace,
    ) -> PlannerResult:
        prompt = (
            "Repair this cricket analytics JSON plan. Return JSON only.\n"
            "Do not write SQL. Use only the provided ontology and schema.\n\n"
            f"Ontology: {json.dumps(ontology_context(), sort_keys=True)}\n"
            f"Original question: {question}\n"
            f"Invalid plan or response: {invalid_plan.model_dump_json() if invalid_plan else trace.gemini_raw_response}\n"
            f"Validation errors: {validation.model_dump_json()}\n"
        )
        return self._run_gemini_attempt(
            question,
            prompt,
            trace,
            attempt="repair",
            prefer_complex=True,
        )

    def _run_gemini_attempt(
        self,
        question: str,
        prompt: str,
        trace: QueryTrace,
        *,
        attempt: str,
        prefer_complex: bool,
    ) -> PlannerResult:
        generated = self._generate_structured(prompt, prefer_complex=prefer_complex)
        raw = generated.text
        if attempt == "repair":
            trace.gemini_raw_response = f"{trace.gemini_raw_response or ''}\n\nREPAIR:\n{raw or ''}".strip()
        else:
            trace.gemini_raw_response = raw

        attempt_trace: dict[str, Any] = {
            "attempt": attempt,
            "selected_model": generated.selected_model,
            "model_version": generated.model_version,
            "finish_reason": generated.finish_reason,
            "latency_ms": round(generated.latency_ms, 3),
            "parse_outcome": "not_started",
            "validation_outcome": "not_run",
            "error_kind": generated.error_kind,
            "prompt_token_count": generated.prompt_token_count,
            "output_token_count": generated.output_token_count,
            "schema_constrained": generated.schema_constrained,
        }
        trace.planner_attempts.append(attempt_trace)

        if generated.finish_reason != "STOP":
            attempt_trace["parse_outcome"] = (
                "truncated" if generated.finish_reason == "MAX_TOKENS" else "incomplete"
            )
            validation = ValidationResult(
                valid=False,
                errors=[f"Gemini planner did not finish cleanly ({generated.finish_reason or 'unknown'})."],
            )
            trace.validation_result = validation.model_dump(mode="json")
            return PlannerResult(plan=None, validation=validation, used_gemini=True)

        if not raw:
            attempt_trace["parse_outcome"] = "empty"
            validation = ValidationResult(valid=False, errors=["Gemini returned no planner response."])
            trace.validation_result = validation.model_dump(mode="json")
            return PlannerResult(plan=None, validation=validation, used_gemini=True)

        payload = self._parse_json_object(raw)
        trace.parsed_json_plan = payload if isinstance(payload, dict) else None
        if not isinstance(payload, dict):
            attempt_trace["parse_outcome"] = "invalid_json"
            validation = ValidationResult(
                valid=False,
                errors=["Gemini response was not a valid JSON object."],
            )
            trace.validation_result = validation.model_dump(mode="json")
            return PlannerResult(plan=None, validation=validation, used_gemini=True)

        try:
            plan = CricketQueryPlan.model_validate(payload)
        except ValidationError as exc:
            attempt_trace["parse_outcome"] = "schema_invalid"
            attempt_trace["validation_outcome"] = "invalid"
            validation = ValidationResult(valid=False, errors=[f"Plan schema validation failed: {exc}"])
            trace.validation_result = validation.model_dump(mode="json")
            return PlannerResult(plan=None, validation=validation, used_gemini=True)

        attempt_trace["parse_outcome"] = "parsed"
        normalized = self._normalize_and_resolve_players(
            plan,
            question,
            infer_meaning=not generated.schema_constrained,
        )
        validation = validate_plan(normalized, question)
        attempt_trace["validation_outcome"] = "valid" if validation.valid else "invalid"
        trace.normalized_plan = normalized.model_dump(mode="json")
        trace.validation_result = validation.model_dump(mode="json")
        trace.operation_type = normalized.operation
        return PlannerResult(plan=normalized, validation=validation, used_gemini=True)

    def _generate_structured(self, prompt: str, *, prefer_complex: bool) -> GeminiStructuredResult:
        generator = getattr(self.gemini_client, "generate_structured", None)
        if callable(generator):
            return generator(
                prompt,
                response_schema=CricketQueryPlan.model_json_schema(),
                prefer_complex=prefer_complex,
                max_output_tokens=2048,
            )

        # Compatibility for existing test doubles. The production Gemini client always uses the typed path above.
        raw = self.gemini_client.generate_text(prompt, prefer_complex=prefer_complex)
        return GeminiStructuredResult(
            text=raw,
            selected_model="legacy-test-double",
            model_version=None,
            finish_reason="STOP" if raw else None,
            latency_ms=0.0,
            error_kind=None if raw else "empty_response",
            schema_constrained=False,
        )

    @staticmethod
    def _finalize_planner_trace(trace: QueryTrace, *, repair_outcome: str) -> None:
        last_attempt = trace.planner_attempts[-1] if trace.planner_attempts else {}
        trace.planner_outcome = {
            "attempt_count": len(trace.planner_attempts),
            "selected_model": last_attempt.get("selected_model"),
            "model_version": last_attempt.get("model_version"),
            "finish_reason": last_attempt.get("finish_reason"),
            "parse_outcome": last_attempt.get("parse_outcome", "not_attempted"),
            "validation_outcome": last_attempt.get("validation_outcome", "not_run"),
            "repair_outcome": repair_outcome,
            "latency_ms": round(
                sum(float(item.get("latency_ms", 0.0)) for item in trace.planner_attempts),
                3,
            ),
        }

    def _normalize_and_resolve_players(
        self,
        plan: CricketQueryPlan,
        question: str,
        *,
        infer_meaning: bool,
    ) -> CricketQueryPlan:
        normalized = normalize_plan(plan)
        filters = dict(normalized.filters)

        for key in ("batter", "bowler", "player"):
            value = filters.get(key)
            if not isinstance(value, str):
                continue
            resolution = resolve_player_name(value, self.available_players)
            if resolution.canonical_name:
                filters[key] = resolution.canonical_name

        compare_players = filters.get("compare_players")
        if infer_meaning and normalized.operation == "player_compare" and not isinstance(compare_players, list):
            compare_players = normalized.compare_values or self._extract_players(question)
        if isinstance(compare_players, list):
            resolved_players: list[object] = []
            for value in compare_players:
                if not isinstance(value, str):
                    resolved_players.append(value)
                    continue
                resolution = resolve_player_name(value, self.available_players)
                resolved_players.append(resolution.canonical_name or value)
            filters["compare_players"] = resolved_players

        updates: dict[str, object] = {"filters": filters}
        resolved_compare_players = filters.get("compare_players")
        if (
            normalized.operation == "player_compare"
            and isinstance(resolved_compare_players, list)
            and len(resolved_compare_players) >= 2
            and (
                infer_meaning
                or not self._comparison_has_explicit_metric_request(question.lower())
            )
        ):
            comparison_metrics = self._infer_comparison_metrics(
                question.lower(),
                normalized.metric,
                normalized.entity,
            )
            filters["comparison_metrics"] = comparison_metrics
            primary_metric = comparison_metrics[0]
            updates.update(
                {
                    "filters": filters,
                    "metric": primary_metric,
                    "group_by": [normalized.entity],
                    "sort": SortSpec(by=primary_metric, direction=METRICS[primary_metric].default_sort),
                }
            )

        normalized = normalized.model_copy(update=updates)
        return self._apply_question_guardrails(normalized, question) if infer_meaning else normalized

    @staticmethod
    def _apply_question_guardrails(plan: CricketQueryPlan, question: str) -> CricketQueryPlan:
        lowered = question.lower()
        filters = dict(plan.filters)
        compare_players = filters.get("compare_players")
        has_comparison_pair = isinstance(compare_players, list) and len(compare_players) >= 2
        leaderboard_wording = (
            any(prefix in lowered for prefix in ("who has", "which batter", "which bowler", "which player"))
            and any(
                token in lowered
                for token in ("best", "worst", "highest", "lowest", "most", "least", "fewest")
            )
        )

        operation = plan.operation
        entity = plan.entity
        group_by = plan.group_by
        unsupported_reason = plan.unsupported_reason
        direct_batter_style_metric = (
            operation == "matchup"
            and isinstance(filters.get("batter"), str)
            and "bowler" not in filters
            and any(token in lowered for token in ("strike rate", "average", "dot ball", "boundary"))
            and not any(token in lowered for token in ("matchup", "which bowler", "dismissed", "dismisses", "controls"))
        )
        if direct_batter_style_metric:
            operation = "aggregate"
            group_by = ["batter"]
        if operation == "aggregate" and SemanticQueryPlanner._asks_for_bowling_perspective(lowered):
            if "bowler" not in filters:
                named_player = filters.pop("batter", None)
                if isinstance(named_player, str):
                    filters["bowler"] = named_player
            entity = "bowler"
            if not group_by or group_by in (["batter"], ["bowler"]):
                group_by = ["bowler"]
        if operation == "player_compare" and leaderboard_wording and not has_comparison_pair:
            operation = "aggregate"
            group_by = [plan.entity] if plan.entity in {"batter", "bowler", "team"} else group_by
            filters.pop("compare_players", None)
            filters.pop("comparison_metrics", None)
        if (
            operation == "player_compare"
            and not has_comparison_pair
            and SemanticQueryPlanner._is_direct_player_metric_question(lowered, filters)
        ):
            operation = "aggregate"
            group_by = [plan.entity] if plan.entity in {"batter", "bowler"} else group_by
            filters.pop("compare_players", None)
            filters.pop("comparison_metrics", None)
            unsupported_reason = None

        explicit_minimum = re.search(
            r"\b(?:minimum|min\.?|at least)\s+(\d{1,7})\s+(legal balls|balls|deliveries|innings)\b",
            lowered,
        )
        ranking_wording = any(
            token in lowered
            for token in (
                "best",
                "worst",
                "highest",
                "lowest",
                "most",
                "least",
                "fewest",
                "biggest",
                "smallest",
                "fastest",
                "slowest",
            )
        )
        metric = METRICS.get(plan.metric)
        is_rate_ranking = bool(metric and metric.denominator is not None and ranking_wording)
        minimum_sample: MinimumSampleSpec | None = None
        if explicit_minimum:
            value = int(explicit_minimum.group(1))
            unit = explicit_minimum.group(2)
            if unit == "innings":
                minimum_sample = MinimumSampleSpec(innings=value)
            elif unit == "legal balls" or (metric and metric.denominator == "legal_balls"):
                minimum_sample = MinimumSampleSpec(legal_balls=value)
            else:
                minimum_sample = MinimumSampleSpec(balls=value)
        elif is_rate_ranking:
            defaults = metric.minimum_sample.as_dict() if metric else {}
            minimum_sample = MinimumSampleSpec(**defaults) if defaults else None

        return plan.model_copy(
            update={
                "operation": operation,
                "entity": entity,
                "group_by": group_by,
                "filters": filters,
                "minimum_sample": minimum_sample,
                "minimum_sample_explicit": bool(explicit_minimum),
                "unsupported_reason": unsupported_reason,
            }
        )

    def _planner_prompt(self, question: str) -> str:
        schema = CricketQueryPlan.model_json_schema()
        return (
            "You are CricAtlas's semantic planner for ODI cricket analytics.\n"
            "Return strict JSON only. Do not explain. Do not write SQL.\n"
            "The LLM understands language; the backend enforces statistical correctness.\n"
            "Choose one operation and fixed metric/dimension IDs from the ontology.\n\n"
            f"Ontology: {json.dumps(ontology_context(), sort_keys=True)}\n\n"
            f"JSON schema: {json.dumps(schema, sort_keys=True)}\n\n"
            "Rules:\n"
            "- bowling type/style questions group_by bowling_style, not bowler.\n"
            "- length questions group/filter length.\n"
            "- shot questions group/filter shot_type.\n"
            "- scoring zone questions group/filter field_zone.\n"
            "- fastest scoring means batting_strike_rate unless the user explicitly asks runs.\n"
            "- hardest to bowl dots to means batter dot_ball_percentage sorted ascending.\n"
            "- For player_compare, preserve every named player and every supported phase, venue, opposition, and bowling_style filter.\n"
            "- For player_compare, infer one shared role from the wording and requested metrics: entity batter for batting metrics, or entity bowler for bowling metrics.\n"
            "- Every comparison_metrics entry must belong to that shared entity role; never mix batter-owned and bowler-owned metrics.\n"
            "- An unqualified batter comparison uses batting_strike_rate, runs_scored, batting_average, batter_dot_ball_percentage, and boundary_percentage.\n"
            "- An unqualified bowler comparison uses economy_rate, bowling_average, bowling_strike_rate, wickets_taken, bowler_dot_ball_percentage, and boundary_percentage.\n"
            "- If the question materially mixes player roles or does not establish one shared comparison role, set unsupported_reason and explain the ambiguity.\n"
            "- If unsupported, set unsupported_reason and choose the closest operation.\n\n"
            f"User question: {question}"
        )

    def _fallback_plan(self, question: str) -> CricketQueryPlan:
        lowered = question.lower()
        operation = self._infer_operation(lowered)
        metric = self._infer_metric(lowered)
        entity = self._infer_entity(lowered, metric)
        group_by = self._infer_group_by(lowered, entity)
        filters = self._infer_filters(question, lowered, metric)
        compare_players = self._extract_players(question)
        unsupported_reason = self._unsupported_factual_reason(lowered)
        ordered_players = sorted(
            compare_players,
            key=lambda player: lowered.find(player.lower()),
        )
        named_matchup = self._named_batter_bowler_matchup(lowered, ordered_players)
        if named_matchup:
            batter, bowler = named_matchup
            operation = "matchup"
            entity = "matchup"
            metric = "batting_strike_rate"
            group_by = []
            filters = {
                **{key: value for key, value in filters.items() if key not in {"batter", "bowler"}},
                "batter": batter,
                "bowler": bowler,
            }
        if (
            operation == "aggregate"
            and " against " in lowered
            and len(ordered_players) >= 2
            and "batting" in lowered
        ):
            operation = "matchup"
            entity = "batter"
            group_by = ["batter", "bowler"]
            filters.pop("batter", None)
            filters.pop("bowler", None)
            filters["batter"] = ordered_players[0]
            filters["bowler"] = ordered_players[1]
        if operation == "player_compare":
            filters.pop("batter", None)
            filters.pop("bowler", None)
            if self._comparison_looks_bowling(compare_players, lowered, metric):
                entity = "bowler"
                if metric in {"runs_scored", "batting_strike_rate"}:
                    metric = "economy_rate"
            elif self._comparison_looks_batting(compare_players, lowered, metric):
                entity = "batter"
            group_by = [entity]
            filters["compare_players"] = compare_players
            comparison_metrics = self._infer_comparison_metrics(lowered, metric, entity)
            if comparison_metrics:
                filters["comparison_metrics"] = comparison_metrics
                metric = comparison_metrics[0]
            if (
                "phase-wise" in lowered
                or "phase wise" in lowered
                or all(token in lowered for token in ("powerplay", "middle overs", "death overs"))
            ):
                filters["comparison_view"] = "phase"
                filters.pop("phase", None)
            elif "team-wise" in lowered or "team wise" in lowered or "by opposition" in lowered:
                filters["comparison_view"] = "opposition"
            if not unsupported_reason and len(compare_players) < 2:
                unsupported_reason = "Player comparison requires at least two named players."
            if not unsupported_reason and self._comparison_has_mixed_roles(compare_players):
                unsupported_reason = "Mixed batter-versus-bowler player comparisons are not supported in Semantic V2."
        if operation == "match_fact":
            entity = "team"
            metric = "runs_scored"
            group_by = ["team"]
            filters.update(self._infer_match_fact_filters(lowered))
        requested_limit = self._infer_limit(lowered)
        requested_minimum_sample = self._infer_minimum_sample(lowered, metric)
        split_by, compare_values = self._infer_split(lowered, filters)
        event, window = self._infer_event(lowered, filters)
        default_sort = METRICS.get(metric).default_sort if metric in METRICS else "desc"
        if (
            metric == "runs_scored"
            and "which length" in lowered
            and any(token in lowered for token in ("best", "effective", "against"))
        ):
            entity = "batter"
            metric = "batting_strike_rate"
            default_sort = "asc"
        if "worst" in lowered and metric == "bowling_average":
            default_sort = "desc"
        if any(token in lowered for token in ("fewest", "lowest", "least")) and metric in {
            "boundary_percentage",
            "economy_rate",
            "dot_ball_percentage",
            "false_shot_percentage",
        }:
            default_sort = "asc"
        if (
            any(token in lowered for token in ("struggle", "struggles", "weakness", "vulnerable"))
            and not any(token in lowered for token in ("dominates", "better against", "difference", "compare"))
            and metric in {
            "batting_strike_rate",
            "batting_average",
            "control_percentage",
            }
        ):
            default_sort = "asc"

        if "hardest to bowl dot balls to" in lowered:
            entity = "batter"
            metric = "dot_ball_percentage"
            default_sort = "asc"
            if "batter" not in group_by:
                group_by = ["batter"]
        if operation == "matchup":
            entity, metric, group_by, filters, default_sort = self._refine_matchup_plan(
                lowered,
                entity,
                metric,
                group_by,
                filters,
                default_sort,
            )
        if (
            operation == "aggregate"
            and "bowler" in filters
            and "batter" not in filters
            and metric in {
                "dot_ball_percentage",
                "bowler_dot_ball_percentage",
                "economy_rate",
                "wickets_taken",
                "wickets",
                "yorker_percentage",
                "yorker_count",
                "false_shots_per_over",
            }
        ):
            entity = "bowler"
            if group_by == ["batter"]:
                group_by = ["bowler"]
        if (
            operation == "aggregate"
            and (not group_by or group_by == [entity])
            and self._is_direct_player_metric_question(lowered, filters)
        ):
            if "batter" in filters and "bowler" not in filters:
                entity = "batter"
                group_by = ["batter"]
            elif "bowler" in filters and "batter" not in filters:
                entity = "bowler"
                group_by = ["bowler"]

        if not group_by and operation == "aggregate":
            group_by = [entity] if entity in {"batter", "bowler", "team"} else []

        minimum_sample = requested_minimum_sample or (MinimumSampleSpec(**METRICS[metric].minimum_sample.as_dict()) if metric in METRICS else None)
        return CricketQueryPlan(
            operation=operation,
            entity=entity,
            metric=metric,
            group_by=group_by,
            filters=filters,
            split_by=split_by,
            compare_values=compare_values,
            event=event,
            window=window,
            sort=SortSpec(by=metric, direction=default_sort),
            limit=requested_limit,
            minimum_sample=minimum_sample,
            minimum_sample_explicit=requested_minimum_sample is not None,
            question_subject=self._question_subject(lowered),
            explanation_intent="deterministic semantic fallback",
            confidence=0.55,
            unsupported_reason=unsupported_reason,
        )

    @staticmethod
    def _infer_split(lowered: str, filters: dict[str, object]) -> tuple[str | None, list[str] | None]:
        if "powerplay" in lowered and ("death" in lowered or "death-over" in lowered):
            filters.pop("phase", None)
            return "phase", ["powerplay", "death"]
        if "left-handers" in lowered and "right-handers" in lowered:
            filters.pop("batter_hand", None)
            return "batter_hand", ["LHB", "RHB"]
        if "wrist spin" in lowered and "finger spin" in lowered:
            filters.pop("bowling_style", None)
            return "bowling_style_group", ["wrist_spin", "finger_spin"]
        if "pace" in lowered and "spin" in lowered and ("compare" in lowered or "versus" in lowered or "vs" in lowered):
            return "bowling_style_group", ["pace", "spin"]
        if "after facing 20 balls" in lowered or "after 20 balls" in lowered:
            return "balls_faced_window", ["first_20_balls", "after_20_balls"]
        if "between overs" in lowered and "over_range" in filters:
            return "over_range", ["requested_over_range"]
        return None, None

    @staticmethod
    def _infer_event(lowered: str, filters: dict[str, object]) -> tuple[str | None, dict[str, object] | None]:
        if "milestone" in lowered:
            return "batter_reaches_milestone", {"balls_after": 12}
        if "after a wicket" in lowered or "wicket falls" in lowered:
            return "wicket_falls", {"next_n_balls": 6}
        if "after the powerplay" in lowered:
            filters.pop("phase", None)
            return "after_powerplay", {"overs_after": 5}
        if "after early wickets" in lowered or "losing early wickets" in lowered or "lost early wickets" in lowered:
            return "early_wickets", {"overs_after": 10}
        return None, None

    @staticmethod
    def _infer_limit(lowered: str) -> int:
        word_numbers = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        numeric = re.search(r"\b(?:top|bottom|first|last|show|list|give me|which)\s+(?:the\s+)?(\d{1,2})\b", lowered)
        if numeric:
            return max(1, min(int(numeric.group(1)), 50))
        word_match = re.search(r"\b(?:top|bottom|first|last|show|list|give me|which)\s+(?:the\s+)?([a-z]+)\b", lowered)
        if word_match and word_match.group(1) in word_numbers:
            return word_numbers[word_match.group(1)]
        nested_word_match = re.search(r"\b(?:show|list|give me)\s+(?:the\s+)?(?:top|bottom)\s+([a-z]+)\b", lowered)
        if nested_word_match and nested_word_match.group(1) in word_numbers:
            return word_numbers[nested_word_match.group(1)]
        return 10

    @staticmethod
    def _infer_minimum_sample(lowered: str, metric: str) -> MinimumSampleSpec | None:
        match = re.search(r"\bminimum\s+(\d{1,7})\s+(legal balls|balls|deliveries)\b", lowered)
        if not match:
            return None
        value = int(match.group(1))
        sample_key = "legal_balls" if match.group(2) == "legal balls" else "balls"
        if sample_key == "legal_balls":
            return MinimumSampleSpec(legal_balls=value)
        if METRICS.get(metric) and METRICS[metric].denominator == "legal_balls":
            return MinimumSampleSpec(legal_balls=value)
        return MinimumSampleSpec(balls=value)

    @staticmethod
    def _infer_operation(lowered: str) -> str:
        if (
            ("world cup" in lowered or "final" in lowered or "match" in lowered)
            and any(token in lowered for token in ("total", "score", "won", "winner", "win"))
            and "player of the match" not in lowered
        ):
            return "match_fact"
        if any(token in lowered for token in ("should bowl", "optimal", "plan against", "field placement", "defending", "held back", "introduce spin", "introduced early", "targeted", "tactics")):
            return "tactical_recommendation"
        if any(token in lowered for token in ("predict", "predicts", "factor", "factors", "outcome", "victories", "successful chases", "wins most")):
            return "predictive_analysis"
        if any(token in lowered for token in ("immediately after", "after a wicket", "milestone", "after the powerplay", "after early wickets", "losing early wickets", "lost early wickets", "after a timeout", "after timeout")):
            return "event_window"
        if lowered.startswith("compare ") or " compare " in lowered or "who has the better" in lowered or "who scores faster" in lowered:
            return "player_compare"
        if any(token in lowered for token in ("concentrated", "concentration", "entropy", "spread", "variation", "changes most", "changes the most", "distribution", "varies")):
            return "distribution_analysis"
        if "matchup" in lowered or "batter-bowler" in lowered or "finishers" in lowered:
            return "matchup"
        if (
            ("which bowler" in lowered and ("dismissed" in lowered or "dismisses" in lowered or "controls" in lowered))
            or (lowered.startswith("who ") and ("dismissed" in lowered or "dismisses" in lowered))
            or "against wrist spin" in lowered
            or "against left-arm pace" in lowered
            or "against left arm pace" in lowered
            or "dominates left-arm pace" in lowered
            or "dominates left arm pace" in lowered
        ):
            return "matchup"
        if any(token in lowered for token in ("difference", "compare", "better against", "left-handers than right-handers", "wrist spin", "finger spin", "after 20 balls", "after facing 20 balls", "accelerates", "between overs")):
            return "split_compare"
        return "aggregate"

    @staticmethod
    def _infer_metric(lowered: str) -> str:
        if "bowling strike rate" in lowered:
            return "bowling_strike_rate"
        if "average" in lowered or re.search(r"\bavg\b", lowered):
            return "bowling_average" if "bowler" in lowered or "bowling" in lowered else "batting_average"
        if "dismissal count" in lowered or "dismissals" in lowered:
            return "dismissals"
        if "overs bowled" in lowered or "bowled the most overs" in lowered or "most overs" in lowered:
            return "overs_bowled"
        if "how many dot balls" in lowered or "dot ball count" in lowered:
            return "dot_balls"
        if "legal balls" in lowered and "minimum" not in lowered:
            return "legal_balls"
        if "balls has" in lowered or "balls did" in lowered or "how many balls" in lowered:
            return "balls_faced"
        if "bowl most" in lowered or "bowls most" in lowered or "bowled most" in lowered or "bowl most often" in lowered or "bowls most often" in lowered:
            return "legal_balls"
        if "length changes" in lowered or "length changes the most" in lowered or "length changes most" in lowered or "varies line" in lowered:
            return "balls_faced"
        if "after a wicket" in lowered and ("effective" in lowered or "bowler" in lowered):
            return "economy_rate"
        if ("after early wickets" in lowered or "losing early wickets" in lowered or "lost early wickets" in lowered) and ("fastest" in lowered or "scores" in lowered or "recovers" in lowered or "recovers best" in lowered):
            return "batting_strike_rate"
        if "milestone" in lowered or "vulnerable" in lowered:
            return "wickets"
        if "left-handers than right-handers" in lowered:
            return "economy_rate"
        if "death-over economy" in lowered or "death over economy" in lowered:
            return "economy_rate"
        if "accelerates" in lowered or "accelerate" in lowered:
            return "run_rate"
        if "wrist spin" in lowered or "finger spin" in lowered or "leg spin matchups" in lowered:
            return "batting_strike_rate"
        if "one-sided" in lowered and "matchup" in lowered:
            return "batting_strike_rate"
        if "controls" in lowered and "which bowler" in lowered:
            return "dot_ball_percentage"
        if "field placement" in lowered:
            return "runs_scored"
        if "finishers" in lowered:
            return "wickets"
        if "bowling factor" in lowered and "wins" in lowered:
            return "wickets"
        if "false shots per over" in lowered or "false-shot per over" in lowered or "false shots/over" in lowered:
            return "false_shots_per_over"
        if "economy" in lowered or "economical" in lowered:
            return "economy_rate"
        if "wicket opportunity" in lowered:
            return "wicket_opportunity_rate"
        if "yorker percentage" in lowered or "percentage of yorkers" in lowered:
            return "yorker_percentage"
        if "how many yorkers" in lowered or "yorker count" in lowered:
            return "yorker_count"
        if "yorker" in lowered:
            return "yorker_percentage"
        if "false shot" in lowered or "false-shot" in lowered:
            return "false_shot_percentage"
        if "dot ball" in lowered or "dot balls" in lowered or "dot-ball" in lowered or "dot-balls" in lowered or "dots" in lowered:
            return "dot_ball_percentage"
        if "boundaries per 100" in lowered or "boundary rate" in lowered:
            return "boundary_percentage"
        if "boundary" in lowered:
            return "boundary_percentage"
        if "control" in lowered:
            return "control_percentage"
        if "most balls" in lowered or "balls faced" in lowered or "faced the most balls" in lowered:
            return "balls_faced"
        if any(
            token in lowered
            for token in (
                "fastest",
                "strike rate",
                "scoring rate",
                "score rate",
                "how quickly",
                "sr ",
                " sr",
                "score fastest",
                "scores fastest",
                "dominates",
                "struggle",
                "struggles",
                "improves",
                "vulnerable",
                "effective",
                "optimal bowling plan",
                "introduce spin",
                "introduced early",
            )
        ):
            return "batting_strike_rate"
        if "defending" in lowered or "held back" in lowered:
            return "economy_rate"
        if any(token in lowered for token in ("dismiss", "dismissed", "dismisses", "wicket", "wickets")):
            return "wickets"
        if "runs" in lowered or "score most" in lowered or "scores most" in lowered:
            return "runs_scored"
        return "runs_scored"

    @staticmethod
    def _infer_entity(lowered: str, metric: str) -> str:
        if SemanticQueryPlanner._asks_for_bowling_perspective(lowered):
            return "bowler"
        if metric in {"economy_rate", "bowling_average", "bowling_strike_rate", "wickets_per_over", "wickets_taken", "bowler_dot_ball_percentage", "false_shots_per_over", "yorker_percentage", "yorker_count"}:
            return "bowler"
        if "which length" in lowered or "which line" in lowered:
            return "bowler"
        if "phase of an innings" in lowered:
            return "innings"
        if "team" in lowered or "teams" in lowered:
            return "team"
        if any(token in lowered for token in ("victories", "successful chases", "predicts", "predict ", "factor", "wins most", "defeat")):
            return "team"
        if "matchup" in lowered:
            return "matchup"
        if "who should bowl" in lowered or "should bowl" in lowered or "which bowler" in lowered or "bowler" in lowered or metric in {"economy_rate", "yorker_percentage", "wickets_per_over", "wicket_opportunity_rate", "false_shots_per_over"}:
            return "bowler"
        if "which batter" in lowered or "batter" in lowered or metric in {"batting_strike_rate", "runs_scored", "balls_faced"}:
            return "batter"
        if metric in {"wickets", "wickets_taken", "economy_rate", "bowling_strike_rate", "yorker_percentage", "yorker_count", "legal_balls", "overs_bowled", "false_shots_per_over", "bowler_dot_ball_percentage"}:
            return "bowler"
        return "batter"

    @staticmethod
    def _asks_for_bowling_perspective(lowered: str) -> bool:
        return any(token in lowered for token in ("concede", "concedes", "conceded"))

    @staticmethod
    def _is_direct_player_metric_question(lowered: str, filters: dict[str, object]) -> bool:
        if not (filters.get("batter") or filters.get("bowler")):
            return False
        if any(lowered.startswith(prefix) for prefix in ("which ", "who ")):
            return False
        explicit_breakdown_markers = (
            "against which",
            "which bowling",
            "which type",
            "which line",
            "which length",
            "what shot",
            "which shot",
            " by ",
            "group by",
            "breakdown",
            "split",
            "wise",
            "per ",
            " vs ",
            " versus ",
            "matchup",
        )
        return not any(marker in lowered for marker in explicit_breakdown_markers)

    @staticmethod
    def _infer_group_by(lowered: str, entity: str) -> list[str]:
        if any(token in lowered for token in ("bowling type", "bowling style", "type of bowling")):
            return ["bowling_style"]
        if "matchup" in lowered or "batter-bowler" in lowered:
            return ["matchup"]
        if "length" in lowered:
            return ["length"]
        if "line" in lowered:
            return ["line"]
        if "shot" in lowered and "false shot" not in lowered and "false-shot" not in lowered:
            return ["shot_type"]
        if "scoring zone" in lowered or "field zone" in lowered or "wagon" in lowered:
            return ["field_zone"]
        if "phase" in lowered:
            return ["phase"]
        if any(token in lowered for token in ("by year", "year by year", "each year", "year-wise", "year wise")):
            return ["year"]
        if "which venue" in lowered or "which ground" in lowered or "by venue" in lowered:
            return ["venue"]
        if "batting team" in lowered or "which team" in lowered:
            return ["team"]
        if "which bowler" in lowered:
            return ["bowler"]
        if "which batter" in lowered:
            return ["batter"]
        return [entity] if entity in {"batter", "bowler", "team"} else []

    def _infer_filters(self, question: str, lowered: str, metric: str) -> dict[str, object]:
        filters: dict[str, object] = {}
        player = self._extract_player(question)
        if player:
            metric_owner = METRICS[metric].owner if metric in METRICS else ""
            if self._asks_for_bowling_perspective(lowered):
                filters["bowler"] = player
            elif ("which bowler" in lowered or lowered.startswith("who ")) and any(token in lowered for token in ("dismissed", "dismisses", "controls", "against")):
                filters["batter"] = player
            elif ("which length" in lowered or "which line" in lowered) and any(token in lowered for token in ("dismiss", "against", "to ")):
                filters["batter"] = player
            elif metric_owner == "bowler":
                filters["bowler"] = player
            elif self._is_known_bowler(player) and any(token in lowered for token in ("dot ball", "dot-ball", "economy", "wicket", "yorker")):
                filters["bowler"] = player
            elif any(token in lowered for token in ("score", "scores", "scored", "batter", "batsman", "faced", "dismissed", "dismisses")):
                filters["batter"] = player
            elif any(token in lowered for token in ("bowler", "bowls", "bowled", "economy")):
                filters["bowler"] = player
            else:
                filters["batter"] = player
        year_matches = [int(match) for match in re.findall(r"\b(20\d{2})\b", lowered)]
        if year_matches:
            filters["years"] = year_matches
        if ("after " in lowered or "since " in lowered) and year_matches:
            filters["year_mode"] = "after"
        elif "before " in lowered and year_matches:
            filters["year_mode"] = "before"
        if "powerplay" in lowered or "power play" in lowered:
            filters["phase"] = "powerplay"
        elif "middle overs" in lowered:
            filters["phase"] = "middle"
        elif "death" in lowered or "final overs" in lowered or "final over" in lowered:
            filters["phase"] = "death"
        over_range = re.search(r"between overs?\s+(\d{1,2})\s+(?:and|to|-)\s+(\d{1,2})", lowered)
        if over_range:
            filters["over_range"] = [int(over_range.group(1)), int(over_range.group(2))]
        if "yorker" in lowered and metric not in {"yorker_percentage", "yorker_count"}:
            filters.setdefault("length", "YORKER")
        elif "short ball" in lowered or "short balls" in lowered or "short-ball" in lowered or "short-balls" in lowered:
            filters["length"] = "SHORT"
        elif "good length" in lowered or "good-length" in lowered:
            filters["length"] = "GOOD_LENGTH"
        elif "full ball" in lowered or "full balls" in lowered or "full-ball" in lowered or "full-balls" in lowered:
            filters["length"] = "FULL"
        if "against spin" in lowered or "versus spin" in lowered:
            filters["bowling_style"] = "spin"
        elif "against pace" in lowered or "versus pace" in lowered:
            filters["bowling_style"] = "pace"
        elif "wrist spin" in lowered:
            filters["bowling_style"] = "wrist_spin"
        elif "leg spin" in lowered or "leg-spin" in lowered:
            filters["bowling_style"] = "leg_spin"
        elif "finger spin" in lowered:
            filters["bowling_style"] = "finger_spin"
        elif "off spin" in lowered or "off-spin" in lowered or "off spinner" in lowered:
            filters["bowling_style"] = "off_spin"
        elif "left-arm pace" in lowered or "left arm pace" in lowered:
            filters["bowling_style"] = "left_arm_pace"
        elif "left-arm spin" in lowered or "left arm spin" in lowered:
            filters["bowling_style"] = "left_arm_spin"
        if "left-handers" in lowered or "left handers" in lowered or "left-hand batters" in lowered:
            filters["batter_hand"] = "LHB"
        elif "right-handers" in lowered or "right handers" in lowered or "right-hand batters" in lowered:
            filters["batter_hand"] = "RHB"
        opposition = self._extract_opposition(lowered)
        if opposition:
            filters["opposition"] = opposition
        venue = None if "by venue" in lowered else self._extract_venue(lowered)
        if venue:
            filters["venue"] = venue
        for key, aliases in {
            "midwicket": ("mid wicket", "mid-wicket", "midwicket", "cow corner"),
            "cover": ("cover", "covers"),
            "point": ("point",),
            "third_man": ("third man", "third-man"),
            "fine_leg": ("fine leg", "fine-leg"),
            "square_leg": ("square leg", "square-leg"),
            "long_on": ("long on", "long-on"),
            "long_off": ("long off", "long-off"),
        }.items():
            if any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in aliases):
                filters["field_zone"] = key
        return filters

    def _extract_opposition(self, lowered: str) -> str | None:
        team_aliases = {
            "afg": "Afghanistan",
            "aus": "Australia",
            "aussies": "Australia",
            "ban": "Bangladesh",
            "bangla": "Bangladesh",
            "eng": "England",
            "ind": "India",
            "kiwis": "New Zealand",
            "nz": "New Zealand",
            "pak": "Pakistan",
            "proteas": "South Africa",
            "sa": "South Africa",
            "sl": "Sri Lanka",
            "sri lanka": "Sri Lanka",
            "wi": "West Indies",
        }
        for alias, team in team_aliases.items():
            if (
                f"against {alias}" in lowered
                or f"against the {alias}" in lowered
                or f"versus {alias}" in lowered
                or f"versus the {alias}" in lowered
                or f"vs {alias}" in lowered
                or f"v {alias}" in lowered
            ):
                return team
        teams = self.available_teams or [
            "Australia",
            "India",
            "England",
            "South Africa",
            "New Zealand",
            "Pakistan",
            "Sri Lanka",
            "Bangladesh",
            "West Indies",
            "Afghanistan",
        ]
        for team in teams:
            team_lower = team.lower()
            if f"against {team_lower}" in lowered or f"versus {team_lower}" in lowered or f"vs {team_lower}" in lowered:
                return team
        return None

    def _extract_venue(self, lowered: str) -> str | None:
        aliases = {
            "wankhede": "Wankhede Stadium, Mumbai",
            "lord's": "Lord's, London",
            "lord’s": "Lord's, London",
            "lords": "Lord's, London",
            "mcg": "Melbourne Cricket Ground",
            "melbourne cricket ground": "Melbourne Cricket Ground",
            "the oval": "Kennington Oval, London",
            "kennington oval": "Kennington Oval, London",
        }
        for alias, venue in aliases.items():
            if alias in lowered:
                return venue
        for venue in self.available_venues:
            if venue.lower() in lowered:
                return venue
        return None

    @staticmethod
    def _comparison_looks_bowling(players: list[str], lowered: str, metric: str) -> bool:
        bowler_names = {"Jasprit Bumrah", "Mitchell Starc", "Kagiso Rabada", "Pat Cummins", "Trent Boult"}
        return (
            metric in {"economy_rate", "bowling_strike_rate", "wickets_taken", "wickets_per_over", "bowler_dot_ball_percentage"}
            or any(token in lowered for token in ("economy", "wicket rate", "dot-ball percentage"))
            or (players and all(player in bowler_names for player in players))
        )

    @staticmethod
    def _comparison_looks_batting(players: list[str], lowered: str, metric: str) -> bool:
        return metric in {"runs_scored", "batting_strike_rate", "batter_dot_ball_percentage", "boundary_percentage"} or any(
            token in lowered for token in ("batting strike rate", "scores faster", "against spin", "short balls")
        )

    @staticmethod
    def _comparison_has_mixed_roles(players: list[str]) -> bool:
        batter_names = {
            "Virat Kohli",
            "Rohit Sharma",
            "Shreyas Iyer",
            "KL Rahul",
            "Hardik Pandya",
            "Ravindra Jadeja",
            "Steve Smith",
            "Jos Buttler",
            "Glenn Maxwell",
            "Heinrich Klaasen",
            "David Miller",
        }
        bowler_names = {"Jasprit Bumrah", "Mitchell Starc", "Kagiso Rabada", "Pat Cummins", "Trent Boult"}
        return any(player in batter_names for player in players) and any(player in bowler_names for player in players)

    @staticmethod
    def _is_known_bowler(player: str) -> bool:
        return player in {"Jasprit Bumrah", "Mitchell Starc", "Kagiso Rabada", "Pat Cummins", "Trent Boult", "Rashid Khan"}

    @staticmethod
    def _named_batter_bowler_matchup(
        lowered: str,
        ordered_players: list[str],
    ) -> tuple[str, str] | None:
        has_matchup_wording = bool(
            re.search(r"\b(?:vs\.?|versus|against|head[- ]to[- ]head)\b", lowered)
        )
        if not has_matchup_wording or len(ordered_players) != 2:
            return None

        known_bowlers = [
            player for player in ordered_players if SemanticQueryPlanner._is_known_bowler(player)
        ]
        if len(known_bowlers) != 1:
            return None
        bowler = known_bowlers[0]
        batter = next(player for player in ordered_players if player != bowler)
        return batter, bowler

    @staticmethod
    def _unsupported_factual_reason(lowered: str) -> str | None:
        if "most catches" in lowered or "catch" in lowered or "catches" in lowered:
            return "Data limitation: fielding catcher records are missing from the available ODI ball-by-ball data."
        if "player of the match" in lowered:
            return "Data limitation: player-of-the-match award metadata is missing from the available ODI data."
        if "which team" in lowered and ("economy" in lowered or "against " in lowered or "versus " in lowered or " vs " in lowered):
            return "Team-level opposition or bowling-economy questions need explicit tested team semantics before Semantic V2 can answer them."
        if "opposition-wise" in lowered or "opponent wise" in lowered:
            return "Opposition-wise splits are understood, but Semantic V2 does not have a tested opposition capability yet."
        if "record against" in lowered:
            return "Head-to-head opposition records are not implemented in Semantic V2 yet."
        return None

    def _infer_match_fact_filters(self, lowered: str) -> dict[str, object]:
        filters: dict[str, object] = {}
        if "world cup" in lowered:
            filters["competition"] = "ICC Cricket World Cup"
        if "final" in lowered:
            filters["match_stage"] = "final"
        if any(token in lowered for token in ("won", "winner", " win")):
            filters["fact_type"] = "winner"
        elif any(token in lowered for token in ("total", "score")):
            filters["fact_type"] = "team_total"
        team = self._extract_team_mention(lowered)
        if team:
            filters["team"] = team
        return filters

    def _extract_team_mention(self, lowered: str) -> str | None:
        aliases = {
            "afghanistan": "Afghanistan",
            "australia": "Australia",
            "aussies": "Australia",
            "bangladesh": "Bangladesh",
            "england": "England",
            "india": "India",
            "new zealand": "New Zealand",
            "pakistan": "Pakistan",
            "south africa": "South Africa",
            "sri lanka": "Sri Lanka",
            "west indies": "West Indies",
        }
        teams = self.available_teams or list(aliases.values())
        for team in teams:
            if re.search(rf"\b{re.escape(team.lower())}\b", lowered):
                return team
        for alias, team in aliases.items():
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return team
        return None

    @staticmethod
    def _refine_matchup_plan(
        lowered: str,
        entity: str,
        metric: str,
        group_by: list[str],
        filters: dict[str, object],
        default_sort: str,
    ) -> tuple[str, str, list[str], dict[str, object], str]:
        is_pair_matchup = "matchup" in lowered or "batter-bowler" in lowered
        if "one-sided" in lowered and "matchup" in lowered:
            return "matchup", "batting_strike_rate", ["matchup"], filters, "desc"
        if is_pair_matchup:
            entity = "matchup"
            group_by = ["matchup"]
        if "which bowler" in lowered and not is_pair_matchup:
            entity = "bowler"
            group_by = ["bowler"]
        if "which batter" in lowered and not is_pair_matchup:
            entity = "batter"
            group_by = ["batter"]
        if "highest false-shot percentage" in lowered or "highest false shot percentage" in lowered:
            metric = "false_shot_percentage"
            default_sort = "desc"
        elif "controls" in lowered:
            metric = "dot_ball_percentage"
            default_sort = "desc"
        elif "dismissed" in lowered or "dismisses" in lowered or "most wickets" in lowered or "successful" in lowered:
            metric = "wickets"
            default_sort = "desc"
        elif "perform" in lowered or "dominates" in lowered:
            metric = "batting_strike_rate"
            default_sort = "desc"
        if "finishers" in lowered:
            entity = "bowler"
            group_by = ["bowler"]
            filters.setdefault("phase", "death")
            metric = "wickets"
            default_sort = "desc"
        return entity, metric, group_by, filters, default_sort

    def _extract_player(self, question: str) -> str | None:
        normalized_question = normalize_name(question)
        for player in self.available_players:
            if normalize_name(player) in normalized_question:
                return player
        for alias, canonical in ALIASES.items():
            if normalize_name(alias) in normalized_question:
                result = resolve_player_name(canonical, self.available_players)
                if result.canonical_name:
                    return result.canonical_name
        for ngram in re.findall(r"(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,})){0,3}", question):
            result = resolve_player_name(ngram, self.available_players)
            if result.canonical_name:
                return result.canonical_name
        return None

    def _extract_players(self, question: str) -> list[str]:
        normalized_question = normalize_name(question)
        found: list[str] = []
        for player in self.available_players:
            if normalize_name(player) in normalized_question and player not in found:
                found.append(player)
        for alias, canonical in ALIASES.items():
            if normalize_name(alias) in normalized_question:
                result = resolve_player_name(canonical, self.available_players)
                player = result.canonical_name or canonical
                if player not in found:
                    found.append(player)
        for ngram in re.findall(r"(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,})){0,3}", question):
            result = resolve_player_name(ngram, self.available_players)
            if result.canonical_name and result.canonical_name not in found:
                found.append(result.canonical_name)
        return found

    @staticmethod
    def _infer_comparison_metrics(lowered: str, primary_metric: str, entity: str) -> list[str]:
        metrics: list[str] = []
        if "wicket rate" in lowered or "wickets per over" in lowered:
            metrics.append("wickets_per_over")
        if "wickets taken" in lowered:
            metrics.append("wickets_taken")
        if "dot-ball percentage" in lowered or "dot ball percentage" in lowered or "dot percentage" in lowered:
            metrics.append("bowler_dot_ball_percentage" if entity == "bowler" else "batter_dot_ball_percentage")
        if "boundary percentage" in lowered:
            metrics.append("boundary_percentage")
        if "economy" in lowered:
            metrics.append("economy_rate")
        if "average" in lowered or re.search(r"\bavg\b", lowered):
            metrics.append("bowling_average" if entity == "bowler" else "batting_average")
        if "bowling strike rate" in lowered:
            metrics.append("bowling_strike_rate")
        elif "batting strike rate" in lowered or "strike rate" in lowered or "scores faster" in lowered:
            metrics.append("batting_strike_rate")
        if not metrics:
            metrics.extend(
                ["economy_rate", "bowling_average", "bowling_strike_rate", "wickets_taken", "bowler_dot_ball_percentage", "boundary_percentage"]
                if entity == "bowler"
                else ["batting_strike_rate", "runs_scored", "batting_average", "batter_dot_ball_percentage", "boundary_percentage"]
            )
        deduped: list[str] = []
        for metric in metrics:
            if metric not in deduped:
                deduped.append(metric)
        return deduped

    @staticmethod
    def _comparison_has_explicit_metric_request(lowered: str) -> bool:
        return bool(re.search(r"\b(?:runs?|wickets?|boundaries)\b", lowered)) or any(
            token in lowered
            for token in (
                "average",
                "avg",
                "boundary percentage",
                "dot-ball percentage",
                "dot ball percentage",
                "dot percentage",
                "economy",
                "runs scored",
                "scores faster",
                "strike rate",
                "wicket rate",
                "wickets per over",
                "wickets taken",
            )
        )

    @staticmethod
    def _question_subject(lowered: str) -> str | None:
        if any(token in lowered for token in ("struggle", "struggles", "weakness", "vulnerable")):
            return "weakness_check"
        if "one-sided" in lowered and "matchup" in lowered:
            return "one_sided_matchup"
        if "which bowler" in lowered:
            return "bowler"
        if "which batter" in lowered:
            return "batter"
        if "which length" in lowered:
            return "length"
        if "which shot" in lowered or "what shot" in lowered:
            return "shot_type"
        return None

    @staticmethod
    def _needs_complex_model(question: str) -> bool:
        lowered = question.lower()
        return (
            len(question) > 140
            or any(token in lowered for token in ("tactical", "optimal", "predict", "factor", "explain why"))
        )

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(text.strip())
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
