from __future__ import annotations

from backend.app.domain.metric_models import MetricDefinition, QueryClass


CATALOG: dict[str, MetricDefinition] = {
    "balls_faced": MetricDefinition(
        metric_id="balls_faced",
        label="Balls Faced",
        formula="COUNT(*) where player is batter",
        description="Total recorded balls faced by the batter in the selected sample.",
        unit="balls",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["bat"],
    ),
    "balls_bowled": MetricDefinition(
        metric_id="balls_bowled",
        label="Legal Balls Bowled",
        formula="SUM(CASE WHEN wide = 0 AND noball = 0 THEN 1 ELSE 0 END) where player is bowler",
        description="Legal balls bowled by the bowler in the selected sample.",
        unit="balls",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["bowl", "wide", "noball"],
    ),
    "overs_bowled": MetricDefinition(
        metric_id="overs_bowled",
        label="Overs Bowled",
        formula="legal balls bowled / 6.0",
        description="Overs bowled by the bowler in the selected sample.",
        unit="overs",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["bowl", "wide", "noball"],
    ),
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
    "strike_rate_improvement_after_20": MetricDefinition(
        metric_id="strike_rate_improvement_after_20",
        label="Strike Rate Improvement After 20 Balls",
        formula="SR after ball 20 - SR from balls 1-20",
        description="Change in batting strike rate once a batter has faced more than 20 balls.",
        unit="strike_rate_points",
        supported_query_classes=[QueryClass.venue_context_leaderboard],
        required_fields=["cur_bat_bf", "batruns", "ballfaced"],
    ),
    "milestone_vulnerability_lift": MetricDefinition(
        metric_id="milestone_vulnerability_lift",
        label="Milestone Vulnerability Lift",
        formula="post-milestone dismissal % - normal set-batter dismissal %",
        description="How much more often a batter is dismissed immediately after reaching 50 or 100 than in normal set-batter balls.",
        unit="percentage_points",
        supported_query_classes=[QueryClass.venue_context_leaderboard],
        required_fields=["cur_bat_runs", "cur_bat_bf", "batruns", "ballfaced", "out"],
    ),
    "batting_average": MetricDefinition(
        metric_id="batting_average",
        label="Batting Average",
        formula="SUM(batruns) / NULLIF(SUM(CASE WHEN LOWER(out) = 'true' THEN 1 ELSE 0 END), 0)",
        description="Runs scored per dismissal in the selected batting sample.",
        unit="runs_per_dismissal",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns", "out"],
    ),
    "dismissals": MetricDefinition(
        metric_id="dismissals",
        label="Dismissals",
        formula="SUM(CASE WHEN LOWER(out) = 'true' THEN 1 ELSE 0 END)",
        description="Dismissals recorded on the selected ball set.",
        unit="dismissals",
        supported_query_classes=[
            QueryClass.role_comparison,
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
    "dot_percentage": MetricDefinition(
        metric_id="dot_percentage",
        label="Dot Ball Percentage",
        formula="SUM(CASE WHEN batruns = 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100",
        description="Share of balls where the batter scored zero runs.",
        unit="percent",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
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
            QueryClass.role_comparison,
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
            QueryClass.trend_progression,
        ],
        required_fields=["control"],
    ),
    "economy_rate": MetricDefinition(
        metric_id="economy_rate",
        label="Economy Rate",
        formula="SUM(bowlruns) / NULLIF(legal balls / 6.0, 0)",
        description="Runs conceded per over.",
        unit="runs_per_over",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["bowlruns", "wide", "noball"],
    ),
    "runs_conceded": MetricDefinition(
        metric_id="runs_conceded",
        label="Runs Conceded",
        formula="SUM(bowlruns)",
        description="Runs charged to the bowler in the selected sample.",
        unit="runs",
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
        formula="SUM(CASE WHEN dismissal is credited to bowler THEN 1 ELSE 0 END)",
        description="Number of wickets credited to the bowler in the selected bowling set.",
        unit="wickets",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["dismissal"],
    ),
    "bowler_dot_percentage": MetricDefinition(
        metric_id="bowler_dot_percentage",
        label="Bowler Dot Ball Percentage",
        formula=(
            "SUM(CASE WHEN legal ball AND bowlruns = 0 THEN 1 ELSE 0 END) / "
            "NULLIF(SUM(CASE WHEN legal ball THEN 1 ELSE 0 END), 0) * 100"
        ),
        description="Share of legal balls where the bowler conceded no runs charged to the bowler.",
        unit="percent",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["bowlruns", "wide", "noball"],
    ),
    "dot_balls": MetricDefinition(
        metric_id="dot_balls",
        label="Dot Balls",
        formula="SUM(CASE WHEN batruns = 0 THEN 1 ELSE 0 END)",
        description="Balls where the batter scored zero runs in the selected sample.",
        unit="balls",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns"],
    ),
    "bowler_dot_balls": MetricDefinition(
        metric_id="bowler_dot_balls",
        label="Bowler Dot Balls",
        formula="SUM(CASE WHEN legal ball AND bowlruns = 0 THEN 1 ELSE 0 END)",
        description="Legal balls where the bowler conceded no runs charged to the bowler.",
        unit="balls",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["bowlruns", "wide", "noball"],
    ),
    "yorker_percentage": MetricDefinition(
        metric_id="yorker_percentage",
        label="Yorker Percentage",
        formula="SUM(CASE WHEN legal ball AND length = 'YORKER' THEN 1 ELSE 0 END) / NULLIF(legal balls, 0) * 100",
        description="Share of a bowler's legal deliveries recorded as yorkers.",
        unit="percent",
        supported_query_classes=[
            QueryClass.venue_context_leaderboard,
            QueryClass.role_comparison,
        ],
        required_fields=["bowl", "length", "wide", "noball"],
    ),
    "boundaries": MetricDefinition(
        metric_id="boundaries",
        label="Boundaries",
        formula="SUM(CASE WHEN batruns IN (4, 6) THEN 1 ELSE 0 END)",
        description="Balls hit for four or six by the batter in the selected sample.",
        unit="boundaries",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.strengths_weaknesses,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns"],
    ),
    "boundaries_conceded": MetricDefinition(
        metric_id="boundaries_conceded",
        label="Boundaries Conceded",
        formula="SUM(CASE WHEN legal ball AND batruns IN (4, 6) THEN 1 ELSE 0 END)",
        description="Legal balls bowled that were hit for four or six.",
        unit="boundaries",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns", "wide", "noball"],
    ),
    "balls_per_wicket": MetricDefinition(
        metric_id="balls_per_wicket",
        label="Balls Per Wicket",
        formula="legal balls / NULLIF(bowler-credit wickets, 0)",
        description="Legal balls bowled per wicket credited to the bowler.",
        unit="balls_per_wicket",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["wide", "noball", "dismissal"],
    ),
    "balls_per_boundary": MetricDefinition(
        metric_id="balls_per_boundary",
        label="Balls Per Boundary",
        formula="legal balls / NULLIF(legal balls with batruns IN (4, 6), 0)",
        description="Legal balls bowled per boundary conceded from the bat.",
        unit="balls_per_boundary",
        supported_query_classes=[
            QueryClass.role_comparison,
            QueryClass.head_to_head_matchup,
            QueryClass.venue_context_leaderboard,
            QueryClass.trend_progression,
        ],
        required_fields=["batruns", "wide", "noball"],
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
