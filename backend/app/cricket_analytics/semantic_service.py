from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from typing import Any

from backend.app.cricket_analytics.executors import (
    distribution_executor,
    event_window_executor,
    matchup_executor,
    player_compare_executor,
    predictive_executor,
    split_compare_executor,
    tactical_executor,
)
from backend.app.cricket_analytics.ontology import METRICS
from backend.app.cricket_analytics.cricket_definitions import public_label
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.result_validator import validate_result
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, QueryBuildResult, SortSpec, ValidationResult
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.domain.evidence_models import (
    ChartBlock,
    Citation,
    CitationSource,
    EvidenceNote,
    EvidenceQueryBlock,
    EvidenceStatus,
    FieldZoneBlock,
    FieldZoneMetric,
    InsufficientEvidenceBlock,
    MetricReference,
    PitchMapBlock,
    PitchMapCell,
    QueryInterpretation,
    QueryResponse,
    ShotProfileBlock,
    ShotTypeMetric,
    SummaryBlock,
    TableBlock,
    VisualCoverage,
    VisualPayload,
)
from backend.app.domain.metric_models import QueryClass
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.player_resolution import resolve_player_name


MATCHUP_PITCH_MIN_COVERED_BALLS = 12
MATCHUP_PITCH_MIN_COVERAGE_PERCENTAGE = 50.0


@dataclass(slots=True)
class SemanticAnalyticsService:
    repository: Any
    gemini_client: GeminiClient
    app_env: str = "development"
    allow_dev_fallback: bool = True
    planner: SemanticQueryPlanner = field(init=False)

    def __post_init__(self) -> None:
        self.planner = SemanticQueryPlanner(
            self.gemini_client,
            self.repository.list_player_names(),
            self.repository.list_venues(),
            self.repository.list_teams(),
            allow_dev_fallback=self.allow_dev_fallback,
        )

    def answer_question(self, question: str) -> QueryResponse:
        profile_response = self._maybe_answer_batting_profile(question)
        if profile_response is not None:
            return profile_response
        position_response = self._maybe_answer_batting_position_comparison(question)
        if position_response is not None:
            return position_response
        trace = QueryTrace(original_user_question=question)
        planner_result = self.planner.plan(question, trace)
        plan = planner_result.plan
        if plan is None:
            return self._invalid_plan_response(question, trace, planner_result.validation)
        if not planner_result.validation.valid:
            return self._invalid_plan_response(question, trace, planner_result.validation, plan)
        if plan.operation == "tactical_recommendation":
            if plan.unsupported_reason:
                return self._unsupported_operation_response(question, plan, trace)
            return self._answer_tactical_recommendation(question, plan, trace)
        if plan.unsupported_reason:
            return self._unsupported_operation_response(question, plan, trace)
        if plan.operation == "player_compare":
            return self._answer_player_compare(question, plan, trace)
        if plan.operation == "split_compare":
            return self._answer_split_compare(question, plan, trace)
        if plan.operation == "matchup":
            return self._answer_matchup(question, plan, trace)
        if plan.operation == "match_fact":
            return self._answer_match_fact(question, plan, trace)
        if plan.operation != "aggregate":
            return self._unsupported_operation_response(question, plan, trace)
        return self._answer_aggregate(question, plan, trace)

    def answer_matchup_page(
        self,
        batter: str,
        bowler: str,
        phase: str = "all",
        year: int | None = None,
        venue: str | None = None,
    ) -> dict[str, QueryResponse]:
        """Execute page-selected matchup filters without asking an LLM to reinterpret them."""
        available_players = self.repository.list_player_names()
        batter_resolution = resolve_player_name(batter, available_players)
        bowler_resolution = resolve_player_name(bowler, available_players)
        batter = batter_resolution.canonical_name or next(iter(batter_resolution.suggestions), batter.strip())
        bowler = bowler_resolution.canonical_name or next(iter(bowler_resolution.suggestions), bowler.strip())
        context_filters: dict[str, object] = {}
        if phase != "all":
            context_filters["phase"] = phase
        if year is not None:
            context_filters["years"] = [year]
        if venue:
            context_filters["venue"] = venue.strip()

        context_parts = []
        if phase != "all":
            context_parts.append(f"in the {phase} overs")
        if year is not None:
            context_parts.append(f"in {year}")
        if venue:
            context_parts.append(f"at {venue.strip()}")
        context = f" {' '.join(context_parts)}" if context_parts else ""

        matchup_question = f"What is {batter}'s batting strike rate against {bowler}{context}?"
        matchup_plan = CricketQueryPlan(
            operation="matchup",
            entity="matchup",
            metric="batting_strike_rate",
            filters={**context_filters, "batter": batter.strip(), "bowler": bowler.strip()},
            sort=SortSpec(by="batting_strike_rate", direction="desc"),
        )
        matchup_trace = self._structured_trace(matchup_question, matchup_plan)

        baseline_question = f"What is {batter}'s overall ODI batting strike rate{context}?"
        baseline_plan = CricketQueryPlan(
            operation="aggregate",
            entity="batter",
            metric="batting_strike_rate",
            filters={**context_filters, "batter": batter.strip()},
            sort=SortSpec(by="batting_strike_rate", direction="desc"),
            minimum_sample=MinimumSampleSpec(balls=1),
            minimum_sample_explicit=True,
        )
        baseline_trace = self._structured_trace(baseline_question, baseline_plan)
        return {
            "matchup": self._answer_matchup(matchup_question, matchup_plan, matchup_trace),
            "baseline": self._answer_aggregate(baseline_question, baseline_plan, baseline_trace),
        }

    @staticmethod
    def _structured_trace(question: str, plan: CricketQueryPlan) -> QueryTrace:
        trace = QueryTrace(original_user_question=question)
        trace.parsed_json_plan = plan.model_dump(mode="json")
        trace.normalized_plan = plan.model_dump(mode="json")
        trace.validation_result = {"valid": True, "errors": [], "warnings": []}
        trace.operation_type = plan.operation
        trace.planner_outcome = {"parse_outcome": "structured_page_filters", "validation_outcome": "valid"}
        return trace

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
            detail = "The question was understood, but the returned data did not pass result validation."
            suggestions = result_validation.errors or ["Try a broader sample or a simpler aggregate question."]
            empty_result = any("empty" in error.lower() for error in result_validation.errors)
            has_minimum_sample = bool(
                plan.minimum_sample
                and any(
                    value is not None
                    for value in (
                        plan.minimum_sample.balls,
                        plan.minimum_sample.legal_balls,
                        plan.minimum_sample.innings,
                    )
                )
            )
            if empty_result and has_minimum_sample:
                detail = "No result met the requested minimum sample threshold in the available ODI data."
                suggestions = ["Lower the minimum sample threshold or broaden the filters."]
            elif empty_result:
                detail = "No matching ODI records were found for the requested player and filters."
                suggestions = ["Check the player name or broaden the filters."]
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail=detail,
                suggestions=suggestions,
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
                    parameters=_display_parameters(build.params),
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

    def _answer_player_compare(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = "executors.player_compare_executor.execute_player_compare"
        try:
            compare = player_compare_executor.execute_player_compare(plan, self.repository)
        except Exception as exc:  # pragma: no cover - protected integration path.
            trace.final_answer_metadata = {"status": "comparison_failed", "error": str(exc)}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The player comparison could not be executed safely.",
                suggestions=["Check that the compared players use the same role and the requested metrics are supported."],
            )

        trace.final_sql_or_method = "\n---\n".join(compare.executed_sql[:4])
        trace.result_columns = compare.columns
        missing_players = [
            str(row.get("player"))
            for row in compare.rows
            if any(
                row.get(metric) is None
                for metric in compare.metrics
                if metric != "bowling_strike_rate"
            )
        ]
        if missing_players:
            trace.final_answer_metadata = {
                "status": "comparison_no_rows",
                "players": missing_players,
                "metrics": compare.metrics,
            }
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The comparison was understood, but at least one compared player did not meet the requested sample or filters.",
                suggestions=["Lower the minimum sample threshold or use broader filters."],
            )
        tables = self._comparison_tables_for_rows(compare)
        table = tables[0]
        summary = self._comparison_summary_for_rows(compare)
        trace.final_answer_metadata = {
            "status": "supported",
            "row_count": len(compare.rows),
            "columns": compare.columns,
            "metrics": compare.metrics,
            "players": compare.players,
        }
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=self._interpretation(question, plan),
            summaries=[summary],
            tables=tables,
            metric_references=[self._metric_reference(metric) for metric in compare.metrics],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Semantic V2 player comparison",
                    description="Player comparison executed through canonical aggregate metric queries.",
                    sql=trace.final_sql_or_method or "",
                    parameters=[],
                    table=table,
                )
            ],
            evidence_notes=self._trace_notes(trace, plan),
            citations=[
                Citation(
                    label="Semantic player comparison source",
                    source_type=CitationSource.database,
                    locator="analytics.deliveries_v1",
                )
            ],
        )

    def _answer_matchup(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = "executors.matchup_executor.build_matchup_query"
        try:
            matchup_build = matchup_executor.build_matchup_query(plan)
            build = matchup_build.query
            trace.final_sql_or_method = build.sql
            rows = self.repository._fetchall(build.sql, build.params)
        except Exception as exc:  # pragma: no cover - protected integration path.
            trace.final_answer_metadata = {"status": "query_execution_failed", "error": str(exc)}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The semantic matchup query could not be executed safely.",
                suggestions=["Check the V2 query trace, matchup dimensions, metric, and supported filters."],
            )

        dict_rows = [dict(zip(build.columns, row)) for row in rows]
        trace.result_columns = build.columns
        if not dict_rows or not any(isinstance(row.get("balls"), int | float) and row["balls"] > 0 for row in dict_rows):
            trace.final_answer_metadata = {"status": "no_matchup_rows", "columns": build.columns}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The matchup was understood, but no delivery rows matched the requested filters.",
                suggestions=["Try a broader phase, style, or player matchup."],
            )

        table = self._matchup_table_for_rows(plan, matchup_build, dict_rows)
        summary = self._matchup_summary_for_rows(plan, matchup_build, dict_rows)
        visuals, visual_notes = self._matchup_pitch_visual(plan)
        metadata: dict[str, object] = {
            "status": "supported",
            "row_count": len(dict_rows),
            "columns": build.columns,
            "soft_minimum_sample": matchup_build.soft_minimum_sample,
        }
        if matchup_build.ranking_note:
            metadata["ranking_note"] = matchup_build.ranking_note
        trace.final_answer_metadata = metadata
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=self._interpretation(question, plan),
            summaries=[summary],
            tables=[table],
            visuals=visuals,
            metric_references=[self._metric_reference(plan.metric)],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Semantic V2 matchup query",
                    description=build.description,
                    sql=build.sql,
                    parameters=_display_parameters(build.params),
                    table=table,
                )
            ],
            evidence_notes=[*self._trace_notes(trace, plan), *visual_notes],
            citations=[
                Citation(
                    label="Semantic matchup source",
                    source_type=CitationSource.database,
                    locator="analytics.deliveries_v1",
                )
            ],
        )

    def _matchup_pitch_visual(
        self,
        plan: CricketQueryPlan,
    ) -> tuple[VisualPayload | None, list[EvidenceNote]]:
        batter = plan.filters.get("batter")
        bowler = plan.filters.get("bowler")
        get_pitch_map = getattr(self.repository, "get_pitch_map", None)
        if not isinstance(batter, str) or not isinstance(bowler, str) or not callable(get_pitch_map):
            return None, []

        try:
            visual_filters = {
                key: value
                for key, value in {
                    "phase": plan.filters.get("phase"),
                    "years": plan.filters.get("years"),
                    "venue": plan.filters.get("venue"),
                }.items()
                if value is not None
            }
            pitch = get_pitch_map(batter, bowler, **visual_filters)
        except Exception:  # Optional visuals must not turn a supported statistic into a failed answer.
            return None, []
        coverage = pitch.get("coverage") if isinstance(pitch, dict) else None
        cells = pitch.get("cells") if isinstance(pitch, dict) else None
        if not isinstance(coverage, dict) or not isinstance(cells, list):
            return None, []

        covered_balls = int(coverage.get("covered_balls") or 0)
        coverage_percentage = float(coverage.get("coverage_percentage") or 0)
        if (
            covered_balls < MATCHUP_PITCH_MIN_COVERED_BALLS
            or coverage_percentage < MATCHUP_PITCH_MIN_COVERAGE_PERCENTAGE
            or not cells
        ):
            return None, []

        visual = VisualPayload(
            pitch_map=PitchMapBlock(
                handedness=pitch.get("handedness"),
                coverage=VisualCoverage(**coverage),
                cells=[PitchMapCell(**cell) for cell in cells],
            )
        )
        note = EvidenceNote(
            title="Matchup pitch-map coverage",
            detail=(
                f"Line and length are available for {covered_balls} matchup balls "
                f"({coverage_percentage:.2f}% coverage)."
            ),
        )
        return visual, [note]

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
                    parameters=_display_parameters(build.params),
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

    def _answer_tactical_recommendation(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = "executors.tactical_executor.execute_tactical_recommendation"
        try:
            workup = tactical_executor.execute_tactical_recommendation(plan, self.repository)
        except ValueError:
            return self._unsupported_operation_response(question, plan, trace)
        except Exception as exc:  # pragma: no cover - protected integration path.
            trace.final_answer_metadata = {"status": "tactical_workup_failed", "error": str(exc)}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The tactical workup was understood, but the evidence probes could not be executed safely.",
                suggestions=["Try a named batter bowling-plan prompt with broader filters."],
                failure_state="data_limitation",
            )

        tables = [self._tactical_probe_table(probe) for probe in workup.probes]
        trace.final_sql_or_method = "\n---\n".join(probe.sql for probe in workup.probes)
        trace.result_columns = sorted({column for probe in workup.probes for column in probe.columns})
        trace.final_answer_metadata = {
            "status": "supported",
            "batter": workup.batter,
            "probe_count": len(workup.probes),
            "probes": [probe.title for probe in workup.probes],
        }
        checked = ", ".join(probe.title.replace(" probe", "").lower() for probe in workup.probes)
        best_probe_text = self._tactical_recommendation_sentence(workup)
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=self._interpretation(question, plan),
            summaries=[
                SummaryBlock(
                    title=f"Starter bowling plan for {workup.batter}",
                    body=(
                        f"Checked {checked} against {workup.batter}. {best_probe_text} "
                        "Use this as a database-grounded starter plan rather than a complete match strategy."
                    ),
                )
            ],
            tables=tables,
            evidence_queries=[
                EvidenceQueryBlock(
                    title=probe.title,
                    description=probe.description,
                    sql=probe.sql,
                    parameters=_display_parameters(probe.params),
                    table=table,
                )
                for probe, table in zip(workup.probes, tables, strict=True)
            ],
            evidence_notes=[
                *self._trace_notes(trace, plan),
                *[EvidenceNote(title="Tactical limitation", detail=limitation) for limitation in workup.limitations],
            ],
            citations=[
                Citation(
                    label="Semantic tactical workup source",
                    source_type=CitationSource.database,
                    locator="analytics.deliveries_v1",
                )
            ],
        )

    def _answer_match_fact(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = "semantic_service._answer_match_fact"
        years = plan.filters.get("years")
        year = int(years[0]) if isinstance(years, list) and years else None
        competition = plan.filters.get("competition")
        if year is None or not isinstance(competition, str):
            trace.final_answer_metadata = {"status": "match_fact_missing_anchor"}
            return self._unsupported_response_for_reason(
                question,
                plan,
                trace,
                "Match facts require a database-identifiable year and competition.",
            )

        match_clauses = ["TRY_CAST(year AS INTEGER) = ?", "competition = ?"]
        match_params: list[object] = [year, competition]
        order_sql = "date DESC, p_match DESC" if plan.filters.get("match_stage") == "final" else "date DESC, p_match DESC"
        match_sql = _clean_match_fact_sql(
            f"""
            SELECT p_match, date, competition, ground, winner
            FROM analytics.deliveries_v1
            WHERE {' AND '.join(match_clauses)}
            GROUP BY p_match, date, competition, ground, winner
            ORDER BY {order_sql}
            LIMIT 1
            """
        )
        match_row = self.repository._fetchone(match_sql, match_params)
        if match_row is None:
            trace.final_answer_metadata = {"status": "match_fact_no_match"}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="No matching ODI database match metadata was found for the requested fact.",
                suggestions=["Ask about a match, year, or competition present in the ODI dataset."],
            )

        match_id, date, matched_competition, ground, winner = match_row
        innings_sql = _clean_match_fact_sql(
            """
            SELECT
              team_bat AS team,
              team_bowl AS opposition,
              inns AS innings,
              MAX(TRY_CAST(inns_runs AS INTEGER)) AS runs,
              MAX(TRY_CAST(inns_wkts AS INTEGER)) AS wickets,
              COUNT(*) AS deliveries
            FROM analytics.deliveries_v1
            WHERE p_match = ?
            GROUP BY team_bat, team_bowl, inns
            ORDER BY TRY_CAST(inns AS INTEGER)
            """
        )
        innings_rows = self.repository._fetchall(innings_sql, [match_id])
        columns = ["team", "opposition", "innings", "runs", "wickets", "deliveries"]
        dict_rows = [dict(zip(columns, row)) for row in innings_rows]
        team = plan.filters.get("team")
        fact_type = plan.filters.get("fact_type")
        if isinstance(team, str):
            dict_rows = [row for row in dict_rows if row.get("team") == team]
        if not dict_rows:
            trace.final_answer_metadata = {"status": "match_fact_no_team_rows", "match_id": match_id}
            return self._insufficient_response(
                question=question,
                plan=plan,
                trace=trace,
                detail="The match was found, but the requested team fact was not present in its innings rows.",
                suggestions=["Ask for the match scorecard or another team in that database match."],
            )

        table = TableBlock(
            title="Database match fact",
            columns=["Team", "Opposition", "Innings", "Runs", "Wickets", "Deliveries"],
            rows=[[_display_value(row.get(column)) for column in columns] for row in dict_rows],
        )
        trace.final_sql_or_method = f"{match_sql}\n---\n{innings_sql}"
        trace.result_columns = columns
        trace.final_answer_metadata = {
            "status": "supported",
            "match_id": match_id,
            "date": date,
            "competition": matched_competition,
            "ground": ground,
            "winner": winner,
        }
        if fact_type == "winner":
            summary_body = (
                f"Within the ODI database, {winner} won the {year} {competition} match "
                f"recorded on {date} at {ground}."
            )
        elif isinstance(team, str) and dict_rows:
            row = dict_rows[0]
            summary_body = (
                f"Within the ODI database, {team} made {row['runs']}/{row['wickets']} "
                f"in innings {row['innings']} of the {year} {competition} match at {ground}."
            )
        else:
            summary_body = f"Within the ODI database, this match fact is grounded in the {year} {competition} scorecard."
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=self._interpretation(question, plan),
            summaries=[SummaryBlock(title="Database-backed match fact", body=summary_body)],
            tables=[table],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Match metadata lookup",
                    description="Finds the database match from year and competition metadata.",
                    sql=match_sql,
                    parameters=_display_parameters(match_params),
                    table=table,
                ),
                EvidenceQueryBlock(
                    title="Innings score lookup",
                    description="Reads innings totals from ball-by-ball innings state fields.",
                    sql=innings_sql,
                    parameters=_display_parameters([match_id]),
                    table=table,
                ),
            ],
            evidence_notes=self._trace_notes(trace, plan),
            citations=[Citation(label="ODI match fact source", source_type=CitationSource.database, locator="analytics.deliveries_v1")],
        )

    def _unsupported_operation_response(self, question: str, plan: CricketQueryPlan, trace: QueryTrace) -> QueryResponse:
        trace.selected_executor = f"executors.{plan.operation}"
        reason_by_operation = {
            "split_compare": split_compare_executor.unsupported_reason,
            "event_window": event_window_executor.unsupported_reason,
            "distribution_analysis": distribution_executor.unsupported_reason,
            "matchup": matchup_executor.unsupported_reason,
            "player_compare": player_compare_executor.unsupported_reason,
            "predictive_analysis": predictive_executor.unsupported_reason,
            "tactical_recommendation": tactical_executor.unsupported_reason,
        }
        reason = plan.unsupported_reason or reason_by_operation.get(plan.operation, lambda _: "Operation is not implemented yet.")(plan)
        return self._unsupported_response_for_reason(question, plan, trace, reason)

    def _unsupported_response_for_reason(
        self,
        question: str,
        plan: CricketQueryPlan,
        trace: QueryTrace,
        reason: str,
    ) -> QueryResponse:
        failure_state = "data_limitation" if reason.lower().startswith("data limitation:") else "unsupported_capability"
        trace.final_answer_metadata = {
            "status": "data_limitation" if failure_state == "data_limitation" else "understood_not_implemented",
            "reason": reason,
        }
        trace.log()
        title = "Data limitation" if failure_state == "data_limitation" else "Understood, not implemented"
        status = EvidenceStatus.insufficient_evidence if failure_state == "data_limitation" else EvidenceStatus.unsupported
        return QueryResponse(
            status=status,
            failure_state=failure_state,
            interpretation=self._interpretation(question, plan),
            summaries=[SummaryBlock(title=title, body=reason)],
            insufficiencies=[
                InsufficientEvidenceBlock(
                    title=title,
                    detail=reason,
                    suggestions=(
                        ["Ask for batting, bowling, matchup, or tactical evidence available in the ODI database."]
                        if failure_state == "data_limitation"
                        else ["Use an aggregate leaderboard/stat question while this operation executor is being added."]
                    ),
                )
            ],
            evidence_notes=self._trace_notes(trace, plan),
        )

    def _maybe_answer_batting_profile(self, question: str) -> QueryResponse | None:
        lowered = question.lower()
        if not self._is_batting_profile_question(lowered):
            return None
        player = self.planner._extract_player(question)
        if not player:
            return None

        shot_profile = self.repository.get_shot_type_profile(player)
        field_zones = self.repository.get_field_zone_profile(player)
        shots = list(shot_profile.get("metrics", []))
        zones = sorted(
            list(field_zones.get("zones", [])),
            key=lambda row: (int(row.get("runs") or 0), int(row.get("balls") or 0)),
            reverse=True,
        )
        if not shots and not zones:
            interpretation = QueryInterpretation(
                original_question=question,
                query_class=QueryClass.strengths_weaknesses.value,
                entities=[player],
                filters={"semantic_operation": "batting_profile", "profile_dimensions": ["field_zone", "shot_type"]},
            )
            return QueryResponse(
                status=EvidenceStatus.insufficient_evidence,
                interpretation=interpretation,
                insufficiencies=[
                    InsufficientEvidenceBlock(
                        title="Insufficient profile evidence",
                        detail=f"No shot or field-zone profile could be built for {player}.",
                        suggestions=["Try another ODI batter or ask for a broader batting summary."],
                    )
                ],
            )

        top_zone = zones[0] if zones else None
        top_shot = shots[0] if shots else None
        zone_text = (
            f"{top_zone['label']} with {top_zone['runs']} runs from {top_zone['balls']} balls"
            if top_zone
            else "no recorded field-zone leader"
        )
        shot_text = (
            f"{_shot_label(str(top_shot['shot']))} with {top_shot['runs']} runs from {top_shot['balls']} balls"
            if top_shot
            else "no recorded shot leader"
        )
        interpretation = QueryInterpretation(
            original_question=question,
            query_class=QueryClass.strengths_weaknesses.value,
            entities=[player],
            filters={
                "semantic_operation": "batting_profile",
                "semantic_metric": "runs_scored",
                "profile_dimensions": ["field_zone", "shot_type"],
                "batter": player,
            },
        )
        zone_table = TableBlock(
            title=f"{player} scoring areas",
            columns=["Area", "Balls", "Runs", "Strike Rate", "Run Share %", "Fours", "Sixes", "Dismissals"],
            rows=[
                [
                    row.get("label"),
                    row.get("balls"),
                    row.get("runs"),
                    _display_value(row.get("strike_rate")),
                    _display_value(row.get("run_share_percentage")),
                    row.get("fours"),
                    row.get("sixes"),
                    row.get("dismissals"),
                ]
                for row in zones[:8]
            ],
        )
        shot_table = TableBlock(
            title=f"{player} scoring shots",
            columns=["Shot", "Balls", "Runs", "Run Share %", "Control %", "Boundary %", "Dismissal Rate"],
            rows=[
                [
                    _shot_label(str(row.get("shot"))),
                    row.get("balls"),
                    row.get("runs"),
                    _display_value(row.get("run_share_percentage")),
                    _display_value(row.get("control_percentage")),
                    _display_value(row.get("boundary_percentage")),
                    _display_value(row.get("dismissal_rate")),
                ]
                for row in shots[:8]
            ],
        )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} scoring profile",
                    body=(
                        f"Within the available ODI dataset, {player} scores most by area through {zone_text}. "
                        f"For {player}, the top scoring shot is {shot_text}."
                    ),
                )
            ],
            tables=[zone_table, shot_table],
            charts=[
                ChartBlock(
                    title=f"{player} runs by area",
                    chart_type="bar",
                    series=[{"label": str(row.get("label")), "value": int(row.get("runs") or 0)} for row in zones[:8]],
                ),
                ChartBlock(
                    title=f"{player} runs by shot",
                    chart_type="bar",
                    series=[{"label": _shot_label(str(row.get("shot"))), "value": int(row.get("runs") or 0)} for row in shots[:8]],
                ),
            ],
            visuals=VisualPayload(
                shot_profile=ShotProfileBlock(
                    coverage=VisualCoverage(**shot_profile["coverage"]),
                    metrics=[ShotTypeMetric(**_humanized_shot_metric(row)) for row in shots],
                ),
                field_zones=FieldZoneBlock(
                    handedness=field_zones.get("handedness"),
                    coverage=VisualCoverage(**field_zones["coverage"]),
                    zones=[FieldZoneMetric(**row) for row in field_zones.get("zones", [])],
                ),
            ),
            metric_references=[self._metric_reference("runs_scored")],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Batting profile source",
                    description="Combines the batter's hand-adjusted wagon-zone profile with recorded shot labels.",
                    sql=(
                        "SELECT wagonZone, shot, SUM(batruns), COUNT(*) "
                        "FROM analytics.deliveries_v1 WHERE bat = :player AND ballfaced = 1 "
                        "GROUP BY wagonZone/shot profile dimensions"
                    ),
                    parameters=[player],
                    table=zone_table,
                )
            ],
            citations=[Citation(label="ODI batting profile source", source_type=CitationSource.database, locator="analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(title="Field-zone coverage", detail=str(field_zones["coverage"].get("detail", ""))),
                EvidenceNote(title="Shot-profile coverage", detail=str(shot_profile["coverage"].get("detail", ""))),
            ],
        )

    @staticmethod
    def _is_batting_profile_question(lowered: str) -> bool:
        asks_location = any(token in lowered for token in ("where", "area", "areas", "zone", "zones", "wagon"))
        asks_shots = any(token in lowered for token in ("shot", "shots"))
        asks_scoring = any(token in lowered for token in ("score", "scores", "scoring", "runs"))
        return asks_scoring and (asks_location or asks_shots) and (
            (asks_location and asks_shots)
            or "profile" in lowered
            or "breakdown" in lowered
        )

    def _maybe_answer_batting_position_comparison(self, question: str) -> QueryResponse | None:
        lowered = question.lower()
        position_groups = self._extract_position_groups(lowered)
        if len(position_groups) < 2:
            return None
        player = self.planner._extract_player(question)
        if not player:
            return None

        summaries: list[dict[str, object]] = []
        for group in position_groups:
            summary = self.repository.get_player_batting_position_summary(player, group["positions"])
            if summary is not None:
                summary["role_label"] = group["label"]
                summaries.append(summary)
        interpretation = QueryInterpretation(
            original_question=question,
            query_class=QueryClass.role_comparison.value,
            entities=[player],
            filters={
                "semantic_operation": "batting_position_compare",
                "semantic_metric": "runs_scored",
                "batter": player,
                "position_groups": position_groups,
            },
        )
        if len(summaries) < 2:
            return QueryResponse(
                status=EvidenceStatus.insufficient_evidence,
                interpretation=interpretation,
                insufficiencies=[
                    InsufficientEvidenceBlock(
                        title="Insufficient batting-position evidence",
                        detail=f"Not enough ODI batting-position evidence was found for {player} across the requested roles.",
                        suggestions=["Try comparing roles with larger samples, for example opening vs number 3."],
                    )
                ],
            )

        strike_rate_leader = max(summaries, key=lambda item: float(item.get("strike_rate") or 0))
        average_leader = max(summaries, key=lambda item: float(item.get("average") or 0))
        table = TableBlock(
            title="Derived batting-position metrics",
            columns=[
                "Role",
                "Positions",
                "Innings",
                "Runs",
                "Balls",
                "Dismissals",
                "Average",
                "Strike Rate",
                "Runs/Innings",
                "Boundary %",
                "Dot %",
                "Control %",
            ],
            rows=[
                [
                    summary["role_label"],
                    ", ".join(str(position) for position in summary["positions"]),
                    summary["innings"],
                    summary["runs_scored"],
                    summary["balls_faced"],
                    summary["dismissals"],
                    _display_value(summary.get("average")),
                    _display_value(summary.get("strike_rate")),
                    _display_value(summary.get("runs_per_innings")),
                    _display_value(summary.get("boundary_percentage")),
                    _display_value(summary.get("dot_percentage")),
                    _display_value(summary.get("control_percentage")),
                ]
                for summary in summaries
            ],
        )
        sample_text = "; ".join(
            f"{summary['role_label']}: {summary['innings']} innings, {summary['runs_scored']} runs/{summary['balls_faced']} balls"
            for summary in summaries
        )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player}: batting-position comparison",
                    body=(
                        f"For {player}, this derived ODI batting-order comparison uses {sample_text}. "
                        f"{strike_rate_leader['role_label']} has the higher strike rate "
                        f"({_display_value(strike_rate_leader.get('strike_rate'))}), while "
                        f"{average_leader['role_label']} has the better average "
                        f"({_display_value(average_leader.get('average'))})."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title="Strike rate by batting position",
                    chart_type="bar",
                    series=[
                        {"label": str(summary["role_label"]), "value": round(float(summary.get("strike_rate") or 0), 2)}
                        for summary in summaries
                    ],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Derived batting-position source",
                    description="Derives batting position from each batter's first recorded ball faced in an innings.",
                    sql=(
                        "WITH batter_first_balls AS (...) "
                        "SELECT batting_position_group, innings, runs, balls, dismissals "
                        "FROM analytics.deliveries_v1 JOIN batting_order USING (p_match, inns, team_bat, bat)"
                    ),
                    parameters=[player, *[str(group["positions"]) for group in position_groups]],
                    table=table,
                )
            ],
            citations=[Citation(label="ODI derived batting-position source", source_type=CitationSource.database, locator="analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Position derivation",
                    detail="Batting position is derived from first recorded ball faced in each team innings, then grouped into the requested roles.",
                )
            ],
        )

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
            failure_state="planner_uncertainty",
            interpretation=self._interpretation(question, plan),
            summaries=[
                SummaryBlock(
                    title="Invalid semantic plan",
                    body="CricAtlas was not confident enough in the semantic plan to answer from the database.",
                )
            ],
            insufficiencies=[
                InsufficientEvidenceBlock(
                    title="Planner uncertainty",
                    detail=(
                        "CricAtlas was not confident enough to produce a validated semantic plan. "
                        + ("; ".join(validation.errors) or "The semantic plan could not be validated.")
                    ),
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
        failure_state: str = "data_limitation",
    ) -> QueryResponse:
        trace.log()
        return QueryResponse(
            status=EvidenceStatus.insufficient_evidence,
            failure_state=failure_state,  # type: ignore[arg-type]
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
                **_public_object(plan.filters),
                "semantic_operation": plan.operation,
                "semantic_metric": plan.metric,
                "semantic_group_by": plan.group_by,
            }
            entities = [
                str(plan.filters[key])
                for key in ("batter", "bowler", "team")
                if isinstance(plan.filters.get(key), str)
            ]
            compare_players = plan.filters.get("compare_players")
            if isinstance(compare_players, list):
                entities.extend(str(player) for player in compare_players if isinstance(player, str))
        return QueryInterpretation(
            original_question=question,
            query_class=(
                QueryClass.strengths_weaknesses.value
                if plan and plan.question_subject == "weakness_check"
                else QueryClass.venue_context_leaderboard.value
            ),
            entities=entities,
            filters=filters,
        )

    def _trace_notes(self, trace: QueryTrace, plan: CricketQueryPlan | None) -> list[EvidenceNote]:
        notes = [
            EvidenceNote(
                title="Semantic V2 trace",
                detail=json.dumps(_public_object(trace.as_dict()), sort_keys=True, default=str)[:50000],
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
            *_metric_evidence_columns(plan.metric, plan.entity),
            "matches",
        ]
        table_rows: list[list[str | int | float | None]] = []
        for row in rows:
            table_rows.append(
                [
                    _display_dimension_value(row.get(column), column)
                    if column in dimension_columns
                    else _display_value(row.get(column))
                    for column in columns
                ]
            )
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
            subject = " / ".join(
                str(_display_dimension_value(top.get(column), column))
                for column in dimension_columns
                if top.get(column) is not None
            )
        scope = _summary_scope(plan, dimension_columns)
        context = _summary_context(plan, scope)
        metric_value = _display_value(top.get(plan.metric))
        metric_unit = METRICS[plan.metric].unit
        metric_text = f"{metric_value}%" if metric_unit == "percent" and metric_value is not None else str(metric_value)
        denominator = METRICS[plan.metric].denominator
        sample_key, sample_label = {
            "legal_balls": ("legal_balls", "legal ball"),
            "balls_faced": ("balls_faced", "ball"),
            "balls": ("balls", "ball"),
            "dismissals": ("dismissals", "dismissal"),
            "wickets": ("wickets", "wicket"),
        }.get(denominator, ("balls", "ball"))
        sample = top.get(sample_key) or top.get("balls") or top.get("legal_balls")
        plural = "" if sample == 1 else "s"
        sample_text = f" from {sample} {sample_label}{plural}" if sample else ""
        if plan.metric == "bowling_strike_rate":
            sample_text = (
                f" from {top.get('legal_balls')} legal balls and "
                f"{top.get('wickets')} bowler-credit wickets"
            )
        if plan.question_subject == "weakness_check" and dimension_columns:
            context_parts = []
            if plan.filters.get("length"):
                context_parts.append(f"{str(plan.filters['length']).replace('_', ' ').lower()} balls")
            if plan.filters.get("bowling_style"):
                context_parts.append(f"{str(plan.filters['bowling_style']).replace('_', ' ')}")
            if plan.filters.get("year_mode") == "after" and isinstance(plan.filters.get("years"), list) and plan.filters["years"]:
                context_parts.append(f"since {min(int(year) for year in plan.filters['years'])}")
            context = " ".join(context_parts) or "the requested filter"
            verdict = "This filtered metric alone is not enough to call it a weakness."
            if plan.metric == "batting_strike_rate" and isinstance(top.get(plan.metric), int | float):
                strike_rate = float(top[plan.metric])
                verdict = (
                    "On scoring rate alone, this does not look like a current struggle."
                    if strike_rate >= 100
                    else "On scoring rate alone, this does point to a possible weakness."
                )
            return SummaryBlock(
                title="Semantic weakness check",
                body=(
                    f"For {subject} on {context}, {_label(plan.metric)} is {metric_text}{sample_text}. "
                    f"{verdict} Cross-check dot-ball percentage, false-shot percentage, and dismissals before making the final call."
                ),
            )
        if len(rows) == 1 and subject != "overall":
            return SummaryBlock(
                title="Semantic aggregate answer",
                body=(
                    f"{context}{subject}'s {_label(plan.metric)} is {metric_text}{sample_text}."
                ),
            )
        return SummaryBlock(
            title="Semantic aggregate answer",
            body=(
                f"{context}{subject} ranks first for {_label(plan.metric)} at {metric_text}{sample_text}."
                + (
                    " Bowlers with no bowler-credit wickets are excluded."
                    if plan.metric == "bowling_strike_rate"
                    else ""
                )
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
    def _comparison_table_for_rows(compare: player_compare_executor.PlayerCompareResult) -> TableBlock:
        return TableBlock(
            title="Semantic player comparison",
            columns=[_label(column) for column in compare.columns],
            rows=[
                [
                    _display_dimension_value(row.get(column), "batter")
                    if column == "player"
                    else (
                        "N/A — no wickets taken"
                        if column == "bowling_strike_rate" and row.get(column) is None
                        else _display_value(row.get(column))
                    )
                    for column in compare.columns
                ]
                for row in compare.rows
            ],
        )

    @staticmethod
    def _comparison_tables_for_rows(
        compare: player_compare_executor.PlayerCompareResult,
    ) -> list[TableBlock]:
        if compare.view != "opposition":
            return [SemanticAnalyticsService._comparison_table_for_rows(compare)]

        columns = [column for column in compare.columns if column != "player"]
        return [
            TableBlock(
                title=f"{player} by opposition",
                columns=[_label(column) for column in columns],
                rows=[
                    [
                        "N/A — no wickets taken"
                        if column == "bowling_strike_rate" and row.get(column) is None
                        else _display_dimension_value(row.get(column), column)
                        for column in columns
                    ]
                    for row in compare.rows
                    if row.get("player") == player
                ],
            )
            for player in compare.players
        ]

    @staticmethod
    def _comparison_summary_for_rows(compare: player_compare_executor.PlayerCompareResult) -> SummaryBlock:
        metric_labels = ", ".join(_label(metric) for metric in compare.metrics)
        players = " and ".join(compare.players)
        if compare.view == "opposition" and len(compare.players) >= 2:
            first_player, second_player = compare.players[:2]
            first_rows = {
                str(row.get("opposition")): row
                for row in compare.rows
                if row.get("player") == first_player and row.get("opposition")
            }
            second_rows = {
                str(row.get("opposition")): row
                for row in compare.rows
                if row.get("player") == second_player and row.get("opposition")
            }
            candidates: list[tuple[float, str, str, dict[str, object], dict[str, object]]] = []
            for metric in compare.metrics:
                metric_candidates: list[
                    tuple[float, str, str, dict[str, object], dict[str, object]]
                ] = []
                for opposition in first_rows.keys() & second_rows.keys():
                    first_value = first_rows[opposition].get(metric)
                    second_value = second_rows[opposition].get(metric)
                    if not isinstance(first_value, int | float) or not isinstance(second_value, int | float):
                        continue
                    metric_candidates.append(
                        (
                            abs(float(first_value) - float(second_value)),
                            metric,
                            opposition,
                            first_rows[opposition],
                            second_rows[opposition],
                        )
                    )
                if metric_candidates:
                    candidates.append(max(metric_candidates, key=lambda item: item[0]))

            sample_column = compare.sample_columns[0]
            sample_label = sample_column.replace("_", " ")
            highlights: list[str] = []
            for gap, metric, opposition, first_row, second_row in sorted(
                candidates,
                key=lambda item: (-item[0], item[1], item[2]),
            )[:3]:
                first_value = float(first_row[metric])
                second_value = float(second_row[metric])
                direction = "higher" if first_value > second_value else "lower"
                highlights.append(
                    f"Against {opposition}, {first_player}'s {_label(metric)} "
                    f"({_display_value(first_value)} from {first_row.get(sample_column)} {sample_label}) is "
                    f"{_display_value(gap)} {direction} than {second_player}'s "
                    f"({_display_value(second_value)} from {second_row.get(sample_column)} {sample_label})"
                )
            if highlights:
                return SummaryBlock(
                    title="Semantic team-wise comparison answer",
                    body="Calculated standout differences: " + "; ".join(highlights) + ".",
                )
        return SummaryBlock(
            title="Semantic player comparison answer",
            body=(
                f"Compared {players} on {metric_labels}. "
                "The table includes the shared sample and formula inputs for verification."
            ),
        )

    @staticmethod
    def _matchup_table_for_rows(
        plan: CricketQueryPlan,
        matchup_build: matchup_executor.MatchupBuild,
        rows: list[dict[str, object]],
    ) -> TableBlock:
        balls_match_legal_balls = all(
            row.get("balls") == row.get("legal_balls") for row in rows
        )
        dot_percentages_match = all(
            row.get("dot_percentage") == row.get("bowler_dot_percentage") for row in rows
        )
        dot_columns = (
            ["bowler_dot_percentage"]
            if dot_percentages_match and plan.metric == "bowler_dot_ball_percentage"
            else ["dot_percentage"]
            if dot_percentages_match
            else ["dot_percentage", "bowler_dot_percentage"]
        )
        columns = [
            *matchup_build.dimension_columns,
            "balls",
            *([] if balls_match_legal_balls else ["legal_balls"]),
            "runs",
            "dismissals",
            "wickets",
            "strike_rate",
            *dot_columns,
            "boundary_percentage",
            "false_shot_percentage",
            "dismissal_rate",
        ]
        return TableBlock(
            title="Semantic matchup result",
            columns=[_matchup_column_label(column) for column in columns],
            rows=[[_display_value(row.get(column)) for column in columns] for row in rows],
        )

    @staticmethod
    def _matchup_summary_for_rows(
        plan: CricketQueryPlan,
        matchup_build: matchup_executor.MatchupBuild,
        rows: list[dict[str, object]],
    ) -> SummaryBlock:
        top = rows[0]
        named_batter = plan.filters.get("batter")
        named_bowler = plan.filters.get("bowler")
        if isinstance(named_batter, str) and isinstance(named_bowler, str):
            balls = top.get("balls")
            runs = top.get("runs")
            dismissals = top.get("dismissals")
            strike_rate = _display_value(top.get("strike_rate"))
            dismissal_label = "dismissal" if dismissals == 1 else "dismissals"
            sample_context = (
                f"This is a low sample of {balls} balls, so it should be treated as descriptive only."
                if top.get("low_sample")
                else f"The recorded ODI sample contains {balls} balls."
            )
            return SummaryBlock(
                title="Semantic matchup answer",
                body=(
                    f"{named_batter} scored {runs} runs from {balls} balls against {named_bowler}, "
                    f"with {dismissals} {dismissal_label} and a batting strike rate of {strike_rate}. "
                    f"{sample_context}"
                ),
            )
        subject_parts = [
            str(_display_dimension_value(top.get(column), column))
            for column in matchup_build.dimension_columns
            if top.get(column) is not None
        ]
        subject = " / ".join(subject_parts) or "the top matchup"
        sample = top.get("sample_size")
        low_sample = " low-sample flagged" if top.get("low_sample") else ""
        ranking_note = f" Ranking: {matchup_build.ranking_note}." if matchup_build.ranking_note else ""
        return SummaryBlock(
            title="Semantic matchup answer",
            body=(
                f"Within the available ODI dataset, {subject} ranks first for {_label(plan.metric)} "
                f"with {sample} balls in the matchup sample{low_sample}.{ranking_note}"
            ),
        )

    @staticmethod
    def _tactical_probe_table(probe: tactical_executor.TacticalProbe) -> TableBlock:
        columns = [
            "bucket",
            "balls",
            "runs",
            "strike_rate",
            "dot_percentage",
            "false_shot_percentage",
            "boundary_percentage",
            "dismissals",
        ]
        return TableBlock(
            title=probe.title,
            columns=[_label(column) for column in columns],
            rows=[
                [
                    _display_dimension_value(row.get(column), "field_zone" if "zone" in probe.title.lower() else None)
                    if column == "bucket"
                    else _display_value(row.get(column))
                    for column in columns
                ]
                for row in probe.rows
            ],
        )

    @staticmethod
    def _tactical_recommendation_sentence(workup: tactical_executor.TacticalWorkup) -> str:
        candidate: tuple[str, dict[str, object]] | None = None
        for probe in workup.probes:
            if not probe.rows:
                continue
            row = probe.rows[0]
            if candidate is None or float(row.get("dot_percentage") or 0) > float(candidate[1].get("dot_percentage") or 0):
                candidate = (probe.title, row)
        if candidate is None:
            return "The probes did not return enough rows to identify a preferred pressure area."
        title, row = candidate
        bucket = _display_dimension_value(
            row.get("bucket"),
            "field_zone" if "zone" in title.lower() else None,
        )
        dots = _display_value(row.get("dot_percentage"))
        false_shots = _display_value(row.get("false_shot_percentage"))
        return (
            f"The strongest pressure signal is {bucket} in the {title.replace(' probe', '').lower()} "
            f"view, with {dots}% dots and {false_shots}% false shots in the available sample."
        )

    @staticmethod
    def _metric_reference(metric: str) -> MetricReference:
        definition = METRICS[metric]
        try:
            registry_definition = get_metric(metric)
            label = registry_definition.label
        except KeyError:
            label = _label(metric)
        return MetricReference(
            metric_id=metric,
            label=label,
            formula=definition.formula,
            unit=definition.unit,
        )


def _label(value: str) -> str:
    try:
        return get_metric(value).label
    except KeyError:
        return value.replace("_", " ").title()


def _matchup_column_label(value: str) -> str:
    labels = {
        "strike_rate": "Batting Strike Rate",
        "dot_percentage": "Batter Dot Ball Percentage",
        "bowler_dot_percentage": "Bowler Dot Ball Percentage",
    }
    return labels.get(value, _label(value))


def _shot_label(value: str) -> str:
    return str(public_label(value))


def _humanized_shot_metric(row: dict[str, object]) -> dict[str, object]:
    next_row = dict(row)
    shot = next_row.get("shot")
    if isinstance(shot, str):
        next_row["shot"] = _shot_label(shot)
    return next_row


def _summary_scope(plan: CricketQueryPlan, dimension_columns: list[str]) -> str:
    for key in ("batter", "bowler", "team"):
        value = plan.filters.get(key)
        if isinstance(value, str) and key not in dimension_columns:
            return f"for {value}, "
    return ""


def _summary_context(plan: CricketQueryPlan, scope: str = "") -> str:
    contexts: list[str] = []
    if scope:
        contexts.append(scope.rstrip(" ,"))
    phase_labels = {
        "powerplay": "in powerplay overs",
        "middle": "in middle overs",
        "death": "in death overs",
    }
    phase = plan.filters.get("phase")
    if isinstance(phase, str):
        contexts.append(phase_labels.get(phase, f"in {phase.replace('_', ' ')}"))

    style = plan.filters.get("bowling_style")
    if isinstance(style, str):
        contexts.append(f"against {style.replace('_', ' ')}")

    opposition = plan.filters.get("opposition")
    if isinstance(opposition, str):
        contexts.append(f"against {opposition}")

    venue = plan.filters.get("venue")
    if isinstance(venue, str):
        contexts.append(f"at {venue}")

    length = plan.filters.get("length")
    if isinstance(length, str):
        contexts.append(f"against {length.replace('_', ' ').lower()} balls")

    if plan.minimum_sample and plan.minimum_sample_explicit:
        minimums = (
            (plan.minimum_sample.legal_balls, "legal balls"),
            (plan.minimum_sample.balls, "balls"),
            (plan.minimum_sample.innings, "innings"),
        )
        for value, label in minimums:
            if value is not None:
                contexts.append(f"with a minimum sample of {value} {label}")

    if not contexts:
        return ""
    text = ", ".join(contexts)
    return f"{text[0].upper()}{text[1:]}, "


def _metric_evidence_columns(metric: str, entity: str) -> list[str]:
    columns_by_metric = {
        "batting_strike_rate": ["runs_scored", "balls_faced"],
        "batting_average": ["runs_scored", "dismissals"],
        "bowling_average": ["runs_conceded", "wickets"],
        "bowling_strike_rate": ["legal_balls", "wickets"],
        "economy_rate": ["runs_conceded", "legal_balls"],
        "batter_dot_ball_percentage": ["dot_balls", "balls_faced"],
        "bowler_dot_ball_percentage": ["bowler_dot_balls", "legal_balls"],
        "dot_ball_percentage": ["bowler_dot_balls", "legal_balls"]
        if entity == "bowler"
        else ["dot_balls", "balls_faced"],
        "boundary_percentage": ["boundary_balls", "balls_faced"],
        "false_shot_percentage": ["false_shots", "balls_faced"],
        "wickets_taken": ["wickets", "legal_balls"],
        "wickets": ["wickets", "legal_balls"],
        "yorker_percentage": ["yorker_balls", "legal_balls"],
    }
    return columns_by_metric.get(metric, ["legal_balls" if entity == "bowler" else "balls_faced"])


def _display_dimension_value(value: object, column: str | None = None) -> str | int | float | None:
    if isinstance(value, str):
        if column in {"batter", "bowler", "team", "batting_team", "bowling_team"}:
            return value.title() if value == value.lower() else value
        if column in {"shot", "shot_type", "length", "line", "bowling_style", "bowling_type"}:
            return _shot_label(value)
        if "_" in value:
            return _shot_label(value)
    return _display_value(value)


def _display_value(value: object) -> str | int | float | None:
    return public_label(value)


def _display_parameters(params: list[object]) -> list[str | int | float | None]:
    return [_display_value(param) for param in params]


def _clean_match_fact_sql(sql: str) -> str:
    return " ".join(line.strip() for line in sql.strip().splitlines() if line.strip())


def _public_object(value: object) -> object:
    if isinstance(value, dict):
        return {key: _public_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_object(item) for item in value]
    if isinstance(value, tuple):
        return [_public_object(item) for item in value]
    if isinstance(value, str):
        return public_label(value) if value.isupper() else value
    return value
