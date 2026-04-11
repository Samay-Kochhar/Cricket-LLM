from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.evidence_models import (
    ChartBlock,
    Citation,
    CitationSource,
    EvidenceNote,
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
        interpretation = QueryInterpretation(
            original_question=question,
            query_class=route.query_class.value,
            entities=list(route.entities),
            filters=route.filters,
        )
        handler_map = {
            QueryClass.role_comparison: self._handle_role_comparison,
            QueryClass.strengths_weaknesses: self._handle_strengths_weaknesses,
            QueryClass.head_to_head_matchup: self._handle_matchup,
            QueryClass.venue_context_leaderboard: self._handle_venue_context,
            QueryClass.trend_progression: self._handle_trend,
        }
        return handler_map[route.query_class](interpretation, route)

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
        if phase == "powerplay":
            return "powerplay"
        if phase == "middle":
            return "middle overs"
        if phase == "death":
            return "death overs"
        return "all phases"

    def _handle_role_comparison(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if not route.entities:
            return self._insufficient(
                interpretation,
                "No supported ODI player entity could be resolved from the question.",
                ["Ask with a full player name present in the ODI dataset."],
            )
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
            self.metric_catalog.get("batting_strike_rate"),
            self.metric_catalog.get("boundary_percentage"),
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
                    body=(
                        f"In {phase_label}, {strike_rate_leader['player_name']} leads strike rate at "
                        f"{strike_rate_leader['strike_rate']:.2f}, while {control_leader['player_name']} "
                        f"has the better control rate at {(control_leader['control_percentage'] or 0):.2f}%."
                    ),
                )
            ]
        benchmark_player = summaries[1]["player_name"] if len(summaries) > 1 else None
        visuals, coverage_notes = self._build_batter_visuals(
            summaries[0]["player_name"],
            benchmark_player=benchmark_player,
            phase=phase,
        )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=summary_blocks,
            tables=[
                TableBlock(
                    title="Primary batting metrics",
                    columns=["Player", "Runs", "Balls", "Strike Rate", "Boundary %", "Control %"],
                    rows=[
                        [
                            summary["player_name"],
                            summary["runs_scored"],
                            summary["balls_faced"],
                            round(summary["strike_rate"] or 0, 2),
                            round(summary["boundary_percentage"] or 0, 2),
                            round(summary["control_percentage"] or 0, 2),
                        ]
                        for summary in summaries
                    ],
                )
            ],
            charts=[
                ChartBlock(
                    title=f"Strike rate comparison ({phase_label})",
                    chart_type="bar",
                    series=[{"label": summary["player_name"], "value": round(summary["strike_rate"] or 0, 2)} for summary in summaries],
                )
            ],
            visuals=visuals,
            metric_references=[MetricReference(metric_id=m.metric_id, label=m.label, formula=m.formula, unit=m.unit) for m in metrics],
            citations=[database_citation("ODI batting summary", "analytics.deliveries_v1")],
            evidence_notes=[
                EvidenceNote(title="Interpretation basis", detail=f"This answer is derived entirely from the local ODI dataset for {phase_label}."),
                *coverage_notes,
            ],
        )

    def _handle_strengths_weaknesses(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
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
        visuals, coverage_notes = self._build_batter_visuals(player, phase=phase)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} shot profile",
                    body=f"In {phase_label}, {player}'s highest-yield recorded shot is {top_shot['shot']} with {top_shot['runs']} runs.",
                )
            ],
            tables=[
                TableBlock(
                    title="Top scoring shots",
                    columns=["Shot", "Balls", "Runs"],
                    rows=[[item["shot"], item["balls"], item["runs"]] for item in shot_breakdown],
                )
            ],
            charts=[ChartBlock(title="Runs by shot", chart_type="bar", series=[{"label": item["shot"], "value": item["runs"]} for item in shot_breakdown[:6]])],
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
        question = interpretation.original_question.lower()
        venue_name = self._match_venue(question)
        if venue_name is None:
            return self._insufficient(
                interpretation,
                "A recognizable ODI venue is required for the current venue leaderboard response.",
                ["Try naming the ground explicitly."],
            )
        interpretation = interpretation.model_copy(
            update={"filters": {**interpretation.filters, "venue_name": venue_name}}
        )
        leaderboard = self.repository.get_venue_bowling_leaderboard(venue_name)
        if not leaderboard:
            return self._insufficient(
                interpretation,
                f"No venue leaderboard could be built for {venue_name}.",
                ["Try another ODI venue with more match data."],
            )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[SummaryBlock(title=f"Top ODI bowlers at {venue_name}", body="The leaderboard is ranked by wickets with a delivery threshold.")],
            tables=[
                TableBlock(
                    title="Venue bowling leaderboard",
                    columns=["Bowler", "Deliveries", "Runs Conceded", "Wickets", "Economy"],
                    rows=[[row["player_name"], row["deliveries"], row["runs_conceded"], row["wickets"], round(row["economy_rate"] or 0, 2)] for row in leaderboard],
                )
            ],
            charts=[ChartBlock(title="Wickets at venue", chart_type="bar", series=[{"label": row["player_name"], "value": row["wickets"]} for row in leaderboard[:5]])],
            citations=[database_citation("Venue leaderboard", "analytics.deliveries_v1.ground")],
        )

    def _handle_trend(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if not route.entities:
            return self._insufficient(
                interpretation,
                "A player entity is required for trend analysis.",
                ["Try: Has Shimron Hetmyer become more destructive over time?"],
            )
        player = route.entities[0]
        trend = self.repository.get_player_year_trend(player)
        if not trend:
            return self._insufficient(
                interpretation,
                f"No year-level ODI trend data was found for {player}.",
                ["Try another ODI player with year-by-year batting data."],
            )
        trend = self._apply_year_filter(trend, route.filters)
        if not trend:
            return self._insufficient(
                interpretation,
                f"The ODI dataset does not contain enough year-level data for the requested time filter on {player}.",
                ["Relax the year filter or ask for the player's full ODI trend."],
            )
        phase = route.filters.get("phase")
        visuals, coverage_notes = self._build_batter_visuals(player, phase=phase)
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} year-by-year trend",
                    body=(
                        f"The filtered ODI trend view covers {len(trend)} recorded years "
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

    def _match_venue(self, question: str) -> str | None:
        lowered = question.lower()
        question_tokens = self.repository._tokenize(lowered)
        best_match: tuple[float, str] | None = None
        for venue in self.available_venues:
            venue_tokens = self.repository._tokenize(venue)
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
