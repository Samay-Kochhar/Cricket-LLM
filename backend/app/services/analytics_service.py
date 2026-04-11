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
    QueryInterpretation,
    QueryResponse,
    SummaryBlock,
    TableBlock,
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

    def _handle_role_comparison(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if not route.entities:
            return self._insufficient(
                interpretation,
                "No supported ODI player entity could be resolved from the question.",
                ["Ask with a full player name present in the ODI dataset."],
            )
        summaries = []
        for player in route.entities[:2]:
            summary = self.repository.get_player_batting_summary(player)
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
                        f"{player} has {summary['runs_scored']} runs from {summary['balls_faced']} balls "
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
                        f"{strike_rate_leader['player_name']} leads strike rate at "
                        f"{strike_rate_leader['strike_rate']:.2f}, while {control_leader['player_name']} "
                        f"has the better control rate at {(control_leader['control_percentage'] or 0):.2f}%."
                    ),
                )
            ]
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
                    title="Strike rate comparison",
                    chart_type="bar",
                    series=[{"label": summary["player_name"], "value": round(summary["strike_rate"] or 0, 2)} for summary in summaries],
                )
            ],
            metric_references=[MetricReference(metric_id=m.metric_id, label=m.label, formula=m.formula, unit=m.unit) for m in metrics],
            citations=[database_citation("ODI batting summary", "analytics.deliveries_v1")],
            evidence_notes=[EvidenceNote(title="Interpretation basis", detail="This answer is derived entirely from the local ODI dataset.")],
        )

    def _handle_strengths_weaknesses(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if not route.entities:
            return self._insufficient(
                interpretation,
                "A player name is required for strengths and weaknesses analysis.",
                ["Ask with a full player name, for example: Where does Hardik Pandya score the most?"],
            )
        player = route.entities[0]
        shot_breakdown = self.repository.get_player_shot_breakdown(player)
        if not shot_breakdown:
            return self._insufficient(
                interpretation,
                f"The ODI dataset does not contain enough shot-level evidence for {player}.",
                ["Try another ODI batter or use a trend question."],
            )
        top_shot = shot_breakdown[0]
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{player} shot profile",
                    body=f"{player}'s highest-yield recorded shot is {top_shot['shot']} with {top_shot['runs']} runs.",
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
            citations=[database_citation("ODI shot breakdown", "analytics.deliveries_v1.shot")],
            metric_references=[
                MetricReference(
                    metric_id="shot_share_percentage",
                    label="Shot Share Percentage",
                    formula=self.metric_catalog.get("shot_share_percentage").formula,
                    unit="percent",
                )
            ],
        )

    def _handle_matchup(self, interpretation: QueryInterpretation, route: QueryRoute) -> QueryResponse:
        if len(route.entities) < 2:
            return self._insufficient(
                interpretation,
                "A matchup requires two ODI player entities in the question.",
                ["Try: Bumrah vs Steven Smith in ODIs."],
            )
        batter_name, bowler_name = route.entities[0], route.entities[1]
        matchup = self.repository.get_matchup_summary(batter_name, bowler_name)
        if matchup is None:
            return self._insufficient(
                interpretation,
                f"No direct ODI matchup was found for {batter_name} against {bowler_name}.",
                ["Try another ODI batter-versus-bowler pairing."],
            )
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=interpretation,
            summaries=[
                SummaryBlock(
                    title=f"{batter_name} vs {bowler_name}",
                    body=(
                        f"{batter_name} scored {matchup['runs_scored']} runs from {matchup['balls']} balls "
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
            citations=[database_citation("Direct ODI matchup", "analytics.deliveries_v1 bat/bowl pairing")],
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
            citations=[database_citation("Player year trend", "analytics.player_year_batting")],
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
