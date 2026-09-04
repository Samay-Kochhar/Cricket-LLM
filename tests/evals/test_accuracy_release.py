from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from scripts import odi_correctness_gate
from scripts.accuracy_release import (
    AccuracyArtifactStore,
    classify_first_failing_stage,
    reconcile_summary,
    score_release,
    validate_unique_case_ids,
)


ROOT = Path(__file__).resolve().parents[2]
FROZEN_INPUT_SHA256 = {
    "tests/evals/dl4nlp_cricket_analyst_supported_100.yaml": (
        "c1d55391a1f9e7ebf14b86f148e654004f7d62116c3d479467ef4c7e01a15cf9"
    ),
    "tests/benchmarks/odi_unseen_paraphrases_v1.yaml": (
        "c9c1d3b8cf7f3d5199dce5a67e3fdfac9681a055e0c15044e777ef1c909569f0"
    ),
    "tests/evals/results/aryaman_stats_desk_presentation_100.jsonl": (
        "287e845ecd1f8876c725a835338d78dda662052c95fd5b6c5d43a22cc5034a29"
    ),
}


def test_accuracy_release_inputs_and_saved_external_responses_are_immutable() -> None:
    actual = {
        relative_path: hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        for relative_path in FROZEN_INPUT_SHA256
    }

    assert actual == FROZEN_INPUT_SHA256


def test_artifact_store_resumes_completed_cases_without_repeating_calls(tmp_path) -> None:
    path = tmp_path / "run.jsonl"
    calls: list[str] = []

    first = AccuracyArtifactStore(path)
    for case_id in ("one", "two"):
        if case_id not in first.completed_ids:
            calls.append(case_id)
            first.append({"case_id": case_id, "turns": []})

    resumed = AccuracyArtifactStore(path)
    for case_id in ("one", "two"):
        if case_id not in resumed.completed_ids:
            calls.append(case_id)

    assert calls == ["one", "two"]
    assert resumed.completed_ids == {"one", "two"}
    assert [record["case_id"] for record in resumed.records] == ["one", "two"]


def test_duplicate_ids_are_rejected_in_inputs_and_saved_artifacts(tmp_path) -> None:
    with pytest.raises(ValueError, match="Duplicate benchmark case id"):
        validate_unique_case_ids([{"id": "same"}, {"id": "same"}])

    path = tmp_path / "run.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"case_id": "same"}),
                json.dumps({"case_id": "same"}),
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate case id"):
        AccuracyArtifactStore(path)


def test_artifact_recursively_excludes_credentials_and_headers(tmp_path) -> None:
    path = tmp_path / "run.jsonl"
    store = AccuracyArtifactStore(path)
    store.append(
        {
            "case_id": "safe",
            "model": {
                "name": "gemini-test",
                "api_key": "super-secret",
                "headers": {"Authorization": "Bearer secret", "X-Trace": "okay"},
            },
            "error": "upstream failed with Bearer leaked-token",
            "turns": [{"candidate": {"access_token": "hidden", "metric": "runs_scored"}}],
        }
    )

    saved = path.read_text(encoding="utf-8")
    assert "super-secret" not in saved
    assert "Bearer secret" not in saved
    assert "hidden" not in saved
    assert "leaked-token" not in saved
    record = store.records[0]
    assert record["model"]["api_key"] == "[REDACTED]"
    assert record["model"]["headers"]["Authorization"] == "[REDACTED]"
    assert record["model"]["headers"]["X-Trace"] == "okay"


def test_saved_run_replays_deterministically_and_reports_release_views(tmp_path) -> None:
    benchmark = {
        "version": 1,
        "name": "Frozen pair gate",
        "cases": [
            {"id": "meaning-one-a", "family": "direct"},
            {"id": "meaning-one-b", "family": "direct"},
            {"id": "meaning-two-a", "family": "behavior"},
            {"id": "meaning-two-b", "family": "behavior"},
        ],
    }
    records = [
        {"case_id": "meaning-one-a", "turns": [{"errors": [], "deterministic_errors": []}]},
        {"case_id": "meaning-one-b", "turns": [{"errors": [], "deterministic_errors": ["plan.metric"]}]},
        {
            "case_id": "meaning-two-a",
            "turns": [{"errors": ["wrong status"], "deterministic_errors": []}],
            "first_failing_stage": "response policy",
        },
        {
            "case_id": "meaning-two-b",
            "turns": [{"errors": ["wrong status"], "deterministic_errors": ["wrong plan"]}],
            "first_failing_stage": "response policy",
        },
    ]
    previous = [
        {"case_id": "meaning-one-a", "turns": [{"errors": ["old failure"]}]},
        {"case_id": "meaning-one-b", "turns": [{"errors": []}]},
        {"case_id": "meaning-two-a", "turns": [{"errors": []}]},
        {"case_id": "meaning-two-b", "turns": [{"errors": ["wrong status"]}]},
    ]

    first = score_release(benchmark, records, previous_records=previous)
    artifact_path = tmp_path / "run.jsonl"
    artifact_path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    replayed = score_release(benchmark, AccuracyArtifactStore(artifact_path).records, previous_records=previous)

    assert replayed == first
    assert first["strict_accuracy"] == {"passed": 2, "total": 4, "rate": 0.5}
    assert first["families"]["direct"]["passed"] == 2
    assert first["paraphrase_pair_consistency"]["consistent_pairs"] == 2
    assert first["planner_overlap"] == {
        "both_pass": 1,
        "production_only": 1,
        "deterministic_only": 1,
        "both_fail": 1,
        "total": 4,
    }
    assert first["improvements"] == ["meaning-one-a"]
    assert first["regressions"] == ["meaning-two-a"]


def test_release_comparison_accepts_the_saved_compact_baseline_format() -> None:
    benchmark = {
        "version": 1,
        "cases": [
            {"id": "still-passes", "family": "direct"},
            {"id": "now-regresses", "family": "ranking"},
        ],
    }
    current = [
        {"case_id": "still-passes", "turns": [{"errors": []}]},
        {"case_id": "now-regresses", "turns": [{"errors": ["new failure"]}]},
    ]
    compact_previous = [
        {"case_id": "still-passes", "passed": True, "errors": []},
        {"case_id": "now-regresses", "passed": True, "errors": []},
    ]

    report = score_release(benchmark, current, previous_records=compact_previous)

    assert report["regressions"] == ["now-regresses"]



def test_summary_reconciliation_rejects_inconsistent_totals() -> None:
    summary = {
        "strict_accuracy": {"passed": 1, "total": 2, "rate": 0.5},
        "families": {"direct": {"passed": 1, "total": 1, "rate": 1.0}},
        "failures": [{"case_id": "two"}],
        "planner_overlap": {"both_pass": 0, "production_only": 0, "deterministic_only": 0, "both_fail": 0, "total": 0},
    }

    with pytest.raises(ValueError, match="Family totals"):
        reconcile_summary(summary)


def test_failure_stage_reports_compilation_when_canonical_candidate_cannot_compile() -> None:
    expected_plan = {
        "query_type": "aggregate",
        "metric": "runs_scored",
        "players": ["Virat Kohli"],
    }
    record = {
        "case_id": "compile-failure",
        "turns": [
            {
                "errors": ["compiled plan is missing"],
                "canonical_meaning": {"plan": expected_plan},
                "raw_structured_candidate": expected_plan,
                "compiled_plan": None,
                "trace": {"validation_result": {"valid": True}},
                "response": {"status": "unsupported"},
            }
        ],
    }

    assert classify_first_failing_stage(record) == "compilation"


def test_release_runner_resumes_without_repeating_completed_case_calls(tmp_path, monkeypatch) -> None:
    benchmark_path = tmp_path / "benchmark.yaml"
    artifact_path = tmp_path / "release.jsonl"
    benchmark_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "name": "Release",
                "cases": [
                    {"id": "one", "family": "direct", "turns": []},
                    {"id": "two", "family": "direct", "turns": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_run(case):
        calls.append(case["id"])
        return {
            "case_id": case["id"],
            "family": case["family"],
            "turns": [{"errors": [], "deterministic_errors": []}],
        }

    monkeypatch.setattr(odi_correctness_gate, "_run_case_evidence", fake_run)

    odi_correctness_gate.run_accuracy_release(benchmark_path, output_path=artifact_path)
    odi_correctness_gate.run_accuracy_release(benchmark_path, output_path=artifact_path)

    assert calls == ["one", "two"]


def test_release_runner_rejects_systemic_production_model_failure(tmp_path, monkeypatch) -> None:
    benchmark_path = tmp_path / "benchmark.yaml"
    artifact_path = tmp_path / "release.jsonl"
    benchmark_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "name": "Production release",
                "cases": [
                    {
                        "id": "one",
                        "family": "direct",
                        "planner_mode": "production_live",
                        "turns": [{"prompt": "Question", "expected": {}}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def failed_model_call(case):
        return {
            "case_id": case["id"],
            "family": case["family"],
            "planner_mode": case["planner_mode"],
            "turns": [
                {
                    "errors": ["status expected supported, got unsupported"],
                    "deterministic_errors": [],
                    "production_planner_errors": ["missing plan"],
                    "trace": {
                        "parsed_json_plan": None,
                        "planner_attempts": [
                            {"attempt": "initial", "error_kind": "request_failed"},
                            {"attempt": "repair", "error_kind": "request_failed"},
                        ],
                    },
                }
            ],
        }

    monkeypatch.setattr(odi_correctness_gate, "_run_case_evidence", failed_model_call)

    with pytest.raises(RuntimeError, match="production planner unavailable"):
        odi_correctness_gate.run_accuracy_release(benchmark_path, output_path=artifact_path)

    assert AccuracyArtifactStore(artifact_path).records == []
