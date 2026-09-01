from __future__ import annotations

from collections import Counter

from scripts.build_odi_unseen_benchmark import build_benchmark


def test_unseen_benchmark_is_frozen_balanced_and_unique() -> None:
    benchmark = build_benchmark()
    cases = benchmark["cases"]

    assert len(cases) == 150
    assert len({case["id"] for case in cases}) == 150
    assert all(case["planner_mode"] == "production_live" for case in cases)
    families = Counter(case["family"] for case in cases)
    assert families == {
        "direct": 20,
        "ranking": 24,
        "breakdown": 20,
        "matchup": 16,
        "comparison": 16,
        "split": 14,
        "trend": 10,
        "context": 10,
        "behavior": 20,
    }


def test_unseen_supported_cases_require_database_evidence() -> None:
    for case in build_benchmark()["cases"]:
        for turn in case["turns"]:
            expected = turn["expected"]
            if expected.get("status") == "supported":
                assert expected["evidence"] == "required"
