"""Independent meaning pack: metric/axis/role/filter transformations, not phrase snapshots."""

from pathlib import Path

import pytest
import yaml

from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
    compile_canonical_meaning,
)
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate

# Twenty meanings, each exercised with three different grammatical arrangements.
PACK = [
    (
        "V. Kohli",
        "Virat Kohli",
        "runs",
        "runs_scored",
        "batter",
        "line",
        "bowling lines",
        "",
    ),
    (
        "Rohit",
        "Rohit Sharma",
        "dot-ball percentage",
        "batter_dot_ball_percentage",
        "batter",
        "length",
        "delivery lengths",
        "",
    ),
    (
        "Babar",
        "Babar Azam",
        "scoring rate",
        "batting_strike_rate",
        "batter",
        "bowling_style",
        "bowler types",
        "",
    ),
    (
        "Buttler",
        "Jos Buttler",
        "runs",
        "runs_scored",
        "batter",
        "shot_type",
        "shot selections",
        "",
    ),
    (
        "Klaasen",
        "Heinrich Klaasen",
        "boundary percentage",
        "boundary_percentage",
        "batter",
        "field_zone",
        "regions",
        "",
    ),
    (
        "Bumrah",
        "Jasprit Bumrah",
        "wickets",
        "wickets_taken",
        "bowler",
        "length",
        "lengths",
        "",
    ),
    (
        "Starc",
        "Mitchell Starc",
        "dot-ball percentage",
        "bowler_dot_ball_percentage",
        "bowler",
        "line",
        "lines",
        "",
    ),
    (
        "Rashid",
        "Rashid Khan",
        "economy",
        "economy_rate",
        "bowler",
        "phase",
        "stages of the innings",
        "",
    ),
    (
        "Boult",
        "Trent Boult",
        "wickets",
        "wickets_taken",
        "bowler",
        "batter_hand",
        "batter handedness",
        "",
    ),
    (
        "Warner",
        "David Warner",
        "batting strike rate",
        "batting_strike_rate",
        "batter",
        "year",
        "years",
        "",
    ),
    (
        "Kohli",
        "Virat Kohli",
        "dot ball count",
        "dot_balls",
        "batter",
        "line",
        "lines",
        "",
    ),
    (
        "Bumrah",
        "Jasprit Bumrah",
        "dot ball count",
        "bowler_dot_balls",
        "bowler",
        "length",
        "lengths",
        "",
    ),
    (
        "Starc",
        "Mitchell Starc",
        "runs conceded",
        "runs_conceded",
        "bowler",
        "phase",
        "innings phases",
        "",
    ),
    (
        "Rohit",
        "Rohit Sharma",
        "runs",
        "runs_scored",
        "batter",
        "year",
        "years",
        "against off spin",
    ),
    (
        "Kohli",
        "Virat Kohli",
        "runs",
        "runs_scored",
        "batter",
        "shot_type",
        "shots",
        "against leg spin",
    ),
    (
        "Buttler",
        "Jos Buttler",
        "batting strike rate",
        "batting_strike_rate",
        "batter",
        "length",
        "lengths",
        "against wrist spin",
    ),
    (
        "Klaasen",
        "Heinrich Klaasen",
        "runs",
        "runs_scored",
        "batter",
        "line",
        "lines",
        "against finger spin",
    ),
    (
        "Babar",
        "Babar Azam",
        "runs",
        "runs_scored",
        "batter",
        "field_zone",
        "scoring zones",
        "against left-arm pace",
    ),
    (
        "Rashid",
        "Rashid Khan",
        "dot-ball percentage",
        "bowler_dot_ball_percentage",
        "bowler",
        "year",
        "years",
        "against lefties",
    ),
    (
        "Kohli",
        "Virat Kohli",
        "batting strike rate",
        "batting_strike_rate",
        "batter",
        "length",
        "lengths",
        "in 2023 during opening ten with at least 40 balls",
    ),
]
PLAYERS = sorted({row[1] for row in PACK})


def resolver():
    from backend.app.cricket_analytics.player_roles import PlayerParticipation
    return CanonicalMeaningResolver(available_players=PLAYERS, player_participation={
        row[1]: PlayerParticipation(100, 1000) if row[4] == "bowler" else PlayerParticipation(1000, 100)
        for row in PACK
    })


@pytest.mark.parametrize("alias,player,words,metric,role,dimension,axis,filters", PACK)
def test_transformed_breakdown_meanings(
    alias, player, words, metric, role, dimension, axis, filters
):
    questions = [
        f"Show {alias}'s {words} across {axis} {filters}.",
        f"{filters}, partition {words} for {alias} by {axis}.",
        f"Grouped by {axis}, give {alias}'s {words} {filters}.",
    ]
    meanings = []
    for question in questions:
        result = resolver().resolve(question, None)
        assert result.status == MeaningStatus.resolved
        meaning = result.meaning
        assert meaning.family == "breakdown"
        assert (meaning.metric, meaning.role, meaning.group_by) == (
            metric,
            role,
            [dimension],
        )
        assert meaning.filters[role] == player
        plan = compile_canonical_meaning(meaning)
        assert (
            plan.limit is None
        )  # Complete category coverage, including >10 shots/years.
        meanings.append(meaning.model_dump())
    assert meanings[0] == meanings[1] == meanings[2]
    if filters.startswith("against") and "lefties" not in filters:
        assert meanings[0]["filters"]["bowling_style"] == filters.removeprefix(
            "against "
        ).replace("-", "_").replace(" ", "_")
    if "2023" in filters:
        assert meanings[0]["filters"]["years"] == [2023]
        assert meanings[0]["filters"]["phase"] == "powerplay"
        assert meanings[0]["minimum_sample"]["balls"] == 40
        assert meanings[0]["minimum_sample_explicit"]


def test_frozen_unseen_breakdowns():
    benchmark = yaml.safe_load(
        (
            Path(__file__).parents[1] / "benchmarks/odi_unseen_paraphrases_v1.yaml"
        ).read_text()
    )
    for case in benchmark["cases"]:
        if case["family"] != "breakdown":
            continue
        turn = case["turns"][0]
        result = resolver().resolve(turn["prompt"], None)
        assert result.status == MeaningStatus.resolved, turn["prompt"]
        plan = compile_canonical_meaning(result.meaning).model_dump(
            mode="json", exclude_none=True
        )
        for key, value in turn["expected"]["plan"].items():
            assert plan[key] == value, (turn["prompt"], key)


def test_productive_shot_preserves_runs_and_candidate_cannot_change_metric():
    question = "Which is Buttler's most productive shot?"
    result = resolver().resolve_candidate(
        question,
        None,
        LanguageMeaningCandidate(
            version=1,
            family="breakdown",
            metric_concept="batting_strike_rate",
            role="batter",
            breakdown_dimensions=["shot type"],
        ),
    )
    assert result.meaning.metric == "runs_scored"
    assert result.meaning.group_by == ["shot_type"]


@pytest.mark.parametrize("word,direction", [("highest", "desc"), ("lowest", "asc")])
def test_breakdown_sorting(word, direction):
    result = resolver().resolve(
        f"Which length gives Kohli the {word} dot-ball percentage?", None
    )
    assert result.meaning.sort_direction == direction


def test_split_surface_gloss_and_duplicate_player_fact_reconcile():
    from backend.app.cricket_analytics.language_meaning import ExpressedFilter

    result = resolver().resolve_candidate(
        "Split Babar's scoring rate by bowler type",
        None,
        LanguageMeaningCandidate(
            version=1,
            family="split",
            metric_concept="scoring rate",
            split_dimensions=["bowler type"],
            filters=[
                ExpressedFilter(
                    concept="player", values=["Babar Azam"], evidence="Babar"
                )
            ],
        ),
    )
    assert result.meaning.family == "breakdown"
    assert result.meaning.filters == {"batter": "Babar Azam"}
    assert result.meaning.metric == "batting_strike_rate"


def test_complete_breakdown_sql_has_no_implicit_ten_category_limit():
    from backend.app.cricket_analytics.query_builders.aggregate_builder import (
        build_aggregate_query,
    )

    meaning = resolver().resolve("Buttler runs by shot type", None).meaning
    query = build_aggregate_query(compile_canonical_meaning(meaning))
    assert "LIMIT" not in query.sql


def test_explicit_batting_role_overrides_known_bowler_name():
    meaning = (
        resolver()
        .resolve("Starc dot-ball percentage as a batter by year", None)
        .meaning
    )
    assert meaning.metric == "batter_dot_ball_percentage"
    assert meaning.filters["batter"] == "Mitchell Starc"


def test_breakdown_keeps_explicit_delivery_filter():
    meaning = resolver().resolve("Kohli runs by line against short balls", None).meaning
    assert meaning.filters == {"batter": "Virat Kohli", "length": "SHORT"}
    assert meaning.group_by == ["line"]


def test_explicit_category_limit_and_per_over_metric_are_preserved():
    meaning = (
        resolver()
        .resolve("Show Bumrah's top 3 lines by false shots per over", None)
        .meaning
    )
    assert meaning.metric == "false_shots_per_over"
    assert meaning.role == "bowler"
    assert meaning.filters == {"bowler": "Jasprit Bumrah"}
    assert meaning.limit == 3


def test_unavailable_named_player_cannot_turn_into_an_all_player_breakdown():
    result = CanonicalMeaningResolver(available_players=["Virat Kohli"]).resolve(
        "Bumrah wickets by length", None
    )
    assert result.status == MeaningStatus.clarification
    assert result.meaning is None
