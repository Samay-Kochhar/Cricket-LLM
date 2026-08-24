from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.schemas import CricketQueryPlan


CapabilityStatus = Literal["production_ready", "partial", "unsupported"]


@dataclass(frozen=True, slots=True)
class Capability:
    capability_id: str
    name: str
    operation: str
    allowed_entities: tuple[str, ...]
    allowed_metrics: tuple[str, ...]
    required_filters: tuple[str, ...] = ()
    optional_filters: tuple[str, ...] = ()
    allowed_groupings: tuple[str, ...] = ()
    expected_executor: str = ""
    sample_size_rule: str = ""
    status: CapabilityStatus = "unsupported"
    wording_limitations: tuple[str, ...] = ()
    test_files: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return self.name

    @property
    def required_shape(self) -> str:
        pieces = [f"operation={self.operation}", f"entities={','.join(self.allowed_entities)}"]
        if self.required_filters:
            pieces.append(f"requires={','.join(self.required_filters)}")
        if self.allowed_groupings:
            pieces.append(f"group_by={','.join(self.allowed_groupings)}")
        return "; ".join(pieces)


COMMON_OPTIONAL_FILTERS = (
    "phase",
    "years",
    "year_mode",
    "line",
    "length",
    "shot_type",
    "field_zone",
    "bowling_style",
    "batter_hand",
    "bowler_hand",
    "venue",
    "innings",
    "competition",
    "opposition",
)

PLAYER_METRICS = (
    "runs_scored",
    "balls_faced",
    "batting_strike_rate",
    "runs_conceded",
    "legal_balls",
    "overs_bowled",
    "wickets_taken",
    "economy_rate",
    "bowling_strike_rate",
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
    "control_percentage",
)


CAPABILITIES: dict[str, Capability] = {
    "direct_player_statistic": Capability(
        "direct_player_statistic",
        "Direct player statistic",
        "aggregate",
        ("batter", "bowler"),
        PLAYER_METRICS,
        optional_filters=COMMON_OPTIONAL_FILTERS,
        allowed_groupings=("batter", "bowler"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample for rates/percentages; raw totals have no threshold unless requested.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_phase1_contract.py", "tests/backend/test_chat_phase2_contract.py"),
    ),
    "global_leaderboard": Capability(
        "global_leaderboard",
        "Global leaderboard",
        "aggregate",
        ("batter", "bowler", "team", "venue"),
        PLAYER_METRICS,
        optional_filters=COMMON_OPTIONAL_FILTERS,
        allowed_groupings=("batter", "bowler", "team", "venue"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample applies to rate/percentage leaderboards.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_stage2_suite.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "top_bottom_n_leaderboard": Capability(
        "top_bottom_n_leaderboard",
        "Top/bottom N leaderboard",
        "aggregate",
        ("batter", "bowler", "team", "venue"),
        PLAYER_METRICS,
        optional_filters=COMMON_OPTIONAL_FILTERS,
        allowed_groupings=("batter", "bowler", "team", "venue"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry defaults plus explicit minimum_sample when parsed.",
        status="partial",
        wording_limitations=("Explicit top-N limits are normalized, but minimum-sample wording is still limited.",),
        test_files=("tests/backend/test_golden_factual_chat.py",),
    ),
    "player_comparison": Capability(
        "player_comparison",
        "Player comparison",
        "player_compare",
        ("batter", "bowler"),
        ("runs_scored", "batting_strike_rate", "economy_rate", "bowling_strike_rate", "wickets_taken", "wickets_per_over", "batter_dot_ball_percentage", "bowler_dot_ball_percentage"),
        optional_filters=("phase", "years", "year_mode", "bowling_style", "length", "venue", "opposition", "line", "over_range"),
        allowed_groupings=("batter", "bowler"),
        expected_executor="executors.player_compare_executor.execute_player_compare",
        sample_size_rule="Comparison summaries expose balls/legal balls where available.",
        status="production_ready",
        wording_limitations=("Mixed batter-vs-bowler comparisons are rejected.",),
        test_files=("tests/backend/test_semantic_trace_suite.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "batter_versus_bowler_matchup": Capability(
        "batter_versus_bowler_matchup",
        "Batter-versus-bowler matchup",
        "matchup",
        ("matchup", "batter", "bowler"),
        ("runs_scored", "balls_faced", "batting_strike_rate", "batter_dot_ball_percentage", "bowler_dot_ball_percentage", "boundary_percentage", "false_shot_percentage", "dismissals", "wickets_taken"),
        optional_filters=("batter", "bowler", "phase", "bowling_style", "batter_hand"),
        allowed_groupings=("matchup", "batter", "bowler", "bowling_style", "batter_hand"),
        expected_executor="executors.matchup_executor.build_matchup_query",
        sample_size_rule="Soft low-sample flag; pair matchups default to 20 balls unless overridden.",
        status="production_ready",
        test_files=("tests/backend/test_matchup_executor.py", "tests/backend/test_chat_phase2_contract.py"),
    ),
    "bowler_against_named_batter": Capability(
        "bowler_against_named_batter",
        "Which bowler against this batter matchup ranking",
        "matchup",
        ("bowler",),
        ("wickets_taken", "bowler_dot_ball_percentage", "boundary_percentage", "false_shot_percentage"),
        required_filters=("batter",),
        optional_filters=("phase", "years", "year_mode", "length", "line"),
        allowed_groupings=("bowler",),
        expected_executor="executors.matchup_executor.build_matchup_query",
        sample_size_rule="Soft low-sample flag, default 24 balls for ranking.",
        status="production_ready",
        test_files=("tests/backend/test_matchup_executor.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "phase_filtered_metric": Capability(
        "phase_filtered_metric",
        "Phase-filtered metric",
        "aggregate",
        ("batter", "bowler", "team"),
        PLAYER_METRICS,
        required_filters=("phase",),
        optional_filters=("years", "year_mode", "venue", "bowling_style"),
        allowed_groupings=("batter", "bowler", "team"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample after phase filter.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_stage2_suite.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "year_filtered_metric": Capability(
        "year_filtered_metric",
        "Year-filtered metric",
        "aggregate",
        ("batter", "bowler", "team"),
        PLAYER_METRICS,
        required_filters=("years",),
        optional_filters=("year_mode", "phase", "competition"),
        allowed_groupings=("batter", "bowler", "team"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample after year filter.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_phase1_contract.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "opposition_filtered_metric": Capability(
        "opposition_filtered_metric",
        "Opposition-filtered metric",
        "aggregate",
        ("batter", "bowler"),
        PLAYER_METRICS,
        required_filters=("opposition",),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample after role-aware opposition filter.",
        status="production_ready",
        wording_limitations=("Team-level opposition semantics remain unsupported until wording is explicit and tested.",),
        test_files=("tests/backend/test_golden_factual_chat.py", "tests/backend/test_semantic_phase3_truth_sql.py"),
    ),
    "venue_filtered_metric": Capability(
        "venue_filtered_metric",
        "Venue-filtered metric",
        "aggregate",
        ("batter", "bowler", "venue"),
        PLAYER_METRICS,
        required_filters=("venue",),
        optional_filters=("phase", "years", "year_mode"),
        allowed_groupings=("batter", "bowler", "venue"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample after venue filter.",
        status="production_ready",
        wording_limitations=("Venue aliases cover tested names; unseen aliases still require adding to the venue resolver.",),
        test_files=("tests/backend/test_golden_factual_chat.py", "tests/backend/test_semantic_phase3_truth_sql.py"),
    ),
    "line_breakdown": Capability(
        "line_breakdown",
        "Line breakdown",
        "aggregate",
        ("batter", "bowler"),
        PLAYER_METRICS,
        optional_filters=COMMON_OPTIONAL_FILTERS,
        allowed_groupings=("line",),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample by line bucket.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_trace_suite.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "length_breakdown": Capability(
        "length_breakdown",
        "Length breakdown",
        "aggregate",
        ("batter", "bowler"),
        PLAYER_METRICS,
        optional_filters=COMMON_OPTIONAL_FILTERS,
        allowed_groupings=("length",),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum sample by length bucket.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_trace_suite.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "shot_type_breakdown": Capability(
        "shot_type_breakdown",
        "Shot-type breakdown",
        "aggregate",
        ("batter",),
        ("runs_scored", "balls_faced", "batting_strike_rate", "boundary_percentage", "dismissals"),
        optional_filters=("batter", "phase", "years", "year_mode", "bowling_style", "length"),
        allowed_groupings=("shot_type",),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query or batting_profile special handler",
        sample_size_rule="Balls by shot type; registry minimum for rates.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_trace_suite.py", "tests/backend/test_semantic_phase1_contract.py"),
    ),
    "field_zone_breakdown": Capability(
        "field_zone_breakdown",
        "Field-zone breakdown",
        "aggregate",
        ("batter",),
        ("runs_scored", "balls_faced", "batting_strike_rate", "boundary_percentage", "dismissals"),
        optional_filters=("batter", "phase", "years", "year_mode", "bowling_style", "length"),
        allowed_groupings=("field_zone",),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query or batting_profile special handler",
        sample_size_rule="Balls by hand-adjusted field zone.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_phase1_contract.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "bowling_style_split": Capability(
        "bowling_style_split",
        "Bowling-style split",
        "aggregate",
        ("batter", "bowler"),
        ("runs_scored", "batting_strike_rate", "false_shot_percentage", "boundary_percentage", "economy_rate"),
        optional_filters=("batter", "bowler", "phase", "years", "year_mode"),
        allowed_groupings=("bowling_style",),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum by bowling-style bucket.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_analytics_v2.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "hand_split": Capability(
        "hand_split",
        "Batter-hand / bowler-hand split",
        "aggregate",
        ("batter", "bowler"),
        ("runs_scored", "batting_strike_rate", "economy_rate", "boundary_percentage", "false_shot_percentage"),
        optional_filters=("phase", "years", "year_mode"),
        allowed_groupings=("batter_hand", "bowler_hand"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum by hand bucket.",
        status="partial",
        wording_limitations=("Bowler-hand is derived from bowling style and may be coarse.",),
        test_files=("tests/backend/test_golden_factual_chat.py",),
    ),
    "split_comparison": Capability(
        "split_comparison",
        "Split comparison",
        "split_compare",
        ("batter", "bowler", "team"),
        ("batting_strike_rate", "economy_rate", "runs_scored", "run_rate", "batter_dot_ball_percentage", "bowler_dot_ball_percentage", "boundary_percentage", "wickets_taken", "dismissal_rate"),
        optional_filters=COMMON_OPTIONAL_FILTERS,
        allowed_groupings=("batter", "bowler", "team"),
        expected_executor="executors.split_compare_executor.build_split_compare_query",
        sample_size_rule="Both sides must satisfy the split minimum sample.",
        status="production_ready",
        test_files=("tests/backend/test_split_compare_executor.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "line_length_filtered_player_stat": Capability(
        "line_length_filtered_player_stat",
        "Line/length filtered player statistic",
        "aggregate",
        ("batter", "bowler"),
        PLAYER_METRICS,
        optional_filters=("batter", "bowler", "line", "length", "phase", "years", "year_mode"),
        allowed_groupings=("batter", "bowler"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum after line/length filters.",
        status="production_ready",
        test_files=("tests/backend/test_golden_factual_chat.py",),
    ),
    "yorker_metrics": Capability(
        "yorker_metrics",
        "Yorker volume and yorker percentage",
        "aggregate",
        ("bowler",),
        ("yorker_count", "yorker_percentage"),
        optional_filters=("phase", "years", "year_mode", "batter", "venue"),
        allowed_groupings=("bowler", "phase", "length"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Yorker percentage requires legal-ball minimum.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_trace_suite.py", "tests/backend/test_golden_factual_chat.py"),
    ),
    "false_shot_control_metrics": Capability(
        "false_shot_control_metrics",
        "False-shot and control metrics",
        "aggregate",
        ("batter", "bowler"),
        ("false_shot_percentage", "false_shots_per_over", "control_percentage"),
        optional_filters=("phase", "years", "year_mode", "bowling_style", "length", "line", "batter", "bowler"),
        allowed_groupings=("batter", "bowler", "line", "length", "bowling_style"),
        expected_executor="query_builders.aggregate_builder.build_aggregate_query",
        sample_size_rule="Registry minimum for false-shot rates; control is legacy-compatible in ontology.",
        status="production_ready",
        test_files=("tests/backend/test_semantic_stage2_suite.py", "tests/backend/test_golden_factual_chat.py"),
    ),
}


IMPLEMENTED_OPERATIONS = {"aggregate", "matchup", "split_compare", "player_compare"}


def validate_capability(plan: CricketQueryPlan) -> list[str]:
    errors: list[str] = []
    if plan.operation not in IMPLEMENTED_OPERATIONS:
        return []

    try:
        metric = get_metric(plan.metric, entity=plan.entity, filters=plan.filters)
    except KeyError:
        return []

    if metric.owner == "batter" and plan.entity == "bowler":
        errors.append(f"Metric '{metric.metric_id}' is batter-owned and cannot be ranked as a bowler metric.")
    if metric.owner == "bowler" and plan.entity == "batter":
        errors.append(f"Metric '{metric.metric_id}' is bowler-owned and cannot be ranked as a batter metric.")

    unsupported_groupings = [dimension for dimension in plan.group_by if dimension not in metric.allowed_groupings]
    if unsupported_groupings:
        errors.append(
            f"Metric '{metric.metric_id}' does not support group_by: {', '.join(unsupported_groupings)}."
        )

    internal_filters = {"compare_players", "comparison_metrics", "comparison_view"} if plan.operation == "player_compare" else set()
    unsupported_filters = [key for key in plan.filters if key not in metric.allowed_filters and key not in internal_filters]
    if unsupported_filters:
        errors.append(f"Metric '{metric.metric_id}' does not support filters: {', '.join(unsupported_filters)}.")

    return errors
