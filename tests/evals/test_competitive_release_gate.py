from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.competitive_release_gate import (
    REQUIRED_METAMORPHIC_TRANSFORMATIONS,
    evaluate_release,
    load_release_evidence,
)


ROOT = Path(__file__).resolve().parents[2]


def _passing_evidence() -> dict[str, object]:
    return {
        "original": {
            "semantic_capability": {"correct": 98, "total": 100},
            "safeguard_aware": {"correct": 97, "total": 100},
            "critical_errors": [],
        },
        "unseen": {
            "strict_accuracy": {"passed": 140, "total": 150},
            "families": {
                "direct": {"passed": 18, "total": 20},
                "ranking": {"passed": 22, "total": 24},
                "breakdown": {"passed": 18, "total": 20},
                "matchup": {"passed": 15, "total": 16},
                "comparison": {"passed": 15, "total": 16},
                "split": {"passed": 13, "total": 14},
                "trend": {"passed": 10, "total": 10},
                "context": {"passed": 10, "total": 10},
                "behavior": {"passed": 19, "total": 20},
            },
            "paraphrase_pair_consistency": {"both_pass": 68, "total_pairs": 75},
        },
        "holdout": {"strict_accuracy": {"passed": 18, "total": 20}},
        "metamorphic": {
            "covered_transformations": sorted(REQUIRED_METAMORPHIC_TRANSFORMATIONS),
            "equivalent": {"passed": 20, "total": 20},
            "distinct": {"passed": 4, "total": 4},
            "lost_constraints": [],
            "critical_errors": [],
        },
        "stability": {
            "minimum_repetitions": 3,
            "cases": 9,
            "captured_outputs": 27,
            "replayable_offline": True,
        },
        "stats_desk": {"semantic_score": 96, "queried_again": False},
        "full_suite": {"passed": True},
        "approved_ui": {"unchanged": True},
    }


def test_competitive_release_passes_only_when_every_issue_34_gate_passes() -> None:
    report = evaluate_release(_passing_evidence())

    assert report["passed"] is True
    assert all(check["passed"] for check in report["checks"])


@pytest.mark.parametrize(
    ("mutation", "failed_gate"),
    [
        (lambda evidence: evidence["original"]["semantic_capability"].update(correct=96), "original_semantic"),
        (lambda evidence: evidence["unseen"]["families"]["ranking"].update(passed=21), "unseen_family_ranking"),
        (lambda evidence: evidence["holdout"]["strict_accuracy"].update(passed=17), "untouched_holdout"),
        (lambda evidence: evidence["metamorphic"].update(lost_constraints=["phase"]), "metamorphic_constraints"),
        (lambda evidence: evidence["original"].update(critical_errors=["legal-ball denominator"]), "critical_errors"),
        (lambda evidence: evidence["stability"].update(minimum_repetitions=2), "production_stability"),
    ],
)
def test_competitive_release_fails_closed(mutation, failed_gate: str) -> None:
    evidence = _passing_evidence()
    mutation(evidence)

    report = evaluate_release(evidence)

    assert report["passed"] is False
    assert failed_gate in {check["id"] for check in report["checks"] if not check["passed"]}


def test_committed_issue_34_evidence_passes_the_aggregate_gate() -> None:
    evidence_path = ROOT / "tests/evals/results/releases/issue-34/release-evidence.json"
    evidence = load_release_evidence(evidence_path)

    report = evaluate_release(evidence)

    assert report["passed"] is True, report
    assert evidence["stats_desk"]["queried_again"] is False
    assert evidence["full_suite"]["passed"] is True


def test_issue_34_evidence_paths_exist_and_json_summaries_are_replayable() -> None:
    evidence = load_release_evidence(
        ROOT / "tests/evals/results/releases/issue-34/release-evidence.json"
    )

    for relative_path in evidence["artifact_paths"]:
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
