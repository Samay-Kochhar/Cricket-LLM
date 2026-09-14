from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "tests/evals/results/releases/issue-34/release-evidence.json"
DEFAULT_REPORT = ROOT / "tests/evals/results/releases/issue-34/release-gate.summary.json"

REQUIRED_METAMORPHIC_TRANSFORMATIONS = frozenset(
    {
        "aliases",
        "synonyms",
        "abbreviations",
        "punctuation",
        "word_order",
        "active_passive_voice",
        "explicit_over_ranges",
        "participant_order",
        "filter_placement",
        "equivalent_temporal_language",
    }
)

FAMILY_THRESHOLDS = {
    "direct": (18, 20),
    "ranking": (22, 24),
    "breakdown": (18, 20),
    "matchup": (15, 16),
    "comparison": (15, 16),
    "split": (13, 14),
    "trend": (9, 10),
    "context": (9, 10),
    "behavior": (18, 20),
}


def load_release_evidence(path: Path = DEFAULT_EVIDENCE) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Release evidence must be a JSON object")
    return value


def _count(section: dict[str, Any], key: str = "passed") -> tuple[int, int]:
    return int(section.get(key, 0)), int(section.get("total", 0))


def _rate(section: dict[str, Any], key: str = "passed") -> float:
    passed, total = _count(section, key)
    return passed / total if total else 0.0


def evaluate_release(evidence: dict[str, Any]) -> dict[str, Any]:
    """Evaluate every aggregate issue 34 gate from durable evidence.

    The evaluator fails closed: absent sections, totals, coverage tags, replay
    metadata, or explicit safety attestations count as failed gates.
    """

    original = evidence.get("original") or {}
    unseen = evidence.get("unseen") or {}
    holdout = evidence.get("holdout") or {}
    metamorphic = evidence.get("metamorphic") or {}
    stability = evidence.get("stability") or {}
    stats_desk = evidence.get("stats_desk") or {}
    full_suite = evidence.get("full_suite") or {}
    approved_ui = evidence.get("approved_ui") or {}
    checks: list[dict[str, Any]] = []

    def add(check_id: str, passed: bool, actual: Any, required: Any) -> None:
        checks.append(
            {"id": check_id, "passed": bool(passed), "actual": actual, "required": required}
        )

    semantic = original.get("semantic_capability") or {}
    semantic_correct, semantic_total = _count(semantic, "correct")
    stats_desk_score = int(stats_desk.get("semantic_score", 96))
    add(
        "original_semantic",
        semantic_total == 100 and semantic_correct >= 97 and semantic_correct > stats_desk_score,
        f"{semantic_correct}/{semantic_total}",
        f"> {stats_desk_score}/100 and >= 97/100",
    )

    safeguard = original.get("safeguard_aware") or {}
    safeguard_correct, safeguard_total = _count(safeguard, "correct")
    add(
        "original_safeguards",
        safeguard_total == 100 and safeguard_correct >= 95,
        f"{safeguard_correct}/{safeguard_total}",
        ">= 95/100",
    )

    unseen_strict = unseen.get("strict_accuracy") or {}
    unseen_passed, unseen_total = _count(unseen_strict)
    add(
        "unseen_strict",
        unseen_total == 150 and unseen_passed >= 135,
        f"{unseen_passed}/{unseen_total}",
        ">= 135/150",
    )

    families = unseen.get("families") or {}
    for family, (minimum, total) in FAMILY_THRESHOLDS.items():
        actual_passed, actual_total = _count(families.get(family) or {})
        add(
            f"unseen_family_{family}",
            actual_total == total and actual_passed >= minimum,
            f"{actual_passed}/{actual_total}",
            f">= {minimum}/{total}",
        )

    pairs = unseen.get("paraphrase_pair_consistency") or {}
    both_pass = int(pairs.get("both_pass", 0))
    total_pairs = int(pairs.get("total_pairs", 0))
    add(
        "unseen_paraphrase_pairs",
        total_pairs == 75 and both_pass >= 68,
        f"{both_pass}/{total_pairs}",
        ">= 68/75",
    )

    holdout_score = holdout.get("semantic_capability") or holdout.get("strict_accuracy") or {}
    holdout_key = "correct" if "correct" in holdout_score else "passed"
    holdout_passed, holdout_total = _count(holdout_score, holdout_key)
    add(
        "untouched_holdout",
        holdout_total > 0 and _rate(holdout_score, holdout_key) >= 0.90,
        f"{holdout_passed}/{holdout_total}",
        ">= 90%",
    )

    covered = set(metamorphic.get("covered_transformations") or [])
    missing_coverage = sorted(REQUIRED_METAMORPHIC_TRANSFORMATIONS - covered)
    add(
        "metamorphic_coverage",
        not missing_coverage,
        {"covered": sorted(covered), "missing": missing_coverage},
        sorted(REQUIRED_METAMORPHIC_TRANSFORMATIONS),
    )
    equivalent = metamorphic.get("equivalent") or {}
    equivalent_passed, equivalent_total = _count(equivalent)
    distinct = metamorphic.get("distinct") or {}
    distinct_passed, distinct_total = _count(distinct)
    add(
        "metamorphic_equivalence",
        equivalent_total > 0 and equivalent_passed == equivalent_total,
        f"{equivalent_passed}/{equivalent_total}",
        "all equivalent meanings pass",
    )
    add(
        "metamorphic_distinctions",
        distinct_total > 0 and distinct_passed == distinct_total,
        f"{distinct_passed}/{distinct_total}",
        "all materially different meanings remain distinct",
    )
    lost_constraints = list(metamorphic.get("lost_constraints") or [])
    add("metamorphic_constraints", not lost_constraints, lost_constraints, "no lost metrics or filters")

    critical_errors = [
        *list(original.get("critical_errors") or []),
        *list(unseen.get("critical_errors") or []),
        *list(holdout.get("critical_errors") or []),
        *list(metamorphic.get("critical_errors") or []),
    ]
    add("critical_errors", not critical_errors, critical_errors, "zero")

    repetitions = int(stability.get("minimum_repetitions", 0))
    stability_cases = int(stability.get("cases", 0))
    captured_outputs = int(stability.get("captured_outputs", 0))
    replayable = stability.get("replayable_offline") is True
    add(
        "production_stability",
        repetitions >= 3
        and stability_cases > 0
        and captured_outputs >= repetitions * stability_cases
        and replayable,
        {
            "minimum_repetitions": repetitions,
            "cases": stability_cases,
            "captured_outputs": captured_outputs,
            "replayable_offline": replayable,
        },
        "at least 3 runs per case with replayable captures",
    )
    add(
        "saved_stats_desk_only",
        stats_desk.get("queried_again") is False,
        stats_desk.get("queried_again"),
        False,
    )
    add("complete_test_suite", full_suite.get("passed") is True, full_suite, {"passed": True})
    add("approved_ui_unchanged", approved_ui.get("unchanged") is True, approved_ui, {"unchanged": True})

    return {
        "gate": "issue-34-competitive-odi-release",
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "failed_checks": [check["id"] for check in checks if not check["passed"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the issue 34 competitive ODI release gate.")
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = evaluate_release(load_release_evidence(args.evidence))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
