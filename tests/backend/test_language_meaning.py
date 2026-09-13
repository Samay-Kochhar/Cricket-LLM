from __future__ import annotations

import json
import pytest

from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
)
from backend.app.cricket_analytics.language_meaning import LanguageMeaningCandidate
from backend.app.cricket_analytics.player_roles import PlayerParticipation

from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.services.gemini_client import GeminiStructuredResult


class ExtractionClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def is_configured(self):
        return True

    def generate_structured(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        response = self.responses.pop(0)
        return GeminiStructuredResult(
            text=json.dumps(response) if isinstance(response, dict) else response,
            selected_model="pro" if kwargs["prefer_complex"] else "flash",
            model_version="test",
            finish_reason="STOP",
            latency_ms=1,
        )


def test_production_direct_extracts_language_once_and_compiles_in_code():
    client = ExtractionClient(
        {"version": 1, "family": "direct", "metric_concept": "run tally"}
    )
    planner = SemanticQueryPlanner(client, ["Virat Kohli"], allow_dev_fallback=False)
    trace = QueryTrace("How many runs has Kohli scored?")
    result = planner.plan(trace.original_user_question, trace)
    assert result.validation.valid
    assert result.plan.metric == "runs_scored"
    assert result.plan.filters == {"batter": "Virat Kohli"}
    assert len(client.calls) == 1
    assert client.calls[0]["response_schema"]["title"] == "LanguageMeaningCandidate"
    assert client.calls[0]["prefer_complex"] is False
    assert trace.parsed_json_plan is None
    assert trace.canonical_meaning["family"] == "direct"


def test_surface_candidate_supplies_meaning_missing_from_deterministic_vocabulary():
    resolver = CanonicalMeaningResolver(available_players=["Virat Kohli"])
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "batting strike rate",
            "entities": [{"name": "Kohli", "kind": "player", "role": "batter"}],
        }
    )
    resolution = resolver.resolve_candidate("Kohli's scoring pace?", None, candidate)
    assert resolution.status == MeaningStatus.resolved
    assert resolution.meaning.metric == "batting_strike_rate"
    assert resolution.meaning.filters == {"batter": "Virat Kohli"}


def test_candidate_explicit_filter_is_preserved_when_deterministic_candidate_omits_it():
    resolver = CanonicalMeaningResolver(available_players=["Virat Kohli"])
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "runs",
            "filters": [{"concept": "innings", "values": [2], "evidence": "chasing"}],
        }
    )
    resolution = resolver.resolve_candidate("Kohli's runs chasing?", None, candidate)
    assert resolution.meaning.filters == {"batter": "Virat Kohli", "innings": 2}


# Independently specified meanings: these are not generated from planner output or
# from the frozen unseen benchmark. Each pack varies both wording and model surface.
MEANING_PACKS = [
    (
        "run-alias",
        ["Kohli: runs?", "Virat Kohli's run tally?"],
        "direct",
        "batter",
        "runs_scored",
        ["runs", "run tally"],
        {"batter": "Virat Kohli"},
    ),
    (
        "batting-rate",
        ["Rohit batting strike rate?", "Batting strike rate — Rohit Sharma?"],
        "direct",
        "batter",
        "batting_strike_rate",
        ["batting strike rate", "batting_strike_rate"],
        {"batter": "Rohit Sharma"},
    ),
    (
        "batting-average",
        ["Kohli's average?", "Batting average for Virat Kohli?"],
        "direct",
        "batter",
        "batting_average",
        ["batting average", "batting_average"],
        {"batter": "Virat Kohli"},
    ),
    (
        "bowling-rate",
        ["Bumrah bowling strike rate?", "Bowling strike rate: Jasprit Bumrah."],
        "direct",
        "bowler",
        "bowling_strike_rate",
        ["bowling strike rate", "bowling_strike_rate"],
        {"bowler": "Jasprit Bumrah"},
    ),
    (
        "bowling-average",
        ["Starc bowling average?", "Mitchell Starc's bowling average, please."],
        "direct",
        "bowler",
        "bowling_average",
        ["bowling average", "bowling_average"],
        {"bowler": "Mitchell Starc"},
    ),
    (
        "economy",
        ["Bumrah economy?", "Jasprit Bumrah's economy rate?"],
        "direct",
        "bowler",
        "economy_rate",
        ["economy", "economy_rate"],
        {"bowler": "Jasprit Bumrah"},
    ),
    (
        "wickets",
        ["Starc wickets?", "Wickets taken by Mitchell Starc?"],
        "direct",
        "bowler",
        "wickets_taken",
        ["wickets", "wickets_taken"],
        {"bowler": "Mitchell Starc"},
    ),
    (
        "yorker-count",
        ["How many yorkers has Bumrah bowled?", "Jasprit Bumrah yorker count?"],
        "direct",
        "bowler",
        "yorker_count",
        ["yorker count", "yorker_count"],
        {"bowler": "Jasprit Bumrah"},
    ),
    (
        "yorker-rate",
        ["Bumrah yorker percentage?", "Yorker rate for Jasprit Bumrah?"],
        "direct",
        "bowler",
        "yorker_percentage",
        ["yorker rate", "yorker_percentage"],
        {"bowler": "Jasprit Bumrah"},
    ),
    (
        "dots-batting",
        ["Kohli dot percentage?", "Virat Kohli's dot-ball rate?"],
        "direct",
        "batter",
        "batter_dot_ball_percentage",
        ["batter dot percentage", "batter_dot_ball_percentage"],
        {"batter": "Virat Kohli"},
    ),
    (
        "dots-bowling",
        ["Bumrah dot percentage?", "Dot-ball rate for bowler Jasprit Bumrah?"],
        "direct",
        "bowler",
        "bowler_dot_ball_percentage",
        ["bowler dot percentage", "bowler_dot_ball_percentage"],
        {"bowler": "Jasprit Bumrah"},
    ),
    (
        "false-shots",
        ["Rohit false-shot percentage?", "False shot rate: Rohit Sharma."],
        "direct",
        "batter",
        "false_shot_percentage",
        ["false shot rate", "false_shot_percentage"],
        {"batter": "Rohit Sharma"},
    ),
    (
        "boundaries",
        ["Kohli boundary rate?", "Virat Kohli boundary percentage?"],
        "direct",
        "batter",
        "boundary_percentage",
        ["boundary rate", "boundary_percentage"],
        {"batter": "Virat Kohli"},
    ),
    (
        "boundary-conceded",
        [
            "Boundaries conceded by Bumrah, percentage?",
            "Jasprit Bumrah's boundary rate conceded?",
        ],
        "direct",
        "bowler",
        "boundary_percentage",
        ["boundary percentage", "boundary_percentage"],
        {"bowler": "Jasprit Bumrah"},
    ),
    (
        "team-alias",
        ["Kohli runs versus AUS?", "Against Australia, Virat Kohli's runs?"],
        "direct",
        "batter",
        "runs_scored",
        ["runs", "runs_scored"],
        {"batter": "Virat Kohli", "opposition": "Australia"},
    ),
    (
        "venue-punctuation",
        ["Kohli runs at Lord's?", "At Lord’s, Virat Kohli run tally?"],
        "direct",
        "batter",
        "runs_scored",
        ["runs", "run tally"],
        {"batter": "Virat Kohli", "venue": "Lord's, London"},
    ),
    (
        "year",
        ["Kohli runs in 2018?", "In 2018, Virat Kohli's runs?"],
        "direct",
        "batter",
        "runs_scored",
        ["runs", "runs_scored"],
        {"batter": "Virat Kohli", "years": [2018]},
    ),
    (
        "powerplay",
        ["Rohit runs in overs 1-10?", "Rohit Sharma powerplay runs?"],
        "direct",
        "batter",
        "runs_scored",
        ["runs", "runs_scored"],
        {"batter": "Rohit Sharma", "phase": "powerplay"},
    ),
    (
        "middle",
        ["Kohli runs in middle overs?", "Virat Kohli runs in overs 11 to 40?"],
        "direct",
        "batter",
        "runs_scored",
        ["runs", "runs_scored"],
        {"batter": "Virat Kohli", "phase": "middle"},
    ),
    (
        "death",
        ["Bumrah wickets at the death?", "Jasprit Bumrah wickets after over 40?"],
        "direct",
        "bowler",
        "wickets_taken",
        ["wickets", "wickets_taken"],
        {"bowler": "Jasprit Bumrah", "phase": "death"},
    ),
    (
        "spin",
        ["Kohli runs facing spin?", "Virat Kohli runs against spin?"],
        "direct",
        "batter",
        "runs_scored",
        ["runs", "run tally"],
        {"batter": "Virat Kohli", "bowling_style": "spin"},
    ),
    (
        "left-hand",
        [
            "Bumrah wickets to lefties?",
            "Jasprit Bumrah wickets against left-handed batters?",
        ],
        "direct",
        "bowler",
        "wickets_taken",
        ["wickets", "wickets_taken"],
        {"bowler": "Jasprit Bumrah", "batter_hand": "LHB"},
    ),
    (
        "ranking-limit",
        ["Top 7 batters by runs", "Rank seven batters by runs"],
        "ranking",
        "batter",
        "runs_scored",
        ["run tally", "runs_scored"],
        {},
    ),
    (
        "ranking-count-threshold",
        [
            "Most yorkers, top 4 bowlers, minimum 80 legal balls",
            "Top four bowlers by yorker count, at least 80 legal balls",
        ],
        "ranking",
        "bowler",
        "yorker_count",
        ["yorker count", "yorker_count"],
        {},
    ),
    (
        "ranking-rate-order",
        [
            "Lowest economy, top 6 bowlers, minimum 90 legal balls",
            "Top six bowlers by lowest economy rate, at least 90 legal balls",
        ],
        "ranking",
        "bowler",
        "economy_rate",
        ["economy", "economy_rate"],
        {},
    ),
]


@pytest.mark.parametrize("pack", MEANING_PACKS, ids=lambda pack: pack[0])
def test_independent_meaning_pack_normalizes_different_flash_surfaces(pack):
    name, questions, family, role, metric, surfaces, filters = pack
    meanings = []
    for question, surface in zip(questions, surfaces):
        client = ExtractionClient(
            {"version": 1, "family": family, "metric_concept": surface, "role": role}
        )
        planner = SemanticQueryPlanner(
            client,
            ["Virat Kohli", "Rohit Sharma", "Jasprit Bumrah", "Mitchell Starc"],
            ["Lord's, London"],
            ["Australia"],
            allow_dev_fallback=False,
            player_participation={
                "Virat Kohli": PlayerParticipation(1000, 10),
                "Rohit Sharma": PlayerParticipation(1000, 10),
                "Jasprit Bumrah": PlayerParticipation(10, 1000),
                "Mitchell Starc": PlayerParticipation(10, 1000),
            },
        )
        trace = QueryTrace(question)
        result = planner.plan(question, trace)
        assert result.validation.valid, result.validation.errors
        assert result.plan.metric == metric
        assert result.plan.entity == role
        assert result.plan.filters == filters
        assert len(client.calls) == 1 and not client.calls[0]["prefer_complex"]
        meanings.append(trace.canonical_meaning)
    assert meanings[0] == meanings[1]
    if name == "ranking-limit":
        assert meanings[0]["limit"] == 7
    if name == "ranking-count-threshold":
        assert meanings[0]["limit"] == 4
        assert meanings[0]["minimum_sample"]["legal_balls"] == 80
        assert meanings[0]["minimum_sample_explicit"] is True
    if name == "ranking-rate-order":
        assert meanings[0]["sort_direction"] == "asc"
        assert meanings[0]["minimum_sample"]["legal_balls"] == 90


@pytest.mark.parametrize(
    "output",
    [
        None,
        "not-json",
        '{"version":1}',
        {"version": 1, "family": "direct", "sql": "SELECT 1"},
    ],
)
def test_malformed_or_unavailable_flash_never_repairs_or_drops_explicit_constraints(
    output,
):
    client = ExtractionClient(output)
    planner = SemanticQueryPlanner(
        client, ["Virat Kohli"], available_teams=["Australia"], allow_dev_fallback=False
    )
    trace = QueryTrace("Kohli runs against Australia in 2019?")
    result = planner.plan(trace.original_user_question, trace)
    assert result.validation.valid
    assert result.plan.filters == {
        "batter": "Virat Kohli",
        "opposition": "Australia",
        "years": [2019],
    }
    assert len(client.calls) == 1
    assert trace.planner_outcome["repair_outcome"] == "not_needed"


def test_flash_cannot_override_explicit_player_metric_or_filters():
    client = ExtractionClient(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "economy",
            "role": "bowler",
        }
    )
    planner = SemanticQueryPlanner(
        client, ["Virat Kohli"], available_teams=["Australia"], allow_dev_fallback=False
    )
    result = planner.plan(
        "Kohli runs against Australia?", QueryTrace("Kohli runs against Australia?")
    )
    assert result.plan.metric == "runs_scored"
    assert result.plan.filters == {"batter": "Virat Kohli", "opposition": "Australia"}


def test_unresolved_valid_meaning_is_the_only_reason_for_pro_fallback():
    client = ExtractionClient(
        {"version": 1, "family": "direct"},
        {"version": 1, "family": "direct", "metric_concept": "batting strike rate"},
    )
    planner = SemanticQueryPlanner(client, ["Virat Kohli"], allow_dev_fallback=False)
    trace = QueryTrace("Kohli's scoring pace?")
    result = planner.plan(trace.original_user_question, trace)
    assert result.validation.valid
    assert result.plan.metric == "batting_strike_rate"
    assert [call["prefer_complex"] for call in client.calls] == [False, True]
    assert trace.planner_attempts[1]["reason"] == "unresolved_meaning"
    assert trace.as_dict()["planner_outcome"]["model_call_reasons"] == [
        "initial_meaning_extraction",
        "unresolved_meaning",
    ]
    assert all(
        call["response_schema"]["title"] == "LanguageMeaningCandidate"
        for call in client.calls
    )


def test_unresolved_malformed_meaning_never_enters_legacy_planning():
    client = ExtractionClient("bad json")
    planner = SemanticQueryPlanner(client, ["Virat Kohli"], allow_dev_fallback=False)
    trace = QueryTrace("Kohli's scoring pace?")
    result = planner.plan(trace.original_user_question, trace)
    assert result.plan is None
    assert len(client.calls) == 1


def test_extraction_contract_has_no_execution_or_default_responsibilities():
    from backend.app.cricket_analytics.language_meaning import extraction_prompt

    schema = json.dumps(LanguageMeaningCandidate.model_json_schema()).lower()
    prompt = extraction_prompt(
        "Top batters?", {"operation": "aggregate", "players": ["Kohli"]}
    ).lower()
    for forbidden in [
        "sql",
        "executor",
        "join",
        "presentation",
        "cricketqueryplan",
        "statistical",
        "operation",
    ]:
        assert forbidden not in schema
        assert forbidden not in prompt
    assert "minimumsample" not in schema
    assert "sortspec" not in schema


def test_material_metric_alternatives_remain_clarification_even_if_pro_guesses():
    client = ExtractionClient(
        {
            "version": 1,
            "family": "ranking",
            "ambiguity_candidates": ["batting strike rate", "bowling strike rate"],
        },
        {"version": 1, "family": "ranking", "metric_concept": "batting strike rate"},
    )
    planner = SemanticQueryPlanner(client, [], allow_dev_fallback=False)
    trace = QueryTrace("Rank players")
    result = planner.plan(trace.original_user_question, trace)
    assert result.plan is None
    assert trace.meaning_resolution["status"] == "clarification"
    assert trace.meaning_resolution["clarification_options"] == [
        "batting strike rate",
        "bowling strike rate",
    ]
    assert trace.planner_attempts[1]["reason"] == "ambiguous_meaning"


def test_pro_cannot_drop_a_flash_filter_it_does_not_understand():
    client = ExtractionClient(
        {
            "version": 1,
            "family": "direct",
            "filters": [
                {
                    "concept": "delivery exclusion",
                    "values": ["no balls"],
                    "evidence": "excluding no balls",
                }
            ],
        },
        {"version": 1, "family": "direct", "metric_concept": "batting strike rate"},
    )
    planner = SemanticQueryPlanner(client, ["Virat Kohli"], allow_dev_fallback=False)
    trace = QueryTrace("Kohli's scoring pace excluding no balls?")
    result = planner.plan(trace.original_user_question, trace)
    assert result.plan is None
    assert "delivery exclusion" in trace.meaning_resolution["clarification"]


def test_unknown_explicit_scope_returns_capability_failure_without_model_repair():
    client = ExtractionClient(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "runs",
            "filters": [
                {"concept": "weather", "values": ["rain"], "evidence": "in rain"}
            ],
        }
    )
    planner = SemanticQueryPlanner(client, ["Virat Kohli"], allow_dev_fallback=False)
    trace = QueryTrace("Kohli's runs in rain?")
    result = planner.plan(trace.original_user_question, trace)
    assert result.plan is None
    assert trace.meaning_resolution["status"] == "unsupported"
    assert trace.meaning_resolution["candidate_sources"] == ["response_policy"]
    assert client.calls == []


def test_generic_role_words_are_not_resolved_as_named_players():
    client = ExtractionClient(
        {
            "version": 1,
            "family": "ranking",
            "metric_concept": "economy",
            "entities": [{"kind": "player", "name": "player", "role": "bowler"}],
        }
    )
    planner = SemanticQueryPlanner(client, [], allow_dev_fallback=False)
    result = planner.plan(
        "Rank bowlers by economy", QueryTrace("Rank bowlers by economy")
    )
    assert result.validation.valid
    assert result.plan.filters == {}


@pytest.mark.parametrize(
    "concept,evidence,values,expected",
    [
        ("phase_of_innings", "powerplay", ["powerplay"], {"phase": "powerplay"}),
        ("innings_overs_range", "first ten overs", ["1-10"], {"phase": "powerplay"}),
        ("bowler_type", "facing spin", ["spin"], {"bowling_style": "spin"}),
        ("phase of play", "death overs", ["death"], {"phase": "death"}),
        ("overs_phase", "middle overs", ["middle"], {"phase": "middle"}),
    ],
)
def test_language_filter_labels_normalize_by_concept_and_evidence(
    concept, evidence, values, expected
):
    resolver = CanonicalMeaningResolver(available_players=["Virat Kohli"])
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "runs",
            "filters": [{"concept": concept, "evidence": evidence, "values": values}],
        }
    )
    result = resolver.resolve_candidate(f"Kohli runs {evidence}?", None, candidate)
    assert result.meaning.filters == {"batter": "Virat Kohli", **expected}


def test_explicit_direct_sample_is_preserved_without_adding_a_default():
    client = ExtractionClient(
        {"version": 1, "family": "direct", "metric_concept": "batting strike rate"}
    )
    planner = SemanticQueryPlanner(client, ["Virat Kohli"], allow_dev_fallback=False)
    result = planner.plan(
        "Kohli batting strike rate, minimum 25 balls?", QueryTrace("sample")
    )
    assert result.validation.valid
    assert result.plan.minimum_sample.balls == 25
    assert result.plan.minimum_sample_explicit


def test_followup_flash_entity_can_come_from_structured_conversation_facts():
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "runs",
            "entities": [{"kind": "player", "name": "Kohli", "role": "batter"}],
        }
    )
    resolver = CanonicalMeaningResolver(available_players=["Virat Kohli"])
    state = {
        "players": ["Virat Kohli"],
        "metric": "runs_scored",
        "filters": {"opposition": "Australia"},
    }
    result = resolver.resolve_candidate("What about 2019?", state, candidate)
    assert result.status == MeaningStatus.resolved
    assert result.meaning.filters == {
        "batter": "Virat Kohli",
        "opposition": "Australia",
        "years": [2019],
    }


def test_compatible_extractor_candidates_keep_additional_expressed_filter():
    candidate = LanguageMeaningCandidate.model_validate(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "runs",
            "filters": [
                {"concept": "innings", "values": [2], "evidence": "during pursuit"}
            ],
        }
    )
    resolver = CanonicalMeaningResolver(
        available_players=["Virat Kohli"],
        candidate_extractors=[("flash", lambda *_: candidate)],
    )
    result = resolver.resolve("Kohli runs during pursuit?", None)
    assert result.meaning.filters == {"batter": "Virat Kohli", "innings": 2}


def test_legality_and_yorker_measurement_do_not_filter_away_rate_denominator():
    candidate = {
        "version": 1,
        "family": "direct",
        "metric_concept": "yorker fraction",
        "filters": [
            {
                "concept": "delivery kind",
                "values": ["legal"],
                "evidence": "legal deliveries",
            },
            {"concept": "delivery type", "values": ["yorker"], "evidence": "yorkers"},
        ],
    }
    client = ExtractionClient(candidate)
    planner = SemanticQueryPlanner(client, ["Lasith Malinga"], allow_dev_fallback=False)
    result = planner.plan(
        "What fraction of Malinga's legal deliveries are yorkers?",
        QueryTrace("yorkers"),
    )
    assert result.validation.valid
    assert result.plan.metric == "yorker_percentage"
    assert result.plan.filters == {"bowler": "Lasith Malinga"}


def test_chat_displays_capability_failure_without_running_database_query():
    from test_gemini_structured_planner import _live_chat

    client = ExtractionClient(
        {
            "version": 1,
            "family": "direct",
            "metric_concept": "runs",
            "filters": [
                {"concept": "weather", "values": ["rain"], "evidence": "in rain"}
            ],
        }
    )
    reply = _live_chat(client).reply("Kohli's runs in rain?", history=[])
    assert reply.mode == "analysis"
    assert "weather" in reply.message.lower()
    assert not reply.query_response.evidence_queries
    assert reply.query_response.failure_state == "unsupported_capability"
    assert client.calls == []


def test_conflicting_candidate_filters_do_not_silently_select_one_value():
    candidate = LanguageMeaningCandidate.model_validate({
        "version": 1, "family": "direct", "metric_concept": "runs",
        "filters": [
            {"concept": "innings", "values": [1], "evidence": "during pursuit"},
            {"concept": "innings", "values": [2], "evidence": "during pursuit"},
        ],
    })
    resolver = CanonicalMeaningResolver(available_players=["Virat Kohli"])
    resolution = resolver.resolve_candidate("Kohli runs during pursuit?", None, candidate)
    assert resolution.status == MeaningStatus.clarification
    assert resolution.meaning is None
