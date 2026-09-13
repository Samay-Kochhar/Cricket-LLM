from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
    compile_canonical_meaning,
)
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.player_roles import PlayerParticipation


FACTS = {
    "Virat Kohli": PlayerParticipation(12000, 400),
    "Rohit Sharma": PlayerParticipation(11000, 300),
    "Babar Azam": PlayerParticipation(9000, 30),
    "Steven Smith": PlayerParticipation(7000, 1000),
    "Jos Buttler": PlayerParticipation(6500, 0),
    "Heinrich Klaasen": PlayerParticipation(3000, 0),
    "David Warner": PlayerParticipation(8000, 20),
    "Jasprit Bumrah": PlayerParticipation(150, 5000),
    "Mitchell Starc": PlayerParticipation(700, 6500),
    "Rashid Khan": PlayerParticipation(1000, 6000, frozenset({"spin"})),
    "Ravichandran Ashwin": PlayerParticipation(800, 6000, frozenset({"spin"})),
    "Kagiso Rabada": PlayerParticipation(300, 5000),
    "Shaheen Shah Afridi": PlayerParticipation(300, 5000),
    "Hardik Pandya": PlayerParticipation(2500, 3000),
    "Ravindra Jadeja": PlayerParticipation(3000, 4500),
}


def resolver() -> CanonicalMeaningResolver:
    return CanonicalMeaningResolver(
        available_players=list(FACTS),
        available_venues=["Wankhede Stadium, Mumbai", "Melbourne Cricket Ground"],
        available_teams=["Australia", "Pakistan", "India"],
        player_participation=FACTS,
    )


PACK = [
    (
        "Compare Kohli and Rohit as ODI batters",
        "Rohit versus Kohli across their batting records",
        "batter",
        None,
        {},
    ),
    (
        "Put Babar and Smith side by side as batters",
        "Contrast Steven Smith with Babar Azam on batting numbers",
        "batter",
        None,
        {},
    ),
    (
        "Compare Bumrah and Starc as bowlers",
        "Starc versus Bumrah across their bowling metrics",
        "bowler",
        None,
        {},
    ),
    (
        "Put Rashid and Ashwin side by side as spin bowlers",
        "Contrast Ashwin with Rashid Khan when bowling spin",
        "bowler",
        None,
        {"bowling_style": "spin"},
    ),
    (
        "Who scores faster, Rohit or Kohli?",
        "Compare Kohli with Rohit by batting strike rate",
        "batter",
        ["batting_strike_rate"],
        {},
    ),
    (
        "Compare Kohli and Rohit by total runs",
        "Total runs: Rohit versus Kohli as batters",
        "batter",
        ["runs_scored"],
        {},
    ),
    (
        "Compare Kohli and Babar by batting average",
        "Babar versus Kohli on batting average",
        "batter",
        ["batting_average"],
        {},
    ),
    (
        "Compare Buttler and Klaasen by boundary rate",
        "Boundary percentage: Klaasen versus Buttler as batters",
        "batter",
        ["boundary_percentage"],
        {},
    ),
    (
        "Compare Bumrah and Starc by economy",
        "Starc versus Bumrah on economy rate",
        "bowler",
        ["economy_rate"],
        {},
    ),
    (
        "Compare Bumrah and Starc by bowling strike rate",
        "Bowling strike rate: Starc versus Bumrah",
        "bowler",
        ["bowling_strike_rate"],
        {},
    ),
    (
        "Compare Rabada and Shaheen by wickets taken",
        "Total wickets: Shaheen versus Rabada as bowlers",
        "bowler",
        ["wickets_taken"],
        {},
    ),
    (
        "Compare Bumrah and Starc on economy and wicket rate",
        "Wickets per over and economy: Starc versus Bumrah",
        "bowler",
        ["economy_rate", "wickets_per_over"],
        {},
    ),
    (
        "Against spin, contrast Buttler and Klaasen",
        "Compare Klaasen with Buttler when facing spin bowling",
        "batter",
        None,
        {"bowling_style": "spin"},
    ),
    (
        "Powerplay batting comparison for Rohit and Warner",
        "In the opening ten, contrast Warner with Rohit as batters",
        "batter",
        None,
        {"phase": "powerplay"},
    ),
    (
        "At the death, compare Bumrah with Starc as bowlers",
        "Starc and Bumrah death-over bowling comparison",
        "bowler",
        None,
        {"phase": "death"},
    ),
    (
        "Compare Kohli and Rohit at Wankhede",
        "At Wankhede, put Rohit and Kohli side by side as batters",
        "batter",
        None,
        {"venue": "Wankhede Stadium, Mumbai"},
    ),
    (
        "Compare Kohli and Rohit against Australia",
        "Against Australia, contrast Rohit with Kohli as batters",
        "batter",
        None,
        {"opposition": "Australia"},
    ),
    (
        "Compare Kohli and Rohit in 2023",
        "For 2023, put Rohit and Kohli side by side as batters",
        "batter",
        None,
        {"years": [2023]},
    ),
    (
        "Compare Bumrah and Starc against India at the death",
        "At the death against India, contrast Starc and Bumrah as bowlers",
        "bowler",
        None,
        {"opposition": "India", "phase": "death"},
    ),
    (
        "Compare Kohli and Rohit by strike rate in the powerplay against Pakistan",
        "Against Pakistan in the opening ten, who scores faster: Rohit or Kohli?",
        "batter",
        ["batting_strike_rate"],
        {"opposition": "Pakistan", "phase": "powerplay"},
    ),
]


@pytest.mark.parametrize("first,second,role,metrics,filters", PACK)
def test_twenty_comparison_meanings_preserve_players_role_metrics_and_filters(
    first: str,
    second: str,
    role: str,
    metrics: list[str] | None,
    filters: dict[str, object],
) -> None:
    results = [resolver().resolve(question, None) for question in (first, second)]
    for result in results:
        assert result.status == MeaningStatus.resolved, result
        assert result.meaning.family == "comparison"
        assert result.meaning.role == role
        assert set(result.meaning.participants) == set(results[0].meaning.participants)
        assert all(
            result.meaning.filters.get(key) == value for key, value in filters.items()
        )
        if metrics:
            assert set(result.meaning.comparison_metrics) == set(metrics)
        assert (
            all(
                metric.startswith(("batting", "batter"))
                or metric in {"runs_scored", "boundary_percentage"}
                for metric in result.meaning.comparison_metrics
            )
            if role == "batter"
            else all(
                metric.startswith(("bowling", "bowler", "wickets", "economy"))
                for metric in result.meaning.comparison_metrics
            )
        )


def test_frozen_comparison_family_compiles_expected_plan_fields() -> None:
    benchmark = yaml.safe_load(
        (
            Path(__file__).parents[1] / "benchmarks/odi_unseen_paraphrases_v1.yaml"
        ).read_text()
    )
    for case in benchmark["cases"]:
        if case["family"] != "comparison":
            continue
        turn = case["turns"][0]
        result = resolver().resolve(turn["prompt"], None)
        assert result.meaning is not None, turn["prompt"]
        plan = compile_canonical_meaning(result.meaning).model_dump(
            mode="json", exclude_none=True
        )
        expected = turn["expected"]["plan"]
        assert plan["operation"] == expected["operation"]
        assert plan["entity"] == expected["entity"]
        assert set(plan["filters"]["compare_players"]) == set(
            expected["filters"]["compare_players"]
        )
        assert set(plan["filters"]["comparison_metrics"]) == set(
            expected["filters"]["comparison_metrics"]
        )
        for key, value in expected["filters"].items():
            if key not in {"compare_players", "comparison_metrics"}:
                assert plan["filters"][key] == value


def test_mixed_and_under_specified_comparisons_ask_targeted_questions() -> None:
    mixed = resolver().resolve("Compare Kohli and Bumrah", None)
    assert mixed.status == MeaningStatus.clarification
    assert "batters" in mixed.clarification and "bowlers" in mixed.clarification
    assert "matchup" in mixed.clarification
    missing = resolver().resolve("Compare only Kohli", None)
    assert missing.status == MeaningStatus.clarification
    assert "second player" in missing.clarification


def test_explicit_shared_role_resolves_dual_role_players() -> None:
    ambiguous = resolver().resolve("Compare Hardik and Jadeja", None)
    assert ambiguous.status == MeaningStatus.clarification
    batting = resolver().resolve("Compare Hardik and Jadeja as batters", None).meaning
    bowling = resolver().resolve("Compare Hardik and Jadeja as bowlers", None).meaning
    assert batting.role == "batter"
    assert bowling.role == "bowler"


def test_model_surface_cannot_replace_canonical_comparison() -> None:
    candidate = LanguageMeaningCandidate(
        version=1,
        family="matchup",
        role="bowler",
        metric_concept="economy",
    )
    meaning = (
        resolver()
        .resolve_candidate("Compare Kohli and Rohit by total runs", None, candidate)
        .meaning
    )
    assert meaning.family == "comparison"
    assert meaning.role == "batter"
    assert meaning.comparison_metrics == ["runs_scored"]
