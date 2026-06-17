from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


EntityName = Literal["batter", "bowler", "team", "matchup", "innings", "venue"]
SortDirection = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class MinimumSample:
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
class MetricDefinition:
    name: str
    owner: str
    formula: str
    required_columns: tuple[str, ...]
    default_sort: SortDirection
    good_direction: SortDirection | None = None
    denominator: str | None = None
    minimum_sample: MinimumSample = field(default_factory=MinimumSample)
    unit: str | None = None


ENTITIES: dict[str, str] = {
    "batter": "A player facing balls and scoring runs.",
    "bowler": "A player delivering balls and conceding/creating outcomes.",
    "team": "A batting or bowling side.",
    "matchup": "A batter-vs-bowler or player-vs-style pairing.",
    "innings": "A team innings within a match.",
    "venue": "The ground where the match was played.",
}


DIMENSIONS: dict[str, str] = {
    "batter": "bat",
    "bowler": "bowl",
    "team": "team_bat or team_bowl depending on metric context",
    "batting_team": "team_bat",
    "bowling_team": "team_bowl",
    "phase": "derived from over",
    "line": "line",
    "length": "length",
    "shot_type": "shot",
    "field_zone": "derived from wagonZone and bat_hand",
    "bowling_style": "bowl_style",
    "batter_hand": "bat_hand",
    "bowler_hand": "derived from bowl_style",
    "venue": "ground",
    "innings": "inns",
    "over_range": "derived from over",
    "matchup": "bat and bowl",
}


METRICS: dict[str, MetricDefinition] = {
    "runs_scored": MetricDefinition(
        name="runs_scored",
        owner="batter",
        formula="SUM(batruns)",
        required_columns=("batruns", "bat"),
        default_sort="desc",
        good_direction="desc",
        unit="runs",
    ),
    "balls_faced": MetricDefinition(
        name="balls_faced",
        owner="batter",
        formula="SUM(ballfaced = 1)",
        required_columns=("ballfaced", "bat"),
        default_sort="desc",
        unit="balls",
    ),
    "batting_strike_rate": MetricDefinition(
        name="batting_strike_rate",
        owner="batter",
        formula="SUM(batruns) * 100 / legal balls faced",
        required_columns=("batruns", "ballfaced", "bat"),
        default_sort="desc",
        good_direction="desc",
        denominator="balls_faced",
        minimum_sample=MinimumSample(balls=20),
        unit="runs per 100 balls",
    ),
    "run_rate": MetricDefinition(
        name="run_rate",
        owner="team",
        formula="SUM(batruns) / legal overs batted",
        required_columns=("batruns", "wide", "noball", "team_bat"),
        default_sort="desc",
        good_direction="desc",
        denominator="legal_balls",
        minimum_sample=MinimumSample(legal_balls=24),
        unit="runs per over",
    ),
    "wickets": MetricDefinition(
        name="wickets",
        owner="bowler",
        formula="SUM(bowler-credit dismissal events)",
        required_columns=("dismissal", "bowl"),
        default_sort="desc",
        good_direction="desc",
        unit="wickets",
    ),
    "economy_rate": MetricDefinition(
        name="economy_rate",
        owner="bowler",
        formula="SUM(bowlruns) / legal overs",
        required_columns=("bowlruns", "wide", "noball", "bowl"),
        default_sort="asc",
        good_direction="asc",
        denominator="legal_balls",
        minimum_sample=MinimumSample(legal_balls=24),
        unit="runs per over",
    ),
    "dot_ball_percentage": MetricDefinition(
        name="dot_ball_percentage",
        owner="batter_or_bowler",
        formula="dot balls / legal balls * 100",
        required_columns=("batruns", "bowlruns", "ballfaced", "wide", "noball"),
        default_sort="desc",
        denominator="balls",
        minimum_sample=MinimumSample(balls=20),
        unit="percent",
    ),
    "boundary_percentage": MetricDefinition(
        name="boundary_percentage",
        owner="batter_or_bowler",
        formula="balls with batter runs 4 or 6 / balls * 100",
        required_columns=("batruns", "ballfaced"),
        default_sort="desc",
        good_direction="desc",
        denominator="balls",
        minimum_sample=MinimumSample(balls=20),
        unit="percent",
    ),
    "false_shot_percentage": MetricDefinition(
        name="false_shot_percentage",
        owner="batter_or_bowler",
        formula="balls with control = 0 / balls * 100",
        required_columns=("control", "ballfaced"),
        default_sort="desc",
        denominator="balls",
        minimum_sample=MinimumSample(balls=20),
        unit="percent",
    ),
    "false_shots_per_over": MetricDefinition(
        name="false_shots_per_over",
        owner="bowler",
        formula="false shots / legal overs",
        required_columns=("control", "wide", "noball", "bowl"),
        default_sort="desc",
        good_direction="desc",
        denominator="legal_balls",
        minimum_sample=MinimumSample(legal_balls=24),
        unit="false shots per over",
    ),
    "yorker_percentage": MetricDefinition(
        name="yorker_percentage",
        owner="bowler",
        formula="legal balls with length YORKER / legal balls * 100",
        required_columns=("length", "wide", "noball", "bowl"),
        default_sort="desc",
        good_direction="desc",
        denominator="legal_balls",
        minimum_sample=MinimumSample(legal_balls=24),
        unit="percent",
    ),
    "control_percentage": MetricDefinition(
        name="control_percentage",
        owner="batter_or_bowler",
        formula="balls with control = 1 / balls * 100",
        required_columns=("control", "ballfaced"),
        default_sort="desc",
        good_direction="desc",
        denominator="balls",
        minimum_sample=MinimumSample(balls=20),
        unit="percent",
    ),
    "dismissal_rate": MetricDefinition(
        name="dismissal_rate",
        owner="batter_or_bowler",
        formula="dismissals / balls * 100",
        required_columns=("out", "dismissal", "ballfaced"),
        default_sort="desc",
        denominator="balls",
        minimum_sample=MinimumSample(balls=20),
        unit="percent",
    ),
    "boundary_rate_per_100_balls": MetricDefinition(
        name="boundary_rate_per_100_balls",
        owner="batter_or_bowler",
        formula="boundary balls / balls * 100",
        required_columns=("batruns", "ballfaced"),
        default_sort="desc",
        denominator="balls",
        minimum_sample=MinimumSample(balls=20),
        unit="per 100 balls",
    ),
    "wickets_per_over": MetricDefinition(
        name="wickets_per_over",
        owner="bowler",
        formula="wickets / legal overs",
        required_columns=("dismissal", "wide", "noball", "bowl"),
        default_sort="desc",
        good_direction="desc",
        denominator="legal_balls",
        minimum_sample=MinimumSample(legal_balls=24),
        unit="wickets per over",
    ),
    "wicket_opportunity_rate": MetricDefinition(
        name="wicket_opportunity_rate",
        owner="bowler",
        formula="(wickets + false shots) / legal balls * 100",
        required_columns=("dismissal", "control", "wide", "noball", "bowl"),
        default_sort="desc",
        good_direction="desc",
        denominator="legal_balls",
        minimum_sample=MinimumSample(legal_balls=24),
        unit="percent",
    ),
}


OPERATION_TYPES = {
    "aggregate",
    "split_compare",
    "event_window",
    "distribution_analysis",
    "matchup",
    "predictive_analysis",
    "tactical_recommendation",
}


def ontology_context() -> dict[str, object]:
    return {
        "entities": sorted(ENTITIES),
        "dimensions": sorted(DIMENSIONS),
        "metrics": {
            name: {
                "owner": definition.owner,
                "formula": definition.formula,
                "default_sort": definition.default_sort,
                "good_direction": definition.good_direction,
                "minimum_sample": definition.minimum_sample.as_dict(),
            }
            for name, definition in METRICS.items()
        },
        "operations": sorted(OPERATION_TYPES),
    }
