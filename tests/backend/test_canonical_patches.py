from __future__ import annotations

import pytest

from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalCricketMeaning,
    CanonicalMeaningResolver,
)
from backend.app.cricket_analytics.canonical_patches import (
    VersionedCanonicalMeaning,
    interpret_meaning_patch,
)
from backend.app.cricket_analytics.player_roles import PlayerParticipation
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.trace import QueryTrace


FACTS = {
    "Virat Kohli": PlayerParticipation(12000, 400),
    "Rohit Sharma": PlayerParticipation(11000, 300),
    "David Warner": PlayerParticipation(8000, 20),
    "Jasprit Bumrah": PlayerParticipation(150, 5000),
    "Mitchell Starc": PlayerParticipation(700, 6500),
}


def resolver() -> CanonicalMeaningResolver:
    return CanonicalMeaningResolver(
        available_players=list(FACTS),
        available_venues=["Lord's, London", "Melbourne Cricket Ground"],
        available_teams=["Australia", "Pakistan", "India"],
        player_participation=FACTS,
    )


def meaning(question: str) -> CanonicalCricketMeaning:
    result = resolver().resolve(question, None)
    assert result.meaning is not None, result
    return result.meaning


SCENARIOS = [
    (
        "What is Kohli's batting strike rate at the death?",
        "Now only in the powerplay",
        "filter.phase",
        "replace",
        "powerplay",
    ),
    (
        "What is Kohli's batting strike rate?",
        "And against spin?",
        "filter.bowling_style",
        "add",
        "spin",
    ),
    (
        "What is Kohli's batting strike rate against Australia?",
        "Use any opposition",
        "filter.opposition",
        "remove",
        None,
    ),
    (
        "What is Kohli's batting strike rate at the MCG?",
        "What about at Lord's?",
        "filter.venue",
        "replace",
        "Lord's, London",
    ),
    (
        "What is Kohli's batting strike rate in 2018?",
        "Instead, since 2020",
        "filter.years",
        "replace",
        [2020],
    ),
    (
        "What is Kohli's batting strike rate?",
        "And in 2020?",
        "filter.years",
        "add",
        [2020],
    ),
    (
        "What is Bumrah's economy rate?",
        "Now against left-handed batters",
        "filter.batter_hand",
        "add",
        "LHB",
    ),
    (
        "What is Kohli's batting strike rate?",
        "What about batting average?",
        "metric",
        "replace",
        "batting_average",
    ),
    (
        "Top 5 batters by batting strike rate",
        "Use top 3 instead",
        "limit",
        "replace",
        3,
    ),
    (
        "Top 5 batters by batting strike rate minimum 60 balls",
        "Minimum 200 balls instead",
        "minimum_sample",
        "replace",
        {"balls": 200},
    ),
    (
        "Top 5 batters by batting strike rate minimum 60 balls",
        "No minimum",
        "minimum_sample",
        "remove",
        None,
    ),
    (
        "Top 5 batters by batting strike rate",
        "Show all results",
        "limit",
        "remove",
        None,
    ),
    (
        "Compare Rohit and Warner as batters",
        "Use just the powerplay",
        "filter.phase",
        "add",
        "powerplay",
    ),
    (
        "How has Kohli scored against Starc?",
        "And at the death?",
        "filter.phase",
        "add",
        "death",
    ),
    (
        "Show Bumrah's economy year by year",
        "Restrict it to death overs",
        "filter.phase",
        "add",
        "death",
    ),
    ("Kohli runs by line", "And against spin?", "filter.bowling_style", "add", "spin"),
    (
        "Compare Bumrah economy in powerplay versus death",
        "And against Australia?",
        "filter.opposition",
        "add",
        "Australia",
    ),
    (
        "What is Kohli's batting strike rate in death overs?",
        "Overall, remove the phase",
        "filter.phase",
        "remove",
        None,
    ),
    (
        "What is Kohli's batting strike rate in 2018?",
        "Use all years",
        "filter.years",
        "remove",
        None,
    ),
    (
        "What is Kohli's batting strike rate against spin?",
        "Against pace instead",
        "filter.bowling_style",
        "replace",
        "pace",
    ),
]


@pytest.mark.parametrize("base,follow_up,target,action,value", SCENARIOS)
def test_contextual_turn_is_a_typed_patch_that_preserves_unmentioned_meaning(
    base: str,
    follow_up: str,
    target: str,
    action: str,
    value: object,
) -> None:
    previous = meaning(base)
    result = interpret_meaning_patch(resolver(), follow_up, previous)

    assert result.status == "resolved"
    assert result.patch is not None
    operation = next(item for item in result.patch.operations if item.target == target)
    assert operation.action == action
    assert operation.value == value
    assert result.meaning is not None
    assert result.meaning.family == previous.family
    assert result.meaning.role == previous.role
    assert result.meaning.participants == previous.participants
    assert result.meaning.comparison_metrics == previous.comparison_metrics
    assert result.meaning.split_by == previous.split_by
    assert result.meaning.compare_values == previous.compare_values
    assert result.meaning.group_by == previous.group_by


def test_two_consecutive_patches_accumulate_without_replanning() -> None:
    original = meaning("What is Kohli's batting strike rate?")
    first = interpret_meaning_patch(resolver(), "Now only at the death", original)
    assert first.meaning is not None
    second = interpret_meaning_patch(resolver(), "And against spin?", first.meaning)
    assert second.meaning is not None
    assert second.meaning.filters == {
        "batter": "Virat Kohli",
        "phase": "death",
        "bowling_style": "spin",
    }


def test_role_context_resolves_an_implicit_strike_rate_patch() -> None:
    previous = meaning("What is Bumrah's economy rate at the death?")
    result = interpret_meaning_patch(resolver(), "What about strike rate?", previous)
    assert result.status == "resolved"
    assert result.meaning is not None
    assert result.meaning.metric == "bowling_strike_rate"
    assert result.meaning.filters["phase"] == "death"


def test_split_axis_patch_requests_targeted_clarification() -> None:
    previous = meaning("Compare Bumrah economy in powerplay versus death")
    result = interpret_meaning_patch(resolver(), "Use middle overs instead", previous)
    assert result.status == "clarification"
    assert "comparison axis" in (result.clarification or "")


class NoModelCalls:
    def is_configured(self) -> bool:
        return True

    def generate_structured(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("A structured patch must not re-plan with a model")


def test_production_planner_compiles_patch_with_original_family_compiler() -> None:
    previous = meaning("Show Bumrah's economy year by year")
    state = {"canonical_meaning": VersionedCanonicalMeaning(meaning=previous)}
    planner = SemanticQueryPlanner(
        gemini_client=NoModelCalls(),  # type: ignore[arg-type]
        available_players=list(FACTS),
        available_venues=["Lord's, London", "Melbourne Cricket Ground"],
        available_teams=["Australia", "Pakistan", "India"],
        player_participation=FACTS,
        allow_dev_fallback=False,
    )
    trace = QueryTrace(original_user_question="Use powerplay instead")

    result = planner.plan("Use powerplay instead", trace, state)

    assert result.validation.valid
    assert result.plan is not None
    assert result.plan.question_subject == "yearly_trend"
    assert result.plan.group_by == ["year"]
    assert result.plan.filters == {
        "bowler": "Jasprit Bumrah",
        "phase": "powerplay",
    }
    assert trace.meaning_patch == {
        "version": 1,
        "operations": [
            {
                "action": "add",
                "target": "filter.phase",
                "value": "powerplay",
            }
        ],
    }
    assert trace.planner_outcome["parse_outcome"] == "canonical_meaning_patch"


def test_complete_new_question_does_not_inherit_the_previous_meaning() -> None:
    previous = meaning("What is Kohli's batting strike rate at the death?")
    state = {"canonical_meaning": VersionedCanonicalMeaning(meaning=previous)}
    planner = SemanticQueryPlanner(
        gemini_client=NoModelCalls(),  # type: ignore[arg-type]
        available_players=list(FACTS),
        available_teams=["Australia", "Pakistan", "India"],
        player_participation=FACTS,
        allow_dev_fallback=True,
    )
    trace = QueryTrace(original_user_question="What are Warner's total runs?")

    result = planner.plan("What are Warner's total runs?", trace, state)

    assert result.plan is not None
    assert result.plan.filters == {"batter": "David Warner"}
    assert result.plan.metric == "runs_scored"
    assert trace.meaning_patch is None
