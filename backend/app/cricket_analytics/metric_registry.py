from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


MetricOwner = Literal["batter", "bowler", "team", "batter_or_bowler"]
SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class SamplePolicy:
    balls: int | None = None
    legal_balls: int | None = None
    innings: int | None = None

    def as_dict(self) -> dict[str, int]:
        return {
            key: value
            for key, value in {
                "balls": self.balls,
                "legal_balls": self.legal_balls,
                "innings": self.innings,
            }.items()
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class MetricRule:
    metric_id: str
    label: str
    owner: MetricOwner
    numerator: str
    denominator: str | None
    aggregation: Literal["count", "sum", "rate", "percentage", "derived"]
    default_sort: SortDirection
    higher_is_better: bool | None
    minimum_sample: SamplePolicy = field(default_factory=SamplePolicy)
    allowed_filters: frozenset[str] = frozenset()
    allowed_groupings: frozenset[str] = frozenset()
    sql_expression: str = ""
    result_field: str = ""
    unit: str | None = None
    formula: str = ""


COMMON_FILTERS = frozenset(
    {
        "batter",
        "bowler",
        "team",
        "batting_team",
        "bowling_team",
        "phase",
        "line",
        "length",
        "shot_type",
        "field_zone",
        "bowling_style",
        "batter_hand",
        "bowler_hand",
        "venue",
        "opposition",
        "innings",
        "over_range",
        "years",
        "year_mode",
        "competition",
    }
)
COMMON_GROUPINGS = frozenset(
    {
        "batter",
        "bowler",
        "team",
        "batting_team",
        "bowling_team",
        "phase",
        "line",
        "length",
        "shot_type",
        "field_zone",
        "bowling_style",
        "batter_hand",
        "bowler_hand",
        "venue",
        "innings",
        "matchup",
    }
)


def _rule(
    metric_id: str,
    label: str,
    owner: MetricOwner,
    numerator: str,
    denominator: str | None,
    aggregation: Literal["count", "sum", "rate", "percentage", "derived"],
    default_sort: SortDirection,
    higher_is_better: bool | None,
    sql_expression: str,
    *,
    minimum_sample: SamplePolicy | None = None,
    unit: str | None = None,
    formula: str | None = None,
) -> MetricRule:
    return MetricRule(
        metric_id=metric_id,
        label=label,
        owner=owner,
        numerator=numerator,
        denominator=denominator,
        aggregation=aggregation,
        default_sort=default_sort,
        higher_is_better=higher_is_better,
        minimum_sample=minimum_sample or SamplePolicy(),
        allowed_filters=COMMON_FILTERS,
        allowed_groupings=COMMON_GROUPINGS,
        sql_expression=sql_expression,
        result_field=metric_id,
        unit=unit,
        formula=formula or sql_expression,
    )


METRIC_REGISTRY: dict[str, MetricRule] = {
    "runs_scored": _rule("runs_scored", "Runs Scored", "batter", "runs_scored", None, "sum", "desc", True, "runs_scored", unit="runs", formula="sum batter runs"),
    "balls_faced": _rule("balls_faced", "Balls Faced", "batter", "balls_faced", None, "count", "desc", None, "balls_faced", unit="balls", formula="count balls faced"),
    "batting_strike_rate": _rule("batting_strike_rate", "Batting Strike Rate", "batter", "runs_scored", "balls_faced", "rate", "desc", True, "runs_scored / NULLIF(balls_faced, 0) * 100.0", minimum_sample=SamplePolicy(balls=20), unit="runs per 100 balls", formula="runs scored / balls faced * 100"),
    "batting_average": _rule("batting_average", "Batting Average", "batter", "runs_scored", "dismissals", "rate", "desc", True, "runs_scored / NULLIF(dismissals, 0)", unit="runs per dismissal", formula="runs scored / dismissals"),
    "runs_conceded": _rule("runs_conceded", "Runs Conceded", "bowler", "runs_conceded", None, "sum", "asc", False, "runs_conceded", unit="runs", formula="sum bowler runs conceded"),
    "legal_balls": _rule("legal_balls", "Legal Balls", "bowler", "legal_balls", None, "count", "desc", None, "legal_balls", unit="balls", formula="count legal balls"),
    "overs_bowled": _rule("overs_bowled", "Overs Bowled", "bowler", "legal_balls", "6", "derived", "desc", None, "legal_balls / 6.0", unit="overs", formula="legal balls / 6"),
    "wickets_taken": _rule("wickets_taken", "Wickets Taken", "bowler", "wickets", None, "sum", "desc", True, "wickets", unit="wickets", formula="sum bowler-credit wickets"),
    "economy_rate": _rule("economy_rate", "Economy Rate", "bowler", "runs_conceded", "legal_balls", "rate", "asc", False, "runs_conceded / NULLIF(legal_balls / 6.0, 0)", minimum_sample=SamplePolicy(legal_balls=24), unit="runs per over", formula="runs conceded / legal overs"),
    "bowling_average": _rule("bowling_average", "Bowling Average", "bowler", "runs_conceded", "wickets", "rate", "asc", False, "runs_conceded / NULLIF(wickets, 0)", minimum_sample=SamplePolicy(legal_balls=24), unit="runs per wicket", formula="runs conceded / wickets"),
    "batter_dot_ball_percentage": _rule("batter_dot_ball_percentage", "Batter Dot Ball Percentage", "batter", "dot_balls", "balls_faced", "percentage", "asc", False, "dot_balls / NULLIF(sample_balls, 0) * 100.0", minimum_sample=SamplePolicy(balls=20), unit="percent", formula="batter dot balls / balls faced * 100"),
    "bowler_dot_ball_percentage": _rule("bowler_dot_ball_percentage", "Bowler Dot Ball Percentage", "bowler", "bowler_dot_balls", "legal_balls", "percentage", "desc", True, "bowler_dot_balls / NULLIF(legal_balls, 0) * 100.0", minimum_sample=SamplePolicy(legal_balls=24), unit="percent", formula="bowler dot balls / legal balls * 100"),
    "dot_balls": _rule("dot_balls", "Dot Balls", "batter", "dot_balls", None, "count", "desc", None, "dot_balls", unit="balls", formula="count batter balls with zero bat runs"),
    "bowler_dot_balls": _rule("bowler_dot_balls", "Bowler Dot Balls", "bowler", "bowler_dot_balls", None, "count", "desc", True, "bowler_dot_balls", unit="balls", formula="count legal balls with zero bowler runs"),
    "boundary_percentage": _rule("boundary_percentage", "Boundary Percentage", "batter_or_bowler", "boundary_balls", "balls", "percentage", "desc", True, "boundary_balls / NULLIF(sample_balls, 0) * 100.0", minimum_sample=SamplePolicy(balls=20), unit="percent", formula="boundary balls / sample balls * 100"),
    "false_shot_percentage": _rule("false_shot_percentage", "False Shot Percentage", "batter_or_bowler", "false_shots", "balls", "percentage", "desc", None, "false_shots / NULLIF(sample_balls, 0) * 100.0", minimum_sample=SamplePolicy(balls=60), unit="percent", formula="false shots / sample balls * 100"),
    "dismissals": _rule("dismissals", "Dismissals", "batter_or_bowler", "dismissals", None, "count", "desc", None, "dismissals", unit="dismissals", formula="count dismissals"),
    "yorker_count": _rule("yorker_count", "Yorker Count", "bowler", "yorker_balls", None, "count", "desc", True, "yorker_balls", unit="balls", formula="count legal yorkers"),
    "yorker_percentage": _rule("yorker_percentage", "Yorker Percentage", "bowler", "yorker_balls", "legal_balls", "percentage", "desc", True, "yorker_balls / NULLIF(legal_balls, 0) * 100.0", minimum_sample=SamplePolicy(legal_balls=24), unit="percent", formula="legal yorkers / legal balls * 100"),
    "wickets_per_over": _rule("wickets_per_over", "Wickets Per Over", "bowler", "wickets", "legal_balls", "rate", "desc", True, "wickets / NULLIF(legal_balls / 6.0, 0)", minimum_sample=SamplePolicy(legal_balls=24), unit="wickets per over", formula="wickets / legal overs"),
    "false_shots_per_over": _rule("false_shots_per_over", "False Shots Per Over", "bowler", "false_shots", "legal_balls", "rate", "desc", True, "false_shots / NULLIF(legal_balls / 6.0, 0)", minimum_sample=SamplePolicy(legal_balls=24), unit="false shots per over", formula="false shots / legal overs"),
}

MIGRATED_METRIC_IDS = tuple(METRIC_REGISTRY)

LEGACY_METRIC_ALIASES = {
    "dot_percentage": "batter_dot_ball_percentage",
    "bowler_dot_percentage": "bowler_dot_ball_percentage",
    "wickets": "wickets_taken",
    "balls_bowled": "legal_balls",
    "dot_ball_percentage": "batter_dot_ball_percentage",
}


def canonical_metric_id(metric_id: str, *, entity: str | None = None, filters: dict[str, object] | None = None) -> str:
    if metric_id == "dot_ball_percentage":
        if entity == "bowler" or (filters and "bowler" in filters and "batter" not in filters):
            return "bowler_dot_ball_percentage"
        return "batter_dot_ball_percentage"
    return LEGACY_METRIC_ALIASES.get(metric_id, metric_id)


def get_metric(metric_id: str, *, entity: str | None = None, filters: dict[str, object] | None = None) -> MetricRule:
    canonical = canonical_metric_id(metric_id, entity=entity, filters=filters)
    return METRIC_REGISTRY[canonical]


def metric_sql_expression(metric_id: str, *, entity: str | None = None, filters: dict[str, object] | None = None) -> str:
    rule = get_metric(metric_id, entity=entity, filters=filters)
    expression = rule.sql_expression
    return expression


def split_metric_expression(metric_id: str, *, entity: str | None = None) -> str:
    canonical = canonical_metric_id(metric_id, entity=entity)
    sample = "SUM(legal_balls)" if sample_denominator(metric_id, entity=entity) == "legal_balls" else "SUM(balls_faced)"
    expressions = {
        "runs_scored": "SUM(runs_scored)",
        "batting_strike_rate": "SUM(runs_scored) / NULLIF(SUM(balls_faced), 0) * 100.0",
        "economy_rate": "SUM(runs_conceded) / NULLIF(SUM(legal_balls) / 6.0, 0)",
        "batter_dot_ball_percentage": f"SUM(dot_balls) / NULLIF({sample}, 0) * 100.0",
        "bowler_dot_ball_percentage": "SUM(bowler_dot_balls) / NULLIF(SUM(legal_balls), 0) * 100.0",
        "boundary_percentage": f"SUM(boundary_balls) / NULLIF({sample}, 0) * 100.0",
        "dismissals": "SUM(dismissals)",
        "wickets_taken": "SUM(wickets)",
    }
    if metric_id == "run_rate":
        return "SUM(runs_scored) / NULLIF(SUM(legal_balls) / 6.0, 0)"
    if metric_id == "dismissal_rate":
        return f"SUM(dismissals) / NULLIF({sample}, 0) * 100.0"
    return expressions[canonical]


MATCHUP_OUTPUT_EXPRESSIONS = {
    "strike_rate": "runs / NULLIF(balls, 0) * 100.0",
    "dot_percentage": "dot_balls / NULLIF(balls, 0) * 100.0",
    "bowler_dot_percentage": "bowler_dot_balls / NULLIF(legal_balls, 0) * 100.0",
    "boundary_percentage": "boundary_balls / NULLIF(balls, 0) * 100.0",
    "false_shot_percentage": "false_shots / NULLIF(balls, 0) * 100.0",
    "dismissal_rate": "dismissals / NULLIF(balls, 0) * 100.0",
}


def matchup_projection_sql() -> list[str]:
    return [f"{expression} AS {alias}" for alias, expression in MATCHUP_OUTPUT_EXPRESSIONS.items()]


def one_sided_matchup_score_expression() -> tuple[str, str]:
    return (
        "(ABS(COALESCE({strike_rate}, 0) - 100.0) "
        "+ COALESCE({dot_percentage}, 0) "
        "+ COALESCE({boundary_percentage}, 0) "
        "+ COALESCE({dismissal_rate}, 0))"
    ).format(**MATCHUP_OUTPUT_EXPRESSIONS), (
        "one_sided_score = abs(strike_rate - 100) + dot_percentage + "
        "boundary_percentage + dismissal_rate"
    )


def matchup_sort_expression(metric_id: str, *, filters: dict[str, object] | None = None) -> tuple[str, str, str | None]:
    canonical = canonical_metric_id(metric_id, entity="batter", filters=filters)
    if canonical == "runs_scored":
        return "runs", "DESC", None
    if canonical == "balls_faced":
        return "balls", "DESC", None
    if canonical == "dismissals":
        return "dismissals", "DESC", None
    if canonical == "wickets_taken":
        return "wickets", "DESC", None
    if canonical == "batting_strike_rate":
        return MATCHUP_OUTPUT_EXPRESSIONS["strike_rate"], "DESC", None
    if canonical == "batter_dot_ball_percentage":
        return MATCHUP_OUTPUT_EXPRESSIONS["dot_percentage"], "DESC", None
    if canonical == "bowler_dot_ball_percentage":
        return MATCHUP_OUTPUT_EXPRESSIONS["bowler_dot_percentage"], "DESC", None
    if canonical == "boundary_percentage":
        return MATCHUP_OUTPUT_EXPRESSIONS["boundary_percentage"], "DESC", None
    if canonical == "false_shot_percentage":
        return MATCHUP_OUTPUT_EXPRESSIONS["false_shot_percentage"], "DESC", None
    if metric_id == "dismissal_rate":
        return MATCHUP_OUTPUT_EXPRESSIONS["dismissal_rate"], "DESC", None
    return "sample_size", "DESC", None


def sample_denominator(metric_id: str, *, entity: str | None = None, filters: dict[str, object] | None = None) -> str:
    canonical = canonical_metric_id(metric_id, entity=entity, filters=filters)
    rule = METRIC_REGISTRY.get(canonical)
    if rule and rule.denominator == "legal_balls":
        return "legal_balls"
    if canonical in {"legal_balls", "overs_bowled", "wickets_taken", "bowler_dot_balls"}:
        return "legal_balls"
    return "balls"


def percentage_metric_ids() -> set[str]:
    return {
        metric_id
        for metric_id, rule in METRIC_REGISTRY.items()
        if rule.aggregation == "percentage" or rule.unit == "percent"
    } | {"dot_ball_percentage", "dot_percentage", "bowler_dot_percentage", "dismissal_rate", "control_percentage"}
