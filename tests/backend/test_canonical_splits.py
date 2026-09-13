from __future__ import annotations

import pytest

from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
    compile_canonical_meaning,
)
from backend.app.cricket_analytics.player_roles import PlayerParticipation


FACTS = {
    "Virat Kohli": PlayerParticipation(12000, 400),
    "Heinrich Klaasen": PlayerParticipation(3000, 0),
    "David Miller": PlayerParticipation(5000, 0),
    "Jasprit Bumrah": PlayerParticipation(150, 5000),
    "Mitchell Starc": PlayerParticipation(700, 6500),
    "Trent Boult": PlayerParticipation(400, 6000),
}


def resolver() -> CanonicalMeaningResolver:
    return CanonicalMeaningResolver(
        available_players=list(FACTS),
        available_venues=["Wankhede Stadium, Mumbai", "Melbourne Cricket Ground"],
        available_teams=["Australia", "Pakistan", "India"],
        player_participation=FACTS,
    )


CASES = [
    (
        "How different is Bumrah's economy in powerplay versus death?",
        "bowler",
        "economy_rate",
        "phase",
        ["powerplay", "death"],
        {"bowler": "Jasprit Bumrah"},
        "descriptive",
        "absolute",
    ),
    (
        "Compare Jasprit Bumrah's death and opening-ten economy",
        "bowler",
        "economy_rate",
        "phase",
        ["death", "powerplay"],
        {"bowler": "Jasprit Bumrah"},
        "descriptive",
        "absolute",
    ),
    (
        "Starc economy to lefties versus righties?",
        "bowler",
        "economy_rate",
        "batter_hand",
        ["LHB", "RHB"],
        {"bowler": "Mitchell Starc"},
        "descriptive",
        "absolute",
    ),
    (
        "Compare Mitchell Starc's economy by batter hand",
        "bowler",
        "economy_rate",
        "batter_hand",
        ["LHB", "RHB"],
        {"bowler": "Mitchell Starc"},
        "descriptive",
        "absolute",
    ),
    (
        "Kohli strike rate in powerplay compared with death overs?",
        "batter",
        "batting_strike_rate",
        "phase",
        ["powerplay", "death"],
        {"batter": "Virat Kohli"},
        "descriptive",
        "absolute",
    ),
    (
        "Compare Virat Kohli's scoring rate at the start and the death",
        "batter",
        "batting_strike_rate",
        "phase",
        ["powerplay", "death"],
        {"batter": "Virat Kohli"},
        "descriptive",
        "absolute",
    ),
    (
        "Klaasen against wrist spin versus finger spin?",
        "batter",
        "batting_strike_rate",
        "bowling_style_group",
        ["wrist_spin", "finger_spin"],
        {"batter": "Heinrich Klaasen"},
        "descriptive",
        "absolute",
    ),
    (
        "Compare Heinrich Klaasen's strike rate across finger-spin and wrist-spin",
        "batter",
        "batting_strike_rate",
        "bowling_style_group",
        ["finger_spin", "wrist_spin"],
        {"batter": "Heinrich Klaasen"},
        "descriptive",
        "absolute",
    ),
    (
        "Boult dot rate to LHB compared with RHB",
        "bowler",
        "bowler_dot_ball_percentage",
        "batter_hand",
        ["LHB", "RHB"],
        {"bowler": "Trent Boult"},
        "descriptive",
        "absolute",
    ),
    (
        "Compare Trent Boult's dot-ball percentage by handedness",
        "bowler",
        "bowler_dot_ball_percentage",
        "batter_hand",
        ["LHB", "RHB"],
        {"bowler": "Trent Boult"},
        "descriptive",
        "absolute",
    ),
    (
        "Miller boundary percentage: opening ten or death?",
        "batter",
        "boundary_percentage",
        "phase",
        ["powerplay", "death"],
        {"batter": "David Miller"},
        "descriptive",
        "absolute",
    ),
    (
        "Which team changes run rate most from powerplay to death?",
        "team",
        "run_rate",
        "phase",
        ["powerplay", "death"],
        {},
        "ranking",
        "absolute",
    ),
    (
        "Rank teams by the gap between death overs and powerplay run rate",
        "team",
        "run_rate",
        "phase",
        ["death", "powerplay"],
        {},
        "ranking",
        "absolute",
    ),
    (
        "Which team accelerates most from middle overs to death overs?",
        "team",
        "run_rate",
        "phase",
        ["death", "middle"],
        {},
        "ranking",
        "increase",
    ),
    (
        "Which batter increases boundary percentage most from powerplay to death overs?",
        "batter",
        "boundary_percentage",
        "phase",
        ["death", "powerplay"],
        {},
        "ranking",
        "increase",
    ),
    (
        "Which bowler is most different against right-handers and left-handers by economy?",
        "bowler",
        "economy_rate",
        "batter_hand",
        ["RHB", "LHB"],
        {},
        "ranking",
        "absolute",
    ),
    (
        "Which bowler's dot-ball percentage changes most by batter handedness?",
        "bowler",
        "bowler_dot_ball_percentage",
        "batter_hand",
        ["LHB", "RHB"],
        {},
        "ranking",
        "absolute",
    ),
    (
        "Which batter improves their strike rate the most after facing 20 balls?",
        "batter",
        "batting_strike_rate",
        "balls_faced_window",
        ["after_20_balls", "first_20_balls"],
        {},
        "ranking",
        "increase",
    ),
    (
        "Which batter has the biggest strike-rate gap between pace and spin?",
        "batter",
        "batting_strike_rate",
        "bowling_style_group",
        ["pace", "spin"],
        {},
        "ranking",
        "absolute",
    ),
    (
        "Which batter scores fastest between overs 15 and 20 compared with before over 15?",
        "batter",
        "batting_strike_rate",
        "over_range",
        ["overs_15_to_20", "before_over_15"],
        {"over_range": [15, 20]},
        "ranking",
        "absolute",
    ),
    (
        "Which bowler changes economy most between powerplay and death at the MCG since 2019?",
        "bowler",
        "economy_rate",
        "phase",
        ["powerplay", "death"],
        {"venue": "Melbourne Cricket Ground", "years": [2019], "year_mode": "after"},
        "ranking",
        "absolute",
    ),
    (
        "Compare Kohli's powerplay and death strike rate against Pakistan",
        "batter",
        "batting_strike_rate",
        "phase",
        ["powerplay", "death"],
        {"batter": "Virat Kohli", "opposition": "Pakistan"},
        "descriptive",
        "absolute",
    ),
]


@pytest.mark.parametrize(
    "question,subject,metric,split_by,values,filters,intent,direction", CASES
)
def test_split_meanings_compile_independent_parts(
    question: str,
    subject: str,
    metric: str,
    split_by: str,
    values: list[str],
    filters: dict[str, object],
    intent: str,
    direction: str,
) -> None:
    result = resolver().resolve(question, None)

    assert result.status == MeaningStatus.resolved
    assert result.meaning is not None
    assert result.meaning.family == "split"
    assert result.meaning.subject == subject
    assert result.meaning.metric == metric
    assert result.meaning.split_by == split_by
    assert result.meaning.compare_values == values
    assert result.meaning.split_intent == intent
    assert result.meaning.split_direction == direction
    for key, value in filters.items():
        assert result.meaning.filters[key] == value

    plan = compile_canonical_meaning(result.meaning)
    assert plan.operation == "split_compare"
    assert plan.entity == subject
    assert plan.metric == metric
    assert plan.group_by == [subject]
    assert plan.split_by == split_by
    assert plan.compare_values == values
    assert plan.minimum_sample is not None


def test_two_named_players_remain_a_player_comparison() -> None:
    result = resolver().resolve(
        "Compare Kohli and Miller in powerplay and death overs", None
    )

    assert result.status == MeaningStatus.resolved
    assert result.meaning is not None
    assert result.meaning.family == "comparison"


def test_split_axis_is_not_left_as_a_filter() -> None:
    result = resolver().resolve(
        "Compare Bumrah's economy in powerplay versus death", None
    )

    assert result.meaning is not None
    assert "phase" not in result.meaning.filters
