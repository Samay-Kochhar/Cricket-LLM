from __future__ import annotations

from backend.app.cricket_analytics.capabilities import CAPABILITIES, validate_capability
from backend.app.cricket_analytics.cricket_definitions import (
    BOWLER_WICKET_PREDICATE,
    LEGAL_BALL_PREDICATE,
    classify_phase,
    is_bowler_credit_wicket,
    public_label,
)
from backend.app.cricket_analytics.metric_registry import (
    LEGACY_METRIC_ALIASES,
    METRIC_REGISTRY,
    MIGRATED_METRIC_IDS,
    canonical_metric_id,
    metric_sql_expression,
)
from backend.app.cricket_analytics.schemas import CricketQueryPlan


EXPECTED_MIGRATED = {
    "runs_scored",
    "balls_faced",
    "batting_strike_rate",
    "batting_average",
    "runs_conceded",
    "legal_balls",
    "overs_bowled",
    "wickets_taken",
    "economy_rate",
    "bowling_average",
    "batter_dot_ball_percentage",
    "bowler_dot_ball_percentage",
    "dot_balls",
    "bowler_dot_balls",
    "boundary_percentage",
    "false_shot_percentage",
    "dismissals",
    "yorker_count",
    "yorker_percentage",
    "wickets_per_over",
    "false_shots_per_over",
}


def test_registry_contains_phase1_migrated_metrics_with_metadata() -> None:
    assert set(MIGRATED_METRIC_IDS) == EXPECTED_MIGRATED
    for metric_id in EXPECTED_MIGRATED:
        rule = METRIC_REGISTRY[metric_id]
        assert rule.metric_id == metric_id
        assert rule.label
        assert rule.owner in {"batter", "bowler", "team", "batter_or_bowler"}
        assert rule.numerator
        assert rule.sql_expression
        assert rule.result_field == metric_id
        assert rule.allowed_filters
        assert rule.allowed_groupings


def test_ambiguous_dot_ball_metric_is_contextual_alias_only() -> None:
    assert "dot_ball_percentage" not in METRIC_REGISTRY
    assert LEGACY_METRIC_ALIASES["dot_percentage"] == "batter_dot_ball_percentage"
    assert canonical_metric_id("dot_ball_percentage", entity="batter") == "batter_dot_ball_percentage"
    assert canonical_metric_id("dot_ball_percentage", entity="bowler") == "bowler_dot_ball_percentage"
    assert "dot_balls / NULLIF(sample_balls" in metric_sql_expression("dot_ball_percentage", entity="batter")
    assert "bowler_dot_balls / NULLIF(legal_balls" in metric_sql_expression("dot_ball_percentage", entity="bowler")


def test_shared_cricket_predicates_and_phase_boundaries() -> None:
    assert "wide" in LEGAL_BALL_PREDICATE and "noball" in LEGAL_BALL_PREDICATE
    assert "caught and bowled" in BOWLER_WICKET_PREDICATE
    assert is_bowler_credit_wicket("caught and bowled")
    assert not is_bowler_credit_wicket("run out")
    assert classify_phase(9.5) == "powerplay"
    assert classify_phase(10.1) == "middle"
    assert classify_phase(41) == "death"


def test_rate_and_percentage_denominators_are_explicit() -> None:
    assert METRIC_REGISTRY["batting_strike_rate"].denominator == "balls_faced"
    assert METRIC_REGISTRY["batter_dot_ball_percentage"].denominator == "balls_faced"
    assert METRIC_REGISTRY["bowler_dot_ball_percentage"].denominator == "legal_balls"
    assert METRIC_REGISTRY["economy_rate"].denominator == "legal_balls"
    assert METRIC_REGISTRY["yorker_percentage"].denominator == "legal_balls"


def test_capability_registry_lists_phase1_factual_families() -> None:
    assert set(CAPABILITIES) == {
        "direct_player_statistic",
        "global_leaderboard",
        "top_bottom_n_leaderboard",
        "player_comparison",
        "batter_versus_bowler_matchup",
        "bowler_against_named_batter",
        "phase_filtered_metric",
        "year_filtered_metric",
        "opposition_filtered_metric",
        "venue_filtered_metric",
        "line_breakdown",
        "length_breakdown",
        "shot_type_breakdown",
        "field_zone_breakdown",
        "bowling_style_split",
        "hand_split",
        "split_comparison",
        "line_length_filtered_player_stat",
        "yorker_metrics",
        "false_shot_control_metrics",
    }


def test_capability_validation_rejects_invalid_metric_owner() -> None:
    plan = CricketQueryPlan(
        operation="aggregate",
        entity="bowler",
        metric="batter_dot_ball_percentage",
        group_by=["bowler"],
    )

    errors = validate_capability(plan)

    assert errors
    assert "batter-owned" in errors[0]


def test_public_label_contract_hides_raw_enum_values() -> None:
    assert public_label("ON_DRIVE") == "on drive"
    assert public_label("GOOD_LENGTH") == "good length"
    assert public_label("third_man") == "third man"
