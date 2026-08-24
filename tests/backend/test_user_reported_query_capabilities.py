from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


class ScriptedGeminiClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return self.response


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    config = AppConfig.from_env()
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(config.duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


def _trace(response) -> dict[str, object]:
    trace_note = next(note for note in response.evidence_notes if note.title == "Semantic V2 trace")
    return json.loads(trace_note.detail)


def test_least_death_economy_honors_explicit_minimum_sample(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Who has the least economy in death overs, minimum 100 balls?"
    )
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["metric"] == "economy_rate"
    assert plan["filters"]["phase"] == "death"
    assert plan["minimum_sample"]["legal_balls"] == 100
    assert plan["sort"] == {"by": "economy_rate", "direction": "asc"}
    assert response.tables[0].rows
    assert "death overs" in response.summaries[0].body.lower()
    assert "100" in response.summaries[0].body


def test_worst_false_shot_percentage_against_leg_spin_keeps_style_filter(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Who has the worst false shot percentage against leg spinners?"
    )
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "aggregate"
    assert plan["entity"] == "batter"
    assert plan["metric"] == "false_shot_percentage"
    assert plan["group_by"] == ["batter"]
    assert plan["filters"]["bowling_style"] == "leg_spin"
    assert plan["sort"] == {"by": "false_shot_percentage", "direction": "desc"}
    assert "leg spin" in response.summaries[0].body.lower()


def test_gemini_cannot_turn_a_false_shot_leaderboard_into_player_compare(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "player_compare",
              "entity": "batter",
              "metric": "false_shot_percentage",
              "filters": {"bowling_style": "Legbreak"},
              "sort": {"by": "false_shot_percentage", "direction": "desc"},
              "minimum_sample": {"balls": 20}
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question(
        "Who has the worst false shot percentage against leg spinners?"
    )
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "aggregate"
    assert plan["group_by"] == ["batter"]
    assert plan["filters"]["bowling_style"] == "leg_spin"
    assert plan["minimum_sample"]["balls"] == 60


def test_highest_batter_dot_percentage_against_left_arm_spin_in_middle_overs(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Who has the highest dot ball percentage against left arm spin in middle overs?"
    )
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "aggregate"
    assert plan["entity"] == "batter"
    assert plan["metric"] == "batter_dot_ball_percentage"
    assert plan["group_by"] == ["batter"]
    assert plan["filters"]["bowling_style"] == "left_arm_spin"
    assert plan["filters"]["phase"] == "middle"
    assert "left arm spin" in response.summaries[0].body.lower()
    assert "middle overs" in response.summaries[0].body.lower()


def test_malinga_economy_against_australia_keeps_opposition_filter(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Lasith Malinga economy against Australia")
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["entity"] == "bowler"
    assert plan["metric"] == "economy_rate"
    assert plan["filters"]["bowler"] == "Lasith Malinga"
    assert plan["filters"]["opposition"] == "Australia"
    assert "against australia" in response.summaries[0].body.lower()


def test_rohit_boundary_percentage_at_the_oval_resolves_venue(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Rohit Sharma's boundary percentage at The Oval")
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["entity"] == "batter"
    assert plan["metric"] == "boundary_percentage"
    assert plan["filters"]["batter"] == "Rohit Sharma"
    assert plan["filters"]["venue"] == "Kennington Oval, London"
    assert "Kennington Oval" in response.summaries[0].body


def test_rohit_highest_scoring_shot_groups_by_shot_type(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Rohit Sharma highest scoring shot")
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "aggregate"
    assert plan["entity"] == "batter"
    assert plan["metric"] == "runs_scored"
    assert plan["group_by"] == ["shot_type"]
    assert plan["filters"]["batter"] == "Rohit Sharma"
    assert response.tables[0].rows
    assert "Rohit Sharma" in response.summaries[0].body
    assert str(response.tables[0].rows[0][0]) in response.summaries[0].body


def test_default_strike_rate_sample_is_not_repeated_and_table_shows_formula_inputs(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Who has the best ODI strike rate?")
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert "minimum sample" not in response.summaries[0].body.lower()
    assert plan["minimum_sample"] == {"balls": 60, "legal_balls": None, "innings": None}
    balls_faced_index = response.tables[0].columns.index("Balls Faced")
    assert all(row[balls_faced_index] >= 60 for row in response.tables[0].rows)
    assert response.tables[0].columns == [
        "Batter",
        "Batting Strike Rate",
        "Runs Scored",
        "Balls Faced",
        "Matches",
    ]


def test_dot_ball_table_shows_dot_count_and_denominator(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Which batter has the highest dot ball percentage?")

    assert response.status.value == "supported"
    assert response.tables[0].columns == [
        "Batter",
        "Batter Dot Ball Percentage",
        "Dot Balls",
        "Balls Faced",
        "Matches",
    ]


def test_unqualified_batter_comparison_returns_core_metric_set(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Compare Kohli and Steve Smith")
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["minimum_sample"] is None
    assert response.interpretation.entities == ["Virat Kohli", "Steven Smith"]
    assert response.tables[0].columns == [
        "Player",
        "Batting Strike Rate",
        "Runs Scored",
        "Batting Average",
        "Batter Dot Ball Percentage",
        "Boundary Percentage",
        "Balls Faced",
        "Dismissals",
        "Matches",
    ]


def test_live_gemini_compare_values_plan_is_repaired_to_core_comparison(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "player_compare",
              "entity": "batter",
              "metric": "batting_average",
              "compare_values": ["Virat Kohli", "Steve Smith"],
              "sort": {"by": "batting_average", "direction": "desc"}
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question("Compare Kohli and Steve Smith")
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["filters"]["compare_players"] == ["Virat Kohli", "Steven Smith"]
    assert plan["filters"]["comparison_metrics"] == [
        "batting_strike_rate",
        "runs_scored",
        "batting_average",
        "batter_dot_ball_percentage",
        "boundary_percentage",
    ]
    assert response.tables[0].columns == [
        "Player",
        "Batting Strike Rate",
        "Runs Scored",
        "Batting Average",
        "Batter Dot Ball Percentage",
        "Boundary Percentage",
        "Balls Faced",
        "Dismissals",
        "Matches",
    ]


def test_maxwell_strike_rate_against_off_spin_preserves_style_scope(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("What is Maxwell's strike rate against off spinners?")
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["normalized_plan"]["filters"]["batter"] == "Glenn Maxwell"
    assert trace["normalized_plan"]["filters"]["bowling_style"] == "off_spin"
    assert "against off spin" in response.summaries[0].body.lower()


def test_live_gemini_off_break_plan_is_repaired_to_direct_off_spin_aggregate(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "matchup",
              "entity": "batter",
              "metric": "batting_strike_rate",
              "filters": {"batter": "Glenn Maxwell", "bowling_style": "Off-break"},
              "sort": {"by": "batting_strike_rate", "direction": "desc"}
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question("what is maxwell strike rate against off spinner")
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "aggregate"
    assert plan["filters"]["batter"] == "Glenn Maxwell"
    assert plan["filters"]["bowling_style"] == "off_spin"
    assert response.tables[0].rows[0][3] == 453


def test_live_gemini_single_player_compare_is_repaired_to_direct_off_spin_aggregate(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "player_compare",
              "entity": "batter",
              "metric": "batting_strike_rate",
              "filters": {"batter": "Glenn Maxwell", "bowling_style": "Offbreak"},
              "minimum_sample": {"balls": 60}
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question(
        "What is Glenn Maxwell's batting strike rate against off spinners?"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "aggregate"
    assert plan["filters"]["batter"] == "Glenn Maxwell"
    assert plan["filters"]["bowling_style"] == "off_spin"
    assert response.tables[0].rows[0][1] == 134.22


def test_worst_bowling_average_against_named_batter_uses_bowling_formula(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Which bowler has the worst average against Virat Kohli?")
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["entity"] == "bowler"
    assert plan["metric"] == "bowling_average"
    assert plan["filters"]["batter"] == "Virat Kohli"
    assert plan["group_by"] == ["bowler"]
    assert plan["sort"] == {"by": "bowling_average", "direction": "desc"}
    assert "from 1 wicket" in response.summaries[0].body.lower()
    assert "from 196 balls" not in response.summaries[0].body.lower()
    assert response.tables[0].columns == [
        "Bowler",
        "Bowling Average",
        "Runs Conceded",
        "Wickets Taken",
        "Matches",
    ]


def test_best_length_against_named_batter_ranks_by_lowest_strike_rate(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Which length is best against Kane Williamson?")
    trace = _trace(response)
    plan = trace["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["metric"] == "batting_strike_rate"
    assert plan["filters"]["batter"] == "Kane Williamson"
    assert plan["group_by"] == ["length"]
    assert plan["sort"] == {"by": "batting_strike_rate", "direction": "asc"}
    assert response.tables[0].columns == [
        "Length",
        "Batting Strike Rate",
        "Runs Scored",
        "Balls Faced",
        "Matches",
    ]


def test_unqualified_death_over_bowler_comparison_returns_core_metric_set(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Compare Bumrah and Starc in death overs")
    trace = _trace(response)

    assert response.status.value == "supported"
    assert trace["normalized_plan"]["entity"] == "bowler"
    assert trace["normalized_plan"]["filters"]["phase"] == "death"
    assert response.tables[0].columns == [
        "Player",
        "Economy Rate",
        "Bowling Average",
        "Bowling Strike Rate",
        "Wickets Taken",
        "Bowler Dot Ball Percentage",
        "Boundary Percentage",
        "Legal Balls",
        "Runs Conceded",
        "Matches",
    ]


def test_direct_bowling_strike_rate_uses_legal_balls_per_bowler_wicket(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "What is Jasprit Bumrah's bowling strike rate in death overs?"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["entity"] == "bowler"
    assert plan["metric"] == "bowling_strike_rate"
    assert plan["filters"]["bowler"] == "Jasprit Bumrah"
    assert plan["filters"]["phase"] == "death"
    assert response.tables[0].columns == [
        "Bowler",
        "Bowling Strike Rate",
        "Legal Balls",
        "Wickets Taken",
        "Matches",
    ]
    row = response.tables[0].rows[0]
    assert row[1] == round(row[2] / row[3], 2)
    assert "Bowling Strike Rate" in response.summaries[0].body


def test_bowling_strike_rate_ranking_excludes_zero_wicket_rows(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Which bowler has the best bowling strike rate?"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["minimum_sample"]["legal_balls"] == 60
    assert all(row[1] is not None for row in response.tables[0].rows)
    assert "70 legal balls and 7 bowler-credit wickets" in response.summaries[0].body
    assert "no bowler-credit wickets are excluded" in response.summaries[0].body


def test_bowling_strike_rate_ranking_honors_user_legal_ball_threshold(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Which bowler has the best bowling strike rate, minimum 100 legal balls"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["minimum_sample"]["legal_balls"] == 100
    legal_balls_index = response.tables[0].columns.index("Legal Balls")
    assert all(row[legal_balls_index] >= 100 for row in response.tables[0].rows)


def test_descriptive_bowling_strike_rate_comparison_keeps_zero_wicket_players(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Compare Abul Hasan and Aaron Jones by bowling strike rate"
    )

    assert response.status.value == "supported"
    assert response.tables[0].columns == [
        "Player",
        "Bowling Strike Rate",
        "Legal Balls",
        "Wickets Taken",
        "Runs Conceded",
        "Matches",
    ]
    assert response.tables[0].rows == [
        ["Aaron Jones", "N/A — no wickets taken", 197, 0, 189, 10],
        ["Abul Hasan", "N/A — no wickets taken", 216, 0, 244, 7],
    ]


def test_phase_wise_bowler_comparison_returns_one_combined_table(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Compare Bumrah and Starc across powerplay, middle overs, and death overs"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["filters"]["comparison_view"] == "phase"
    assert "phase" not in plan["filters"]
    assert response.tables[0].columns[:2] == ["Player", "Phase"]
    assert "Legal Balls" in response.tables[0].columns
    assert len(response.tables[0].rows) == 6
    assert {row[1] for row in response.tables[0].rows} == {"powerplay", "middle", "death"}
    assert {row[0] for row in response.tables[0].rows} == {"Jasprit Bumrah", "Mitchell Starc"}


def test_team_wise_comparison_returns_one_opposition_table_per_player(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Compare Bumrah and Starc team-wise")
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["filters"]["comparison_view"] == "opposition"
    assert len(response.tables) == 2
    assert [table.title for table in response.tables] == [
        "Jasprit Bumrah by opposition",
        "Mitchell Starc by opposition",
    ]
    for table in response.tables:
        assert table.columns[0] == "Opposition"
        assert "Legal Balls" in table.columns
        assert table.rows
        assert all(row[0] for row in table.rows)
    summary = response.summaries[0].body
    assert "Calculated standout differences:" in summary
    assert 1 <= summary.count("Against ") <= 3
    assert "legal balls" in summary
    assert " higher " in summary or " lower " in summary


def test_named_matchup_is_descriptive_and_hides_duplicate_or_internal_columns(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "matchup",
              "entity": "batter",
              "metric": "batting_strike_rate",
              "filters": {"batter": "Virat Kohli", "bowler": "Mitchell Starc"},
              "group_by": ["batter", "bowler"]
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )
    response = service.answer_question(
        "What is Virat Kohli's batting strike rate against Mitchell Starc?"
    )

    assert response.status.value == "supported"
    assert "ranks first" not in response.summaries[0].body
    assert response.summaries[0].body == (
        "Virat Kohli's Batting Strike Rate against Mitchell Starc is 100.65 from 155 balls."
    )
    assert response.tables[0].columns == [
        "Batter",
        "Bowler",
        "Balls",
        "Runs",
        "Dismissals",
        "Wickets Taken",
        "Batting Strike Rate",
        "Batter Dot Ball Percentage",
        "Boundary Percentage",
        "False Shot Percentage",
        "Dismissal Rate",
    ]
    assert response.tables[0].rows == [
        ["Virat Kohli", "Mitchell Starc", 155, 156, 1, 1, 100.65, 43.23, 9.68, 18.71, 0.65]
    ]


def test_named_matchup_keeps_distinct_ball_and_dot_columns_when_values_differ(
    semantic_service: SemanticAnalyticsService,
) -> None:
    service = SemanticAnalyticsService(
        repository=semantic_service.repository,
        gemini_client=ScriptedGeminiClient(
            """{
              "operation": "matchup",
              "entity": "batter",
              "metric": "batting_strike_rate",
              "filters": {"batter": "Paul Stirling", "bowler": "Mohammad Nabi"},
              "group_by": ["batter", "bowler"]
            }"""
        ),
        app_env="production",
        allow_dev_fallback=False,
    )

    response = service.answer_question(
        "What is Paul Stirling's batting strike rate against Mohammad Nabi?"
    )

    assert response.status.value == "supported"
    columns = response.tables[0].columns
    assert "Balls" in columns
    assert "Legal Balls" in columns
    assert "Batter Dot Ball Percentage" in columns
    assert "Bowler Dot Ball Percentage" in columns
    assert "Sample Size" not in columns
    assert "Low Sample" not in columns


def test_offline_planner_routes_named_batter_against_named_bowler_as_matchup(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "What is Virat Kohli's batting strike rate against Mitchell Starc?"
    )
    plan = _trace(response)["normalized_plan"]

    assert response.status.value == "supported"
    assert plan["operation"] == "matchup"
    assert plan["filters"]["batter"] == "Virat Kohli"
    assert plan["filters"]["bowler"] == "Mitchell Starc"
