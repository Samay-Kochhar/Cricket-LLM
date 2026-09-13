from __future__ import annotations

import pytest

from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
)
from backend.app.cricket_analytics.canonical_patches import (
    interpret_meaning_patch,
)
from backend.app.cricket_analytics.player_roles import PlayerParticipation
from backend.app.cricket_analytics.response_policy import (
    POLICY_SOURCE,
    apply_response_policy,
)


PLAYERS = [
    "Jasprit Bumrah",
    "Virat Kohli",
    "Rohit Sharma",
    "David Warner",
    "Heinrich Klaasen",
    "Steven Smith",
    "Ishant Sharma",
    "Rashid Khan",
    "Ayaan Khan",
]
PARTICIPATION = {
    "Jasprit Bumrah": PlayerParticipation(balls_faced=30, balls_bowled=1200),
    "Virat Kohli": PlayerParticipation(balls_faced=1500),
    "Rohit Sharma": PlayerParticipation(balls_faced=1400),
    "David Warner": PlayerParticipation(balls_faced=1300),
    "Heinrich Klaasen": PlayerParticipation(balls_faced=900),
    "Steven Smith": PlayerParticipation(balls_faced=1200),
    "Ishant Sharma": PlayerParticipation(balls_faced=20, balls_bowled=900),
    "Rashid Khan": PlayerParticipation(balls_faced=200, balls_bowled=1000),
    "Ayaan Khan": PlayerParticipation(balls_faced=150),
}


def resolver() -> CanonicalMeaningResolver:
    return CanonicalMeaningResolver(
        available_players=PLAYERS,
        available_teams=["India", "Australia"],
        player_participation=PARTICIPATION,
    )


POLICY_CASES = [
    ("What's Bumrah's strike rate?", MeaningStatus.clarification),
    ("Give me Jasprit Bumrah's SR.", MeaningStatus.clarification),
    ("Who has the best numbers?", MeaningStatus.clarification),
    ("Which player has the strongest statistics?", MeaningStatus.clarification),
    ("Rank the top stats.", MeaningStatus.clarification),
    ("Show the best statistics.", MeaningStatus.clarification),
    ("How good is Sharma?", MeaningStatus.clarification),
    ("Show me Khan's record.", MeaningStatus.clarification),
    ("What are Sharma's numbers?", MeaningStatus.clarification),
    ("How has Khan performed?", MeaningStatus.clarification),
    ("Who took the most catches?", MeaningStatus.data_limitation),
    ("Leading ODI catcher in 2019?", MeaningStatus.data_limitation),
    ("Rank players by fielding record.", MeaningStatus.data_limitation),
    ("Who captained India most often?", MeaningStatus.data_limitation),
    ("Which captain won most often?", MeaningStatus.data_limitation),
    ("Show India's captaincy record.", MeaningStatus.data_limitation),
    ("How did rain affect Kohli?", MeaningStatus.unsupported),
    ("Bumrah's economy in humid weather?", MeaningStatus.unsupported),
    ("Rank players by salary.", MeaningStatus.unsupported),
    ("Who gives the most runs per million dollars?", MeaningStatus.unsupported),
    ("Predict the next World Cup champion.", MeaningStatus.unsupported),
    ("Who will win India's next ODI?", MeaningStatus.unsupported),
    ("Which team has the best economy?", MeaningStatus.unsupported),
    ("Rank national sides by strike rate.", MeaningStatus.unsupported),
]


@pytest.mark.parametrize("question,expected", POLICY_CASES)
def test_policy_classifies_ambiguity_and_capability_after_interpretation(
    question: str, expected: MeaningStatus
) -> None:
    meaning_resolver = resolver()
    candidate = meaning_resolver.resolve(question, None)

    decision = apply_response_policy(
        question,
        candidate,
        available_players=PLAYERS,
        player_roles=meaning_resolver.player_roles,
    )

    assert decision.status == expected
    assert decision.candidate_sources == [POLICY_SOURCE]
    if expected == MeaningStatus.clarification:
        assert decision.clarification
    else:
        assert decision.reason


@pytest.mark.parametrize(
    "question,metric,role",
    [
        ("What is Bumrah's batting strike rate?", "batting_strike_rate", "batter"),
        ("What is Bumrah's bowling strike rate?", "bowling_strike_rate", "bowler"),
        ("What is Kohli's strike rate?", "batting_strike_rate", "batter"),
        ("David Warner strike rate year by year?", "batting_strike_rate", "batter"),
        (
            "Compare Klaasen's strike rate across wrist and finger spin.",
            "batting_strike_rate",
            "batter",
        ),
        ("Smith's scoring record off Bumrah?", "batting_strike_rate", "batter"),
        ("What is Bumrah's economy rate?", "economy_rate", "bowler"),
    ],
)
def test_policy_does_not_change_a_resolved_metric_or_role(
    question: str, metric: str, role: str
) -> None:
    meaning_resolver = resolver()
    candidate = meaning_resolver.resolve(question, None)
    decision = apply_response_policy(
        question,
        candidate,
        available_players=PLAYERS,
        player_roles=meaning_resolver.player_roles,
    )

    assert decision.status == MeaningStatus.resolved
    assert decision.meaning is not None
    assert decision.meaning.metric == metric
    assert decision.meaning.role == role


@pytest.mark.parametrize(
    "base,follow_up,expected_metric",
    [
        ("What is Bumrah's economy rate?", "And SR?", "bowling_strike_rate"),
        ("What is Kohli's batting average?", "And strike rate?", "batting_strike_rate"),
    ],
)
def test_canonical_context_resolves_role_implicit_strike_rate(
    base: str, follow_up: str, expected_metric: str
) -> None:
    meaning_resolver = resolver()
    previous = meaning_resolver.resolve(base, None).meaning
    assert previous is not None

    result = interpret_meaning_patch(meaning_resolver, follow_up, previous)

    assert result.status == "resolved"
    assert result.meaning is not None
    assert result.meaning.metric == expected_metric
    assert result.meaning.role == previous.role


def test_rankings_get_a_default_threshold_while_descriptive_answers_do_not() -> None:
    meaning_resolver = resolver()
    direct = meaning_resolver.resolve("What is Kohli's strike rate?", None).meaning
    ranking = meaning_resolver.resolve("Who has the highest strike rate?", None).meaning

    assert direct is not None and direct.minimum_sample is None
    assert ranking is not None and ranking.minimum_sample is not None
    assert ranking.minimum_sample.balls == 60
    assert ranking.minimum_sample_explicit is False


def test_explicit_ranking_threshold_is_preserved() -> None:
    meaning = (
        resolver()
        .resolve("Rank the best batting strike rates with at least 120 balls.", None)
        .meaning
    )

    assert meaning is not None and meaning.minimum_sample is not None
    assert meaning.minimum_sample.balls == 120
    assert meaning.minimum_sample_explicit is True


def test_supported_team_phase_comparison_is_not_reclassified() -> None:
    meaning_resolver = resolver()
    candidate = meaning_resolver.resolve(
        "Rank teams by the gap between powerplay and death-over run rate.", None
    )
    decision = apply_response_policy(
        "Rank teams by the gap between powerplay and death-over run rate.",
        candidate,
        available_players=PLAYERS,
        player_roles=meaning_resolver.player_roles,
    )

    assert decision.status == MeaningStatus.resolved
    assert decision.meaning is not None
    assert decision.meaning.family == "split"
