from pathlib import Path

import pytest
import yaml

from backend.app.config import AppConfig
from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
    compile_canonical_meaning,
)
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.executors.matchup_executor import build_matchup_query
from backend.app.cricket_analytics.query_builders.aggregate_builder import BOWLER_WICKET
from backend.app.cricket_analytics.player_roles import PlayerParticipation
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.db.repository import AnalyticsRepository


FACTS = {
    "Virat Kohli": PlayerParticipation(12000, 400),
    "Steven Smith": PlayerParticipation(6000, 1000),
    "Glenn Maxwell": PlayerParticipation(3500, 4000),
    "Ravichandran Ashwin": PlayerParticipation(800, 6000),
    "Mitchell Starc": PlayerParticipation(800, 7000),
    "Jasprit Bumrah": PlayerParticipation(200, 5000),
    "David Warner": PlayerParticipation(6000, 30),
    "David Miller": PlayerParticipation(5000, 0),
    "Heinrich Klaasen": PlayerParticipation(1000, 0),
    "Rashid Khan": PlayerParticipation(1000, 6000),
    "Hardik Pandya": PlayerParticipation(2000, 3000),
    "Ravindra Jadeja": PlayerParticipation(3000, 5000),
    "Unlisted Batter": PlayerParticipation(700, 0),
    "Unlisted Bowler": PlayerParticipation(0, 900),
}


def resolver():
    return CanonicalMeaningResolver(
        available_players=list(FACTS), player_participation=FACTS
    )


# Twenty separate metric/relationship/filter meanings, with two forms apiece.
PACK = [
    (
        "Kohli versus Starc head-to-head numbers",
        "Starc bowling to Kohli: head-to-head numbers",
        "batting_strike_rate",
        "named",
        {},
    ),
    (
        "Smith's scoring record off Bumrah",
        "Bumrah against Smith: show the matchup",
        "batting_strike_rate",
        "named",
        {},
    ),
    (
        "How many runs has Maxwell taken from Ashwin?",
        "Maxwell v Ashwin run tally",
        "runs_scored",
        "named",
        {},
    ),
    (
        "Which bowler gets Warner out most?",
        "Warner's most frequent dismissor",
        "dismissals",
        "bowler_ranking",
        {},
    ),
    (
        "Who controls Klaasen by dot-ball percentage, minimum 60 legal balls?",
        "Against Klaasen rank bowlers on dot rate with 60+ balls",
        "bowler_dot_ball_percentage",
        "bowler_ranking",
        {},
    ),
    (
        "Which bowler induces Miller's highest false-shot percentage after 60 balls?",
        "Miller's toughest bowler by false-shot rate, 60-ball minimum",
        "false_shot_percentage",
        "bowler_ranking",
        {},
    ),
    (
        "Which batter has the best boundary rate off Rashid with 60 balls faced?",
        "Against Rashid who finds boundaries most often after 60 deliveries?",
        "boundary_percentage",
        "batter_ranking",
        {},
    ),
    (
        "Which pace bowler has the highest boundary rate conceded to Kohli, minimum 60 balls?",
        "Kohli versus pace: rank opposing bowlers by boundary percentage with a 60-ball floor",
        "boundary_percentage",
        "bowler_ranking",
        {"bowling_style": "pace"},
    ),
    (
        "Kohli batting strike rate against Starc in the powerplay",
        "In opening ten, Starc bowling to Kohli: batting strike rate",
        "batting_strike_rate",
        "named",
        {"phase": "powerplay"},
    ),
    (
        "Maxwell runs against Ashwin in 2023",
        "In 2023, Maxwell v Ashwin run tally",
        "runs_scored",
        "named",
        {"years": [2023]},
    ),
    (
        "Which bowler dismissed Warner most often at the death?",
        "At the death, who has dismissed Warner most often?",
        "wickets_taken",
        "bowler_ranking",
        {"phase": "death"},
    ),
    (
        "Which bowler controls Kohli by dot rate against off spin?",
        "Against off spin, rank bowlers by dot rate against Kohli",
        "bowler_dot_ball_percentage",
        "bowler_ranking",
        {"bowling_style": "off_spin"},
    ),
    (
        "Which bowler induces false-shot percentage against Miller facing wrist spin?",
        "Facing wrist spin, rank bowlers by false-shot percentage against Miller",
        "false_shot_percentage",
        "bowler_ranking",
        {"bowling_style": "wrist_spin"},
    ),
    (
        "Which batter has the highest batting strike rate against Rashid at the death?",
        "At the death, rank batters by batting strike rate against Rashid",
        "batting_strike_rate",
        "batter_ranking",
        {"phase": "death"},
    ),
    (
        "Which batter has the highest runs against Bumrah?",
        "Against Bumrah rank batters by runs",
        "runs_scored",
        "batter_ranking",
        {},
    ),
    (
        "How many dot balls has Kohli faced against Starc?",
        "Kohli dot ball count facing Starc",
        "dot_balls",
        "named",
        {},
    ),
    (
        "Kohli dot-ball percentage facing Starc",
        "Kohli's dot rate against Starc",
        "batter_dot_ball_percentage",
        "named",
        {},
    ),
    (
        "How many wickets has Starc taken against Kohli?",
        "Kohli facing Starc: wickets taken",
        "wickets_taken",
        "named",
        {},
    ),
    (
        "Unlisted Batter against Unlisted Bowler head-to-head numbers",
        "Unlisted Bowler bowling to Unlisted Batter: head-to-head numbers",
        "batting_strike_rate",
        "named",
        {},
    ),
    (
        "Hardik facing Jadeja: runs",
        "Jadeja bowling to Hardik: runs",
        "runs_scored",
        "named",
        {},
    ),
]


@pytest.mark.parametrize("first,second,metric,relationship,filters", PACK)
def test_twenty_transformed_matchup_meanings(
    first, second, metric, relationship, filters
):
    meanings = []
    for question in (first, second):
        result = resolver().resolve(question, None)
        assert result.status == MeaningStatus.resolved, (question, result)
        meaning = result.meaning
        assert meaning.metric == metric
        assert meaning.relationship == relationship
        assert all(meaning.filters.get(k) == v for k, v in filters.items())
        meanings.append(meaning.model_dump())
    assert meanings[0] == meanings[1]


def test_frozen_matchup_family_compiles_all_expected_fields():
    benchmark = yaml.safe_load(
        (
            Path(__file__).parents[1] / "benchmarks/odi_unseen_paraphrases_v1.yaml"
        ).read_text()
    )
    for case in benchmark["cases"]:
        if case["family"] != "matchup":
            continue
        turn = case["turns"][0]
        result = resolver().resolve(turn["prompt"], None)
        assert result.meaning is not None, turn["prompt"]
        plan = compile_canonical_meaning(result.meaning).model_dump(
            mode="json", exclude_none=True
        )
        for key, value in turn["expected"]["plan"].items():
            assert plan[key] == value, (turn["prompt"], key, plan)


def test_dual_role_players_require_direction_but_explicit_words_resolve_it():
    ambiguous = resolver().resolve("Hardik versus Jadeja head-to-head numbers", None)
    assert ambiguous.status == MeaningStatus.clarification
    assert len(ambiguous.clarification_options) == 2
    for question, batter, bowler in [
        ("Hardik facing Jadeja: runs", "Hardik Pandya", "Ravindra Jadeja"),
        ("Hardik bowling to Jadeja: runs", "Ravindra Jadeja", "Hardik Pandya"),
        ("Jadeja was dismissed by Hardik", "Ravindra Jadeja", "Hardik Pandya"),
    ]:
        meaning = resolver().resolve(question, None).meaning
        assert meaning.filters == {"batter": batter, "bowler": bowler}


def test_explicit_role_nouns_and_initials():
    meaning = (
        resolver().resolve("Bowler M. Starc versus batter V. Kohli: runs", None).meaning
    )
    assert meaning.filters == {"batter": "Virat Kohli", "bowler": "Mitchell Starc"}


def test_surface_comparison_cannot_override_resolved_matchup():
    candidate = LanguageMeaningCandidate(
        version=1, family="comparison", role="bowler", metric_concept="economy_rate"
    )
    meaning = (
        resolver()
        .resolve_candidate("Kohli runs against Starc", None, candidate)
        .meaning
    )
    assert meaning.family == "matchup"
    assert meaning.metric == "runs_scored"
    assert meaning.filters == {"batter": "Virat Kohli", "bowler": "Mitchell Starc"}


def test_repository_participation_covers_both_roles():
    repo = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    facts = repo.player_participation()
    assert facts["Glenn Maxwell"].balls_faced > 0
    assert facts["Glenn Maxwell"].balls_bowled > 0
    assert facts["Jasprit Bumrah"].balls_bowled > facts["Jasprit Bumrah"].balls_faced


def test_rate_rankings_enforce_sample_but_direct_pair_is_descriptive():
    direct = (
        resolver().resolve("Smith against Bumrah: head-to-head numbers", None).meaning
    )
    ranked = (
        resolver().resolve("Which batter scores fastest against Bumrah?", None).meaning
    )
    assert direct.minimum_sample is None
    assert ranked.minimum_sample.balls == 60
    assert not ranked.minimum_sample_explicit


def test_same_role_comparison_stays_outside_matchup_family():
    result = resolver().resolve("Compare Kohli and Smith by batting strike rate", None)
    assert result.meaning is None or result.meaning.family != "matchup"


def execute_matchup(question):
    repo = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    meaning = resolver().resolve(question, None).meaning
    query = build_matchup_query(compile_canonical_meaning(meaning)).query
    return [
        dict(zip(query.columns, row)) for row in repo._fetchall(query.sql, query.params)
    ]


def test_named_dot_count_matches_delivery_truth_and_explicit_floor_is_enforced():
    repo = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    expected = repo._fetchone(
        "SELECT COUNT(*) FROM analytics.deliveries_v1 WHERE bat = ? AND bowl = ? AND TRY_CAST(ballfaced AS INTEGER) = 1 AND COALESCE(TRY_CAST(batruns AS INTEGER), 0) = 0",
        ["Virat Kohli", "Mitchell Starc"],
    )[0]
    rows = execute_matchup("How many dot balls has Kohli faced against Starc?")
    assert rows[0]["rank_value"] == expected
    assert (
        execute_matchup("Kohli dot ball count facing Starc, minimum 100000 balls") == []
    )


def test_opponent_rate_rankings_enforce_legal_ball_floor():
    rows = execute_matchup("Which bowler controls Klaasen by dot percentage?")
    assert rows
    assert all(row["legal_balls"] >= 60 for row in rows)
    assert all(
        row["rank_value"]
        == pytest.approx(100 * row["bowler_dot_balls"] / row["legal_balls"], abs=0.01)
        for row in rows
    )


def test_dismissor_ranking_credits_only_bowler_wickets():
    repo = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    rows = execute_matchup("Warner's most frequent dismissor")
    for row in rows:
        expected = repo._fetchone(
            f"SELECT COUNT(*) FROM analytics.deliveries_v1 WHERE bat = ? AND bowl = ? AND {BOWLER_WICKET}",
            ["David Warner", row["bowler"]],
        )[0]
        assert row["rank_value"] == expected


def test_reversed_subject_syntax_preserves_explicit_batting_direction():
    meaning = (
        resolver()
        .resolve("Against Jadeja, how many runs has Hardik scored?", None)
        .meaning
    )
    assert meaning.filters == {"batter": "Hardik Pandya", "bowler": "Ravindra Jadeja"}
