from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import pytest
import yaml

from backend.app.cricket_analytics.canonical_meaning import (
    CanonicalMeaningResolver,
    MeaningStatus,
    compile_canonical_meaning,
)
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.services.gemini_client import GeminiStructuredResult


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = yaml.safe_load(
    (ROOT / "tests/benchmarks/odi_unseen_paraphrases_v1.yaml").read_text(encoding="utf-8")
)
FAMILY_CASES = [
    case for case in BENCHMARK["cases"] if case["family"] in {"direct", "ranking"}
]
BREAKDOWN_CASES = [case for case in BENCHMARK["cases"] if case["family"] == "breakdown"]
EXPECTED_PLAYERS = sorted(
    {
        str(value)
        for case in [*FAMILY_CASES, *BREAKDOWN_CASES]
        for value in case["turns"][0]["expected"]["plan"].get("filters", {}).values()
        if isinstance(value, str)
        and value
        in {
            "Virat Kohli",
            "Rohit Sharma",
            "Babar Azam",
            "Heinrich Klaasen",
            "Jos Buttler",
            "Jasprit Bumrah",
            "Mitchell Starc",
            "Rashid Khan",
            "Lasith Malinga",
            "Ravichandran Ashwin",
            "Trent Boult",
            "David Warner",
        }
    }
    | {"David Miller", "Shreyas Iyer"}
)


def _resolver() -> CanonicalMeaningResolver:
    return CanonicalMeaningResolver(
        available_players=EXPECTED_PLAYERS,
        available_venues=["Lord's, London"],
        available_teams=["Australia"],
    )


@pytest.mark.parametrize("case", FAMILY_CASES, ids=lambda case: case["id"])
def test_direct_and_ranking_family_pack_compiles_expected_meaning(case: dict[str, object]) -> None:
    turn = case["turns"][0]
    expected = turn["expected"]["plan"]

    resolution = _resolver().resolve(turn["prompt"], conversation_state=None)

    assert resolution.status == MeaningStatus.resolved
    assert resolution.meaning is not None
    actual = compile_canonical_meaning(resolution.meaning).model_dump(
        mode="json", exclude_none=True
    )
    for key, value in expected.items():
        assert actual[key] == value


def test_equivalent_family_phrasings_have_identical_canonical_meanings() -> None:
    meanings: dict[str, list[dict[str, object]]] = defaultdict(list)
    resolver = _resolver()
    for case in FAMILY_CASES:
        turn = case["turns"][0]
        resolution = resolver.resolve(turn["prompt"], conversation_state=None)
        assert resolution.meaning is not None
        pair_id = str(case["id"]).rsplit("-", 1)[0]
        meanings[pair_id].append(resolution.meaning.model_dump(mode="json"))

    assert len(meanings) >= 20
    assert all(len(pair) == 2 and pair[0] == pair[1] for pair in meanings.values())


@pytest.mark.parametrize("case", BREAKDOWN_CASES, ids=lambda case: case["id"])
def test_breakdown_family_pack_compiles_expected_meaning(case: dict[str, object]) -> None:
    turn = case["turns"][0]
    expected = turn["expected"]["plan"]

    resolution = _resolver().resolve(turn["prompt"], conversation_state=None)

    assert resolution.status == MeaningStatus.resolved
    assert resolution.meaning is not None
    assert resolution.meaning.family == "breakdown"
    actual = compile_canonical_meaning(resolution.meaning).model_dump(
        mode="json", exclude_none=True
    )
    for key, value in expected.items():
        assert actual[key] == value


def test_breakdown_dimension_is_independent_of_metric_role_and_filters() -> None:
    resolver = _resolver()

    percentage = resolver.resolve(
        "Across delivery lengths, what percentage of Rohit's balls are dots against off spin in 2019?",
        None,
    )
    count = resolver.resolve(
        "Grouped by line, how many dot balls did Starc bowl to left-handers in 2019?",
        None,
    )

    assert percentage.meaning is not None
    assert percentage.meaning.model_dump(mode="json", exclude_none=True) == {
        "family": "breakdown",
        "role": "batter",
        "metric": "batter_dot_ball_percentage",
        "filters": {
            "years": [2019],
            "bowling_style": "off_spin",
            "batter": "Rohit Sharma",
        },
        "group_by": ["length"],
        "limit": 10,
        "sort_direction": "asc",
        "minimum_sample": {"balls": 60},
        "minimum_sample_explicit": False,
    }
    assert count.meaning is not None
    assert count.meaning.metric == "bowler_dot_balls"
    assert count.meaning.role == "bowler"
    assert count.meaning.group_by == ["line"]
    assert count.meaning.filters == {
        "years": [2019],
        "batter_hand": "LHB",
        "bowler": "Mitchell Starc",
    }


@pytest.mark.parametrize(
    ("prompt", "metric"),
    [
        (
            "Which line generates the most dot balls against Virat Kohli?",
            "bowler_dot_ball_percentage",
        ),
        (
            "Which length produces the most false shots against Shreyas Iyer?",
            "false_shot_percentage",
        ),
        ("Which length dismisses David Miller most often?", "wickets_taken"),
    ],
)
def test_breakdown_preserves_named_batter_as_the_object_of_bowling_analysis(
    prompt: str,
    metric: str,
) -> None:
    resolution = _resolver().resolve(prompt, None)

    assert resolution.meaning is not None
    assert resolution.meaning.family == "breakdown"
    assert resolution.meaning.role == "bowler"
    assert resolution.meaning.metric == metric
    assert resolution.meaning.filters == {
        "batter": "Virat Kohli"
        if "Kohli" in prompt
        else "Shreyas Iyer"
        if "Iyer" in prompt
        else "David Miller"
    }


def test_breakdown_preserves_the_existing_line_length_matrix() -> None:
    resolution = _resolver().resolve(
        "Show Virat Kohli's batting strike rate by line and length",
        None,
    )

    assert resolution.meaning is not None
    assert resolution.meaning.family == "breakdown"
    assert resolution.meaning.group_by == ["line", "length"]
    assert resolution.meaning.filters == {"batter": "Virat Kohli"}


@pytest.mark.parametrize(
    ("prompts", "dimension"),
    [
        (("Map Kohli's runs across bowling lines", "Which line accounts for Kohli's runs?"), "line"),
        (("Kohli's runs grouped by delivery length", "Where by length does Kohli score?"), "length"),
        (("Kohli's runs for every bowler type", "How do Kohli's runs vary with bowling kind?"), "bowling_style"),
        (("Kohli's runs across stroke selection", "Which shots account for Kohli's runs?"), "shot_type"),
        (("Kohli's runs around the ground", "Which scoring areas account for Kohli's runs?"), "field_zone"),
        (("Kohli's runs across innings stages", "How do Kohli's runs vary from powerplay through death?"), "phase"),
        (("Bumrah wickets by batting handedness", "Does Bumrah take wickets against lefties or righties more?"), "batter_hand"),
        (("Kohli's runs annually", "Chart Kohli's runs season by season"), "year"),
    ],
)
def test_unseen_breakdown_dimension_wording_converges(
    prompts: tuple[str, str], dimension: str
) -> None:
    resolver = _resolver()

    meanings = [resolver.resolve(prompt, None).meaning for prompt in prompts]

    assert all(meaning is not None for meaning in meanings)
    assert [meaning.group_by for meaning in meanings if meaning is not None] == [
        [dimension],
        [dimension],
    ]


def test_production_planner_keeps_valid_canonical_meaning_when_gemini_fails() -> None:
    class UnavailableGemini:
        @staticmethod
        def is_configured() -> bool:
            return True

        @staticmethod
        def generate_structured(*args: object, **kwargs: object) -> GeminiStructuredResult:
            return GeminiStructuredResult(
                text=None,
                selected_model="gemini-test",
                model_version=None,
                finish_reason=None,
                latency_ms=1.0,
                error_kind="request_failed",
            )

    planner = SemanticQueryPlanner(
        UnavailableGemini(),
        available_players=EXPECTED_PLAYERS,
        available_venues=["Lord's, London"],
        available_teams=["Australia"],
        allow_dev_fallback=False,
    )
    trace = QueryTrace(original_user_question="Who owns the five largest run totals in overs 1-10?")

    result = planner.plan(trace.original_user_question, trace)

    assert result.validation.valid
    assert result.plan is not None
    assert result.plan.filters == {"phase": "powerplay"}
    assert result.plan.metric == "runs_scored"
    assert result.plan.limit == 5
    assert trace.canonical_meaning["family"] == "ranking"


def test_canonical_meaning_inherits_structured_conversation_state_without_losing_filters() -> None:
    state = {
        "players": ["Virat Kohli"],
        "operation": "aggregate",
        "metric": "runs_scored",
        "group_by": ["batter"],
        "filters": {"batter": "Virat Kohli", "opposition": "Australia"},
    }

    resolution = _resolver().resolve("What about in 2019?", conversation_state=state)

    assert resolution.status == MeaningStatus.resolved
    assert resolution.meaning is not None
    assert resolution.meaning.metric == "runs_scored"
    assert resolution.meaning.filters == {
        "batter": "Virat Kohli",
        "opposition": "Australia",
        "years": [2019],
    }


def test_valid_language_candidate_survives_a_failed_secondary_extractor() -> None:
    def unavailable(*args: object) -> CricketQueryPlan | None:
        raise RuntimeError("candidate unavailable")

    resolver = CanonicalMeaningResolver(
        available_players=EXPECTED_PLAYERS,
        candidate_extractors=[("unavailable", unavailable)],
    )

    resolution = resolver.resolve("What is Kohli's ODI run tally?", None)

    assert resolution.status == MeaningStatus.resolved
    assert resolution.meaning is not None
    assert resolution.meaning.metric == "runs_scored"


def test_two_valid_ambiguous_candidates_request_targeted_clarification() -> None:
    def plan(role: str, metric: str) -> CricketQueryPlan:
        return CricketQueryPlan(
            operation="aggregate",
            entity=role,
            metric=metric,
            group_by=[role],
            filters={},
            sort=SortSpec(by=metric, direction="asc"),
            limit=10,
        )

    resolver = CanonicalMeaningResolver(
        available_players=EXPECTED_PLAYERS,
        candidate_extractors=[
            ("batting", lambda *_: plan("batter", "batting_strike_rate")),
            ("bowling", lambda *_: plan("bowler", "bowling_strike_rate")),
        ],
    )

    resolution = resolver.resolve("Rank players", None)

    assert resolution.status == MeaningStatus.clarification
    assert resolution.clarification_options == [
        "batter batting_strike_rate",
        "bowler bowling_strike_rate",
    ]


def test_interface_distinguishes_unsupported_and_missing_data_meanings() -> None:
    resolver = _resolver()

    missing = resolver.resolve("Rank players by catches", None)
    unsupported = resolver.resolve("Rank players by salary", None)

    assert missing.status == MeaningStatus.data_limitation
    assert "does not contain" in str(missing.reason)
    assert unsupported.status == MeaningStatus.unsupported
    assert "outside supported" in str(unsupported.reason)


def test_direct_meaning_has_no_ranking_threshold_but_ranking_gets_the_default() -> None:
    resolver = _resolver()

    direct = resolver.resolve("What is Kohli's batting strike rate?", None)
    ranking = resolver.resolve("Rank batters by batting strike rate", None)

    assert direct.meaning is not None and direct.meaning.minimum_sample is None
    assert ranking.meaning is not None and ranking.meaning.minimum_sample is not None
    assert ranking.meaning.minimum_sample.balls == 60
    assert ranking.meaning.minimum_sample_explicit is False


def test_saved_issue_26_production_capture_and_impact_replay_reconcile() -> None:
    release_dir = ROOT / "tests/evals/results/releases/issue-26"
    live = json.loads(
        (release_dir / "cricatlas-issue26-production-release.summary.json").read_text()
    )
    replay = json.loads(
        (release_dir / "cricatlas-issue26-production-replay.summary.json").read_text()
    )
    impact = json.loads(
        (release_dir / "cricatlas-issue26-impact-replay.summary.json").read_text()
    )
    captured_rows = (
        release_dir / "cricatlas-issue26-production-release.jsonl"
    ).read_text().splitlines()

    assert len(captured_rows) == 150
    assert live == replay
    assert live["families"]["direct"]["passed"] == 20
    assert live["families"]["ranking"]["passed"] == 24
    assert impact["families"] == {
        "behavior": {"passed": 2, "rate": 0.1, "total": 20},
        "breakdown": {"passed": 14, "rate": 0.7, "total": 20},
        "comparison": {"passed": 0, "rate": 0.0, "total": 16},
        "context": {"passed": 0, "rate": 0.0, "total": 10},
        "direct": {"passed": 20, "rate": 1.0, "total": 20},
        "matchup": {"passed": 7, "rate": 0.4375, "total": 16},
        "ranking": {"passed": 24, "rate": 1.0, "total": 24},
        "split": {"passed": 0, "rate": 0.0, "total": 14},
        "trend": {"passed": 0, "rate": 0.0, "total": 10},
    }
