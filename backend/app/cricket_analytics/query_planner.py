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
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.player_resolution import ALIASES, normalize_name, resolve_player_name


@dataclass(slots=True)
class PlannerResult:
    plan: CricketQueryPlan | None
    validation: ValidationResult
    used_gemini: bool


class SemanticQueryPlanner:
    def __init__(self, gemini_client: GeminiClient, available_players: list[str]) -> None:
        self.gemini_client = gemini_client
        self.available_players = available_players

    def plan(self, question: str, trace: QueryTrace) -> PlannerResult:
        if self.gemini_client.is_configured():
            planned = self._plan_with_gemini(question, trace, prefer_complex=self._needs_complex_model(question))
            if planned.plan is not None and planned.validation.valid:
                return planned
            if planned.plan is not None:
                repaired = self._repair_with_gemini(question, planned.plan, planned.validation, trace)
                if repaired.plan is not None and repaired.validation.valid:
                    return repaired

        fallback = self._fallback_plan(question)
        normalized = normalize_plan(fallback)
        validation = validate_plan(normalized, question)
        trace.parsed_json_plan = fallback.model_dump(mode="json")
        trace.normalized_plan = normalized.model_dump(mode="json")
        trace.validation_result = validation.model_dump(mode="json")
        trace.operation_type = normalized.operation
        return PlannerResult(plan=normalized, validation=validation, used_gemini=False)

    def _plan_with_gemini(self, question: str, trace: QueryTrace, prefer_complex: bool) -> PlannerResult:
        prompt = self._planner_prompt(question)
        raw = self.gemini_client.generate_text(prompt, prefer_complex=prefer_complex)
        trace.gemini_raw_response = raw
        if not raw:
            return PlannerResult(
                plan=None,
                validation=ValidationResult(valid=False, errors=["Gemini returned no planner response."]),
                used_gemini=True,
            )

        payload = self._parse_json_object(raw)
        trace.parsed_json_plan = payload if isinstance(payload, dict) else None
        if not isinstance(payload, dict):
            return PlannerResult(
                plan=None,
                validation=ValidationResult(valid=False, errors=["Gemini response was not valid JSON object."]),
                used_gemini=True,
            )
        try:
            plan = CricketQueryPlan.model_validate(payload)
        except ValidationError as exc:
            return PlannerResult(
                plan=None,
                validation=ValidationResult(valid=False, errors=[f"Plan schema validation failed: {exc}"]),
                used_gemini=True,
            )
        normalized = normalize_plan(plan)
        validation = validate_plan(normalized, question)
        trace.normalized_plan = normalized.model_dump(mode="json")
        trace.validation_result = validation.model_dump(mode="json")
        trace.operation_type = normalized.operation
        return PlannerResult(plan=normalized, validation=validation, used_gemini=True)

    def _repair_with_gemini(
        self,
        question: str,
        invalid_plan: CricketQueryPlan,
        validation: ValidationResult,
        trace: QueryTrace,
    ) -> PlannerResult:
        prompt = (
            "Repair this cricket analytics JSON plan. Return JSON only.\n"
            "Do not write SQL. Use only the provided ontology and schema.\n\n"
            f"Ontology: {json.dumps(ontology_context(), sort_keys=True)}\n"
            f"Original question: {question}\n"
            f"Invalid plan: {invalid_plan.model_dump_json()}\n"
            f"Validation errors: {validation.model_dump_json()}\n"
        )
        raw = self.gemini_client.generate_text(prompt, prefer_complex=True)
        if not raw:
            return PlannerResult(plan=invalid_plan, validation=validation, used_gemini=True)
        trace.gemini_raw_response = f"{trace.gemini_raw_response or ''}\n\nREPAIR:\n{raw}".strip()
        payload = self._parse_json_object(raw)
        if not isinstance(payload, dict):
            return PlannerResult(plan=invalid_plan, validation=validation, used_gemini=True)
        try:
            repaired = normalize_plan(CricketQueryPlan.model_validate(payload))
        except ValidationError:
            return PlannerResult(plan=invalid_plan, validation=validation, used_gemini=True)
        repaired_validation = validate_plan(repaired, question)
        trace.parsed_json_plan = payload
        trace.normalized_plan = repaired.model_dump(mode="json")
        trace.validation_result = repaired_validation.model_dump(mode="json")
        trace.operation_type = repaired.operation
        return PlannerResult(plan=repaired, validation=repaired_validation, used_gemini=True)

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
        split_by, compare_values = self._infer_split(lowered, filters)
        event, window = self._infer_event(lowered, filters)
        default_sort = METRICS.get(metric).default_sort if metric in METRICS else "desc"
        if any(token in lowered for token in ("fewest", "lowest", "least")) and metric in {
            "boundary_rate_per_100_balls",
            "boundary_percentage",
            "economy_rate",
            "dot_ball_percentage",
            "false_shot_percentage",
        }:
            default_sort = "asc"

        if "hardest to bowl dot balls to" in lowered:
            entity = "batter"
            metric = "dot_ball_percentage"
            default_sort = "asc"
            if "batter" not in group_by:
                group_by = ["batter"]

        if not group_by and operation == "aggregate":
            group_by = [entity] if entity in {"batter", "bowler", "team"} else []

        minimum_sample = MinimumSampleSpec(**METRICS[metric].minimum_sample.as_dict()) if metric in METRICS else None
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
            limit=10,
            minimum_sample=minimum_sample,
            question_subject=self._question_subject(lowered),
            explanation_intent="deterministic semantic fallback",
            confidence=0.55,
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
    def _infer_operation(lowered: str) -> str:
        if any(token in lowered for token in ("should bowl", "optimal", "plan against", "field placement", "defending", "held back", "introduce spin", "introduced early")):
            return "tactical_recommendation"
        if any(token in lowered for token in ("predict", "predicts", "factor", "factors", "outcome", "victories", "successful chases", "wins most")):
            return "predictive_analysis"
        if any(token in lowered for token in ("immediately after", "after a wicket", "milestone", "after the powerplay", "after early wickets", "losing early wickets", "lost early wickets", "after a timeout", "after timeout")):
            return "event_window"
        if any(token in lowered for token in ("concentrated", "concentration", "entropy", "spread", "variation", "changes most", "changes the most", "distribution", "varies")):
            return "distribution_analysis"
        if any(token in lowered for token in ("difference", "compare", "better against", "left-handers than right-handers", "wrist spin", "finger spin", "after 20 balls", "after facing 20 balls", "accelerates", "between overs")):
            return "split_compare"
        if "matchup" in lowered or "batter-bowler" in lowered or "finishers" in lowered:
            return "matchup"
        return "aggregate"

    @staticmethod
    def _infer_metric(lowered: str) -> str:
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
        if "accelerates" in lowered or "accelerate" in lowered:
            return "run_rate"
        if "wrist spin" in lowered or "finger spin" in lowered or "leg spin matchups" in lowered:
            return "batting_strike_rate"
        if "one-sided" in lowered and "matchup" in lowered:
            return "batting_strike_rate"
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
        if "yorker" in lowered:
            return "yorker_percentage"
        if "false shot" in lowered or "false-shot" in lowered:
            return "false_shot_percentage"
        if "dot ball" in lowered or "dot balls" in lowered or "dots" in lowered:
            return "dot_ball_percentage"
        if "boundaries per 100" in lowered or "boundary rate" in lowered:
            return "boundary_rate_per_100_balls"
        if "boundary" in lowered:
            return "boundary_percentage"
        if "control" in lowered:
            return "control_percentage"
        if "most balls" in lowered or "balls faced" in lowered or "faced the most balls" in lowered:
            return "balls_faced"
        if any(token in lowered for token in ("fastest", "strike rate", "score fastest", "scores fastest", "dominates", "struggles", "improves", "vulnerable", "effective", "optimal bowling plan", "introduce spin", "introduced early")):
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
        if "which length" in lowered or "which line" in lowered:
            return "bowler"
        if "phase of an innings" in lowered:
            return "innings"
        if "team" in lowered or "teams" in lowered:
            return "team"
        if any(token in lowered for token in ("victories", "successful chases", "predicts", "predict ", "factor", "wins most", "defeat")):
            return "team"
        if "venue" in lowered or "ground" in lowered:
            return "venue"
        if "matchup" in lowered:
            return "matchup"
        if "who should bowl" in lowered or "should bowl" in lowered or "which bowler" in lowered or "bowler" in lowered or metric in {"economy_rate", "yorker_percentage", "wickets_per_over", "wicket_opportunity_rate", "dot_ball_percentage", "false_shots_per_over"}:
            return "bowler"
        if "which batter" in lowered or "batter" in lowered or metric in {"batting_strike_rate", "runs_scored", "balls_faced"}:
            return "batter"
        if metric in {"wickets", "economy_rate", "yorker_percentage"}:
            return "bowler"
        return "batter"

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
        if "which venue" in lowered or "which ground" in lowered:
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
            if any(token in lowered for token in ("score", "scores", "scored", "batter", "batsman", "faced", "dismisses")):
                filters["batter"] = player
            elif any(token in lowered for token in ("bowler", "bowls", "bowled", "economy")):
                filters["bowler"] = player
            else:
                filters["batter"] = player
        if "powerplay" in lowered or "power play" in lowered:
            filters["phase"] = "powerplay"
        elif "middle overs" in lowered:
            filters["phase"] = "middle"
        elif "death" in lowered or "final overs" in lowered or "final over" in lowered:
            filters["phase"] = "death"
        over_range = re.search(r"between overs?\s+(\d{1,2})\s+(?:and|to|-)\s+(\d{1,2})", lowered)
        if over_range:
            filters["over_range"] = [int(over_range.group(1)), int(over_range.group(2))]
        if "yorker" in lowered and metric != "yorker_percentage":
            filters.setdefault("length", "YORKER")
        if "against spin" in lowered or "versus spin" in lowered:
            filters["bowling_style"] = "spin"
        elif "against pace" in lowered or "versus pace" in lowered:
            filters["bowling_style"] = "pace"
        if "left-handers" in lowered or "left handers" in lowered or "left-hand batters" in lowered:
            filters["batter_hand"] = "LHB"
        elif "right-handers" in lowered or "right handers" in lowered or "right-hand batters" in lowered:
            filters["batter_hand"] = "RHB"
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

    @staticmethod
    def _question_subject(lowered: str) -> str | None:
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
