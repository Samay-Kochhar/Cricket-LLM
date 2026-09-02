from __future__ import annotations

import json

import pytest
import yaml

from scripts import odi_correctness_gate
from scripts.accuracy_release import (
    AccuracyArtifactStore,
    reconcile_summary,
    score_release,
    validate_unique_case_ids,
)


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


def test_summary_reconciliation_rejects_inconsistent_totals() -> None:
    summary = {
        "strict_accuracy": {"passed": 1, "total": 2, "rate": 0.5},
        "families": {"direct": {"passed": 1, "total": 1, "rate": 1.0}},
        "failures": [{"case_id": "two"}],
        "planner_overlap": {"both_pass": 0, "production_only": 0, "deterministic_only": 0, "both_fail": 0, "total": 0},
    }

    with pytest.raises(ValueError, match="Family totals"):
        reconcile_summary(summary)


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
