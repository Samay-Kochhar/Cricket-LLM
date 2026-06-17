from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.cricket_analytics.executors import (
    distribution_executor,
    event_window_executor,
    matchup_executor,
    predictive_executor,
    split_compare_executor,
    tactical_executor,
)
from backend.app.cricket_analytics.ontology import METRICS
from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.result_validator import validate_result
from backend.app.cricket_analytics.schemas import CricketQueryPlan, QueryBuildResult, ValidationResult
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.domain.evidence_models import (
    Citation,
    CitationSource,
    EvidenceNote,
    EvidenceQueryBlock,
    EvidenceStatus,
    InsufficientEvidenceBlock,
    MetricReference,
    QueryInterpretation,
    QueryResponse,
    SummaryBlock,
    TableBlock,
)
from backend.app.domain.metric_models import QueryClass
from backend.app.services.gemini_client import GeminiClient


@dataclass(slots=True)
class SemanticAnalyticsService:
    repository: Any
    gemini_client: GeminiClient
    app_env: str = "development"
    planner: SemanticQueryPlanner = field(init=False)

    def __post_init__(self) -> None:
        self.planner = SemanticQueryPlanner(self.gemini_client, self.repository.list_player_names())

    def answer_question(self, question: str) -> QueryResponse:
        trace = QueryTrace(original_user_question=question)
        planner_result = self.planner.plan(question, trace)
        plan = planner_result.plan
        if plan is None:
            return self._invalid_plan_response(question, trace, planner_result.validation)
        if not planner_result.validation.valid:
            return self._invalid_plan_response(question, trace, planner_result.validation, plan)
        if plan.operation == "split_compare":
            return self._answer_split_compare(question, plan, trace)
        if plan.operation != "aggregate":
            return self._unsupported_operation_response(question, plan, trace)
        return self._answer_aggregate(question, plan, trace)

    def _answer_aggregate(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = "query_builders.aggregate_builder.build_aggregate_query"
        try:
            build = build_aggregate_query(plan)
            trace.final_sql_or_method = build.sql
            rows = self.repository._fetchall(build.sql, build.params)
        except Exception as exc:  # pragma: no cover - exercised through integration, kept safe for production.
            trace.final_answer_metadata = {"status": "query_execution_failed", "error": str(exc)}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The semantic aggregate query could not be executed safely.",
                suggestions=["Check the V2 query trace and supported database columns."],
            )

        dict_rows = [dict(zip(build.columns, row)) for row in rows]
        trace.result_columns = build.columns
        result_validation = validate_result(plan, build, dict_rows)
        if not result_validation.valid:
            trace.final_answer_metadata = {
                "status": "result_validation_failed",
                "result_validation": result_validation.model_dump(mode="json"),
            }
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The question was understood, but the returned data did not pass result validation.",
                suggestions=result_validation.errors or ["Try a broader sample or a simpler aggregate question."],
            )

        table = self._table_for_rows(plan, dict_rows)
        summary = self._summary_for_rows(plan, dict_rows)
        trace.final_answer_metadata = {
            "status": "supported",
            "row_count": len(dict_rows),
            "columns": build.columns,
            "result_validation": result_validation.model_dump(mode="json"),
        }
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=self._interpretation(question, plan),
            summaries=[summary],
            tables=[table],
            metric_references=[self._metric_reference(plan.metric)],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Semantic V2 aggregate query",
                    description=build.description,
                    sql=build.sql,
                    parameters=build.params,
                    table=table,
                )
            ],
            evidence_notes=self._trace_notes(trace, plan),
            citations=[
                Citation(
                    label="Semantic aggregate source",
                    source_type=CitationSource.database,
                    locator="analytics.deliveries_v1",
                )
            ],
        )

    def _answer_split_compare(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = "executors.split_compare_executor.build_split_compare_query"
        try:
            split_build = split_compare_executor.build_split_compare_query(plan)
            build = split_build.query
            trace.final_sql_or_method = build.sql
            rows = self.repository._fetchall(build.sql, build.params)
        except Exception as exc:  # pragma: no cover - protected integration path.
            trace.final_answer_metadata = {"status": "query_execution_failed", "error": str(exc)}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The semantic split comparison query could not be executed safely.",
                suggestions=["Check the V2 query trace, split type, metric, and required database columns."],
            )

        dict_rows = [dict(zip(build.columns, row)) for row in rows]
        trace.result_columns = build.columns
        if not dict_rows:
            trace.final_answer_metadata = {"status": "no_rows_after_split_sample_filter", "columns": build.columns}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The split comparison was understood, but no entity met the minimum sample on both split sides.",
                suggestions=["Lower the minimum sample threshold or choose a broader split."],
            )

        table = self._split_table_for_rows(plan, split_build, dict_rows)
        summary = self._split_summary_for_rows(plan, split_build, dict_rows)
        trace.final_answer_metadata = {
            "status": "supported",
            "row_count": len(dict_rows),
            "columns": build.columns,
            "split_by": plan.split_by,
            "split_a": split_build.split_a_label,
            "split_b": split_build.split_b_label,
        }
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=self._interpretation(question, plan),
            summaries=[summary],
            tables=[table],
            metric_references=[self._metric_reference(plan.metric)],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Semantic V2 split comparison query",
                    description=build.description,
                    sql=build.sql,
                    parameters=build.params,
                    table=table,
                )
            ],
            evidence_notes=self._trace_notes(trace, plan),
            citations=[
                Citation(
                    label="Semantic split comparison source",
                    source_type=CitationSource.database,
                    locator="analytics.deliveries_v1",
                )
            ],
        )

    def _unsupported_operation_response(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = f"executors.{plan.operation}"
        reason_by_operation = {
            "split_compare": split_compare_executor.unsupported_reason,
            "event_window": event_window_executor.unsupported_reason,
            "distribution_analysis": distribution_executor.unsupported_reason,
            "matchup": matchup_executor.unsupported_reason,
            "predictive_analysis": predictive_executor.unsupported_reason,
            "tactical_recommendation": tactical_executor.unsupported_reason,
        }
        reason = plan.unsupported_reason or reason_by_operation.get(plan.operation, lambda _: "Operation is not implemented yet.")(plan)
        trace.final_answer_metadata = {"status": "understood_not_implemented", "reason": reason}
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.unsupported,
            interpretation=self._interpretation(question, plan),
            summaries=[SummaryBlock(title="Understood, not implemented", body=reason)],
            insufficiencies=[
                InsufficientEvidenceBlock(
                    title="Understood, not implemented",
                    detail=reason,
                    suggestions=["Use an aggregate leaderboard/stat question while this operation executor is being added."],
                )
            ],
            evidence_notes=self._trace_notes(trace, plan),
        )

    def _invalid_plan_response(
        self,
        question: str,
        trace: QueryTrace,
        validation: ValidationResult,
        plan: CricketQueryPlan | None = None,
    ) -> QueryResponse:
        trace.final_answer_metadata = {"status": "invalid_plan", "errors": validation.errors}
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.unsupported,
            interpretation=self._interpretation(question, plan),
            summaries=[
                SummaryBlock(
                    title="Invalid semantic plan",
                    body="The question was understood by the planner, but the backend rejected the plan shape.",
                )
            ],
            insufficiencies=[
                InsufficientEvidenceBlock(
                    title="Invalid plan",
                    detail="; ".join(validation.errors) or "The semantic plan could not be validated.",
                    suggestions=["Rephrase as a simpler aggregate question, or inspect the V2 query trace."],
                )
            ],
            evidence_notes=self._trace_notes(trace, plan),
        )

    def _insufficient_response(
        self,
        question: str,
        plan: CricketQueryPlan,
        trace: QueryTrace,
        detail: str,
        suggestions: list[str],
    ) -> QueryResponse:
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.insufficient_evidence,
            interpretation=self._interpretation(question, plan),
            insufficiencies=[
                InsufficientEvidenceBlock(
                    title="Insufficient evidence",
                    detail=detail,
                    suggestions=suggestions,
                )
            ],
            evidence_notes=self._trace_notes(trace, plan),
        )

    def _interpretation(self, question: str, plan: CricketQueryPlan | None) -> QueryInterpretation:
        filters: dict[str, object] = {}
        entities: list[str] = []
        if plan is not None:
            filters = {
                **plan.filters,
                "semantic_operation": plan.operation,
                "semantic_metric": plan.metric,
                "semantic_group_by": plan.group_by,
            }
            entities = [
                str(plan.filters[key])
                for key in ("batter", "bowler", "team")
                if isinstance(plan.filters.get(key), str)
            ]
        return QueryInterpretation(
            original_question=question,
            query_class=QueryClass.venue_context_leaderboard.value,
            entities=entities,
            filters=filters,
        )

    def _trace_notes(self, trace: QueryTrace, plan: CricketQueryPlan | None) -> list[EvidenceNote]:
        notes = [
            EvidenceNote(
                title="Semantic V2 trace",
                detail=trace.compact_json(max_chars=50000),
            )
        ]
        if plan and plan.assumptions:
            notes.append(EvidenceNote(title="Semantic V2 assumptions", detail=" | ".join(plan.assumptions)))
        return notes

    @staticmethod
    def _table_for_rows(plan: CricketQueryPlan, rows: list[dict[str, object]]) -> TableBlock:
        dimension_columns = plan.group_by or ([plan.entity] if rows and plan.entity in rows[0] else [])
        columns = [
            *dimension_columns,
            plan.metric,
            "balls",
            "legal_balls",
            "matches",
        ]
        table_rows: list[list[str | int | float | None]] = []
        for row in rows:
            table_rows.append([_display_value(row.get(column)) for column in columns])
        return TableBlock(
            title="Semantic aggregate result",
            columns=[_label(column) for column in columns],
            rows=table_rows,
        )

    @staticmethod
    def _summary_for_rows(plan: CricketQueryPlan, rows: list[dict[str, object]]) -> SummaryBlock:
        top = rows[0]
        dimension_columns = plan.group_by or ([plan.entity] if plan.entity in top else [])
        subject = "overall"
        if dimension_columns:
            subject = " / ".join(str(top.get(column)) for column in dimension_columns if top.get(column) is not None)
        metric_value = _display_value(top.get(plan.metric))
        metric_unit = METRICS[plan.metric].unit
        metric_text = f"{metric_value}%" if metric_unit == "percent" and metric_value is not None else str(metric_value)
        sample_key = "legal_balls" if METRICS[plan.metric].denominator == "legal_balls" else "balls"
        sample = top.get(sample_key) or top.get("balls") or top.get("legal_balls")
        sample_label = "legal balls" if sample_key == "legal_balls" else "balls"
        sample_text = f" from {sample} {sample_label}" if sample else ""
        return SummaryBlock(
            title="Semantic aggregate answer",
            body=(
                f"Within the available ODI dataset, {subject} ranks first for "
                f"{_label(plan.metric)} at {metric_text}{sample_text}."
            ),
        )

    @staticmethod
    def _split_table_for_rows(
        plan: CricketQueryPlan,
        split_build: split_compare_executor.SplitCompareBuild,
        rows: list[dict[str, object]],
    ) -> TableBlock:
        entity_column = plan.group_by[0] if plan.group_by else plan.entity
        columns = [
            entity_column,
            split_build.value_a_column,
            split_build.value_b_column,
            "difference",
            split_build.sample_a_column,
            split_build.sample_b_column,
            "rank_value",
        ]
        return TableBlock(
            title="Semantic split comparison result",
            columns=[_label(column) for column in columns],
            rows=[[ _display_value(row.get(column)) for column in columns] for row in rows],
        )

    @staticmethod
    def _split_summary_for_rows(
        plan: CricketQueryPlan,
        split_build: split_compare_executor.SplitCompareBuild,
        rows: list[dict[str, object]],
    ) -> SummaryBlock:
        top = rows[0]
        entity_column = plan.group_by[0] if plan.group_by else plan.entity
        subject = str(top.get(entity_column) or "the top entity")
        metric_unit = METRICS[plan.metric].unit
        value_a = _display_value(top.get(split_build.value_a_column))
        value_b = _display_value(top.get(split_build.value_b_column))
        difference = _display_value(top.get("difference"))
        suffix = "%" if metric_unit == "percent" else ""
        return SummaryBlock(
            title="Semantic split comparison answer",
            body=(
                f"Within the available ODI dataset, {subject} has the largest split on {_label(plan.metric)}: "
                f"{_label(split_build.split_a_label)} {value_a}{suffix}, "
                f"{_label(split_build.split_b_label)} {value_b}{suffix}, "
                f"difference {difference}{suffix}."
            ),
        )

    @staticmethod
    def _metric_reference(metric: str) -> MetricReference:
        definition = METRICS[metric]
        return MetricReference(
            metric_id=metric,
            label=_label(metric),
            formula=definition.formula,
            unit=definition.unit,
        )


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _display_value(value: object) -> str | int | float | None:
    if isinstance(value, float):
        return round(value, 2)
    return value  # type: ignore[return-value]
