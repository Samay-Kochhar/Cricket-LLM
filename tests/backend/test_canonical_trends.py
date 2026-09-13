from __future__ import annotations

from unittest.mock import Mock

import pytest

from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.player_roles import PlayerParticipation
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.services.gemini_client import GeminiClient, GeminiStructuredResult


SUBJECTS = [
    ("Kohli", "Virat Kohli", "scoring rate", "batting_strike_rate", "batter"),
    ("Rohit", "Rohit Sharma", "run totals", "runs_scored", "batter"),
    ("Bumrah", "Jasprit Bumrah", "economy", "economy_rate", "bowler"),
    ("Starc", "Mitchell Starc", "bowling average", "bowling_average", "bowler"),
    ("Rashid", "Rashid Khan", "wickets", "wickets_taken", "bowler"),
]
SCOPES = [
    ("since 2018", {"years": [2018], "year_mode": "after"}),
    (
        "from 2018 onward at the death",
        {"years": [2018], "year_mode": "after", "phase": "death"},
    ),
    (
        "against Australia at the MCG",
        {"opposition": "Australia", "venue": "Melbourne Cricket Ground"},
    ),
    ("in the powerplay in 2019", {"phase": "powerplay", "years": [2019]}),
]
TEMPORAL = [
    "annually",
    "season by season",
    "year-over-year",
    "yearly",
    "trend",
    "by year",
    "each year",
]


def production_plan(question: str):
    gemini = Mock(spec=GeminiClient)
    gemini.is_configured.return_value = True
    # Deliberately contradictory gloss: explicit statistic and annual intent win.
    gemini.generate_structured.return_value = GeminiStructuredResult(
        text=LanguageMeaningCandidate(
            version=1,
            family="ranking",
            metric_concept="runs_scored",
            ordering="highest",
            limit=10,
        ).model_dump_json(),
        selected_model="captured-flash",
        model_version=None,
        latency_ms=0,
        finish_reason="STOP",
        schema_constrained=True,
    )
    planner = SemanticQueryPlanner(
        gemini_client=gemini,
        available_players=[s[1] for s in SUBJECTS],
        available_venues=["Melbourne Cricket Ground"],
        available_teams=["Australia"],
        player_participation={
            s[1]: PlayerParticipation(
                5000 if s[4] == "batter" else 100, 5000 if s[4] == "bowler" else 100
            )
            for s in SUBJECTS
        },
        allow_dev_fallback=False,
    )
    trace = QueryTrace(original_user_question=question)
    result = planner.plan(question, trace)
    assert result.used_gemini
    gemini.generate_structured.assert_called_once()
    assert result.validation.valid, result.validation.errors
    assert trace.canonical_meaning["family"] == "trend"
    assert result.plan is not None
    return result.plan


@pytest.mark.parametrize("alias,player,phrase,metric,role", SUBJECTS)
@pytest.mark.parametrize("scope,filters", SCOPES)
@pytest.mark.parametrize("temporal", TEMPORAL)
def test_twenty_meanings_across_temporal_synonyms(
    alias, player, phrase, metric, role, scope, filters, temporal
):
    plan = production_plan(f"{scope}, show {alias}'s {phrase} {temporal}.")
    assert plan.metric == metric
    assert plan.entity == role
    assert plan.filters == {**filters, role: player}
    assert plan.group_by == ["year"]
    assert plan.sort.by == "year"
    assert plan.sort.direction == "asc"
    assert plan.limit is None
    assert plan.question_subject == "yearly_trend"


@pytest.mark.parametrize(
    "tense", ["changed", "change", "evolved", "improved", "declined"]
)
def test_change_with_year_scope(tense):
    plan = production_plan(
        f"How has Kohli's batting strike rate {tense} from 2018 onward against spin?"
    )
    assert plan.metric == "batting_strike_rate"
    assert plan.filters["bowling_style"] == "spin"
    assert plan.filters["year_mode"] == "after"


def test_per_year_explicit_sample_and_all_filters():
    plan = production_plan(
        "Kohli strike rate annually since 2018 against spin against Australia at the MCG in the powerplay, minimum 120 balls per year"
    )
    assert plan.filters == {
        "batter": "Virat Kohli",
        "years": [2018],
        "year_mode": "after",
        "bowling_style": "spin",
        "opposition": "Australia",
        "venue": "Melbourne Cricket Ground",
        "phase": "powerplay",
    }
    assert plan.minimum_sample.balls == 120
    assert plan.minimum_sample_explicit


def test_since_alone_remains_a_total():
    from backend.app.cricket_analytics.canonical_trends import has_annual_meaning

    assert not has_annual_meaning("kohli runs since 2018")


def test_rate_defaults_are_per_year_and_counts_have_no_sample_floor():
    from backend.app.cricket_analytics.query_builders.aggregate_builder import (
        build_aggregate_query,
    )

    rate = production_plan("Kohli batting strike rate annually")
    count = production_plan("Rohit run totals annually")
    assert rate.minimum_sample.balls == 60
    assert not rate.minimum_sample_explicit
    assert count.minimum_sample is None
    query = build_aggregate_query(rate)
    assert "LIMIT" not in query.sql
    assert "year" in query.sql


@pytest.mark.parametrize(
    "scope,years,mode",
    [("before 2018", [2018], "before"), ("in 2018 and 2020", [2018, 2020], None)],
)
def test_year_scope_mode_stays_independent_of_temporal_grouping(scope, years, mode):
    plan = production_plan(f"Kohli batting strike rate {scope} annually")
    assert plan.filters["years"] == years
    assert plan.filters.get("year_mode") == mode


def test_unqualified_bowler_strike_rate_still_requires_role_clarification():
    from backend.app.cricket_analytics.canonical_meaning import (
        CanonicalMeaningResolver,
        MeaningStatus,
    )

    resolver = CanonicalMeaningResolver(
        available_players=["Jasprit Bumrah"],
        player_participation={"Jasprit Bumrah": PlayerParticipation(100, 5000)},
    )
    result = resolver.resolve("Bumrah strike rate annually", None)
    assert result.status == MeaningStatus.clarification
    assert result.meaning is None
