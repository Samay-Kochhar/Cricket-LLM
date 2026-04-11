from __future__ import annotations

from backend.app.domain.metric_models import MetricDefinition, QueryClass


CATALOG: dict[str, MetricDefinition] = {
    "runs_scored": MetricDefinition(
        metric_id="runs_scored",
        label="Runs Scored",
        formula="SUM(batruns)",
        description="Total runs scored by the batter.",
        unit="runs",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns"],
    ),
    "batting_strike_rate": MetricDefinition(
        metric_id="batting_strike_rate",
        label="Batting Strike Rate",
        formula="SUM(batruns) / NULLIF(SUM(ballfaced), 0) * 100",
        description="Runs scored per 100 balls faced.",
        unit="sr",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns", "ballfaced"],
    ),
    "dismissals": MetricDefinition(
        metric_id="dismissals",
        label="Dismissals",
        formula="SUM(CASE WHEN LOWER(out) = 'true' THEN 1 ELSE 0 END)",
        description="Dismissals recorded on the selected ball set.",
        unit="dismissals",
        supported_query_classes=[
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
            QueryClass.trend_progression,
        ],
        required_fields=["out"],
    ),
    "boundary_percentage": MetricDefinition(
        metric_id="boundary_percentage",
        label="Boundary Percentage",
        formula="SUM(CASE WHEN batruns IN (4, 6) THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100",
        description="Share of balls that become boundaries.",
        unit="percent",
        supported_query_classes=[
            QueryClass.strengths_weaknesses,
            QueryClass.role_comparison,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns"],
    ),
    "control_percentage": MetricDefinition(
        metric_id="control_percentage",
        label="Control Percentage",
        formula="AVG(control) * 100",
        description="Average control score on a 0-1 scale turned into percentage.",
        unit="percent",
        supported_query_classes=[
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
            QueryClass.trend_progression,
        ],
        required_fields=["control"],
    ),
    "economy_rate": MetricDefinition(
        metric_id="economy_rate",
        label="Economy Rate",
        formula="SUM(bowlruns) / NULLIF(COUNT(*) / 6.0, 0)",
        description="Runs conceded per over.",
        unit="runs_per_over",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["bowlruns"],
    ),
    "wickets_taken": MetricDefinition(
        metric_id="wickets_taken",
        label="Wickets Taken",
        formula="SUM(CASE WHEN LOWER(out) = 'true' THEN 1 ELSE 0 END)",
        description="Number of dismissals recorded against the selected bowling set.",
        unit="wickets",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["out"],
    ),
    "shot_share_percentage": MetricDefinition(
        metric_id="shot_share_percentage",
        label="Shot Share Percentage",
        formula="COUNT(*) FILTER (WHERE shot = :shot_name) / NULLIF(COUNT(*), 0) * 100",
        description="Share of balls associated with a named shot category.",
        unit="percent",
        supported_query_classes=[
            QueryClass.strengths_weaknesses,
            QueryClass.trend_progression,
        ],
        required_fields=["shot"],
    ),
}


class MetricCatalog:
    def __init__(self, catalog: dict[str, MetricDefinition] | None = None) -> None:
        self._catalog = catalog or CATALOG

    def get(self, metric_id: str) -> MetricDefinition:
        if metric_id not in self._catalog:
            raise KeyError(f"Unknown metric: {metric_id}")
        return self._catalog[metric_id]

    def list_for_query_class(self, query_class: QueryClass) -> list[MetricDefinition]:
        return [
            definition
            for definition in self._catalog.values()
            if query_class in definition.supported_query_classes
        ]
