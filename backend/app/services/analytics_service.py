from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean

from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.evidence_models import (
    ChartBlock,
    Citation,
    CitationSource,
    EvidenceNote,
    EvidenceQueryBlock,
    EvidenceStatus,
    InsufficientEvidenceBlock,
    MetricReference,
    FieldZoneBlock,
    FieldZoneMetric,
    PitchMapBlock,
    PitchMapCell,
    QueryInterpretation,
    QueryResponse,
    RadarBlock,
    RadarMetric,
    SummaryBlock,
    TableBlock,
    VisualPayload,
    VisualCoverage,
    WagonWheelBlock,
    WagonWheelPoint,
    WagonWheelSector,
    ShotProfileBlock,
    ShotTypeMetric,
)
from backend.app.domain.intent_models import AnswerShape, ContextScope, CricketIntentPlan, CricketMetric, QueryType
from backend.app.domain.metric_models import QueryClass
from backend.app.services.metric_catalog import MetricCatalog
from backend.app.services.query_router import QueryRoute, QueryRouter


def database_citation(label: str, locator: str) -> Citation:
    return Citation(label=label, source_type=CitationSource.database, locator=locator)


@dataclass(slots=True)
class AnalyticsService:
    repository: AnalyticsRepository
    metric_catalog: MetricCatalog
    router: QueryRouter = field(init=False)
    available_venues: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self.router = QueryRouter(self.repository.list_player_names())
        self.available_venues = self.repository.list_venues()

    def answer_question(self, question: str) -> QueryResponse:
        route = self.router.route(question)
        return self.answer_route(question, route)

    def answer_route(self, question: str, route: QueryRoute) -> QueryResponse:
        route = self._normalize_route_for_question(question, route)
        filters = route.filters
        if route.intent_plan is not None:
            filters = {
                **route.filters,
                "query_type": route.intent_plan.query_type.value,
                "answer_shape": route.intent_plan.answer_shape.value,
                **({"metric": route.intent_plan.metric.value} if route.intent_plan.metric else {}),
            }
        interpretation = QueryInterpretation(
            original_question=question,
            query_class=route.query_class.value,
            entities=list(route.entities),
            filters=filters,
        )
        if self._can_answer_single_metric(route.intent_plan):
            return self._handle_single_metric_intent(interpretation, route)
        handler_map = {
            QueryClass.role_comparison: self._handle_role_comparison,
            QueryClass.strengths_weaknesses: self._handle_strengths_weaknesses,
            QueryClass.head_to_head_matchup: self._handle_matchup,
            QueryClass.venue_context_leaderboard: self._handle_venue_context,
            QueryClass.trend_progression: self._handle_trend,
        }
        return handler_map[route.query_class](interpretation, route)

    @staticmethod
    def _normalize_route_for_question(question: str, route: QueryRoute) -> QueryRoute:
        filters = dict(route.filters)
        lowered = question.lower()
        field_zone = AnalyticsService._requested_field_zone(lowered)
        if field_zone and any(token in lowered for token in ("batter", "score", "scores", "scored", "runs", "run")):
            filters.update(
                {
                    "subject": "batter",
                    "skill": "batting",
                    "metric": "runs_scored",
                    "field_zone": field_zone,
                    "rank_intent": "best",
                }
            )
            return QueryRoute(
                query_class=QueryClass.venue_context_leaderboard,
                entities=route.entities,
                filters=filters,
                intent_plan=route.intent_plan,
            )
        if AnalyticsService._asks_for_bowling_style_grouping(question):
            filters["group_by"] = "bowling_style"
            if any(token in lowered for token in ("score fastest", "scores fastest", "strike rate", "score most")):
                filters["subject"] = "batter"
                filters["metric"] = "batting_strike_rate"
                filters["rank_intent"] = "best"
            return QueryRoute(
                query_class=QueryClass.venue_context_leaderboard,
                entities=route.entities,
                filters=filters,
                intent_plan=route.intent_plan,
            )
        return route

    @staticmethod
    def _requested_field_zone(lowered_question: str) -> str | None:
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
        return next(
            (
                zone
                for zone, aliases in field_zone_aliases.items()
                if any(alias in lowered_question for alias in aliases)
            ),
            None,
        )

    @staticmethod
    def _field_zone_label(field_zone: str) -> str:
        labels = {
            "midwicket": "mid-wicket",
            "third_man": "third man",
            "fine_leg": "fine leg",
            "square_leg": "square leg",
            "long_on": "long on",
            "long_off": "long off",
        }
        return labels.get(field_zone, field_zone.replace("_", " "))

    @staticmethod
    def _field_zone_wagon_detail(field_zone: str) -> str:
        details = {
            "midwicket": "right-hand batters zone 1 / left-hand batters zone 4",
            "cover": "right-hand batters zone 4 / left-hand batters zone 1",
            "point": "right-hand batters zone 5 / left-hand batters zone 8",
            "third_man": "right-hand batters zone 6 / left-hand batters zone 7",
            "fine_leg": "right-hand batters zone 7 / left-hand batters zone 6",
            "square_leg": "right-hand batters zone 8 / left-hand batters zone 5",
            "long_on": "right-hand batters zone 2 / left-hand batters zone 3",
            "long_off": "right-hand batters zone 3 / left-hand batters zone 2",
        }
        return details.get(field_zone, "hand-adjusted wagon zone")

    @staticmethod
    def _can_answer_single_metric(plan: CricketIntentPlan | None) -> bool:
        return bool(
            plan
            and plan.query_type == QueryType.single_metric
            and plan.answer_shape == AnswerShape.single_number
            and plan.metric in {
                CricketMetric.balls_bowled,
                CricketMetric.overs_bowled,
                CricketMetric.balls_faced,
                CricketMetric.runs_scored,
                CricketMetric.runs_conceded,
                CricketMetric.wickets_taken,
                CricketMetric.dot_balls,
                CricketMetric.bowler_dot_balls,
                CricketMetric.boundaries,
                CricketMetric.boundaries_conceded,
                CricketMetric.economy_rate,
                CricketMetric.batting_strike_rate,
            }
        )

    def _handle_single_metric_intent(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        plan = route.intent_plan
        if plan is None or plan.metric is None:
            return self._insufficient(
                interpretation,
                "The question did not preserve a specific metric to answer.",
                ["Ask for one explicit metric, such as balls bowled, balls faced, wickets, or runs."],
            )
        player = plan.primary_player() or (route.entities[0] if route.entities else None)
        if not player:
            return self._insufficient(
                interpretation,
                "No supported ODI player entity could be resolved from the question.",
                ["Ask with a full player name present in the ODI dataset."],
            )

        metric = plan.metric.value
        if plan.context.scope == ContextScope.single_match or plan.context.stage or plan.context.match_id:
            row = self.repository.get_player_match_metric(
                player,
                metric,
                competition=plan.context.competition,
                year=plan.context.year or (plan.context.years[0] if len(plan.context.years) == 1 else None),
                stage=plan.context.stage,
                teams=plan.context.teams,
                match_id=plan.context.match_id,
            )
            if row is None:
                return self._insufficient(
                    interpretation,
                    "No ODI match was found for the requested match context.",
                    ["Try adding both teams, the year, or a known venue to identify the match."],
                )
            return self._single_metric_match_response(interpretation, plan, row)

        if plan.metric in {CricketMetric.balls_bowled, CricketMetric.overs_bowled, CricketMetric.runs_conceded, CricketMetric.wickets_taken}:
            route = QueryRoute(
                query_class=route.query_class,
                entities=(player,),
                filters={**route.filters, "skill": "bowling", "subject": "bowler", "metric": metric},
                intent_plan=plan,
            )
            return self._handle_bowling_summary(interpretation, route)

        summary = self.repository.get_player_batting_summary(player, phase=plan.context.phase)
        if summary is None:
            return self._insufficient(
                interpretation,
                f"No ODI batting data was found for {player}.",
                ["Try another player or remove context filters to increase the sample."],
            )
        value_key = {
            CricketMetric.balls_faced: "balls_faced",
            CricketMetric.runs_scored: "runs_scored",
            CricketMetric.dot_balls: "dot_balls",
            CricketMetric.boundaries: "boundary_balls",
            CricketMetric.batting_strike_rate: "strike_rate",
        }.get(plan.metric)
        value = summary.get(value_key) if value_key else None
        body = f"{player} has {self._fmt(value)} {self._metric_unit_phrase(plan.metric)} in {self._phase_label(route.filters)}."
        table = TableBlock(
            title="Single player metric",
            columns=["Player", "Metric", "Value", "Context"],
            rows=[[player, self._metric_label(plan.metric), self._fmt(value), self._phase_label(route.filters)]],
        )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[SummaryBlock(title=f"{player} {self._metric_label(plan.metric)}", body=body)],
            tables=[table],
            metric_references=self._metric_references_for([plan.metric.value]),
            citations=[database_citation("ODI player metric", "analytics.deliveries_v1")],
            evidence_notes=[EvidenceNote(title="Intent validation", detail="The answer is constrained to the exact metric requested by the intent plan.")],
        )

    def _single_metric_match_response(
        self,
        interpretation: QueryInterpretation,
        plan: CricketIntentPlan,
        row: dict[str, object],
    ) -> QueryResponse:
        metric = plan.metric
        if metric is None:
            raise ValueError("single metric response requires a metric")
        player = str(row["player_name"])
        value = row.get("metric_value")
        context_label = self._match_context_label(plan, row)
        body = self._single_metric_sentence(player, metric, value, context_label)
        values = row.get("values") if isinstance(row.get("values"), dict) else {}
        alternate_metric = plan.ambiguity.possible_alternate_metric if plan.ambiguity else None
        if metric == CricketMetric.balls_bowled and int(value or 0) == 0 and int(values.get("balls_faced") or 0) > 0:
            alternate_metric = CricketMetric.balls_faced
        if alternate_metric:
            alternate_value = values.get(alternate_metric.value)
            if alternate_value is not None:
                if alternate_metric == CricketMetric.balls_faced:
                    body += f" If you meant balls faced while batting, he faced {self._fmt(alternate_value)} balls."
                else:
                    body += (
                        f" If you meant {self._metric_label(alternate_metric).lower()}, "
                        f"that value was {self._fmt(alternate_value)}."
                    )

        table = TableBlock(
            title="Single-match player metric",
            columns=["Player", "Metric", "Value", "Match", "Date", "Ground"],
            rows=[
                [
                    player,
                    self._metric_label(metric),
                    self._fmt(value),
                    context_label,
                    str(row.get("date") or ""),
                    str(row.get("ground") or ""),
                ]
            ],
        )
        evidence_query = EvidenceQueryBlock(
            title="Single-match metric source",
            description="Resolves the requested match context, then aggregates only the exact requested player metric.",
            sql=(
                "WITH selected_match AS (SELECT p_match FROM analytics.deliveries_v1 WHERE competition/year/team filters identify the match) "
                "SELECT requested batter and bowler aggregates FROM analytics.deliveries_v1 WHERE p_match = selected_match.p_match"
            ),
            parameters=[player, plan.context.competition, plan.context.year, plan.context.stage],
            table=table,
        )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[SummaryBlock(title=f"{player} {self._metric_label(metric)}", body=body)],
            tables=[table],
            metric_references=self._metric_references_for([metric.value]),
            evidence_queries=[evidence_query],
            citations=[database_citation("ODI single-match metric", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Intent validation",
                    detail=(
                        f"The answer targets `{metric.value}` with answer shape `single_number`; broader summaries are not used "
                        "as substitutes for the requested metric."
                    ),
                )
            ],
        )

    def _metric_references_for(self, metric_ids: list[str]) -> list[MetricReference]:
        references = []
        for metric_id in metric_ids:
            try:
                metric = self.metric_catalog.get(metric_id)
            except KeyError:
                continue
            references.append(MetricReference(metric_id=metric.metric_id, label=metric.label, formula=metric.formula, unit=metric.unit))
        return references

    @staticmethod
    def _metric_label(metric: CricketMetric) -> str:
        return {
            CricketMetric.balls_bowled: "Balls Bowled",
            CricketMetric.overs_bowled: "Overs Bowled",
            CricketMetric.balls_faced: "Balls Faced",
            CricketMetric.runs_scored: "Runs Scored",
            CricketMetric.runs_conceded: "Runs Conceded",
            CricketMetric.wickets_taken: "Wickets",
            CricketMetric.dot_balls: "Dot Balls",
            CricketMetric.bowler_dot_balls: "Bowler Dot Balls",
            CricketMetric.boundaries: "Boundaries",
            CricketMetric.boundaries_conceded: "Boundaries Conceded",
            CricketMetric.economy_rate: "Economy Rate",
            CricketMetric.batting_strike_rate: "Batting Strike Rate",
        }.get(metric, metric.value.replace("_", " ").title())

    @staticmethod
    def _metric_unit_phrase(metric: CricketMetric) -> str:
        return {
            CricketMetric.balls_bowled: "legal balls bowled",
            CricketMetric.overs_bowled: "overs bowled",
            CricketMetric.balls_faced: "balls faced",
            CricketMetric.runs_scored: "runs",
            CricketMetric.runs_conceded: "runs conceded",
            CricketMetric.wickets_taken: "wickets",
            CricketMetric.dot_balls: "dot balls",
            CricketMetric.bowler_dot_balls: "bowler dot balls",
            CricketMetric.boundaries: "boundaries",
            CricketMetric.boundaries_conceded: "boundaries conceded",
            CricketMetric.economy_rate: "runs per over",
            CricketMetric.batting_strike_rate: "strike rate",
        }.get(metric, metric.value.replace("_", " "))

    @staticmethod
    def _single_metric_sentence(player: str, metric: CricketMetric, value: object, context_label: str) -> str:
        if metric == CricketMetric.balls_bowled:
            return f"{player} bowled {AnalyticsService._fmt(value)} legal balls in {context_label}."
        if metric == CricketMetric.overs_bowled:
            return f"{player} bowled {AnalyticsService._fmt(value)} overs in {context_label}."
        if metric == CricketMetric.balls_faced:
            return f"{player} faced {AnalyticsService._fmt(value)} balls in {context_label}."
        if metric == CricketMetric.runs_scored:
            return f"{player} scored {AnalyticsService._fmt(value)} runs in {context_label}."
        if metric == CricketMetric.runs_conceded:
            return f"{player} conceded {AnalyticsService._fmt(value)} runs in {context_label}."
        if metric == CricketMetric.wickets_taken:
            return f"{player} took {AnalyticsService._fmt(value)} wickets in {context_label}."
        return f"{player}'s {AnalyticsService._metric_label(metric).lower()} was {AnalyticsService._fmt(value)} in {context_label}."

    @staticmethod
    def _match_context_label(plan: CricketIntentPlan, row: dict[str, object]) -> str:
        parts = []
        if plan.context.year:
            parts.append(str(plan.context.year))
        if plan.context.competition:
            parts.append(plan.context.competition)
        if plan.context.stage:
            parts.append(plan.context.stage)
        if not parts:
            parts.append(str(row.get("competition") or "the selected ODI match"))
        return " ".join(parts)

    def _insufficient(self, interpretation: QueryInterpretation, detail: str, suggestions: list[str]) -> QueryResponse:
        return QueryResponse(
            status=EvidenceStatus.insufficient_evidence,
            interpretation=interpretation,
            insufficiencies=[
                InsufficientEvidenceBlock(
                    title="Insufficient evidence",
                    detail=detail,
                    suggestions=suggestions,
                )
            ],
        )

    @staticmethod
    def _coverage_note(title: str, coverage: dict[str, object]) -> EvidenceNote:
        return EvidenceNote(
            title=title,
            detail=(
                f"{coverage['covered_balls']} of {coverage['total_balls']} balls "
                f"({coverage['coverage_percentage']}%) are usable. {coverage['detail']}"
            ),
        )

    def _build_radar(
        self,
        player_name: str,
        benchmark_player: str | None = None,
        phase: str | None = None,
    ) -> RadarBlock | None:
        subject_summary = self.repository.get_player_batting_summary(player_name, phase=phase)
        if subject_summary is None:
            return None
        subject_split = self.repository.get_player_split_summary(player_name, phase=phase)
        subject_dismissal_resistance = 100.0 - (
            (subject_summary["dismissals"] / subject_summary["balls_faced"]) * 100.0
        ) if subject_summary["balls_faced"] else None

        if benchmark_player:
            benchmark_summary = self.repository.get_player_batting_summary(benchmark_player, phase=phase)
            benchmark_split = self.repository.get_player_split_summary(benchmark_player, phase=phase) if benchmark_summary else None
            benchmark_label = benchmark_player
        else:
            baseline = self.repository.get_global_batting_baseline(phase=phase)
            benchmark_summary = baseline
            benchmark_split = baseline
            benchmark_label = "ODI baseline"

        if benchmark_summary is None:
            return None

        metrics: list[RadarMetric] = []
        candidates = [
            ("Strike Rate", subject_summary.get("strike_rate"), benchmark_summary.get("strike_rate")),
            ("Boundary %", subject_summary.get("boundary_percentage"), benchmark_summary.get("boundary_percentage")),
            ("Control %", subject_summary.get("control_percentage"), benchmark_summary.get("control_percentage")),
            ("Dismissal Resistance", subject_dismissal_resistance, benchmark_summary.get("dismissal_resistance")),
            ("Vs Pace SR", subject_split.get("pace_strike_rate"), benchmark_split.get("pace_strike_rate") if benchmark_split else None),
            ("Vs Spin SR", subject_split.get("spin_strike_rate"), benchmark_split.get("spin_strike_rate") if benchmark_split else None),
        ]
        for label, subject_value, benchmark_value in candidates:
            if subject_value is None or benchmark_value is None:
                continue
            metrics.append(
                RadarMetric(
                    label=label,
                    subject=round(float(subject_value), 2),
                    benchmark=round(float(benchmark_value), 2),
                )
            )
        if not metrics:
            return None
        return RadarBlock(
            subject_label=player_name,
            benchmark_label=benchmark_label,
            metrics=metrics,
        )

    def _build_batter_visuals(
        self,
        player_name: str,
        bowler_name: str | None = None,
        benchmark_player: str | None = None,
        phase: str | None = None,
    ) -> tuple[VisualPayload, list[EvidenceNote]]:
        pitch = self.repository.get_pitch_map(player_name, bowler_name, phase=phase)
        wagon = self.repository.get_wagon_wheel(player_name, bowler_name, phase=phase)
        shot_profile = self.repository.get_shot_type_profile(player_name, bowler_name, phase=phase)
        field_zones = self.repository.get_field_zone_profile(player_name, bowler_name, phase=phase)
        visuals = VisualPayload(
            pitch_map=PitchMapBlock(
                coverage=VisualCoverage(**pitch["coverage"]),
                cells=[PitchMapCell(**cell) for cell in pitch["cells"]],
            ),
            wagon_wheel=WagonWheelBlock(
                handedness=wagon["handedness"],
                coverage=VisualCoverage(**wagon["coverage"]),
                points=[WagonWheelPoint(**point) for point in wagon["points"]],
                sectors=[WagonWheelSector(**sector) for sector in wagon["sectors"]],
            ),
            shot_profile=ShotProfileBlock(
                coverage=VisualCoverage(**shot_profile["coverage"]),
                metrics=[ShotTypeMetric(**metric) for metric in shot_profile["metrics"]],
            ),
            field_zones=FieldZoneBlock(
                handedness=field_zones["handedness"],
                coverage=VisualCoverage(**field_zones["coverage"]),
                zones=[FieldZoneMetric(**zone) for zone in field_zones["zones"]],
            ),
            radar=self._build_radar(player_name, benchmark_player, phase=phase),
        )
        notes = [
            self._coverage_note("Pitch map coverage", pitch["coverage"]),
            self._coverage_note("Wagon wheel coverage", wagon["coverage"]),
            self._coverage_note("Shot profile coverage", shot_profile["coverage"]),
            self._coverage_note("Field-zone coverage", field_zones["coverage"]),
        ]
        return visuals, notes

    @staticmethod
    def _phase_label(filters: dict[str, object]) -> str:
        phase = filters.get("phase")
        if phase == "first6":
            return "first six overs"
        if phase == "powerplay":
            return "powerplay"
        if phase == "middle":
            return "middle overs"
        if phase == "death":
            return "death overs"
        return "all phases"

    def _handle_role_comparison(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if route.entities and route.filters.get("plan_type") == "bowling_to_batter":
            return self._handle_bowling_plan_against_batter(interpretation, route)
        if route.entities and route.filters.get("group_by") in {"line", "length"}:
            return self._handle_line_length_breakdown(interpretation, route)
        if not route.entities:
            return self._insufficient(
                interpretation,
                "No supported ODI player entity could be resolved from the question.",
                ["Ask with a full player name present in the ODI dataset."],
            )
        position_groups = self._position_groups(route.filters)
        if len(route.entities) == 1 and len(position_groups) >= 2:
            return self._handle_batting_position_comparison(interpretation, route, position_groups)
        if len(route.entities) == 1 and route.filters.get("group_by") == "opponent":
            return self._handle_opponent_split(interpretation, route)
        if len(route.entities) == 1 and route.filters.get("group_by") == "venue":
            return self._handle_venue_split(interpretation, route)
        if route.filters.get("skill") == "bowling":
            return self._handle_bowling_summary(interpretation, route)

        summaries = []
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        for player in route.entities[:2]:
            summary = self.repository.get_player_batting_summary(player, phase=phase)
            if summary is not None:
                summaries.append(summary)
        if not summaries:
            return self._insufficient(
                interpretation,
                f"No ODI batting data was found for {route.entities[0]}.",
                ["Try another player or use `/api/players/search` first."],
            )
        metrics = [
            self.metric_catalog.get("runs_scored"),
            self.metric_catalog.get("batting_average"),
            self.metric_catalog.get("batting_strike_rate"),
            self.metric_catalog.get("boundary_percentage"),
            self.metric_catalog.get("dot_percentage"),
            self.metric_catalog.get("control_percentage"),
        ]
        if len(summaries) == 1:
            summary = summaries[0]
            player = summary["player_name"]
            summary_blocks = [
                SummaryBlock(
                    title=f"{player} ODI batting snapshot",
                    body=(
                        f"In {phase_label}, {player} has {summary['runs_scored']} runs from {summary['balls_faced']} balls "
                        f"with a strike rate of {summary['strike_rate']:.2f}."
                    ),
                )
            ]
        else:
            strike_rate_leader = max(summaries, key=lambda item: item["strike_rate"] or 0)
            control_leader = max(summaries, key=lambda item: item["control_percentage"] or 0)
            player_names = " vs ".join(summary["player_name"] for summary in summaries)
            summary_blocks = [
                SummaryBlock(
                    title=f"{player_names} ODI comparison",
                    body=self._player_comparison_summary(summaries, phase_label, strike_rate_leader, control_leader),
                )
            ]
        benchmark_player = summaries[1]["player_name"] if len(summaries) > 1 else None
        visuals, coverage_notes = self._build_batter_visuals(
            summaries[0]["player_name"],
            benchmark_player=benchmark_player,
            phase=phase,
        )
        evidence_queries = self._player_comparison_evidence_queries(summaries)
        comparison_tables = [
            TableBlock(
                title="Primary batting metrics",
                columns=["Player", "Runs", "Balls", "Dismissals", "Average", "Strike Rate", "Boundary %", "Dot %", "Control %"],
                rows=[
                    [
                        summary["player_name"],
                        summary["runs_scored"],
                        summary["balls_faced"],
                        summary["dismissals"],
                        round(summary["average"], 2) if summary["average"] is not None else None,
                        round(summary["strike_rate"] or 0, 2),
                        round(summary["boundary_percentage"] or 0, 2),
                        round(summary["dot_percentage"] or 0, 2),
                        round(summary["control_percentage"] or 0, 2),
                    ]
                    for summary in summaries
                ],
            )
        ]
        comparison_tables.extend(query.table for query in evidence_queries[1:])
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=summary_blocks,
            tables=comparison_tables,
            charts=[
                ChartBlock(
                    title=f"Strike rate comparison ({phase_label})",
                    chart_type="bar",
                    series=[{"label": summary["player_name"], "value": round(summary["strike_rate"] or 0, 2)} for summary in summaries],
                )
            ],
            visuals=visuals,
            metric_references=[MetricReference(metric_id=m.metric_id, label=m.label, formula=m.formula, unit=m.unit) for m in metrics],
            evidence_queries=evidence_queries,
            citations=[database_citation("ODI batting summary", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(title="Interpretation basis", detail=f"This answer is derived entirely from the local ODI dataset for {phase_label}."),
                *coverage_notes,
            ],
        )

    @staticmethod
    def _summary_metric_row(summary: dict[str, object], label_key: str = "player_name") -> list[str | int | float | None]:
        return [
            str(summary[label_key]),
            int(summary["innings"]) if "innings" in summary and summary["innings"] is not None else None,
            int(summary["runs_scored"]),
            int(summary["balls_faced"]),
            int(summary["dismissals"]),
            round(float(summary["average"]), 2) if summary.get("average") is not None else None,
            round(float(summary["strike_rate"]), 2) if summary.get("strike_rate") is not None else None,
            round(float(summary["runs_per_innings"]), 2) if summary.get("runs_per_innings") is not None else None,
            round(float(summary["boundary_percentage"]), 2) if summary.get("boundary_percentage") is not None else None,
            round(float(summary["dot_percentage"]), 2) if summary.get("dot_percentage") is not None else None,
            round(float(summary["control_percentage"]), 2) if summary.get("control_percentage") is not None else None,
        ]

    @staticmethod
    def _rate_table(title: str, first_column: str, rows: list[list[str | int | float | None]]) -> TableBlock:
        return TableBlock(
            title=title,
            columns=[
                first_column,
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
            rows=rows,
        )

    @staticmethod
    def _bowling_metric_row(summary: dict[str, object]) -> list[str | int | float | None]:
        return [
            str(summary["player_name"]),
            int(summary["innings"]),
            int(summary["balls_bowled"]),
            round(float(summary["overs"]), 2) if summary.get("overs") is not None else None,
            int(summary["runs_conceded"]),
            int(summary["wickets"]),
            round(float(summary["economy_rate"]), 2) if summary.get("economy_rate") is not None else None,
            round(float(summary["bowling_average"]), 2) if summary.get("bowling_average") is not None else None,
            round(float(summary["balls_per_wicket"]), 2) if summary.get("balls_per_wicket") is not None else None,
            round(float(summary["dot_percentage"]), 2) if summary.get("dot_percentage") is not None else None,
            round(float(summary["boundary_percentage"]), 2) if summary.get("boundary_percentage") is not None else None,
            round(float(summary["balls_per_boundary"]), 2) if summary.get("balls_per_boundary") is not None else None,
            int(summary["delivery_rows"]),
        ]

    @staticmethod
    def _phase_sql_predicate(phase: object) -> str:
        if phase == "powerplay":
            return "  AND TRY_CAST(over AS DOUBLE) <= 10.0"
        if phase == "middle":
            return "  AND TRY_CAST(over AS DOUBLE) > 10.0 AND TRY_CAST(over AS DOUBLE) <= 40.0"
        if phase == "death":
            return "  AND TRY_CAST(over AS DOUBLE) > 40.0"
        return ""

    @staticmethod
    def _year_filter_label(years: list[int], year_mode: str | None) -> str:
        if not years:
            return "Across all recorded years"
        if year_mode == "after":
            return f"Since {min(years)}"
        if year_mode == "before":
            return f"Up to {max(years)}"
        if len(years) == 1:
            return f"In {years[0]}"
        return "Across " + ", ".join(str(year) for year in sorted(years))

    @staticmethod
    def _context_filter_label(years: list[int], year_mode: str | None, competition: str | None = None) -> str:
        time_label = AnalyticsService._year_filter_label(years, year_mode)
        if competition and years and year_mode not in {"after", "before"}:
            competition_lower = competition.lower()
            if all(str(year) in competition_lower for year in years):
                return f"In {competition}"
            return f"In {competition} {', '.join(str(year) for year in sorted(years))}"
        if competition:
            return f"{time_label} in {competition}"
        return time_label

    @staticmethod
    def _year_sql_predicate(years: list[int], year_mode: str | None) -> str:
        if not years:
            return ""
        if year_mode == "after":
            return "  AND TRY_CAST(year AS INTEGER) >= :year"
        if year_mode == "before":
            return "  AND TRY_CAST(year AS INTEGER) <= :year"
        return "  AND TRY_CAST(year AS INTEGER) IN (:years)"

    @staticmethod
    def _competition_sql_predicate(competition: str | None) -> str:
        return "  AND competition = :competition" if competition else ""

    def _bowling_evidence_query(self, summaries: list[dict[str, object]], phase: object) -> EvidenceQueryBlock:
        player_names = [str(summary["player_name"]) for summary in summaries]
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        sql = f"""
SELECT
  bowl AS player,
  COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bowl AS VARCHAR)) AS bowling_innings,
  SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
  COUNT(*) AS delivery_rows,
  SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
  SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
  SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
  SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
FROM analytics.deliveries_v1
WHERE bowl IN (:players)
{self._phase_sql_predicate(phase)}
GROUP BY bowl
""".strip()
        return EvidenceQueryBlock(
            title="Bowling metric source",
            description="Fetched bowling rows used for economy, wickets, dots, and boundary prevention.",
            sql=sql,
            parameters=player_names,
            table=TableBlock(
                title="Fetched bowling metrics",
                columns=[
                    "Player",
                    "Bowling Innings",
                    "Legal Balls",
                    "Overs",
                    "Runs Conceded",
                    "Wickets",
                    "Economy",
                    "Bowling Average",
                    "Balls/Wicket",
                    "Dot %",
                    "Boundary %",
                    "Balls/Boundary",
                    "Delivery Rows",
                ],
                rows=[self._bowling_metric_row(summary) for summary in summaries],
            ),
        )

    @staticmethod
    def _bowling_leaderboard_order(metric: str, rank_intent: str) -> tuple[str, str]:
        metric_expressions = {
            "economy_rate": "runs_conceded / NULLIF(legal_balls / 6.0, 0)",
            "wickets_taken": "wickets",
            "balls_per_wicket": "legal_balls / NULLIF(wickets, 0)",
            "balls_per_boundary": "legal_balls / NULLIF(boundary_balls, 0)",
        }
        expression = metric_expressions.get(metric, metric_expressions["economy_rate"])
        lower_is_better = metric in {"economy_rate", "balls_per_wicket"}
        if rank_intent == "worst":
            direction = "DESC" if lower_is_better else "ASC"
        else:
            direction = "ASC" if lower_is_better else "DESC"
        return expression, direction

    @staticmethod
    def _bowling_leaderboard_label(metric: str) -> str:
        labels = {
            "economy_rate": "economy",
            "wickets_taken": "wickets",
            "balls_per_wicket": "balls per wicket",
            "balls_per_boundary": "balls per boundary",
        }
        return labels.get(metric, "economy")

    @staticmethod
    def _bowling_rank_phrase(metric: str, rank_intent: str) -> str:
        if metric == "wickets_taken":
            return "fewest" if rank_intent == "worst" else "most"
        if metric == "economy_rate":
            return "worst" if rank_intent == "worst" else "best"
        if metric == "balls_per_wicket":
            return "worst" if rank_intent == "worst" else "best"
        if metric == "balls_per_boundary":
            return "worst" if rank_intent == "worst" else "best"
        return rank_intent

    def _bowling_metric_leaderboard_evidence_query(
        self,
        leaderboard: list[dict[str, object]],
        metric: str,
        phase: object,
        years: list[int],
        year_mode: str | None,
        competition: str | None,
        rank_intent: str,
        min_legal_balls: int,
    ) -> EvidenceQueryBlock:
        order_expression, order_direction = self._bowling_leaderboard_order(metric, rank_intent)
        tiebreak_expression = "runs_conceded / NULLIF(wickets, 0) ASC, legal_balls ASC" if metric == "wickets_taken" else "legal_balls DESC"
        metric_label = self._bowling_leaderboard_label(metric)
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        sql = f"""
WITH bowler_rows AS (
  SELECT
    bowl AS player,
    COUNT(DISTINCT p_match) AS matches,
    COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bowl AS VARCHAR)) AS bowling_innings,
    SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
    COUNT(*) AS delivery_rows,
    SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
    SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
    SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
    SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
  FROM analytics.deliveries_v1
  WHERE NULLIF(TRIM(CAST(bowl AS VARCHAR)), '') IS NOT NULL
{self._phase_sql_predicate(phase)}
{self._year_sql_predicate(years, year_mode)}
{self._competition_sql_predicate(competition)}
  GROUP BY bowl
)
SELECT *
FROM bowler_rows
WHERE legal_balls >= :min_legal_balls
ORDER BY {order_expression} {order_direction}, {tiebreak_expression}
LIMIT :limit
""".strip()
        parameters: list[str | int | float | None] = [min_legal_balls, 10]
        if years:
            parameters.append(min(years) if year_mode == "after" else max(years) if year_mode == "before" else None)
        if competition:
            parameters.append(competition)
        return EvidenceQueryBlock(
            title=f"Bowling {metric_label} leaderboard source",
            description=f"Bowler leaderboard rows ranked by {self._bowling_rank_phrase(metric, rank_intent)} {metric_label} for the selected phase and time filter.",
            sql=sql,
            parameters=parameters,
            table=TableBlock(
                title=f"Fetched bowling {metric_label} leaderboard",
                columns=[
                    "Rank",
                    "Bowler",
                    "Matches",
                    "Bowling Innings",
                    "Legal Balls",
                    "Overs",
                    "Runs Conceded",
                    "Wickets",
                    "Economy",
                    "Dot %",
                    "Boundary %",
                    "Balls/Boundary",
                    "Delivery Rows",
                ],
                rows=[
                    [
                        index + 1,
                        row["player_name"],
                        row["matches"],
                        row["innings"],
                        row["balls_bowled"],
                        round(float(row["overs"]), 2) if row.get("overs") is not None else None,
                        row["runs_conceded"],
                        row["wickets"],
                        round(float(row["economy_rate"]), 2) if row.get("economy_rate") is not None else None,
                        round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                        round(float(row["boundary_percentage"]), 2) if row.get("boundary_percentage") is not None else None,
                        round(float(row["balls_per_boundary"]), 2) if row.get("balls_per_boundary") is not None else None,
                        row["delivery_rows"],
                    ]
                    for index, row in enumerate(leaderboard)
                ],
            ),
        )

    def _handle_bowling_summary(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if route.filters.get("metric") == "best_bowling_figures":
            return self._handle_best_bowling_figures(interpretation, route)

        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        summaries: list[dict[str, object]] = []
        for player in route.entities[:2]:
            summary = self.repository.get_player_bowling_summary(player, phase=phase)
            if summary is not None:
                summaries.append(summary)
        if not summaries:
            return self._insufficient(
                interpretation,
                f"No ODI bowling data was found for {route.entities[0]}.",
                ["Try another bowler, or remove the phase filter to increase the sample."],
            )

        if len(summaries) == 1:
            summary = summaries[0]
            player = str(summary["player_name"])
            metric = str(route.filters.get("metric") or "economy_rate")
            if metric == "balls_bowled":
                summary_body = f"In {phase_label}, {player} has bowled {summary['balls_bowled']} legal balls."
            elif metric == "overs_bowled":
                summary_body = f"In {phase_label}, {player} has bowled {self._fmt(summary.get('overs'))} overs."
            elif metric == "runs_conceded":
                summary_body = f"In {phase_label}, {player} has conceded {summary['runs_conceded']} runs."
            elif metric == "wickets_taken":
                summary_body = f"In {phase_label}, {player} has {summary['wickets']} wickets."
            elif metric == "balls_per_wicket":
                summary_body = (
                    f"In {phase_label}, {player} takes a wicket every "
                    f"{self._fmt(summary.get('balls_per_wicket'))} legal balls."
                )
            elif metric == "balls_per_boundary":
                summary_body = (
                    f"In {phase_label}, {player} concedes a boundary every "
                    f"{self._fmt(summary.get('balls_per_boundary'))} legal balls."
                )
            else:
                summary_body = (
                    f"In {phase_label}, {player}'s economy is "
                    f"{self._fmt(summary.get('economy_rate'))} runs per over."
                )
            title = f"{player} ODI bowling snapshot"
        else:
            economy_leader = min(summaries, key=lambda item: item["economy_rate"] if item.get("economy_rate") is not None else 999.0)
            wicket_leader = max(summaries, key=lambda item: item["wickets"])
            player_names = " vs ".join(str(summary["player_name"]) for summary in summaries)
            sample_text = "; ".join(
                f"{summary['player_name']}: {summary['runs_conceded']} conceded from {summary['balls_bowled']} legal balls"
                for summary in summaries
            )
            summary_body = (
                f"In {phase_label}, the bowling sample is {sample_text}. "
                f"{economy_leader['player_name']} has the better economy ({self._fmt(economy_leader.get('economy_rate'))}), "
                f"while {wicket_leader['player_name']} has the larger wicket count ({wicket_leader['wickets']}). "
                "The table exposes legal balls, delivery rows, runs conceded, wickets, dots, and boundaries so every rate can be recomputed."
            )
            title = f"{player_names} ODI bowling comparison"

        evidence_query = self._bowling_evidence_query(summaries, phase)
        metrics = [
            self.metric_catalog.get("balls_bowled"),
            self.metric_catalog.get("overs_bowled"),
            self.metric_catalog.get("runs_conceded"),
            self.metric_catalog.get("economy_rate"),
            self.metric_catalog.get("wickets_taken"),
            self.metric_catalog.get("balls_per_wicket"),
            self.metric_catalog.get("bowler_dot_percentage"),
            self.metric_catalog.get("balls_per_boundary"),
        ]
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[SummaryBlock(title=title, body=summary_body)],
            tables=[evidence_query.table],
            charts=[
                ChartBlock(
                    title=f"Economy rate ({phase_label})",
                    chart_type="bar",
                    series=[
                        {"label": str(summary["player_name"]), "value": round(float(summary["economy_rate"] or 0), 2)}
                        for summary in summaries
                    ],
                )
            ],
            metric_references=[MetricReference(metric_id=m.metric_id, label=m.label, formula=m.formula, unit=m.unit) for m in metrics],
            evidence_queries=[evidence_query],
            citations=[database_citation("ODI bowling summary", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Bowling interpretation basis",
                    detail=(
                        "This answer filters on `bowl`, not `bat`. Economy uses legal balls only: rows with wides or no-balls "
                        "still count in runs conceded and delivery rows, but not in overs bowled."
                    ),
                ),
                EvidenceNote(
                    title="Wicket credit",
                    detail=(
                        "Wickets exclude run-outs and other non-bowler dismissals. Counted wicket types are caught, bowled, "
                        "leg before wicket, stumped, hit wicket, and caught and bowled."
                    ),
                ),
            ],
        )

    def _infer_player_skill(self, player: str, requested_skill: object) -> str:
        skill = str(requested_skill or "")
        if skill in {"batting", "bowling"}:
            return skill
        batting_summary = self.repository.get_player_batting_summary(player)
        bowling_summary = self.repository.get_player_bowling_summary(player)
        batting_balls = int(batting_summary.get("balls_faced") or 0) if batting_summary else 0
        bowling_balls = int(bowling_summary.get("balls_bowled") or 0) if bowling_summary else 0
        return "bowling" if bowling_balls > batting_balls else "batting"

    def _handle_opponent_split(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        player = route.entities[0]
        skill = self._infer_player_skill(player, route.filters.get("skill"))

        if skill != "bowling":
            return self._insufficient(
                interpretation.model_copy(update={"filters": {**interpretation.filters, "group_by": "opponent"}}),
                "Opponent-wise batting splits are not wired yet for this response path.",
                ["Ask the same question with bowling context, or add batting opponent splits next."],
            )

        rows = self.repository.get_player_bowling_opponent_summary(player, limit=20)
        interpretation = interpretation.model_copy(
            update={"filters": {**interpretation.filters, "group_by": "opponent", "skill": "bowling", "metric": "wickets_taken", "rank_intent": "best"}}
        )
        if not rows:
            return self._insufficient(
                interpretation,
                f"No opponent-wise ODI bowling data was found for {player}.",
                ["Try another bowler in the ODI dataset."],
            )
        leader = rows[0]
        table = TableBlock(
            title="Opponent-wise bowling performance",
            columns=[
                "Rank",
                "Opponent",
                "Matches",
                "Bowling Innings",
                "Legal Balls",
                "Overs",
                "Runs Conceded",
                "Wickets",
                "Economy",
                "Bowling Average",
                "Balls/Wicket",
                "Dot %",
                "Boundary %",
                "Balls/Boundary",
            ],
            rows=[
                [
                    index + 1,
                    row["opponent"],
                    row["matches"],
                    row["innings"],
                    row["balls_bowled"],
                    round(float(row["overs"]), 2) if row.get("overs") is not None else None,
                    row["runs_conceded"],
                    row["wickets"],
                    round(float(row["economy_rate"]), 2) if row.get("economy_rate") is not None else None,
                    round(float(row["bowling_average"]), 2) if row.get("bowling_average") is not None else None,
                    round(float(row["balls_per_wicket"]), 2) if row.get("balls_per_wicket") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["boundary_percentage"]), 2) if row.get("boundary_percentage") is not None else None,
                    round(float(row["balls_per_boundary"]), 2) if row.get("balls_per_boundary") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )
        sql = """
SELECT team_bat AS opponent,
       COUNT(DISTINCT p_match) AS matches,
       COUNT(DISTINCT p_match || ':' || inns || ':' || team_bowl) AS bowling_innings,
       SUM(CASE WHEN legal ball THEN 1 ELSE 0 END) AS legal_balls,
       SUM(bowlruns) AS runs_conceded,
       SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END) AS wickets,
       SUM(CASE WHEN legal ball AND bowlruns = 0 THEN 1 ELSE 0 END) AS dot_balls,
       SUM(CASE WHEN legal ball AND batruns IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
FROM analytics.deliveries_v1
WHERE bowl = :player
GROUP BY team_bat
ORDER BY wickets DESC, runs_conceded / NULLIF(wickets, 0) ASC, legal_balls DESC
LIMIT :limit
""".strip()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} opponent-wise bowling performance",
                    body=(
                        f"{player}'s strongest ODI opponent split by wickets is against {leader['opponent']}: "
                        f"{leader['wickets']} wickets."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title=f"{player} wickets by opponent",
                    chart_type="bar",
                    series=[{"label": str(row["opponent"]), "value": int(row["wickets"])} for row in rows[:8]],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Opponent-wise bowling source",
                    description="Groups the bowler's ODI deliveries by batting team and ranks opponents by bowler-credit wickets.",
                    sql=sql,
                    parameters=[player, 20],
                    table=table,
                )
            ],
            citations=[database_citation("Opponent-wise ODI bowling", "analytics.deliveries_v1 bowl/team_bat")],
            evidence_notes=[
                EvidenceNote(
                    title="Role inference",
                    detail="Because the question did not explicitly say batting or bowling, Atlas used the larger available batting/bowling sample for the named player.",
                ),
                EvidenceNote(
                    title="Success ordering",
                    detail="Opponent splits are sorted from most to least successful by bowler-credit wickets, then runs per wicket as a tie-breaker.",
                ),
            ],
        )

    def _handle_venue_split(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        player = route.entities[0]
        skill = self._infer_player_skill(player, route.filters.get("skill"))
        if skill == "bowling":
            return self._handle_bowling_venue_split(interpretation, route, player)
        return self._handle_batting_venue_split(interpretation, route, player)

    def _handle_batting_venue_split(self, interpretation: QueryInterpretation, route: QueryRoute, player: str) -> QueryResponse:
        rows = self.repository.get_player_batting_venue_summary(player, limit=20)
        interpretation = interpretation.model_copy(
            update={"filters": {**interpretation.filters, "group_by": "venue", "skill": "batting", "metric": "runs_scored", "rank_intent": "best"}}
        )
        if not rows:
            return self._insufficient(
                interpretation,
                f"No venue-wise ODI batting data was found for {player}.",
                ["Try another batter in the ODI dataset."],
            )
        leader = rows[0]
        table = TableBlock(
            title="Venue-wise batting performance",
            columns=[
                "Rank",
                "Venue",
                "Matches",
                "Innings",
                "Runs",
                "Balls",
                "Dismissals",
                "Average",
                "Strike Rate",
                "Boundary %",
                "Dot %",
                "Control %",
            ],
            rows=[
                [
                    index + 1,
                    row["venue"],
                    row["matches"],
                    row["innings"],
                    row["runs_scored"],
                    row["balls_faced"],
                    row["dismissals"],
                    round(float(row["average"]), 2) if row.get("average") is not None else None,
                    round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                    round(float(row["boundary_percentage"]), 2) if row.get("boundary_percentage") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["control_percentage"]), 2) if row.get("control_percentage") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )
        sql = """
SELECT ground AS venue,
       COUNT(DISTINCT p_match) AS matches,
       COUNT(DISTINCT p_match || ':' || inns || ':' || team_bat) AS innings,
       SUM(batruns) AS runs,
       COUNT(*) AS balls,
       SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
       AVG(control) AS control
FROM analytics.deliveries_v1
WHERE bat = :player
GROUP BY ground
ORDER BY runs DESC, runs / NULLIF(dismissals, 0) DESC, balls DESC
LIMIT :limit
""".strip()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} venue-wise batting performance",
                    body=(
                        f"{player}'s top ODI venue split by runs is {leader['venue']}: "
                        f"{leader['runs_scored']} runs."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title=f"{player} runs by venue",
                    chart_type="bar",
                    series=[{"label": str(row["venue"]), "value": int(row["runs_scored"])} for row in rows[:8]],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Venue-wise batting source",
                    description="Groups the batter's ODI deliveries by venue and ranks venues by runs scored.",
                    sql=sql,
                    parameters=[player, 20],
                    table=table,
                )
            ],
            citations=[database_citation("Venue-wise ODI batting", "analytics.deliveries_v1 bat/ground")],
            evidence_notes=[
                EvidenceNote(
                    title="Role inference",
                    detail="Because the question did not explicitly say batting or bowling, Atlas used the larger available batting/bowling sample for the named player.",
                ),
                EvidenceNote(
                    title="Success ordering",
                    detail="Venue batting splits are sorted by runs scored, then average as a tie-breaker.",
                ),
            ],
        )

    def _handle_bowling_venue_split(self, interpretation: QueryInterpretation, route: QueryRoute, player: str) -> QueryResponse:
        rows = self.repository.get_player_bowling_venue_summary(player, limit=20)
        interpretation = interpretation.model_copy(
            update={"filters": {**interpretation.filters, "group_by": "venue", "skill": "bowling", "metric": "wickets_taken", "rank_intent": "best"}}
        )
        if not rows:
            return self._insufficient(
                interpretation,
                f"No venue-wise ODI bowling data was found for {player}.",
                ["Try another bowler in the ODI dataset."],
            )
        leader = rows[0]
        table = TableBlock(
            title="Venue-wise bowling performance",
            columns=[
                "Rank",
                "Venue",
                "Matches",
                "Bowling Innings",
                "Legal Balls",
                "Overs",
                "Runs Conceded",
                "Wickets",
                "Economy",
                "Bowling Average",
                "Balls/Wicket",
                "Dot %",
                "Boundary %",
                "Balls/Boundary",
            ],
            rows=[
                [
                    index + 1,
                    row["venue"],
                    row["matches"],
                    row["innings"],
                    row["balls_bowled"],
                    round(float(row["overs"]), 2) if row.get("overs") is not None else None,
                    row["runs_conceded"],
                    row["wickets"],
                    round(float(row["economy_rate"]), 2) if row.get("economy_rate") is not None else None,
                    round(float(row["bowling_average"]), 2) if row.get("bowling_average") is not None else None,
                    round(float(row["balls_per_wicket"]), 2) if row.get("balls_per_wicket") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["boundary_percentage"]), 2) if row.get("boundary_percentage") is not None else None,
                    round(float(row["balls_per_boundary"]), 2) if row.get("balls_per_boundary") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )
        sql = """
SELECT ground AS venue,
       COUNT(DISTINCT p_match) AS matches,
       COUNT(DISTINCT p_match || ':' || inns || ':' || team_bowl) AS bowling_innings,
       SUM(CASE WHEN legal ball THEN 1 ELSE 0 END) AS legal_balls,
       SUM(bowlruns) AS runs_conceded,
       SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END) AS wickets
FROM analytics.deliveries_v1
WHERE bowl = :player
GROUP BY ground
ORDER BY wickets DESC, runs_conceded / NULLIF(wickets, 0) ASC, legal_balls DESC
LIMIT :limit
""".strip()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} venue-wise bowling performance",
                    body=(
                        f"{player}'s top ODI venue split by wickets is {leader['venue']}: "
                        f"{leader['wickets']} wickets."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title=f"{player} wickets by venue",
                    chart_type="bar",
                    series=[{"label": str(row["venue"]), "value": int(row["wickets"])} for row in rows[:8]],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Venue-wise bowling source",
                    description="Groups the bowler's ODI deliveries by venue and ranks venues by bowler-credit wickets.",
                    sql=sql,
                    parameters=[player, 20],
                    table=table,
                )
            ],
            citations=[database_citation("Venue-wise ODI bowling", "analytics.deliveries_v1 bowl/ground")],
            evidence_notes=[
                EvidenceNote(
                    title="Role inference",
                    detail="Because the question did not explicitly say batting or bowling, Atlas used the larger available batting/bowling sample for the named player.",
                ),
                EvidenceNote(
                    title="Success ordering",
                    detail="Venue bowling splits are sorted by bowler-credit wickets, then runs per wicket as a tie-breaker.",
                ),
            ],
        )

    def _handle_best_bowling_figures(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if not route.entities:
            return self._insufficient(
                interpretation,
                "A bowler name is required to fetch best bowling figures.",
                ["Ask with a full bowler name, for example: Tim Southee best bowling figures."],
            )
        player = route.entities[0]
        figures = self.repository.get_player_best_bowling_figures(player, limit=5)
        if not figures:
            return self._insufficient(
                interpretation,
                f"No ODI bowling figures were found for {player}.",
                ["Try another bowler in the ODI dataset."],
            )

        best = figures[0]
        figures_text = f"{best['wickets']}/{best['runs_conceded']}"
        context_bits = [str(best.get("opposition") or "").strip(), str(best.get("date") or "").strip()]
        context = ", ".join(bit for bit in context_bits if bit)
        summary_body = f"{player}'s best ODI bowling figures are {figures_text}" + (f" against {context}." if context else ".")
        sql = """
SELECT p_match,
       TRY_CAST(date AS DATE) AS match_date,
       competition,
       ground,
       team_bat AS opposition,
       inns,
       SUM(CASE WHEN legal ball THEN 1 ELSE 0 END) AS legal_balls,
       SUM(bowlruns) AS runs_conceded,
       SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END) AS wickets
FROM analytics.deliveries_v1
WHERE bowl = :player
GROUP BY p_match, match_date, competition, ground, opposition, inns
ORDER BY wickets DESC, runs_conceded ASC, legal_balls ASC
LIMIT 5
""".strip()
        table = TableBlock(
            title="Best bowling figures",
            columns=["Rank", "Figures", "Wickets", "Runs", "Overs", "Opposition", "Date", "Ground", "Competition"],
            rows=[
                [
                    index,
                    f"{row['wickets']}/{row['runs_conceded']}",
                    row["wickets"],
                    row["runs_conceded"],
                    round(float(row["balls_bowled"]) / 6.0, 2) if row.get("balls_bowled") is not None else None,
                    row.get("opposition"),
                    row.get("date"),
                    row.get("ground"),
                    row.get("competition"),
                ]
                for index, row in enumerate(figures, start=1)
            ],
        )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation.model_copy(
                update={"filters": {**interpretation.filters, "subject": "bowler", "skill": "bowling", "metric": "best_bowling_figures"}}
            ),
            summaries=[SummaryBlock(title=f"{player} best bowling figures", body=summary_body)],
            tables=[table],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Best bowling figures source",
                    description="Groups the bowler's ODI deliveries by match innings and ranks by wickets, then runs conceded.",
                    sql=sql,
                    parameters=[player],
                    table=table,
                )
            ],
            citations=[database_citation("ODI bowling figures", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Wicket credit",
                    detail="Wickets exclude run-outs and other non-bowler dismissals.",
                )
            ],
        )

    def _player_comparison_evidence_queries(self, summaries: list[dict[str, object]]) -> list[EvidenceQueryBlock]:
        player_names = [str(summary["player_name"]) for summary in summaries]
        phase_rows: list[list[str | int | float | None]] = []
        bowling_kind_rows: list[list[str | int | float | None]] = []
        all_phase_sql = """
SELECT
  bat AS player,
  COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bat AS VARCHAR)) AS innings,
  SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
  COUNT(*) AS balls,
  SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
  AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
FROM analytics.deliveries_v1
WHERE bat IN (:players)
GROUP BY bat
""".strip()
        phase_sql = """
WITH phase_rows AS (
  SELECT
    bat AS player,
    CASE
      WHEN TRY_CAST(over AS DOUBLE) <= 10.0 THEN 'Powerplay (0-10)'
      WHEN TRY_CAST(over AS DOUBLE) > 10.0 AND TRY_CAST(over AS DOUBLE) <= 40.0 THEN 'Middle overs (10-40)'
      WHEN TRY_CAST(over AS DOUBLE) > 40.0 THEN 'Death overs (40-50)'
    END AS phase,
    CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bat AS VARCHAR) AS innings_key,
    TRY_CAST(batruns AS INTEGER) AS batruns,
    LOWER(CAST(out AS VARCHAR)) = 'true' AS is_out,
    TRY_CAST(control AS DOUBLE) AS control
  FROM analytics.deliveries_v1
  WHERE bat IN (:players)
    AND TRY_CAST(over AS DOUBLE) IS NOT NULL
)
SELECT
  player,
  phase,
  COUNT(DISTINCT innings_key) AS innings,
  SUM(batruns) AS runs,
  COUNT(*) AS balls,
  SUM(CASE WHEN is_out THEN 1 ELSE 0 END) AS dismissals,
  SUM(CASE WHEN batruns IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
  SUM(CASE WHEN batruns = 0 THEN 1 ELSE 0 END) AS dot_balls,
  AVG(control) AS avg_control
FROM phase_rows
WHERE phase IS NOT NULL
GROUP BY player, phase
""".strip()
        bowling_kind_sql = """
SELECT
  bat AS player,
  CASE
    WHEN bowl_kind = 'pace bowler' THEN 'Pace'
    WHEN bowl_kind = 'spin bowler' THEN 'Spin'
  END AS bowling_type,
  COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bat AS VARCHAR)) AS innings,
  SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
  COUNT(*) AS balls,
  SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
  AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
FROM analytics.deliveries_v1
WHERE bat IN (:players)
  AND bowl_kind IN ('pace bowler', 'spin bowler')
GROUP BY bat, bowling_type
""".strip()

        for player_name in player_names:
            phase_rows.extend(
                [
                    [player_name, *self._summary_metric_row(summary, "split")]
                    for summary in self.repository.get_player_phase_summary(player_name)
                ]
            )
            bowling_kind_rows.extend(
                [
                    [player_name, *self._summary_metric_row(summary, "split")]
                    for summary in self.repository.get_player_bowling_kind_summary(player_name)
                ]
            )

        evidence_queries = [
            EvidenceQueryBlock(
                title="All-phase comparison source",
                description="Primary ODI batting comparison rows used for the headline summary.",
                sql=all_phase_sql,
                parameters=player_names,
                table=TableBlock(
                    title="Fetched all-phase rows",
                    columns=["Player", "Runs", "Balls", "Dismissals", "Average", "Strike Rate", "Boundary %", "Dot %", "Control %"],
                    rows=[
                        [
                            summary["player_name"],
                            summary["runs_scored"],
                            summary["balls_faced"],
                            summary["dismissals"],
                            round(summary["average"], 2) if summary.get("average") is not None else None,
                            round(summary["strike_rate"] or 0, 2),
                            round(summary["boundary_percentage"] or 0, 2),
                            round(summary["dot_percentage"] or 0, 2),
                            round(summary["control_percentage"] or 0, 2),
                        ]
                        for summary in summaries
                    ],
                ),
            )
        ]

        if phase_rows:
            evidence_queries.append(
                EvidenceQueryBlock(
                    title="Phase split source",
                    description="Phase-wise batting rows for powerplay, middle overs, and death overs.",
                    sql=phase_sql,
                    parameters=player_names,
                    table=TableBlock(
                        title="Fetched phase split rows",
                        columns=[
                            "Player",
                            "Phase",
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
                        rows=phase_rows,
                    ),
                )
            )

        if bowling_kind_rows:
            evidence_queries.append(
                EvidenceQueryBlock(
                    title="Pace and spin split source",
                    description="Rows split by `bowl_kind` so pace/spin performance can be checked.",
                    sql=bowling_kind_sql,
                    parameters=player_names,
                    table=TableBlock(
                        title="Fetched pace/spin split rows",
                        columns=[
                            "Player",
                            "Bowling Type",
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
                        rows=bowling_kind_rows,
                    ),
                )
            )

        return evidence_queries

    @staticmethod
    def _position_groups(filters: dict[str, object]) -> list[dict[str, object]]:
        raw_groups = filters.get("position_groups")
        if not isinstance(raw_groups, list):
            return []

        groups: list[dict[str, object]] = []
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                continue
            label = raw_group.get("label")
            positions = raw_group.get("positions")
            if not isinstance(label, str) or not isinstance(positions, list):
                continue
            normalized_positions = [
                int(position)
                for position in positions
                if isinstance(position, int) or (isinstance(position, str) and position.isdigit())
            ]
            normalized_positions = [position for position in normalized_positions if 1 <= position <= 11]
            if normalized_positions:
                groups.append({"label": label, "positions": normalized_positions})
        return groups

    @staticmethod
    def _fmt(value: object, digits: int = 2) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    @staticmethod
    def _length_label(length: object) -> str:
        labels = {
            "YORKER": "yorker",
            "FULL": "full length",
            "GOOD_LENGTH": "good length",
            "SHORT_OF_A_GOOD_LENGTH": "back of a length",
            "SHORT": "short ball",
            "FULL_TOSS": "full toss",
        }
        return labels.get(str(length), str(length).replace("_", " ").lower())

    @staticmethod
    def _line_label(line: object) -> str:
        labels = {
            "OUTSIDE_OFFSTUMP": "outside off stump",
            "WIDE_OUTSIDE_OFFSTUMP": "wide outside off stump",
            "ON_THE_STUMPS": "at the stumps",
            "DOWN_LEG": "down leg",
            "WIDE_DOWN_LEG": "wide down leg",
        }
        return labels.get(str(line), str(line).replace("_", " ").lower())

    @classmethod
    def _line_length_label(cls, cell: dict[str, object]) -> str:
        return f"{cls._length_label(cell.get('length'))}, {cls._line_label(cell.get('line'))}"

    @classmethod
    def _line_or_length_bucket_label(cls, group_by: str, bucket: object) -> str:
        if group_by == "length":
            return cls._length_label(bucket)
        if group_by == "line":
            return cls._line_label(bucket)
        return str(bucket).replace("_", " ").lower()

    @staticmethod
    def _bowling_style_label(style_code: object) -> str:
        labels = {
            "RF": "right-arm fast",
            "RFM": "right-arm fast-medium",
            "RMF": "right-arm medium-fast",
            "RM": "right-arm medium",
            "LF": "left-arm fast",
            "LFM": "left-arm fast-medium",
            "LMF": "left-arm medium-fast",
            "LM": "left-arm medium",
            "OB": "off spin",
            "SLA": "slow left-arm orthodox",
            "LBG": "legbreak googly",
            "LB": "legbreak",
            "LWS": "left-arm wrist spin",
            "OB/LB": "off spin / legbreak",
        }
        return labels.get(str(style_code), str(style_code).replace("_", " ").lower())

    @staticmethod
    def _shot_label(shot: object) -> str:
        labels = {
            "ON_DRIVE": "on drive",
            "OFF_DRIVE": "off drive",
            "COVER_DRIVE": "cover drive",
            "STRAIGHT_DRIVE": "straight drive",
            "PULL": "pull",
            "HOOK": "hook",
            "CUT_SHOT": "cut shot",
            "SQUARE_CUT": "square cut",
            "LATE_CUT": "late cut",
            "GLANCE": "glance",
            "LEG_GLANCE": "leg glance",
            "SWEEP": "sweep",
            "REVERSE_SWEEP": "reverse sweep",
            "SLOG_SWEEP": "slog sweep",
            "FLICK": "flick",
            "LOFTED_DRIVE": "lofted drive",
            "NO_SHOT": "no shot",
        }
        return labels.get(str(shot), str(shot).replace("_", " ").lower())

    def _player_comparison_summary(
        self,
        summaries: list[dict[str, object]],
        phase_label: str,
        strike_rate_leader: dict[str, object],
        control_leader: dict[str, object],
    ) -> str:
        sample_text = "; ".join(
            f"{summary['player_name']}: {summary['runs_scored']} runs from {summary['balls_faced']} balls"
            for summary in summaries
        )
        if strike_rate_leader["player_name"] == control_leader["player_name"]:
            return (
                f"In {phase_label}, the database sample is {sample_text}. "
                f"{strike_rate_leader['player_name']} is ahead on both scoring tempo "
                f"({self._fmt(strike_rate_leader.get('strike_rate'))} SR) and ball-control "
                f"({self._fmt(control_leader.get('control_percentage'))}% control). "
                "The table exposes runs, balls, dismissals, average, boundary rate, dot rate, and control rate so the read can be checked from the raw counts."
            )
        return (
            f"In {phase_label}, the database sample is {sample_text}. "
            f"{strike_rate_leader['player_name']} scores faster "
            f"({self._fmt(strike_rate_leader.get('strike_rate'))} SR), while "
            f"{control_leader['player_name']} has the stronger control rate "
            f"({self._fmt(control_leader.get('control_percentage'))}%). "
            "The table exposes runs, balls, dismissals, average, boundary rate, dot rate, and control rate so the read can be checked from the raw counts."
        )

    def _handle_batting_position_comparison(
        self,
        interpretation: QueryInterpretation,
        route: QueryRoute,
        position_groups: list[dict[str, object]],
    ) -> QueryResponse:
        player = route.entities[0]
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        summaries: list[dict[str, object]] = []
        for group in position_groups:
            summary = self.repository.get_player_batting_position_summary(
                player,
                positions=group["positions"],
                phase=phase,
            )
            if summary is not None:
                summary["role_label"] = group["label"]
                summaries.append(summary)

        if len(summaries) < 2:
            return self._insufficient(
                interpretation,
                f"The ODI dataset does not contain enough derived batting-order evidence for {player} across the requested roles.",
                ["Try comparing roles with larger samples, for example: opening vs number 3."],
            )

        strike_rate_leader = max(summaries, key=lambda item: item["strike_rate"] or 0)
        average_leader = max(summaries, key=lambda item: item["average"] or 0)
        control_leader = max(summaries, key=lambda item: item["control_percentage"] or 0)
        sample_text = "; ".join(
            f"{summary['role_label']}: {summary['innings']} innings, {summary['runs_scored']} runs/{summary['balls_faced']} balls"
            for summary in summaries
        )
        summary_body = (
            f"For {player} in {phase_label}, this derived batting-order comparison uses {sample_text}. "
            f"{strike_rate_leader['role_label']} is the faster scoring role "
            f"({self._fmt(strike_rate_leader.get('strike_rate'))} SR). "
            f"{average_leader['role_label']} has the better runs-per-dismissal profile "
            f"({self._fmt(average_leader.get('average'))} average), while "
            f"{control_leader['role_label']} has the better control rate "
            f"({self._fmt(control_leader.get('control_percentage'))}%). "
            "Treat this as a role split, not a model prediction: batting position is derived from each batter's first recorded ball faced in an innings."
        )

        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player}: batting-order role comparison",
                    body=summary_body,
                )
            ],
            tables=[
                TableBlock(
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
                            round(summary["average"], 2) if summary["average"] is not None else None,
                            round(summary["strike_rate"], 2) if summary["strike_rate"] is not None else None,
                            round(summary["runs_per_innings"], 2) if summary["runs_per_innings"] is not None else None,
                            round(summary["boundary_percentage"], 2) if summary["boundary_percentage"] is not None else None,
                            round(summary["dot_percentage"], 2) if summary["dot_percentage"] is not None else None,
                            round(summary["control_percentage"], 2) if summary["control_percentage"] is not None else None,
                        ]
                        for summary in summaries
                    ],
                )
            ],
            charts=[
                ChartBlock(
                    title=f"Strike rate by batting role ({phase_label})",
                    chart_type="bar",
                    series=[
                        {"label": summary["role_label"], "value": round(summary["strike_rate"] or 0, 2)}
                        for summary in summaries
                    ],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Derived batting-position source",
                    description="Fetched rows used for the No. 3 versus opening comparison.",
                    sql=(
                        "WITH batter_first_balls AS (SELECT p_match, inns, team_bat, bat, MIN(ball_id) AS first_ball_id "
                        "FROM analytics.deliveries_v1 GROUP BY p_match, inns, team_bat, bat), "
                        "batting_order AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY p_match, inns, team_bat "
                        "ORDER BY first_ball_id, bat) AS batting_position FROM batter_first_balls) "
                        "SELECT bat, batting_position_group, innings, runs, balls, dismissals "
                        "FROM analytics.deliveries_v1 JOIN batting_order USING (p_match, inns, team_bat, bat)"
                    ),
                    parameters=[player, *[str(group["positions"]) for group in position_groups]],
                    table=TableBlock(
                        title="Fetched batting-position rows",
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
                                round(summary["average"], 2) if summary["average"] is not None else None,
                                round(summary["strike_rate"], 2) if summary["strike_rate"] is not None else None,
                                round(summary["runs_per_innings"], 2) if summary["runs_per_innings"] is not None else None,
                                round(summary["boundary_percentage"], 2) if summary["boundary_percentage"] is not None else None,
                                round(summary["dot_percentage"], 2) if summary["dot_percentage"] is not None else None,
                                round(summary["control_percentage"], 2) if summary["control_percentage"] is not None else None,
                            ]
                            for summary in summaries
                        ],
                    ),
                )
            ],
            metric_references=[
                MetricReference(
                    metric_id="derived_batting_position",
                    label="Derived Batting Position",
                    formula="ROW_NUMBER() by first recorded ball faced within p_match + innings + batting team",
                    unit="position",
                ),
                MetricReference(
                    metric_id="batting_average",
                    label="Batting Average",
                    formula="SUM(batruns) / dismissals",
                    unit="runs per dismissal",
                ),
                MetricReference(
                    metric_id="dot_percentage",
                    label="Dot Ball Percentage",
                    formula="dot balls / balls faced * 100",
                    unit="percent",
                ),
            ],
            citations=[
                database_citation(
                    "Derived ODI batting-order split",
                    "analytics.deliveries_v1 joined to first-ball-derived batting_order",
                )
            ],
            evidence_notes=[
                EvidenceNote(
                    title="Verification basis",
                    detail=(
                        "Batting position is derived per match innings by ordering each batter's first recorded ball faced. "
                        "The table exposes the raw runs, balls, innings, and dismissals used to recompute every rate."
                    ),
                ),
                EvidenceNote(
                    title="Interpretation caution",
                    detail=(
                        "Opening is grouped as positions 1 and 2. This is not official scorecard batting order if a non-striker "
                        "appeared before facing a ball; it is the best auditable split available from this ball-by-ball feed."
                    ),
                ),
            ],
        )

    def _handle_strengths_weaknesses(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if route.entities and route.filters.get("group_by") in {"line", "length"}:
            return self._handle_line_length_breakdown(interpretation, route)
        if not route.entities:
            return self._insufficient(
                interpretation,
                "A player name is required for strengths and weaknesses analysis.",
                ["Ask with a full player name, for example: Where does Hardik Pandya score the most?"],
            )
        player = route.entities[0]
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        shot_breakdown = self.repository.get_player_shot_breakdown(player, phase=phase)
        if not shot_breakdown:
            return self._insufficient(
                interpretation,
                f"The ODI dataset does not contain enough shot-level evidence for {player}.",
                ["Try another ODI batter or use a trend question."],
            )
        top_shot = shot_breakdown[0]
        top_shot_label = self._shot_label(top_shot["shot"])
        visuals, coverage_notes = self._build_batter_visuals(player, phase=phase)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} shot profile",
                    body=f"In {phase_label}, {player}'s highest-yield recorded shot is {top_shot_label} with {top_shot['runs']} runs.",
                )
            ],
            tables=[
                TableBlock(
                    title="Top scoring shots",
                    columns=["Shot", "Balls", "Runs"],
                    rows=[[self._shot_label(item["shot"]), item["balls"], item["runs"]] for item in shot_breakdown],
                )
            ],
            charts=[
                ChartBlock(
                    title="Runs by shot",
                    chart_type="bar",
                    series=[{"label": self._shot_label(item["shot"]), "value": item["runs"]} for item in shot_breakdown[:6]],
                )
            ],
            visuals=visuals,
            citations=[database_citation("ODI shot breakdown", "analytics.deliveries_v1.shot")],
            metric_references=[
                MetricReference(
                    metric_id="shot_share_percentage",
                    label="Shot Share Percentage",
                    formula=self.metric_catalog.get("shot_share_percentage").formula,
                    unit="percent",
                )
            ],
            evidence_notes=coverage_notes,
        )

    def _handle_matchup(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if len(route.entities) < 2:
            return self._insufficient(
                interpretation,
                "A matchup requires two ODI player entities in the question.",
                ["Try: Bumrah vs Steven Smith in ODIs."],
            )
        batter_name, bowler_name = route.entities[0], route.entities[1]
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        matchup = self.repository.get_matchup_summary(batter_name, bowler_name, phase=phase)
        if matchup is None:
            return self._insufficient(
                interpretation,
                f"No direct ODI matchup was found for {batter_name} against {bowler_name}.",
                ["Try another ODI batter-versus-bowler pairing."],
            )
        visuals, coverage_notes = self._build_batter_visuals(batter_name, bowler_name, phase=phase)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{batter_name} vs {bowler_name}",
                    body=(
                        f"In {phase_label}, {batter_name} scored {matchup['runs_scored']} runs from {matchup['balls']} balls "
                        f"with {matchup['dismissals']} dismissals in the recorded ODI matchup."
                    ),
                )
            ],
            tables=[
                TableBlock(
                    title="Matchup summary",
                    columns=["Batter", "Bowler", "Balls", "Runs", "Dismissals", "Strike Rate", "Control %"],
                    rows=[[
                        matchup["batter_name"],
                        matchup["bowler_name"],
                        matchup["balls"],
                        matchup["runs_scored"],
                        matchup["dismissals"],
                        round(matchup["strike_rate"] or 0, 2),
                        round(matchup["control_percentage"] or 0, 2),
                    ]],
                )
            ],
            visuals=visuals,
            citations=[database_citation("Direct ODI matchup", "analytics.deliveries_v1 bat/bowl pairing")],
            evidence_notes=coverage_notes,
        )

    def _handle_venue_context(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if route.filters.get("external_fact") == "player_of_match":
            return self._handle_player_of_match_fact(interpretation, route)
        if route.entities and route.filters.get("group_by") in {"line", "length"}:
            return self._handle_line_length_breakdown(interpretation, route)
        if route.filters.get("skill") == "fielding" and route.filters.get("metric") == "catches_taken":
            return self._handle_fielding_catches_leaderboard(interpretation, route)

        venue_name = route.filters.get("venue_name") if isinstance(route.filters.get("venue_name"), str) else None
        if venue_name is not None and venue_name not in self.available_venues:
            venue_name = self._match_venue(venue_name.lower())
        if venue_name is None and self._has_venue_intent(interpretation.original_question):
            venue_name = self._match_venue(interpretation.original_question)

        if route.filters.get("skill") == "bowling" and route.filters.get("metric") in {
            "economy_rate",
            "wickets_taken",
            "balls_per_wicket",
            "balls_per_boundary",
        } and not route.entities and venue_name is None:
            return self._handle_bowling_metric_leaderboard(interpretation, route)
        if self._is_analyst_leaderboard(route) and venue_name is None:
            return self._handle_analyst_leaderboard(interpretation, route)

        if venue_name is None:
            return self._insufficient(
                interpretation,
                "A recognizable ODI venue is required for the current venue leaderboard response.",
                ["Try naming the ground explicitly."],
            )
        interpretation = interpretation.model_copy(
            update={"filters": {**interpretation.filters, "venue_name": venue_name}}
        )
        excluded_teams = [
            str(team)
            for team in route.filters.get("excluded_teams", [])
            if isinstance(team, str) and team.strip()
        ] if isinstance(route.filters.get("excluded_teams"), list) else []
        leaderboard = self.repository.get_venue_bowling_leaderboard(venue_name, excluded_teams=excluded_teams)
        if not leaderboard:
            return self._insufficient(
                interpretation,
                f"No venue leaderboard could be built for {venue_name}.",
                ["Try another ODI venue with more match data."],
            )
        venue_table = TableBlock(
            title="Venue bowling leaderboard",
            columns=["Bowler", "Legal Balls", "Runs Conceded", "Wickets", "Economy"],
            rows=[
                [
                    row["player_name"],
                    row["deliveries"],
                    row["runs_conceded"],
                    row["wickets"],
                    round(row["economy_rate"] or 0, 2),
                ]
                for row in leaderboard
            ],
        )
        sql_lines = [
            "SELECT bowl,",
            "       SUM(CASE WHEN legal ball THEN 1 ELSE 0 END) AS legal_balls,",
            "       SUM(bowlruns) AS runs_conceded,",
            "       SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END) AS wickets",
            "FROM analytics.deliveries_v1",
            "WHERE ground = :venue_name",
        ]
        if excluded_teams:
            sql_lines.append("  AND team_bowl NOT IN (:excluded_teams)")
        sql_lines.extend(
            [
                "GROUP BY bowl",
                "HAVING legal_balls >= :min_legal_balls",
                "ORDER BY wickets DESC, runs_conceded / NULLIF(wickets, 0) ASC, legal_balls ASC",
                "LIMIT :limit",
            ]
        )
        venue_sql = "\n".join(sql_lines)
        exclusion_label = f" excluding {', '.join(excluded_teams)}" if excluded_teams else ""
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"Top ODI bowlers at {venue_name}",
                    body=(
                        f"{leaderboard[0]['player_name']} has the most ODI wickets at {venue_name}{exclusion_label}: "
                        f"{leaderboard[0]['wickets']} wickets."
                    ),
                )
            ],
            tables=[venue_table],
            charts=[ChartBlock(title="Wickets at venue", chart_type="bar", series=[{"label": row["player_name"], "value": row["wickets"]} for row in leaderboard[:5]])],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Venue bowling leaderboard source",
                    description="Filters deliveries to the resolved ODI venue and ranks bowlers by bowler-credit wickets.",
                    sql=venue_sql,
                    parameters=[venue_name, *excluded_teams, 24, 10],
                    table=venue_table,
                )
            ],
            citations=[database_citation("Venue leaderboard", "analytics.deliveries_v1.ground")],
        )

    def _handle_player_of_match_fact(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        years = [int(year) for year in route.filters.get("years", [])] if isinstance(route.filters.get("years"), list) else []
        competition = str(route.filters.get("competition")) if route.filters.get("competition") else ""
        stage = str(route.filters.get("stage")) if route.filters.get("stage") else ""
        is_2011_world_cup_final = (
            2011 in years
            and competition == "ICC Cricket World Cup"
            and stage == "final"
        )
        if not is_2011_world_cup_final:
            return self._insufficient(
                interpretation,
                "The local ODI ball-by-ball table does not include Player-of-the-Match award metadata for this request.",
                ["Use a question answerable from deliveries, or add a complete match-awards source."],
            )

        fact_table = TableBlock(
            title="External match award",
            columns=["Match", "Date", "Venue", "Winner", "Player of the Match", "Player of the Tournament"],
            rows=[[
                "India vs Sri Lanka",
                "2011-04-02",
                "Wankhede Stadium, Mumbai",
                "India",
                "MS Dhoni",
                "Yuvraj Singh",
            ]],
        )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation.model_copy(
                update={
                    "filters": {
                        **interpretation.filters,
                        "external_fact": "player_of_match",
                        "stage": "final",
                    }
                }
            ),
            summaries=[
                SummaryBlock(
                    title="2011 World Cup final Player of the Match",
                    body="MS Dhoni was Player of the Match in the 2011 Cricket World Cup final.",
                )
            ],
            tables=[fact_table],
            citations=[
                Citation(
                    label="ESPNcricinfo scorecard",
                    source_type=CitationSource.external_web,
                    locator="https://www.espncricinfo.com/series/icc-cricket-world-cup-2010-11-381449/india-vs-sri-lanka-final-433606/full-scorecard",
                )
            ],
            evidence_notes=[
                EvidenceNote(
                    title="Source scope",
                    detail=(
                        "This is external match-award metadata. The local ball-by-ball DuckDB table does not include "
                        "Player-of-the-Match awards, so this answer is not derived from analytics.deliveries_v1."
                    ),
                )
            ],
        )

    def _handle_fielding_catches_leaderboard(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        years = [int(year) for year in route.filters.get("years", [])] if isinstance(route.filters.get("years"), list) else []
        competition = str(route.filters.get("competition")) if route.filters.get("competition") else None
        context_label = self._context_filter_label(years, str(route.filters.get("year_mode")) if route.filters.get("year_mode") else None, competition)
        coverage = self.repository.get_fielding_catches_coverage(competition=competition, years=years)

        sql = """
SELECT COUNT(*) AS caught_dismissals,
       COUNT(DISTINCT p_match) AS matches,
       COUNT(DISTINCT bat) AS dismissed_batters
FROM analytics.deliveries_v1
WHERE LOWER(CAST(dismissal AS VARCHAR)) = 'caught'
  AND competition = :competition
  AND TRY_CAST(year AS INTEGER) IN (:years)
""".strip()
        return QueryResponse(
            status=EvidenceStatus.insufficient_evidence,
            interpretation=interpretation.model_copy(
                update={"filters": {**interpretation.filters, "subject": "fielder", "skill": "fielding", "metric": "catches_taken"}}
            ),
            tables=[
                TableBlock(
                    title="Fielding catches dataset check",
                    columns=["Context", "Caught Dismissals", "Matches", "Dismissed Batters", "Catcher/Fielder Column Present"],
                    rows=[
                        [
                            context_label,
                            coverage["caught_dismissals"],
                            coverage["matches"],
                            coverage["dismissed_batters"],
                            "No",
                        ]
                    ],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Caught dismissal coverage source",
                    description="Counts caught dismissals in the selected tournament. This does not identify catchers because the dataset has no catcher/fielder column.",
                    sql=sql,
                    parameters=[competition, *years],
                    table=TableBlock(
                        title="Caught dismissal coverage",
                        columns=["Caught Dismissals", "Matches", "Dismissed Batters", "Available Dismissal Fields"],
                        rows=[
                            [
                                coverage["caught_dismissals"],
                                coverage["matches"],
                                coverage["dismissed_batters"],
                                ", ".join(str(field) for field in coverage["available_dismissal_fields"]),
                            ]
                        ],
                    ),
                )
            ],
            citations=[database_citation("ODI dismissal coverage", "analytics.deliveries_v1 dismissal/p_out")],
            insufficiencies=[
                InsufficientEvidenceBlock(
                    title="Catcher identity not available",
                    detail=(
                        f"The local dataset has {coverage['caught_dismissals']} caught dismissals for {context_label}, "
                        "but it does not include a catcher/fielder column. The `p_out` field is the dismissed batter id, so using it would rank dismissed batters, not catches taken."
                    ),
                    suggestions=[
                        "Add a complete scorecard fielding source with catcher names before asking fielder-catches leaderboards.",
                        "Until that field is ingested, answer bowling wickets or caught-dismissal counts instead of fielder catches.",
                    ],
                )
            ],
        )

    @staticmethod
    def _is_analyst_leaderboard(route: QueryRoute) -> bool:
        filters = route.filters
        if filters.get("venue_name"):
            return False
        if filters.get("subject") in {"bowler", "batter", "player"}:
            return True
        if filters.get("metric") in {
            "yorker_count",
            "yorker_percentage",
            "yorker_success_rate",
            "bowler_dot_balls",
            "boundaries_per_over",
            "false_shot_percentage",
            "batting_strike_rate",
            "batting_average",
            "boundary_percentage",
            "runs_scored",
            "dot_percentage",
            "strike_rotation_percentage",
        }:
            return True
        return False

    @staticmethod
    def _analyst_metric_label(metric: str) -> str:
        labels = {
            "yorker_count": "yorkers bowled",
            "yorker_percentage": "yorker percentage",
            "yorker_success_rate": "yorker success rate",
            "bowler_dot_balls": "dot balls",
            "bowler_dot_percentage": "dot-ball percentage",
            "wickets_taken": "wickets",
            "economy_rate": "economy",
            "boundaries_per_over": "boundaries per over",
            "balls_per_boundary": "balls per boundary",
            "false_shot_percentage": "false-shot percentage",
            "batting_strike_rate": "strike rate",
            "strike_rate_improvement_after_20": "strike-rate improvement after 20 balls",
            "milestone_vulnerability_lift": "milestone vulnerability lift",
            "batting_average": "batting average",
            "boundary_percentage": "boundary percentage",
            "runs_scored": "runs",
            "dot_percentage": "dot-ball percentage",
            "strike_rotation_percentage": "strike-rotation percentage",
        }
        return labels.get(metric, metric.replace("_", " "))

    def _handle_analyst_leaderboard(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        filters = route.filters
        subject = str(filters.get("subject") or ("bowler" if filters.get("skill") == "bowling" else "batter"))
        metric = str(filters.get("metric") or ("wickets_taken" if subject == "bowler" else "batting_strike_rate"))
        rank_intent = str(filters.get("rank_intent") or "best")
        if rank_intent not in {"best", "worst"}:
            rank_intent = "best"
        phase = filters.get("phase") if isinstance(filters.get("phase"), str) else None
        over_range = filters.get("over_range") if isinstance(filters.get("over_range"), list) else None
        metric_label = self._analyst_metric_label(metric)
        phase_label = self._phase_label({"phase": phase})
        entities = list(route.entities)

        if subject == "batter" and (metric == "strike_rate_improvement_after_20" or "split_after_balls" in filters):
            split_after_balls = int(filters.get("split_after_balls") or 20)
            metric = "strike_rate_improvement_after_20"
            metric_label = self._analyst_metric_label(metric)
            return self._handle_batting_strike_rate_split_leaderboard(
                interpretation,
                split_after_balls=split_after_balls,
                rank_intent=rank_intent,
                metric_label=metric_label,
            )

        if subject == "batter" and (metric == "milestone_vulnerability_lift" or filters.get("context_tag") == "after_milestone"):
            post_milestone_balls = int(filters.get("post_milestone_balls") or 12)
            metric = "milestone_vulnerability_lift"
            metric_label = self._analyst_metric_label(metric)
            return self._handle_milestone_vulnerability_leaderboard(
                interpretation,
                post_milestone_balls=post_milestone_balls,
                rank_intent=rank_intent,
                metric_label=metric_label,
            )

        field_zone = filters.get("field_zone") if isinstance(filters.get("field_zone"), str) else None
        if subject == "batter" and metric == "runs_scored" and field_zone:
            return self._handle_batting_field_zone_leaderboard(
                interpretation,
                field_zone=field_zone,
                rank_intent=rank_intent,
            )

        if entities and (filters.get("group_by") == "bowling_style" or self._asks_for_bowling_style_grouping(interpretation.original_question)):
            if self._asks_for_bowling_style_grouping(interpretation.original_question):
                metric = "batting_strike_rate" if "fastest" in interpretation.original_question.lower() else metric
                metric_label = self._analyst_metric_label(metric)
                rank_intent = "best"
            return self._handle_matchup_bowling_style_leaderboard(
                interpretation,
                route,
                batter_name=entities[0],
                metric=metric,
                metric_label=metric_label,
                rank_intent=rank_intent,
            )

        if entities and subject == "bowler":
            bowling_kind = filters.get("bowling_kind") if isinstance(filters.get("bowling_kind"), str) else None
            bowling_style_group = filters.get("bowling_style_group") if isinstance(filters.get("bowling_style_group"), str) else None
            length = filters.get("length") if isinstance(filters.get("length"), str) else None
            rows = self.repository.get_matchup_leaderboard(
                metric=metric,
                batter_name=entities[0],
                subject="bowler",
                rank_intent=rank_intent,
                bowling_kind=bowling_kind,
                bowling_style_group=bowling_style_group,
                length=length,
                limit=10,
                min_balls=12,
            )
            style_rows = []
            if bowling_kind or bowling_style_group:
                style_rows = self.repository.get_matchup_bowling_style_breakdown(
                    metric=metric,
                    batter_name=entities[0],
                    bowling_kind=bowling_kind,
                    bowling_style_group=bowling_style_group,
                    length=length,
                    rank_intent=rank_intent,
                    limit=10,
                    min_balls=12,
                )
            context_label = f" against {entities[0]}"
            table = self._matchup_leaderboard_table(rows, subject_label="Bowler")
            style_table = self._matchup_bowling_style_table(
                style_rows,
                title=f"{'Spin type' if bowling_kind == 'spin bowler' else 'Bowling style'} matchup against {entities[0]}",
            ) if style_rows else None
            sql = self._matchup_leaderboard_sql(metric, subject="bowler", filters=filters, player=entities[0], rank_intent=rank_intent)
            style_sql = self._matchup_bowling_style_sql(metric, filters, entities[0], rank_intent) if style_rows else None
        elif subject == "bowler":
            style_table = None
            style_sql = None
            rows = self.repository.get_analyst_bowling_leaderboard(
                metric=metric,
                phase=phase,
                over_range=[int(item) for item in over_range] if over_range else None,
                rank_intent=rank_intent,
                limit=10,
                min_legal_balls=60,
                length=filters.get("length") if isinstance(filters.get("length"), str) else None,
                line=filters.get("line") if isinstance(filters.get("line"), str) else None,
                batting_hand=filters.get("bat_hand") if isinstance(filters.get("bat_hand"), str) else None,
                bowling_kind=filters.get("bowling_kind") if isinstance(filters.get("bowling_kind"), str) else None,
                bowling_style_group=filters.get("bowling_style_group") if isinstance(filters.get("bowling_style_group"), str) else None,
            )
            context_label = f" in {phase_label}" if phase else ""
            table = self._bowling_analyst_table(rows, ranking_metric_label=metric_label)
            sql = self._bowling_analyst_sql(metric, filters, rank_intent)
        else:
            style_table = None
            style_sql = None
            if metric == "bowler_dot_balls":
                metric = "dot_percentage"
                metric_label = self._analyst_metric_label(metric)
            min_balls = 100 if metric == "dot_percentage" and not phase and not over_range else 60
            limit = 100 if metric == "dot_percentage" and not phase and not over_range else 10
            rows = self.repository.get_analyst_batting_leaderboard(
                metric=metric,
                phase=phase,
                over_range=[int(item) for item in over_range] if over_range else None,
                rank_intent=rank_intent,
                limit=limit,
                min_balls=min_balls,
                length=filters.get("length") if isinstance(filters.get("length"), str) else None,
                bowling_kind=filters.get("bowling_kind") if isinstance(filters.get("bowling_kind"), str) else None,
                bowling_style_group=filters.get("bowling_style_group") if isinstance(filters.get("bowling_style_group"), str) else None,
            )
            filter_labels = []
            if phase:
                filter_labels.append(f"in {phase_label}")
            if filters.get("bowling_kind") == "spin bowler":
                filter_labels.append("against spin")
            elif filters.get("bowling_kind") == "pace bowler":
                filter_labels.append("against pace")
            context_label = f" {' and '.join(filter_labels)}" if filter_labels else ""
            table = self._batting_analyst_table(rows, ranking_metric_label=metric_label)
            sql = self._batting_analyst_sql(metric, filters, rank_intent)

        updated_filters = {**interpretation.filters, "subject": subject, "metric": metric, "rank_intent": rank_intent}
        interpretation = interpretation.model_copy(update={"filters": updated_filters})
        if not rows:
            return self._insufficient(
                interpretation,
                f"No ODI {subject} leaderboard could be built for {metric_label}{context_label}.",
                ["Relax the filters or ask for a broader phase/sample."],
            )

        leader = rows[0]
        player_name = leader["player_name"]
        value = leader.get("metric_value")
        value_text = self._fmt(value) if isinstance(value, (int, float)) else "not available"
        if isinstance(value, (int, float)) and metric in {
            "yorker_percentage",
            "yorker_success_rate",
            "false_shot_percentage",
            "bowler_dot_percentage",
            "dot_percentage",
            "boundary_percentage",
            "strike_rotation_percentage",
        }:
            value_text = f"{value_text}%"
        lower_value_is_good = subject == "batter" and metric in {"dot_percentage"}
        if lower_value_is_good and rank_intent == "best":
            ranking_phrase = f"has the lowest {metric_label}"
        elif lower_value_is_good and rank_intent == "worst":
            ranking_phrase = f"has the highest {metric_label}"
        else:
            ranking_phrase = "ranks lowest" if rank_intent == "worst" else "leads"
        evidence_table = table
        evidence_query = EvidenceQueryBlock(
            title=f"Analyst {subject} leaderboard source",
            description=f"Rows ranked by {metric_label} with the requested filters.",
            sql=sql,
            parameters=[],
            table=evidence_table,
        )
        evidence_queries = [evidence_query]
        tables = [evidence_table]
        if style_table is not None and style_sql is not None:
            tables.append(style_table)
            evidence_queries.append(
                EvidenceQueryBlock(
                    title="Matchup bowling style source",
                    description="Aggregates the same matchup by bowling-style code so the plan shows which subtype is working.",
                    sql=style_sql,
                    parameters=[],
                    table=style_table,
                )
            )
        style_sentence = ""
        if style_table is not None and style_table.rows:
            style_sentence = f" By bowling subtype, {style_table.rows[0][1]} leads this filtered sample."
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{metric_label.title()} leaderboard",
                    body=(
                        f"{player_name} {ranking_phrase} in the local ODI {subject} leaderboard{context_label}: "
                        f"{value_text}."
                        f"{style_sentence}"
                    ),
                )
            ],
            tables=tables,
            charts=[
                ChartBlock(
                    title=f"{metric_label.title()} leaderboard",
                    chart_type="bar",
                    series=[
                        {"label": str(row["player_name"]), "value": round(float(row.get("metric_value") or 0), 2)}
                        for row in rows[:8]
                    ],
                )
            ],
            evidence_queries=evidence_queries,
            citations=[database_citation(f"ODI {subject} analyst leaderboard", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Sample threshold",
                    detail=(
                        "Global leaderboards use minimum samples to avoid ranking tiny one-off samples as leaders. "
                        "Global batter dot-avoidance leaderboards require at least 100 balls faced by default; use the table filter to raise the sample."
                    )
                    if subject == "batter" and metric == "dot_percentage" and not phase and not over_range
                    else "Global leaderboards use minimum samples to avoid ranking tiny one-off samples as leaders.",
                ),
                EvidenceNote(
                    title="Yorker success definition",
                    detail="Yorker success rate counts yorkers that produce a dot, a bowler-credit wicket, or an uncontrolled shot.",
                ),
            ],
        )

    def _handle_batting_field_zone_leaderboard(
        self,
        interpretation: QueryInterpretation,
        *,
        field_zone: str,
        rank_intent: str,
    ) -> QueryResponse:
        zone_label = self._field_zone_label(field_zone)
        rows = self.repository.get_batting_field_zone_leaderboard(
            field_zone=field_zone,
            limit=50,
            min_balls=20,
        )
        if rank_intent == "worst":
            rows = sorted(rows, key=lambda row: (float(row.get("metric_value") or 0), -int(row.get("balls") or 0)))
        updated_filters = {
            **interpretation.filters,
            "subject": "batter",
            "skill": "batting",
            "metric": "runs_scored",
            "field_zone": field_zone,
            "rank_intent": rank_intent,
        }
        interpretation = interpretation.model_copy(update={"filters": updated_filters})
        if not rows:
            return self._insufficient(
                interpretation,
                f"No ODI batting field-zone leaderboard could be built for {zone_label}.",
                ["Ask for a broader fielding zone or lower the sample requirement."],
            )

        leader = rows[0]
        table = self._batting_field_zone_table(rows, zone_label)
        value_text = self._fmt(leader.get("metric_value"))
        sql = self._batting_field_zone_sql(field_zone, rank_intent)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"Runs through {zone_label}",
                    body=(
                        f"{leader['player_name']} has the most recorded ODI runs through {zone_label}: "
                        f"{value_text} from {leader.get('balls')} balls."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title=f"Runs through {zone_label}",
                    chart_type="bar",
                    series=[
                        {"label": str(row["player_name"]), "value": round(float(row.get("metric_value") or 0), 2)}
                        for row in rows[:8]
                    ],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Batting field-zone leaderboard source",
                    description=f"Ranks batters by runs scored into the hand-adjusted {zone_label} wagon zone.",
                    sql=sql,
                    parameters=[],
                    table=table,
                )
            ],
            citations=[database_citation("ODI batting field-zone leaderboard", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Metric definition",
                    detail=(
                        f"Runs through {zone_label} = batter runs on legal batter balls whose wagonZone maps to "
                        f"{zone_label} after adjusting for batting hand."
                    ),
                ),
                EvidenceNote(
                    title="Zone mapping",
                    detail=f"{zone_label.title()} uses {self._field_zone_wagon_detail(field_zone)}.",
                ),
                EvidenceNote(
                    title="Sample threshold",
                    detail="This leaderboard requires at least 20 recorded balls into the selected field zone.",
                ),
            ],
        )

    def _handle_batting_strike_rate_split_leaderboard(
        self,
        interpretation: QueryInterpretation,
        *,
        split_after_balls: int,
        rank_intent: str,
        metric_label: str,
    ) -> QueryResponse:
        rows = self.repository.get_batting_strike_rate_split_leaderboard(
            split_after_balls=split_after_balls,
            rank_intent=rank_intent,
            limit=10,
            min_first_balls=200,
            min_after_balls=120,
        )
        updated_filters = {
            **interpretation.filters,
            "subject": "batter",
            "metric": "strike_rate_improvement_after_20",
            "split_after_balls": split_after_balls,
            "rank_intent": rank_intent,
        }
        interpretation = interpretation.model_copy(update={"filters": updated_filters})
        if not rows:
            return self._insufficient(
                interpretation,
                f"No ODI batting leaderboard could be built for {metric_label}.",
                ["Ask for a broader sample or lower the split/sample requirement."],
            )

        leader = rows[0]
        value_text = self._fmt(leader.get("metric_value"))
        table = self._batting_strike_rate_split_table(rows, split_after_balls)
        ranking_verb = "drops least" if rank_intent == "worst" else "improves most"
        sql = self._batting_strike_rate_split_sql(split_after_balls, rank_intent)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"Strike-rate change after {split_after_balls} balls",
                    body=(
                        f"{leader['player_name']} {ranking_verb} after reaching {split_after_balls} balls: "
                        f"{value_text} strike-rate points "
                        f"({self._fmt(leader.get('first_strike_rate'))} before/through ball {split_after_balls}, "
                        f"{self._fmt(leader.get('after_strike_rate'))} after ball {split_after_balls})."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title=f"Strike-rate change after {split_after_balls} balls",
                    chart_type="bar",
                    series=[
                        {"label": str(row["player_name"]), "value": round(float(row.get("metric_value") or 0), 2)}
                        for row in rows[:8]
                    ],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Batting strike-rate split source",
                    description=(
                        f"Compares each batter's aggregate strike rate on balls 1-{split_after_balls} "
                        f"with their aggregate strike rate after ball {split_after_balls}."
                    ),
                    sql=sql,
                    parameters=[],
                    table=table,
                )
            ],
            citations=[database_citation("ODI batting strike-rate split", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Metric definition",
                    detail=(
                        f"SR Change = strike rate after ball {split_after_balls} minus strike rate from balls 1-{split_after_balls}. "
                        "Positive values mean the batter accelerates after getting set."
                    ),
                ),
                EvidenceNote(
                    title="Sample threshold",
                    detail=(
                        f"This leaderboard requires at least 200 balls in the first-{split_after_balls} segment "
                        f"and at least 120 balls after ball {split_after_balls}."
                    ),
                ),
            ],
        )

    def _handle_milestone_vulnerability_leaderboard(
        self,
        interpretation: QueryInterpretation,
        *,
        post_milestone_balls: int,
        rank_intent: str,
        metric_label: str,
    ) -> QueryResponse:
        rows = self.repository.get_milestone_vulnerability_leaderboard(
            post_milestone_balls=post_milestone_balls,
            rank_intent=rank_intent,
            limit=10,
            min_milestones=5,
            min_post_balls=24,
            min_baseline_balls=60,
        )
        updated_filters = {
            **interpretation.filters,
            "subject": "batter",
            "metric": "milestone_vulnerability_lift",
            "context_tag": "after_milestone",
            "post_milestone_balls": post_milestone_balls,
            "rank_intent": rank_intent,
        }
        interpretation = interpretation.model_copy(update={"filters": updated_filters})
        if not rows:
            return self._insufficient(
                interpretation,
                f"No ODI batting leaderboard could be built for {metric_label}.",
                ["Ask for a broader milestone window or lower the sample requirement."],
            )

        leader = rows[0]
        table = self._milestone_vulnerability_table(rows)
        value_text = self._fmt(leader.get("metric_value"))
        ranking_verb = "is least vulnerable" if rank_intent == "worst" else "is most vulnerable"
        sql = self._milestone_vulnerability_sql(post_milestone_balls, rank_intent)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title="Post-milestone vulnerability",
                    body=(
                        f"{leader['player_name']} {ranking_verb} immediately after milestones: "
                        f"+{value_text} percentage points versus their normal set-batter dismissal rate "
                        f"({self._fmt(leader.get('post_dismissal_percentage'))}% post-milestone, "
                        f"{self._fmt(leader.get('baseline_dismissal_percentage'))}% baseline)."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title="Milestone vulnerability lift",
                    chart_type="bar",
                    series=[
                        {"label": str(row["player_name"]), "value": round(float(row.get("metric_value") or 0), 2)}
                        for row in rows[:8]
                    ],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Milestone vulnerability source",
                    description=(
                        "Finds innings where a batter reaches 50 or 100, measures the next "
                        f"{post_milestone_balls} legal balls, then compares that dismissal rate with normal set-batter balls."
                    ),
                    sql=sql,
                    parameters=[],
                    table=table,
                )
            ],
            citations=[database_citation("ODI milestone vulnerability", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Metric definition",
                    detail=(
                        "Vulnerability Lift = post-milestone dismissal % minus normal set-batter dismissal %. "
                        f"Milestones are 50 and 100; post-milestone means the next {post_milestone_balls} legal balls."
                    ),
                ),
                EvidenceNote(
                    title="Baseline definition",
                    detail=(
                        "Normal set-batter baseline uses balls after the batter has faced 20 balls, excluding balls already counted "
                        "inside post-milestone windows."
                    ),
                ),
                EvidenceNote(
                    title="Sample threshold",
                    detail="This leaderboard requires at least 5 milestone events, 24 post-milestone balls, and 60 baseline set-batter balls.",
                ),
            ],
        )

    @staticmethod
    def _asks_for_bowling_style_grouping(question: str) -> bool:
        lowered = question.lower()
        return any(
            token in lowered
            for token in ("bowling type", "bowling types", "bowling style", "bowling styles", "type of bowling")
        )

    def _handle_matchup_bowling_style_leaderboard(
        self,
        interpretation: QueryInterpretation,
        route: QueryRoute,
        *,
        batter_name: str,
        metric: str,
        metric_label: str,
        rank_intent: str,
    ) -> QueryResponse:
        filters = route.filters
        bowling_kind = filters.get("bowling_kind") if isinstance(filters.get("bowling_kind"), str) else None
        bowling_style_group = filters.get("bowling_style_group") if isinstance(filters.get("bowling_style_group"), str) else None
        length = filters.get("length") if isinstance(filters.get("length"), str) else None
        rows = self.repository.get_matchup_bowling_style_breakdown(
            metric=metric,
            batter_name=batter_name,
            bowling_kind=bowling_kind,
            bowling_style_group=bowling_style_group,
            length=length,
            rank_intent=rank_intent,
            limit=10,
            min_balls=12,
        )
        updated_filters = {**interpretation.filters, "group_by": "bowling_style", "subject": "batter", "metric": metric, "rank_intent": rank_intent}
        interpretation = interpretation.model_copy(update={"filters": updated_filters})
        if not rows:
            return self._insufficient(
                interpretation,
                f"No ODI bowling-style matchup breakdown could be built for {batter_name}.",
                ["Ask for a broader bowling type/style sample or another batter."],
            )

        table = self._matchup_bowling_style_table(rows, title=f"Bowling style matchup against {batter_name}")
        leader = rows[0]
        style_name = self._bowling_style_label(leader.get("bowling_style"))
        value_text = self._fmt(leader.get("metric_value"))
        ranking_verb = "is lowest" if rank_intent == "worst" else "is highest"
        sql = self._matchup_bowling_style_sql(metric, filters, batter_name, rank_intent)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{batter_name} by bowling style",
                    body=(
                        f"Against {batter_name}, {style_name} {ranking_verb} by {metric_label}: {value_text}. "
                        "This is grouped by bowling style, not by individual bowler."
                    ),
                )
            ],
            tables=[table],
            charts=[
                ChartBlock(
                    title=f"{metric_label.title()} by bowling style",
                    chart_type="bar",
                    series=[
                        {"label": self._bowling_style_label(row.get("bowling_style")), "value": round(float(row.get("metric_value") or 0), 2)}
                        for row in rows[:8]
                    ],
                )
            ],
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Matchup bowling style source",
                    description="Aggregates the batter's matchup by bowling-style code, so bowling-type questions do not rank individual bowlers.",
                    sql=sql,
                    parameters=[],
                    table=table,
                )
            ],
            citations=[database_citation(f"Bowling style matchup vs {batter_name}", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Grouping basis",
                    detail="This answer groups by the feed's bowling-style code (`bowl_style`) rather than by bowler name.",
                )
            ],
        )

    @staticmethod
    def _bowling_analyst_table(rows: list[dict[str, object]], ranking_metric_label: str = "metric") -> TableBlock:
        return TableBlock(
            title="Analyst bowling leaderboard",
            columns=[
                "Rank",
                "Bowler",
                "Matches",
                "Innings",
                "Legal Balls",
                "Overs",
                "Runs",
                "Wickets",
                "Economy",
                "Dot Balls",
                "Dot %",
                "Boundary Balls",
                "Boundaries/Over",
                "Yorkers",
                "Yorker Success %",
                "False Shot %",
                ranking_metric_label.title(),
            ],
            rows=[
                [
                    index + 1,
                    row["player_name"],
                    row["matches"],
                    row["innings"],
                    row["balls"],
                    round(float(row["overs"]), 2) if row.get("overs") is not None else None,
                    row["runs"],
                    row["wickets"],
                    round(float(row["economy_rate"]), 2) if row.get("economy_rate") is not None else None,
                    row["dot_balls"],
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    row["boundary_balls"],
                    round(float(row["boundaries_per_over"]), 2) if row.get("boundaries_per_over") is not None else None,
                    row["yorker_balls"],
                    round(float(row["yorker_success_rate"]), 2) if row.get("yorker_success_rate") is not None else None,
                    round(float(row["false_shot_percentage"]), 2) if row.get("false_shot_percentage") is not None else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )

    @staticmethod
    def _batting_analyst_table(rows: list[dict[str, object]], ranking_metric_label: str = "metric") -> TableBlock:
        return TableBlock(
            title="Analyst batting leaderboard",
            columns=[
                "Rank",
                "Batter",
                "Matches",
                "Innings",
                "Balls",
                "Runs",
                "Dismissals",
                "Average",
                "Balls/Dismissal",
                "Strike Rate",
                "Boundary %",
                "Dot %",
                "Rotation %",
                "False Shot %",
                f"{ranking_metric_label.title()} (Rank)",
            ],
            rows=[
                [
                    index + 1,
                    row["player_name"],
                    row["matches"],
                    row["innings"],
                    row["balls"],
                    row["runs"],
                    row["dismissals"],
                    round(float(row["average"]), 2) if row.get("average") is not None else None,
                    round(float(row["balls_per_dismissal"]), 2) if row.get("balls_per_dismissal") is not None else None,
                    round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                    round(float(row["boundary_percentage"]), 2) if row.get("boundary_percentage") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["strike_rotation_percentage"]), 2) if row.get("strike_rotation_percentage") is not None else None,
                    round(float(row["false_shot_percentage"]), 2) if row.get("false_shot_percentage") is not None else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )

    @staticmethod
    def _batting_field_zone_table(rows: list[dict[str, object]], zone_label: str) -> TableBlock:
        return TableBlock(
            title=f"Batter runs in {zone_label} area",
            columns=[
                "Rank",
                "Batter",
                "Matches",
                "Innings",
                "Balls",
                "Runs",
                "Strike Rate",
                "Boundary %",
                "Dot %",
                "False Shot %",
                f"Runs In {zone_label.title()} (Rank)",
            ],
            rows=[
                [
                    index + 1,
                    row["player_name"],
                    row["matches"],
                    row["innings"],
                    row["balls"],
                    row["runs"],
                    round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                    round(float(row["boundary_percentage"]), 2) if row.get("boundary_percentage") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["false_shot_percentage"]), 2) if row.get("false_shot_percentage") is not None else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )

    @staticmethod
    def _batting_strike_rate_split_table(rows: list[dict[str, object]], split_after_balls: int) -> TableBlock:
        return TableBlock(
            title=f"Batter strike-rate change after {split_after_balls} balls",
            columns=[
                "Rank",
                "Batter",
                "Matches",
                "Innings",
                f"Innings Past {split_after_balls}",
                f"Balls 1-{split_after_balls}",
                f"Runs 1-{split_after_balls}",
                f"SR 1-{split_after_balls}",
                f"Balls After {split_after_balls}",
                f"Runs After {split_after_balls}",
                f"SR After {split_after_balls}",
                "SR Change",
            ],
            rows=[
                [
                    index + 1,
                    row["player_name"],
                    row["matches"],
                    row["innings"],
                    row["innings_past_split"],
                    row["first_balls"],
                    row["first_runs"],
                    round(float(row["first_strike_rate"]), 2) if row.get("first_strike_rate") is not None else None,
                    row["after_balls"],
                    row["after_runs"],
                    round(float(row["after_strike_rate"]), 2) if row.get("after_strike_rate") is not None else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )

    @staticmethod
    def _milestone_vulnerability_table(rows: list[dict[str, object]]) -> TableBlock:
        return TableBlock(
            title="Batter vulnerability after milestones",
            columns=[
                "Rank",
                "Batter",
                "Milestones",
                "Post Balls",
                "Post Dismissals",
                "Post Dismissal %",
                "Baseline Balls",
                "Baseline Dismissals",
                "Set Baseline %",
                "Vulnerability Lift",
                "False Shot %",
                "Dot %",
            ],
            rows=[
                [
                    index + 1,
                    row["player_name"],
                    row["milestones"],
                    row["post_balls"],
                    row["post_dismissals"],
                    round(float(row["post_dismissal_percentage"]), 2) if row.get("post_dismissal_percentage") is not None else None,
                    row["baseline_balls"],
                    row["baseline_dismissals"],
                    round(float(row["baseline_dismissal_percentage"]), 2)
                    if row.get("baseline_dismissal_percentage") is not None
                    else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                    round(float(row["post_false_shot_percentage"]), 2) if row.get("post_false_shot_percentage") is not None else None,
                    round(float(row["post_dot_percentage"]), 2) if row.get("post_dot_percentage") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )

    @staticmethod
    def _matchup_leaderboard_table(rows: list[dict[str, object]], subject_label: str) -> TableBlock:
        return TableBlock(
            title=f"Analyst matchup {subject_label.lower()} leaderboard",
            columns=[
                "Rank",
                subject_label,
                "Bowling Style",
                "Balls",
                "Legal Balls",
                "Runs",
                "Dismissals",
                "Strike Rate",
                "Economy",
                "Dot %",
                "False Shot %",
                "Metric",
            ],
            rows=[
                [
                    index + 1,
                    row["player_name"],
                    AnalyticsService._bowling_style_label(row.get("bowling_style")) if row.get("bowling_style") else None,
                    row["balls"],
                    row["legal_balls"],
                    row["runs"],
                    row["dismissals"],
                    round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                    round(float(row["economy_rate"]), 2) if row.get("economy_rate") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["false_shot_percentage"]), 2) if row.get("false_shot_percentage") is not None else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )

    @staticmethod
    def _matchup_bowling_style_table(rows: list[dict[str, object]], title: str) -> TableBlock:
        return TableBlock(
            title=title,
            columns=[
                "Rank",
                "Bowling Style",
                "Code",
                "Bowlers",
                "Balls",
                "Legal Balls",
                "Runs",
                "Dismissals",
                "Strike Rate",
                "Economy",
                "Dot %",
                "False Shot %",
                "Metric",
            ],
            rows=[
                [
                    index + 1,
                    AnalyticsService._bowling_style_label(row.get("bowling_style")),
                    row["bowling_style"],
                    row["bowlers"],
                    row["balls"],
                    row["legal_balls"],
                    row["runs"],
                    row["dismissals"],
                    round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                    round(float(row["economy_rate"]), 2) if row.get("economy_rate") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["false_shot_percentage"]), 2) if row.get("false_shot_percentage") is not None else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )

    @staticmethod
    def _bowling_analyst_sql(metric: str, filters: dict[str, object], rank_intent: str) -> str:
        direction = "DESC"
        if metric in {"economy_rate", "boundaries_per_over"} and rank_intent == "best":
            direction = "ASC"
        if metric in {"economy_rate", "boundaries_per_over"} and rank_intent == "worst":
            direction = "DESC"
        return f"""
WITH bowler_rows AS (
  SELECT
    bowl AS player,
    SUM(CASE WHEN legal ball THEN 1 ELSE 0 END) AS legal_balls,
    SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
    SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END) AS wickets,
    SUM(CASE WHEN legal ball AND bowlruns = 0 THEN 1 ELSE 0 END) AS dot_balls,
    SUM(CASE WHEN legal ball AND batruns IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
    SUM(CASE WHEN legal ball AND length = 'YORKER' THEN 1 ELSE 0 END) AS yorker_balls,
    SUM(CASE WHEN legal ball AND control = 0 THEN 1 ELSE 0 END) AS false_shots
  FROM analytics.deliveries_v1
  WHERE NULLIF(TRIM(CAST(bowl AS VARCHAR)), '') IS NOT NULL
)
SELECT *
FROM bowler_rows
WHERE legal_balls >= :min_legal_balls
ORDER BY :metric_expression_for_{metric} {direction}, legal_balls DESC
LIMIT :limit
""".strip()

    @staticmethod
    def _batting_analyst_sql(metric: str, filters: dict[str, object], rank_intent: str) -> str:
        lower_is_better = metric in {"dot_percentage"}
        direction = "DESC" if lower_is_better == (rank_intent == "worst") else "ASC"
        return f"""
WITH batter_rows AS (
  SELECT
    bat AS player,
    SUM(CASE WHEN ballfaced = 1 THEN 1 ELSE 0 END) AS balls,
    SUM(CASE WHEN ballfaced = 1 THEN batruns ELSE 0 END) AS runs,
    SUM(CASE WHEN ballfaced = 1 AND out = true THEN 1 ELSE 0 END) AS dismissals,
    SUM(CASE WHEN ballfaced = 1 AND batruns IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
    SUM(CASE WHEN ballfaced = 1 AND batruns = 0 THEN 1 ELSE 0 END) AS dot_balls,
    SUM(CASE WHEN ballfaced = 1 AND control = 0 THEN 1 ELSE 0 END) AS false_shots
  FROM analytics.deliveries_v1
  WHERE NULLIF(TRIM(CAST(bat AS VARCHAR)), '') IS NOT NULL
)
SELECT *
FROM batter_rows
WHERE balls >= :min_balls
-- average = runs / NULLIF(dismissals, 0)
-- balls_per_dismissal = balls / NULLIF(dismissals, 0)
ORDER BY :metric_expression_for_{metric} {direction}, balls DESC
LIMIT :limit
""".strip()

    @staticmethod
    def _batting_field_zone_sql(field_zone: str, rank_intent: str) -> str:
        direction = "ASC" if rank_intent == "worst" else "DESC"
        return f"""
WITH zone_rows AS (
  SELECT
    bat AS player,
    COUNT(DISTINCT p_match) AS matches,
    COUNT(DISTINCT batter innings id) AS innings,
    COUNT(*) AS balls,
    SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
    SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
    SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
    SUM(CASE WHEN TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
  FROM analytics.deliveries_v1
  WHERE ballfaced = 1
    AND NULLIF(TRIM(CAST(bat AS VARCHAR)), '') IS NOT NULL
    AND wagonZone maps to hand-adjusted {field_zone}
  GROUP BY bat
)
SELECT *,
  runs / NULLIF(balls, 0) * 100.0 AS strike_rate,
  dot_balls / NULLIF(balls, 0) * 100.0 AS dot_percentage,
  boundary_balls / NULLIF(balls, 0) * 100.0 AS boundary_percentage,
  false_shots / NULLIF(balls, 0) * 100.0 AS false_shot_percentage
FROM zone_rows
WHERE balls >= :min_balls
ORDER BY runs {direction}, balls DESC
LIMIT :limit
""".strip()

    @staticmethod
    def _batting_strike_rate_split_sql(split_after_balls: int, rank_intent: str) -> str:
        direction = "ASC" if rank_intent == "worst" else "DESC"
        return f"""
WITH legal_batter_balls AS (
  SELECT
    bat AS player,
    p_match,
    batter innings id,
    TRY_CAST(cur_bat_bf AS INTEGER) AS ball_number,
    TRY_CAST(batruns AS INTEGER) AS runs
  FROM analytics.deliveries_v1
  WHERE ballfaced = 1
),
split_rows AS (
  SELECT
    player,
    SUM(CASE WHEN ball_number <= {split_after_balls} THEN 1 ELSE 0 END) AS first_balls,
    SUM(CASE WHEN ball_number <= {split_after_balls} THEN runs ELSE 0 END) AS first_runs,
    SUM(CASE WHEN ball_number > {split_after_balls} THEN 1 ELSE 0 END) AS after_balls,
    SUM(CASE WHEN ball_number > {split_after_balls} THEN runs ELSE 0 END) AS after_runs
  FROM legal_batter_balls
  GROUP BY player
)
SELECT *,
  first_runs / NULLIF(first_balls, 0) * 100.0 AS first_sr,
  after_runs / NULLIF(after_balls, 0) * 100.0 AS after_sr,
  after_runs / NULLIF(after_balls, 0) * 100.0
    - first_runs / NULLIF(first_balls, 0) * 100.0 AS sr_change
FROM split_rows
WHERE first_balls >= :min_first_balls
  AND after_balls >= :min_after_balls
ORDER BY sr_change {direction}, after_balls DESC
LIMIT :limit
""".strip()

    @staticmethod
    def _milestone_vulnerability_sql(post_milestone_balls: int, rank_intent: str) -> str:
        direction = "ASC" if rank_intent == "worst" else "DESC"
        return f"""
WITH legal_batter_balls AS (
  SELECT
    bat AS player,
    batter innings id,
    TRY_CAST(cur_bat_bf AS INTEGER) AS ball_number,
    TRY_CAST(cur_bat_runs AS INTEGER) AS current_runs,
    TRY_CAST(batruns AS INTEGER) AS runs_on_ball,
    CASE WHEN out = true THEN 1 ELSE 0 END AS dismissal
  FROM analytics.deliveries_v1
  WHERE ballfaced = 1
),
milestone_events AS (
  SELECT *, 50 AS milestone
  FROM legal_batter_balls
  WHERE current_runs - runs_on_ball < 50 AND current_runs >= 50
  UNION ALL
  SELECT *, 100 AS milestone
  FROM legal_batter_balls
  WHERE current_runs - runs_on_ball < 100 AND current_runs >= 100
),
post_window AS (
  SELECT m.player, b.ball_number, b.dismissal
  FROM milestone_events m
  JOIN legal_batter_balls b
    ON b.same_batter_innings = m.same_batter_innings
   AND b.ball_number > m.ball_number
   AND b.ball_number <= m.ball_number + {post_milestone_balls}
),
baseline AS (
  SELECT player, COUNT(*) AS baseline_balls, SUM(dismissal) AS baseline_dismissals
  FROM legal_batter_balls
  WHERE ball_number > 20
    AND not already in post_window
  GROUP BY player
)
SELECT
  post.player,
  post_dismissals / NULLIF(post_balls, 0) * 100.0 AS post_dismissal_pct,
  baseline_dismissals / NULLIF(baseline_balls, 0) * 100.0 AS baseline_dismissal_pct,
  post_dismissal_pct - baseline_dismissal_pct AS vulnerability_lift
FROM post_window post
JOIN baseline USING (player)
WHERE milestones >= :min_milestones
  AND post_balls >= :min_post_balls
  AND baseline_balls >= :min_baseline_balls
ORDER BY vulnerability_lift {direction}, post_balls DESC
LIMIT :limit
""".strip()

    @staticmethod
    def _matchup_leaderboard_sql(metric: str, subject: str, filters: dict[str, object], player: str, rank_intent: str) -> str:
        group_col = "bowl" if subject == "bowler" else "bat"
        direction = "ASC" if metric == "economy_rate" and rank_intent == "best" else "DESC"
        return f"""
WITH matchup_rows AS (
  SELECT
    {group_col} AS player,
    COUNT(*) AS balls,
    SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
    SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END) AS dismissals
  FROM analytics.deliveries_v1
  WHERE bat = :opponent_player
  GROUP BY {group_col}
)
SELECT *
FROM matchup_rows
WHERE balls >= :min_balls
ORDER BY :metric_expression_for_{metric} {direction}, balls DESC
LIMIT :limit
""".strip()

    @staticmethod
    def _matchup_bowling_style_sql(metric: str, filters: dict[str, object], player: str, rank_intent: str) -> str:
        direction = "ASC" if metric == "economy_rate" and rank_intent == "best" else "DESC"
        return f"""
WITH style_rows AS (
  SELECT
    bowl_style,
    COUNT(DISTINCT bowl) AS bowlers,
    COUNT(*) AS balls,
    SUM(CASE WHEN legal ball THEN 1 ELSE 0 END) AS legal_balls,
    SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
    SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END) AS dismissals,
    SUM(CASE WHEN batruns = 0 THEN 1 ELSE 0 END) AS dot_balls,
    SUM(CASE WHEN control = 0 THEN 1 ELSE 0 END) AS false_shots
  FROM analytics.deliveries_v1
  WHERE bat = :opponent_player
    AND bowl_kind = :bowling_kind
    AND NULLIF(TRIM(CAST(bowl_style AS VARCHAR)), '') IS NOT NULL
  GROUP BY bowl_style
)
SELECT *
FROM style_rows
WHERE balls >= :min_balls
ORDER BY :metric_expression_for_{metric} {direction}, balls DESC
LIMIT :limit
""".strip()

    def _handle_line_length_breakdown(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        player = route.entities[0]
        group_by = str(route.filters.get("group_by") or "length")
        metric = str(route.filters.get("metric") or "wickets_taken")
        rank_intent = str(route.filters.get("rank_intent") or "best")
        phase = route.filters.get("phase") if isinstance(route.filters.get("phase"), str) else None
        rows = self.repository.get_line_length_breakdown(
            batter_name=player,
            group_by=group_by,
            metric=metric,
            phase=phase,
            rank_intent=rank_intent,
            limit=10,
            min_balls=12,
        )
        interpretation = interpretation.model_copy(
            update={"filters": {**interpretation.filters, "group_by": group_by, "metric": metric, "rank_intent": rank_intent}}
        )
        if not rows:
            return self._insufficient(
                interpretation,
                f"No {group_by} breakdown could be built for {player}.",
                ["Try a broader player or remove the phase filter."],
            )
        metric_label = self._analyst_metric_label(metric)
        top = rows[0]
        top_bucket = self._line_or_length_bucket_label(group_by, top["bucket"])
        ranking_verb = "ranks lowest" if rank_intent == "worst" else "leads"
        table = TableBlock(
            title=f"{player} {group_by} breakdown",
            columns=["Rank", group_by.title(), "Balls", "Runs", "Dismissals", "Strike Rate", "Dot %", "False Shot %", "Metric"],
            rows=[
                [
                    index + 1,
                    self._line_or_length_bucket_label(group_by, row["bucket"]),
                    row["balls"],
                    row["runs"],
                    row["dismissals"],
                    round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["false_shot_percentage"]), 2) if row.get("false_shot_percentage") is not None else None,
                    round(float(row["metric_value"]), 2) if row.get("metric_value") is not None else None,
                ]
                for index, row in enumerate(rows)
            ],
        )
        sql = f"""
SELECT {group_by}, COUNT(*) AS balls, SUM(batruns) AS runs, SUM(out) AS dismissals
FROM analytics.deliveries_v1
WHERE bat = :player
GROUP BY {group_by}
ORDER BY :metric_expression_for_{metric} {'ASC' if rank_intent == 'worst' else 'DESC'}
LIMIT :limit
""".strip()
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} {group_by} analysis",
                    body=f"For {player}, {top_bucket} {ranking_verb} in the {group_by} table by {metric_label}: {self._fmt(top.get('metric_value'))}.",
                )
            ],
            tables=[table],
            evidence_queries=[
                EvidenceQueryBlock(
                    title=f"{group_by.title()} breakdown source",
                    description=f"{group_by.title()} rows ranked by {metric_label}.",
                    sql=sql,
                    parameters=[],
                    table=table,
                )
            ],
            citations=[database_citation(f"{player} {group_by} breakdown", "analytics.deliveries_v1")],
        )

    def _handle_bowling_plan_against_batter(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        player = route.entities[0]
        phase = route.filters.get("phase") if isinstance(route.filters.get("phase"), str) else None
        phase_label = self._phase_label({"phase": phase})
        pitch = self.repository.get_pitch_map(player, phase=phase)
        phase_rows = self.repository.get_player_phase_summary(player)
        bowling_type_rows = self.repository.get_player_bowling_kind_summary(player)
        bowling_style_rows = self.repository.get_player_bowling_style_summary(player)
        shot_profile = self.repository.get_shot_type_profile(player, phase=phase)
        field_zones = self.repository.get_field_zone_profile(player, phase=phase)

        cells = list(pitch.get("cells", []))
        if not cells:
            return self._insufficient(
                interpretation,
                f"No line/length evidence could be built for a bowling plan against {player}.",
                ["Try another batter or ask for a simpler batting profile."],
            )

        def cell_value(cell: object, key: str, default: float = 0.0) -> float:
            if isinstance(cell, dict):
                value = cell.get(key)
                return float(value) if value is not None else default
            return default

        recommendation_cells = [cell for cell in cells if cell_value(cell, "balls") >= 24] or cells
        safest_cells = sorted(
            recommendation_cells,
            key=lambda cell: (
                cell_value(cell, "strike_rate", 999.0),
                -(cell_value(cell, "dot_balls") / max(cell_value(cell, "balls"), 1.0)),
                -cell_value(cell, "dismissals"),
            ),
        )
        wicket_cells = sorted(recommendation_cells, key=lambda cell: (-cell_value(cell, "dismissals"), cell_value(cell, "strike_rate", 999.0)))
        avoid_cells = sorted(
            recommendation_cells,
            key=lambda cell: (
                -(cell_value(cell, "boundary_balls") / max(cell_value(cell, "balls"), 1.0)),
                -cell_value(cell, "strike_rate"),
            ),
        )
        recommended = safest_cells[0]
        wicket_option = wicket_cells[0]
        avoid = avoid_cells[0]

        plan_rows = [
            [
                "Primary option",
                self._line_length_label(recommended),
                int(recommended.get("balls", 0)),
                recommended.get("runs"),
                recommended.get("dismissals"),
                round(float(recommended["strike_rate"]), 2) if recommended.get("strike_rate") is not None else None,
                round(cell_value(recommended, "dot_balls") / max(cell_value(recommended, "balls"), 1.0) * 100.0, 2),
                recommended.get("boundary_balls"),
            ],
            [
                "Wicket option",
                self._line_length_label(wicket_option),
                int(wicket_option.get("balls", 0)),
                wicket_option.get("runs"),
                wicket_option.get("dismissals"),
                round(float(wicket_option["strike_rate"]), 2) if wicket_option.get("strike_rate") is not None else None,
                round(cell_value(wicket_option, "dot_balls") / max(cell_value(wicket_option, "balls"), 1.0) * 100.0, 2),
                wicket_option.get("boundary_balls"),
            ],
            [
                "Avoid / high-risk",
                self._line_length_label(avoid),
                int(avoid.get("balls", 0)),
                avoid.get("runs"),
                avoid.get("dismissals"),
                round(float(avoid["strike_rate"]), 2) if avoid.get("strike_rate") is not None else None,
                round(cell_value(avoid, "dot_balls") / max(cell_value(avoid, "balls"), 1.0) * 100.0, 2),
                avoid.get("boundary_balls"),
            ],
        ]
        plan_table = TableBlock(
            title=f"Bowling plan against {player}",
            columns=["Use", "Bowl Here", "Balls", "Runs", "Dismissals", "Strike Rate", "Dot %", "Boundary Balls"],
            rows=plan_rows,
        )
        phase_table = TableBlock(
            title="Phase batting evidence",
            columns=["Phase", "Innings", "Runs", "Balls", "Dismissals", "Average", "Strike Rate", "Runs/Innings", "Boundary %", "Dot %", "Control %"],
            rows=[self._summary_metric_row(row, "split") for row in phase_rows],
        )
        bowling_type_table = TableBlock(
            title="Pace/spin batting evidence",
            columns=["Bowling Type", "Innings", "Runs", "Balls", "Dismissals", "Average", "Strike Rate", "Runs/Innings", "Boundary %", "Dot %", "Control %"],
            rows=[self._summary_metric_row(row, "split") for row in bowling_type_rows],
        )
        style_recommendation_rows = []
        if bowling_style_rows:
            sampled_style_rows = [row for row in bowling_style_rows if int(row.get("balls_faced") or 0) >= 60] or bowling_style_rows
            style_rows = sorted(
                sampled_style_rows,
                key=lambda row: (
                    float(row.get("strike_rate") or 999.0),
                    -int(row.get("dismissals") or 0),
                    -float(row.get("dot_percentage") or 0.0),
                    -int(row.get("balls_faced") or 0),
                ),
            )
            best_style = style_rows[0]
            for row in style_rows[:8]:
                style_code = row.get("style_code") or row.get("split")
                style_recommendation_rows.append(
                    [
                        self._bowling_style_label(style_code),
                        style_code,
                        row["balls_faced"],
                        row["runs_scored"],
                        row["dismissals"],
                        round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                        round(float(row["average"]), 2) if row.get("average") is not None else None,
                        round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                        round(float(row["control_percentage"]), 2) if row.get("control_percentage") is not None else None,
                        "Prefer" if row is best_style else "Secondary",
                    ]
                )
        style_plan_table = TableBlock(
            title=f"Bowling style plan against {player}",
            columns=["Bowling Style", "Code", "Balls", "Runs", "Dismissals", "Strike Rate", "Average", "Dot %", "Control %", "Use"],
            rows=style_recommendation_rows,
        )
        bowling_style_table = TableBlock(
            title="Bowling style evidence",
            columns=["Bowling Style", "Code", "Balls", "Runs", "Dismissals", "Average", "Strike Rate", "Dot %", "Control %"],
            rows=[
                [
                    self._bowling_style_label(row.get("style_code") or row.get("split")),
                    row.get("style_code") or row.get("split"),
                    row["balls_faced"],
                    row["runs_scored"],
                    row["dismissals"],
                    round(float(row["average"]), 2) if row.get("average") is not None else None,
                    round(float(row["strike_rate"]), 2) if row.get("strike_rate") is not None else None,
                    round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                    round(float(row["control_percentage"]), 2) if row.get("control_percentage") is not None else None,
                ]
                for row in bowling_style_rows
            ],
        )
        shot_table = TableBlock(
            title="Shot-risk evidence",
            columns=["Shot", "Balls", "Runs", "Control %", "False Shot %", "Dismissal Rate", "Boundary %"],
            rows=[
                [
                    self._shot_label(item.shot if hasattr(item, "shot") else item.get("shot")),
                    item.balls if hasattr(item, "balls") else item.get("balls"),
                    item.runs if hasattr(item, "runs") else item.get("runs"),
                    item.control_percentage if hasattr(item, "control_percentage") else item.get("control_percentage"),
                    item.false_shot_percentage if hasattr(item, "false_shot_percentage") else item.get("false_shot_percentage"),
                    item.dismissal_rate if hasattr(item, "dismissal_rate") else item.get("dismissal_rate"),
                    item.boundary_percentage if hasattr(item, "boundary_percentage") else item.get("boundary_percentage"),
                ]
                for item in list(shot_profile.get("metrics", []))[:8]
            ],
        )
        evidence_sql = """
SELECT line, length, COUNT(*) AS balls, SUM(batruns) AS runs,
       SUM(CASE WHEN out = true THEN 1 ELSE 0 END) AS dismissals,
       SUM(CASE WHEN batruns = 0 THEN 1 ELSE 0 END) AS dot_balls,
       SUM(CASE WHEN batruns IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
       AVG(control) AS control
FROM analytics.deliveries_v1
WHERE bat = :player
GROUP BY line, length
ORDER BY dot_balls / NULLIF(balls, 0) DESC, dismissals DESC
""".strip()
        visuals, coverage_notes = self._build_batter_visuals(player, phase=phase)
        style_sentence = ""
        if style_recommendation_rows:
            preferred_style = style_recommendation_rows[0]
            style_sentence = (
                f" Prefer {preferred_style[0]} as the bowling-style cue: {preferred_style[5]} SR, "
                f"{preferred_style[7]}% dots, {preferred_style[4]} dismissals in the sample."
            )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation.model_copy(
                update={"filters": {**interpretation.filters, "plan_type": "bowling_to_batter", "subject": "batter"}}
            ),
            summaries=[
                SummaryBlock(
                    title=f"Bowling plan against {player}",
                    body=(
                        f"For {phase_label}, the primary data-backed option against {player} is {self._line_length_label(recommended)}: "
                        f"{recommended.get('runs')} runs from {recommended.get('balls')} balls, "
                        f"{self._fmt(recommended.get('strike_rate'))} SR, and {plan_rows[0][6]}% dots. "
                        f"The wicket option is {self._line_length_label(wicket_option)}; "
                        f"avoid {self._line_length_label(avoid)} based on boundary rate/strike rate."
                        f"{style_sentence}"
                    ),
                )
            ],
            tables=[plan_table, style_plan_table],
            charts=[
                ChartBlock(
                    title=f"Line/length options vs {player}",
                    chart_type="bar",
                    series=[
                        {"label": str(row[1]), "value": float(row[5] or 0)}
                        for row in plan_rows
                    ],
                )
            ],
            visuals=visuals,
            evidence_queries=[
                EvidenceQueryBlock(
                    title="Bowling plan line/length source",
                    description="Line/length cells for the target batter, ranked for dots and wicket threat.",
                    sql=evidence_sql,
                    parameters=[player],
                    table=plan_table,
                ),
                EvidenceQueryBlock(
                    title="Bowling style plan source",
                    description="Bowling-style rows for the target batter. The database has style codes, not ball-speed or swing-tracking data.",
                    sql=(
                        "SELECT bowl_style, bowl_kind, COUNT(*) AS balls, SUM(batruns) AS runs, "
                        "SUM(CASE WHEN out = true THEN 1 ELSE 0 END) AS dismissals, AVG(control) AS control "
                        "FROM analytics.deliveries_v1 WHERE bat = :player GROUP BY bowl_style, bowl_kind"
                    ),
                    parameters=[player],
                    table=bowling_style_table,
                ),
                EvidenceQueryBlock(
                    title="Phase batting source",
                    description="Phase rows kept as supporting evidence, not as the main bowling plan.",
                    sql=(
                        "SELECT phase, COUNT(*) AS balls, SUM(batruns) AS runs "
                        "FROM analytics.deliveries_v1 WHERE bat = :player GROUP BY phase"
                    ),
                    parameters=[player],
                    table=phase_table,
                ),
                EvidenceQueryBlock(
                    title="Shot-risk source",
                    description="Shot rows kept as supporting evidence for tactical risk.",
                    sql=(
                        "SELECT shot, COUNT(*) AS balls, SUM(batruns) AS runs, AVG(control) AS control "
                        "FROM analytics.deliveries_v1 WHERE bat = :player GROUP BY shot"
                    ),
                    parameters=[player],
                    table=shot_table,
                ),
            ],
            citations=[database_citation(f"Bowling plan vs {player}", "analytics.deliveries_v1 line/length/control")],
            evidence_notes=[
                EvidenceNote(
                    title="Plan basis",
                    detail="This is a data-backed tactical summary for bowling to the named batter, not the batter's own bowling record.",
                ),
                *coverage_notes,
            ],
        )

    def _handle_bowling_metric_leaderboard(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        years = [int(year) for year in route.filters.get("years", [])] if isinstance(route.filters.get("years"), list) else []
        year_mode = str(route.filters.get("year_mode")) if route.filters.get("year_mode") else None
        competition = str(route.filters.get("competition")) if route.filters.get("competition") else None
        metric = str(route.filters.get("metric") or "economy_rate")
        if metric not in {"economy_rate", "wickets_taken", "balls_per_wicket", "balls_per_boundary"}:
            metric = "economy_rate"
        rank_intent = str(route.filters.get("rank_intent") or "best")
        if rank_intent not in {"best", "worst"}:
            rank_intent = "best"
        interpretation = interpretation.model_copy(
            update={"filters": {**interpretation.filters, "metric": metric, "rank_intent": rank_intent}}
        )
        min_legal_balls = 60
        leaderboard = self.repository.get_bowling_metric_leaderboard(
            metric=metric,
            phase=phase,
            years=years,
            year_mode=year_mode,
            competition=competition,
            rank_intent=rank_intent,
            limit=10,
            min_legal_balls=min_legal_balls,
        )
        if not leaderboard:
            return self._insufficient(
                interpretation,
                f"No ODI bowling {self._bowling_leaderboard_label(metric)} leaderboard could be built for {phase_label} with the requested filters.",
                ["Relax the year/phase filter or lower the minimum legal-ball threshold."],
            )

        leader = leaderboard[0]
        def rank_metric_value(row: dict[str, object]) -> float | int | None:
            if metric == "wickets_taken":
                return int(row.get("wickets") or 0)
            if metric == "economy_rate":
                value = row.get("economy_rate")
            elif metric == "balls_per_wicket":
                value = row.get("balls_per_wicket")
            else:
                value = row.get("balls_per_boundary")
            return round(float(value), 6) if value is not None else None

        leader_value = rank_metric_value(leader)
        tied_leaders = [row for row in leaderboard if rank_metric_value(row) == leader_value]
        time_label = self._context_filter_label(years, year_mode, competition)
        metric_label = self._bowling_leaderboard_label(metric)
        rank_phrase = self._bowling_rank_phrase(metric, rank_intent)
        evidence_query = self._bowling_metric_leaderboard_evidence_query(
            leaderboard,
            metric=metric,
            phase=phase,
            years=years,
            year_mode=year_mode,
            competition=competition,
            rank_intent=rank_intent,
            min_legal_balls=min_legal_balls,
        )
        metrics = [
            self.metric_catalog.get("economy_rate"),
            self.metric_catalog.get("wickets_taken"),
            self.metric_catalog.get("balls_per_wicket"),
            self.metric_catalog.get("bowler_dot_percentage"),
            self.metric_catalog.get("balls_per_boundary"),
        ]
        if metric == "wickets_taken":
            summary_value = f"{leader['wickets']} wickets"
        elif metric == "economy_rate":
            summary_value = f"{self._fmt(leader.get('economy_rate'))} economy"
        elif metric == "balls_per_wicket":
            summary_value = f"{self._fmt(leader.get('balls_per_wicket'))} balls per wicket"
        else:
            summary_value = f"{self._fmt(leader.get('balls_per_boundary'))} balls per boundary"
        if metric == "wickets_taken":
            summary_tail = f"{leader['runs_conceded']} runs conceded, and an economy of {self._fmt(leader.get('economy_rate'))}."
        else:
            summary_tail = f"{leader['runs_conceded']} runs conceded, and {leader['wickets']} wickets."
        if len(tied_leaders) > 1:
            leader_names = " and ".join(str(row["player_name"]) for row in tied_leaders[:3])
            leader_phrase = f"{leader_names} share the {rank_phrase} {phase_label} {metric_label}"
        else:
            leader_phrase = f"{leader['player_name']} has the {rank_phrase} {phase_label} {metric_label}"
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{rank_phrase.title()} ODI bowling {metric_label}: {phase_label}",
                    body=(
                        f"{time_label}, {leader_phrase} in the local ODI dataset "
                        f"among bowlers with at least {min_legal_balls} legal balls: {summary_value} from {leader['balls_bowled']} legal balls "
                        f"({self._fmt(leader.get('overs'))} overs), {summary_tail}"
                    ),
                )
            ],
            tables=[
                TableBlock(
                    title=f"Bowling {metric_label} leaderboard",
                    columns=[
                        "Rank",
                        "Bowler",
                        "Matches",
                        "Bowling Innings",
                        "Legal Balls",
                        "Overs",
                        "Runs Conceded",
                        "Wickets",
                        "Economy",
                        "Dot %",
                        "Boundary %",
                        "Balls/Boundary",
                    ],
                    rows=[
                        [
                            index + 1,
                            row["player_name"],
                            row["matches"],
                            row["innings"],
                            row["balls_bowled"],
                            round(float(row["overs"]), 2) if row.get("overs") is not None else None,
                            row["runs_conceded"],
                            row["wickets"],
                            round(float(row["economy_rate"]), 2) if row.get("economy_rate") is not None else None,
                            round(float(row["dot_percentage"]), 2) if row.get("dot_percentage") is not None else None,
                            round(float(row["boundary_percentage"]), 2) if row.get("boundary_percentage") is not None else None,
                            round(float(row["balls_per_boundary"]), 2) if row.get("balls_per_boundary") is not None else None,
                        ]
                        for index, row in enumerate(leaderboard)
                    ],
                )
            ],
            charts=[
                ChartBlock(
                    title=f"{rank_phrase.title()} {metric_label} leaderboard ({phase_label})",
                    chart_type="bar",
                    series=[
                        {"label": row["player_name"], "value": round(float((row.get(metric) if metric != "wickets_taken" else row.get("wickets")) or 0), 2)}
                        for row in leaderboard[:8]
                    ],
                )
            ],
            evidence_queries=[evidence_query],
            metric_references=[MetricReference(metric_id=m.metric_id, label=m.label, formula=m.formula, unit=m.unit) for m in metrics],
            citations=[database_citation(f"ODI bowling {metric_label} leaderboard", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Leaderboard threshold",
                    detail=f"Leaderboard excludes bowlers below {min_legal_balls} legal balls for the selected phase/time filter.",
                ),
                EvidenceNote(
                    title="Bowling interpretation basis",
                    detail="This filters on `bowl`, not `bat`. Economy uses legal balls for overs; wides/no-balls count in runs and delivery rows, not overs.",
                ),
            ],
        )

    def _handle_trend(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if not route.entities:
            return self._insufficient(
                interpretation,
                "A player entity is required for trend analysis.",
                ["Try: Has Shimron Hetmyer become more destructive over time?"],
            )
        player = route.entities[0]
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        if route.filters.get("skill") == "bowling":
            return self._handle_bowling_trend(interpretation, route)

        trend = self.repository.get_player_year_trend(player)
        if not trend:
            bowling_trend = self.repository.get_player_bowling_year_trend(player, phase=phase)
            if bowling_trend:
                bowling_route = QueryRoute(
                    query_class=route.query_class,
                    entities=route.entities,
                    filters={**route.filters, "skill": "bowling"},
                )
                bowling_interpretation = interpretation.model_copy(
                    update={"filters": {**interpretation.filters, "skill": "bowling"}}
                )
                return self._handle_bowling_trend(bowling_interpretation, bowling_route)
        if not trend:
            return self._insufficient(
                interpretation,
                f"No year-level ODI trend data was found for {player}.",
                ["Try another ODI player with year-by-year batting or bowling data."],
            )
        trend = self._apply_year_filter(trend, route.filters)
        if not trend:
            return self._insufficient(
                interpretation,
                f"The ODI dataset does not contain enough year-level data for the requested time filter on {player}.",
                ["Relax the year filter or ask for the player's full ODI trend."],
            )
        visuals, coverage_notes = self._build_batter_visuals(player, phase=phase)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} year-by-year trend",
                    body=(
                        f"The filtered ODI batting trend view for {phase_label} covers {len(trend)} recorded years "
                        f"with an average control rate of {mean(item['control_percentage'] or 0 for item in trend):.2f}%."
                    ),
                )
            ],
            tables=[
                TableBlock(
                    title="Year trend",
                    columns=["Year", "Balls Faced", "Runs Scored", "Control %"],
                    rows=[[item["year"], item["balls_faced"], item["runs_scored"], round(item["control_percentage"] or 0, 2)] for item in trend],
                )
            ],
            charts=[ChartBlock(title="Runs scored by year", chart_type="line", series=[{"label": str(item["year"]), "value": item["runs_scored"]} for item in trend])],
            visuals=visuals,
            citations=[database_citation("Player year trend", "analytics.player_year_batting")],
            evidence_notes=coverage_notes,
        )

    def _handle_bowling_trend(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        if len(route.entities) > 1:
            return self._handle_bowling_trend_comparison(interpretation, route)

        player = route.entities[0]
        trend = self.repository.get_player_bowling_year_trend(player, phase=phase)
        if not trend:
            return self._insufficient(
                interpretation,
                f"No year-level ODI bowling trend data was found for {player} in {phase_label}.",
                ["Relax the phase filter or ask for the player's full ODI bowling trend."],
            )
        trend = self._apply_year_filter(trend, route.filters)
        if not trend:
            return self._insufficient(
                interpretation,
                f"The ODI dataset does not contain enough year-level bowling data for the requested time filter on {player}.",
                ["Relax the year filter or ask for the player's full ODI bowling trend."],
            )

        qualified = [item for item in trend if int(item["balls_bowled"]) >= 24 and item.get("economy_rate") is not None]
        economy_reference = min(qualified or trend, key=lambda item: item["economy_rate"] if item.get("economy_rate") is not None else 999.0)
        wicket_reference = max(trend, key=lambda item: int(item["wickets"]))
        evidence_query = self._bowling_year_trend_evidence_query(player, trend, phase)
        metrics = [
            self.metric_catalog.get("economy_rate"),
            self.metric_catalog.get("wickets_taken"),
            self.metric_catalog.get("balls_per_wicket"),
            self.metric_catalog.get("bowler_dot_percentage"),
            self.metric_catalog.get("balls_per_boundary"),
        ]
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} year-by-year bowling trend",
                    body=(
                        f"The ODI bowling trend for {player} in {phase_label} covers {len(trend)} recorded years. "
                        f"Best economy in the table is {self._fmt(economy_reference.get('economy_rate'))} in {economy_reference['year']}; "
                        f"highest wicket year is {wicket_reference['year']} with {wicket_reference['wickets']} wickets. "
                        "The table exposes legal balls, delivery rows, runs conceded, wickets, dots, and boundaries so every rate can be verified."
                    ),
                )
            ],
            tables=[evidence_query.table],
            charts=[
                ChartBlock(
                    title=f"Economy by year ({phase_label})",
                    chart_type="line",
                    series=[
                        {"label": str(item["year"]), "value": round(float(item["economy_rate"] or 0), 2)}
                        for item in trend
                    ],
                )
            ],
            evidence_queries=[evidence_query],
            metric_references=[MetricReference(metric_id=m.metric_id, label=m.label, formula=m.formula, unit=m.unit) for m in metrics],
            citations=[database_citation("Player bowling year trend", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Bowling interpretation basis",
                    detail=(
                        "This trend filters on `bowl`, not `bat`. Economy uses legal balls for overs; wides and no-balls "
                        "remain in delivery rows and runs conceded but do not add to overs bowled."
                    ),
                ),
                EvidenceNote(
                    title="Small-sample caution",
                    detail="Some years can have very small phase samples, especially death overs, so compare economy with legal-ball volume beside it.",
                ),
            ],
        )

    def _handle_bowling_trend_comparison(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        phase = route.filters.get("phase")
        phase_label = self._phase_label(route.filters)
        trends: dict[str, list[dict[str, object]]] = {}
        for player in route.entities[:2]:
            trend = self._apply_year_filter(self.repository.get_player_bowling_year_trend(player, phase=phase), route.filters)
            if trend:
                trends[player] = trend

        if len(trends) < 2:
            missing = [player for player in route.entities[:2] if player not in trends]
            return self._insufficient(
                interpretation,
                f"Not enough year-level ODI bowling trend data was found for {', '.join(missing) or 'the requested players'} in {phase_label}.",
                ["Relax the phase filter or compare bowlers with larger ODI bowling samples."],
            )

        totals = {player: self._bowling_trend_totals(trend) for player, trend in trends.items()}
        economy_leader = min(totals.values(), key=lambda item: item["economy_rate"] if item.get("economy_rate") is not None else 999.0)
        dot_leader = max(totals.values(), key=lambda item: item["dot_percentage"] if item.get("dot_percentage") is not None else -1.0)
        boundary_leader = min(totals.values(), key=lambda item: item["boundary_percentage"] if item.get("boundary_percentage") is not None else 999.0)
        evidence_query = self._bowling_year_trend_comparison_evidence_query(trends, phase)
        metrics = [
            self.metric_catalog.get("economy_rate"),
            self.metric_catalog.get("wickets_taken"),
            self.metric_catalog.get("balls_per_wicket"),
            self.metric_catalog.get("bowler_dot_percentage"),
            self.metric_catalog.get("balls_per_boundary"),
        ]
        player_names = " vs ".join(trends.keys())
        include_year_table = self._explicit_year_by_year_request(interpretation.original_question)
        response_tables = [self._bowling_trend_totals_matrix(totals)]
        if include_year_table:
            response_tables.append(evidence_query.table)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player_names} bowling trend comparison",
                    body=(
                        f"In {phase_label}, this compares year-by-year ODI bowling trends for {player_names}. "
                        f"Across the fetched years, {economy_leader['player_name']} has the lower aggregate economy "
                        f"({self._fmt(economy_leader.get('economy_rate'))}), {dot_leader['player_name']} has the higher dot-ball rate "
                        f"({self._fmt(dot_leader.get('dot_percentage'))}%), and {boundary_leader['player_name']} has the lower boundary rate "
                        f"({self._fmt(boundary_leader.get('boundary_percentage'))}%). "
                        "The table keeps the comparison compact; ask for a year-by-year comparison if you want the season split."
                    ),
                )
            ],
            tables=response_tables,
            charts=[
                ChartBlock(
                    title=f"Economy by year ({phase_label})",
                    chart_type="line",
                    series=[
                        {
                            "label": f"{player} {item['year']}",
                            "value": round(float(item["economy_rate"] or 0), 2),
                        }
                        for player, trend in trends.items()
                        for item in trend
                    ],
                )
            ],
            evidence_queries=[evidence_query],
            metric_references=[MetricReference(metric_id=m.metric_id, label=m.label, formula=m.formula, unit=m.unit) for m in metrics],
            citations=[database_citation("Player bowling year trend comparison", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(
                    title="Comparison basis",
                    detail=(
                        "This comparison keeps the prior trend context: it filters on `bowl` for both players and keeps the same phase filter. "
                        "Aggregate rates are recomputed from raw legal balls, runs, wickets, dots, and boundaries across the fetched years."
                    ),
                ),
                EvidenceNote(
                    title="Small-sample caution",
                    detail="Year-by-year death-over samples can be small, so read economy and boundary rate beside legal balls.",
                ),
            ],
        )

    @staticmethod
    def _explicit_year_by_year_request(question: str) -> bool:
        lowered = question.lower()
        return any(
            token in lowered
            for token in (
                "year by year",
                "year-by-year",
                "year wise",
                "year-wise",
                "by year",
                "season by season",
            )
        )

    @staticmethod
    def _bowling_trend_totals(trend: list[dict[str, object]]) -> dict[str, object]:
        player_name = str(trend[0].get("player_name") or "")
        matches = sum(int(item.get("matches") or 0) for item in trend)
        innings = sum(int(item.get("innings") or 0) for item in trend)
        balls = sum(int(item.get("balls_bowled") or 0) for item in trend)
        runs = sum(int(item.get("runs_conceded") or 0) for item in trend)
        wickets = sum(int(item.get("wickets") or 0) for item in trend)
        dots = sum(int(item.get("dot_balls") or 0) for item in trend)
        boundaries = sum(int(item.get("boundary_balls") or 0) for item in trend)
        overs = balls / 6.0 if balls else None
        return {
            "player_name": player_name,
            "years": len(trend),
            "matches": matches,
            "innings": innings,
            "balls_bowled": balls,
            "overs": overs,
            "runs_conceded": runs,
            "wickets": wickets,
            "economy_rate": (runs / overs) if overs else None,
            "bowling_average": (runs / wickets) if wickets else None,
            "balls_per_wicket": (balls / wickets) if wickets else None,
            "dot_percentage": (dots / balls * 100.0) if balls else None,
            "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
            "balls_per_boundary": (balls / boundaries) if boundaries else None,
        }

    @staticmethod
    def _bowling_trend_totals_matrix(totals: dict[str, dict[str, object]]) -> TableBlock:
        metric_rows: list[tuple[str, str, int]] = [
            ("Years", "years", 0),
            ("Matches", "matches", 0),
            ("Bowling Innings", "innings", 0),
            ("Legal Balls", "balls_bowled", 0),
            ("Overs", "overs", 2),
            ("Runs Conceded", "runs_conceded", 0),
            ("Wickets", "wickets", 0),
            ("Economy", "economy_rate", 2),
            ("Bowling Average", "bowling_average", 2),
            ("Balls/Wicket", "balls_per_wicket", 2),
            ("Dot %", "dot_percentage", 2),
            ("Boundary %", "boundary_percentage", 2),
            ("Balls/Boundary", "balls_per_boundary", 2),
        ]
        players = list(totals.keys())
        rows: list[list[str | int | float | None]] = []
        for label, key, digits in metric_rows:
            row: list[str | int | float | None] = [label]
            for player in players:
                value = totals[player].get(key)
                row.append(round(value, digits) if isinstance(value, float) else value)
            rows.append(row)
        return TableBlock(
            title="Aggregate bowling trend comparison",
            columns=["Metric", *players],
            rows=rows,
        )

    def _bowling_year_trend_evidence_query(
        self,
        player: str,
        trend: list[dict[str, object]],
        phase: object,
    ) -> EvidenceQueryBlock:
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        sql = f"""
SELECT
  TRY_CAST(year AS INTEGER) AS year,
  COUNT(DISTINCT p_match) AS matches,
  COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bowl AS VARCHAR)) AS bowling_innings,
  SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
  COUNT(*) AS delivery_rows,
  SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
  SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
  SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
  SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
FROM analytics.deliveries_v1
WHERE bowl = :player
  AND TRY_CAST(year AS INTEGER) IS NOT NULL
{self._phase_sql_predicate(phase)}
GROUP BY year
ORDER BY year
""".strip()
        return EvidenceQueryBlock(
            title="Bowling year trend source",
            description="Year-by-year bowling rows used for economy, wickets, dots, and boundary prevention.",
            sql=sql,
            parameters=[player],
            table=TableBlock(
                title="Fetched bowling year trend",
                columns=[
                    "Year",
                    "Matches",
                    "Bowling Innings",
                    "Legal Balls",
                    "Overs",
                    "Runs Conceded",
                    "Wickets",
                    "Economy",
                    "Bowling Average",
                    "Balls/Wicket",
                    "Dot %",
                    "Boundary %",
                    "Balls/Boundary",
                    "Delivery Rows",
                ],
                rows=[
                    [
                        item["year"],
                        item["matches"],
                        item["innings"],
                        item["balls_bowled"],
                        round(float(item["overs"]), 2) if item.get("overs") is not None else None,
                        item["runs_conceded"],
                        item["wickets"],
                        round(float(item["economy_rate"]), 2) if item.get("economy_rate") is not None else None,
                        round(float(item["bowling_average"]), 2) if item.get("bowling_average") is not None else None,
                        round(float(item["balls_per_wicket"]), 2) if item.get("balls_per_wicket") is not None else None,
                        round(float(item["dot_percentage"]), 2) if item.get("dot_percentage") is not None else None,
                        round(float(item["boundary_percentage"]), 2) if item.get("boundary_percentage") is not None else None,
                        round(float(item["balls_per_boundary"]), 2) if item.get("balls_per_boundary") is not None else None,
                        item["delivery_rows"],
                    ]
                    for item in trend
                ],
            ),
        )

    def _bowling_year_trend_comparison_evidence_query(
        self,
        trends: dict[str, list[dict[str, object]]],
        phase: object,
    ) -> EvidenceQueryBlock:
        players = list(trends.keys())
        single_player_query = self._bowling_year_trend_evidence_query(":players", [], phase)
        sql = (
            single_player_query.sql
            .replace("SELECT\n  TRY_CAST(year AS INTEGER) AS year,", "SELECT\n  bowl AS player,\n  TRY_CAST(year AS INTEGER) AS year,")
            .replace("WHERE bowl = :player", "WHERE bowl IN (:players)")
            .replace("GROUP BY year\nORDER BY year", "GROUP BY bowl, year\nORDER BY bowl, year")
        )
        trend_by_player_year = {
            player: {int(item["year"]): item for item in trend}
            for player, trend in trends.items()
        }
        years = sorted({year for player_trend in trend_by_player_year.values() for year in player_trend})
        columns = ["Year"]
        for player in players:
            columns.extend(
                [
                    f"{player} Matches",
                    f"{player} Innings",
                    f"{player} Legal Balls",
                    f"{player} Wickets",
                    f"{player} Economy",
                    f"{player} Dot %",
                    f"{player} Boundary %",
                ]
            )
        rows: list[list[str | int | float | None]] = []
        for year in years:
            row: list[str | int | float | None] = [year]
            for player in players:
                item = trend_by_player_year[player].get(year)
                if item is None:
                    row.extend([None, None, None, None, None, None, None])
                    continue
                row.extend(
                    [
                        item["matches"],
                        item["innings"],
                        item["balls_bowled"],
                        item["wickets"],
                        round(float(item["economy_rate"]), 2) if item.get("economy_rate") is not None else None,
                        round(float(item["dot_percentage"]), 2) if item.get("dot_percentage") is not None else None,
                        round(float(item["boundary_percentage"]), 2) if item.get("boundary_percentage") is not None else None,
                    ]
                )
            rows.append(row)
        return EvidenceQueryBlock(
            title="Bowling year trend comparison source",
            description="Year-aligned bowling comparison rows for both players, using the same phase and bowler filters.",
            sql=sql,
            parameters=players,
            table=TableBlock(
                title="Year-by-year bowling trend comparison",
                columns=columns,
                rows=rows,
            ),
        )

    def _match_venue(self, question: str) -> str | None:
        lowered = question.lower()
        question_tokens = self._venue_match_tokens(lowered)
        best_match: tuple[float, str] | None = None
        for venue in self.available_venues:
            venue_tokens = self._venue_match_tokens(venue)
            if not venue_tokens:
                continue
            if venue.lower() in lowered or lowered in venue.lower():
                return venue
            overlap = len(question_tokens & venue_tokens)
            if overlap == 0:
                continue
            score = overlap / len(venue_tokens)
            if best_match is None or score > best_match[0]:
                best_match = (score, venue)
        if best_match and best_match[0] >= 0.5:
            return best_match[1]
        return None

    def _venue_match_tokens(self, value: str) -> set[str]:
        generic_tokens = {
            "cricket",
            "ground",
            "grounds",
            "stadium",
            "oval",
            "club",
            "county",
            "sports",
            "sport",
            "complex",
            "international",
        }
        tokens: set[str] = set()
        for token in re.findall(r"[a-z0-9]+", value.lower()):
            if len(token) < 3:
                continue
            normalized = token[:-1] if token.endswith("s") and len(token) > 4 else token
            if normalized not in generic_tokens:
                tokens.add(normalized)
        return tokens

    @staticmethod
    def _has_venue_intent(question: str) -> bool:
        lowered = question.lower()
        if any(token in lowered for token in (" venue", " ground", " stadium", " oval", "lord's", "lords")):
            return True
        return bool(re.search(r"\b(?:at|in)\s+[a-z0-9'][a-z0-9' .,-]{2,}$", lowered))

    @staticmethod
    def _apply_year_filter(trend: list[dict[str, object]], filters: dict[str, object]) -> list[dict[str, object]]:
        years = filters.get("years")
        if not years:
            return trend

        pivot_year = min(int(year) for year in years)
        mode = filters.get("year_mode")
        if mode == "after":
            return [item for item in trend if int(item["year"]) >= pivot_year]
        if mode == "before":
            return [item for item in trend if int(item["year"]) <= pivot_year]
        return [item for item in trend if int(item["year"]) in {int(year) for year in years}]
