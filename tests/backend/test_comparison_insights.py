from backend.app.cricket_analytics.comparison_insights import build_player_comparison_insight
from backend.app.cricket_analytics.executors.player_compare_executor import PlayerCompareResult


def _result(
    *,
    rows: list[dict[str, object]],
    metrics: list[str],
    players: list[str],
    sample_columns: list[str],
    view: str | None = None,
) -> PlayerCompareResult:
    return PlayerCompareResult(
        rows=rows,
        columns=[],
        metrics=metrics,
        players=players,
        sample_columns=sample_columns,
        executed_sql=[],
        view=view,
    )


def test_overall_batting_summary_uses_two_useful_contrasts_without_row_dump() -> None:
    summary = build_player_comparison_insight(
        _result(
            rows=[
                {
                    "player": "Rohit Sharma",
                    "runs_scored": 1107,
                    "batting_strike_rate": 152.69,
                    "batting_average": None,
                    "balls_faced": 725,
                },
                {
                    "player": "Virat Kohli",
                    "runs_scored": 1523,
                    "batting_strike_rate": 149.9,
                    "batting_average": 39.0,
                    "balls_faced": 1016,
                },
            ],
            metrics=["runs_scored", "batting_strike_rate", "batting_average"],
            players=["Rohit Sharma", "Virat Kohli"],
            sample_columns=["balls_faced"],
        )
    )

    assert summary == (
        "Virat Kohli scored more runs than Rohit Sharma: 1523 vs 1107, while "
        "Rohit Sharma scored faster than Virat Kohli: 152.69 vs 149.9."
    )
    assert "N/A" not in summary
    assert "balls" not in summary


def test_overall_bowling_summary_handles_lower_is_better_metrics() -> None:
    summary = build_player_comparison_insight(
        _result(
            rows=[
                {
                    "player": "Jasprit Bumrah",
                    "wickets_taken": 149,
                    "economy_rate": 4.59,
                    "legal_balls": 3500,
                },
                {
                    "player": "Mitchell Starc",
                    "wickets_taken": 244,
                    "economy_rate": 5.16,
                    "legal_balls": 5000,
                },
            ],
            metrics=["wickets_taken", "economy_rate"],
            players=["Jasprit Bumrah", "Mitchell Starc"],
            sample_columns=["legal_balls"],
        )
    )

    assert summary == (
        "Mitchell Starc took more wickets than Jasprit Bumrah: 244 vs 149, while "
        "Jasprit Bumrah was more economical than Mitchell Starc: 4.59 vs 5.16."
    )


def test_opposition_summary_returns_one_clear_difference() -> None:
    summary = build_player_comparison_insight(
        _result(
            rows=[
                {"player": "A", "opposition": "India", "economy_rate": 4.2},
                {"player": "A", "opposition": "Australia", "economy_rate": 5.0},
                {"player": "B", "opposition": "India", "economy_rate": 6.1},
                {"player": "B", "opposition": "Australia", "economy_rate": 5.1},
            ],
            metrics=["economy_rate"],
            players=["A", "B"],
            sample_columns=["legal_balls"],
            view="opposition",
        )
    )

    assert summary == "Against India, A was more economical than B: 4.2 vs 6.1."
    assert "Calculated standout" not in summary


def test_phase_summary_describes_mixed_leaders_and_only_the_largest_gap() -> None:
    summary = build_player_comparison_insight(
        _result(
            rows=[
                {"player": "A", "phase": "powerplay", "batting_strike_rate": 90.0, "balls_faced": 40},
                {"player": "A", "phase": "middle", "batting_strike_rate": 110.0, "balls_faced": 50},
                {"player": "A", "phase": "death", "batting_strike_rate": 180.0, "balls_faced": 20},
                {"player": "B", "phase": "powerplay", "batting_strike_rate": 100.0, "balls_faced": 40},
                {"player": "B", "phase": "middle", "batting_strike_rate": 105.0, "balls_faced": 50},
                {"player": "B", "phase": "death", "batting_strike_rate": 140.0, "balls_faced": 20},
            ],
            metrics=["batting_strike_rate"],
            players=["A", "B"],
            sample_columns=["balls_faced"],
            view="phase",
        )
    )

    assert summary.startswith("A led in the middle and death overs; B led in the powerplay.")
    assert "largest strike-rate gap was at the death: 180 vs 140" in summary
    assert summary.count("from") == 1
