from __future__ import annotations

import copy
import json

from backend.app.services.gemini_client import GeminiStructuredResult
from scripts.release_regression import (
    case_outcome,
    classify,
    evaluate,
    fingerprint,
    generic_dimension_label,
    mutate_responses,
    restated_subject,
    role_moved,
    typed_operators,
)

CANDIDATE = {
    "version": 1,
    "family": "direct",
    "entities": [{"kind": "player", "name": "Starc", "relationship": "subject", "role": None}],
    "metric_concept": "wickets",
    "role": "bowler",
    "breakdown_dimensions": [],
    "split_dimensions": [],
    "filters": [
        {"concept": "overs", "evidence": "overs 1 to 10", "values": [1, 10]},
        {"concept": "opponent", "evidence": "against India", "values": ["India"]},
        {"concept": "year", "evidence": "since 2018", "values": [2018]},
    ],
    "intent": "value",
    "ordering": None,
    "limit": None,
    "sample_threshold": None,
    "ambiguity_candidates": [],
}


def _turn(status: str = "supported", mode: str = "analysis", rows=None, body: str = "Starc took 86 wickets.") -> dict:
    return {
        "response": {"mode": mode, "status": status, "failure_state": None},
        "displayed_answer_evidence": {
            "clarification_options": [],
            "summaries": [{"body": body}],
            "tables": [{"title": "Result", "columns": ["Bowler", "Wickets"], "rows": rows or [["Mitchell Starc", 86]]}],
        },
    }


def test_fingerprint_keeps_numbers_tables_and_status() -> None:
    print_ = fingerprint(_turn())

    assert print_["status"] == "supported"
    assert print_["answer_numbers"] == ["86"]
    assert print_["tables"][0]["rows"] == [["Mitchell Starc", 86]]


def test_classify_separates_match_safe_refusal_and_wrong() -> None:
    golden = fingerprint(_turn())

    assert classify(fingerprint(_turn()), golden) == "match"
    assert classify(fingerprint(_turn(status="unsupported", mode="analysis", rows=[])), golden) == "safe_refusal"
    assert classify(fingerprint(_turn(status="supported", mode="clarification", rows=[])), golden) == "safe_refusal"
    assert classify(fingerprint(_turn(rows=[["Mitchell Starc", 85]], body="Starc took 85 wickets.")), golden) == "wrong"


def test_an_answer_where_the_stable_version_refused_is_wrong() -> None:
    refusal = fingerprint(_turn(status="unsupported", rows=[]))

    assert classify(fingerprint(_turn()), refusal) == "wrong"


def test_case_outcome_reports_the_worst_turn() -> None:
    assert case_outcome(["match", "safe_refusal"]) == "safe_refusal"
    assert case_outcome(["safe_refusal", "wrong"]) == "wrong"
    assert case_outcome(["match"]) == "match"


def test_evaluate_marks_cases_without_golden_answers() -> None:
    result = {"fingerprints": [fingerprint(_turn())], "benchmark_errors": []}

    assert evaluate({"a": result, "b": result}, {"a": [fingerprint(_turn())]}) == {
        "a": "match",
        "b": "no_golden",
    }


def test_typed_operators_follow_the_filter_values() -> None:
    candidate = copy.deepcopy(CANDIDATE)

    assert typed_operators(candidate) is True
    operators = [fact.get("operator") for fact in candidate["filters"]]
    # A single number is ambiguous (eq/gte), so it is left untouched.
    assert operators == ["between", "eq", None]


def test_restated_subject_repeats_the_subject_as_a_player_filter() -> None:
    candidate = copy.deepcopy(CANDIDATE)

    assert restated_subject(candidate) is True
    assert candidate["filters"][-1] == {"concept": "player", "evidence": "Starc", "operator": "eq", "values": ["Starc"]}


def test_role_moved_swaps_between_candidate_and_subject() -> None:
    candidate = copy.deepcopy(CANDIDATE)

    assert role_moved(candidate) is True
    assert (candidate["role"], candidate["entities"][0]["role"]) == (None, "bowler")


def test_generic_dimension_label_needs_exactly_one_axis() -> None:
    single = {**copy.deepcopy(CANDIDATE), "split_dimensions": ["day_night_condition"]}
    double = {**copy.deepcopy(CANDIDATE), "split_dimensions": ["phase", "year"]}

    assert generic_dimension_label(single) is True
    assert single["split_dimensions"] == ["category"]
    assert generic_dimension_label(double) is False
    assert generic_dimension_label(copy.deepcopy(CANDIDATE)) is False


def test_mutate_responses_only_rewrites_language_meaning_extractions() -> None:
    other = GeminiStructuredResult(text='{"plan": 1}', selected_model="m", model_version="m", finish_reason="STOP", latency_ms=0)
    meaning = GeminiStructuredResult(text=json.dumps(CANDIDATE), selected_model="m", model_version="m", finish_reason="STOP", latency_ms=0)

    mutated = mutate_responses([other, meaning], restated_subject)

    assert mutated is not None
    assert mutated[0] is other
    assert json.loads(mutated[1].text)["filters"][-1]["concept"] == "player"
    assert json.loads(meaning.text) == CANDIDATE
    assert mutate_responses([other], restated_subject) is None


def test_evaluate_keeps_replay_outcomes_such_as_a_needed_model_call() -> None:
    outcomes = evaluate(
        {"a": {"outcome": "needs_model_call", "error": "uncaptured model call"}},
        {"a": [fingerprint(_turn())]},
    )

    assert outcomes == {"a": "needs_model_call"}
