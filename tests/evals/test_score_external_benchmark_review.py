from __future__ import annotations

import pytest

from scripts.score_external_benchmark_review import score_review


def test_review_scores_defaults_and_overrides_by_category() -> None:
    records = [
        {"id": "a", "category": "direct"},
        {"id": "b", "category": "direct"},
        {"id": "c", "category": "comparison"},
    ]
    review = {
        "reviewed_all_records": True,
        "defaults": {"semantic_capability": "pass", "safeguard_aware": "pass"},
        "overrides": {
            "b": {
                "semantic_capability": "pass",
                "safeguard_aware": "fail",
                "reason": "low sample",
            },
            "c": {
                "semantic_capability": "fail",
                "safeguard_aware": "fail",
                "reason": "wrong metric",
            },
        },
    }

    report = score_review(records, review)

    assert report["semantic_capability"]["correct"] == 2
    assert report["safeguard_aware"]["correct"] == 1
    assert report["semantic_capability"]["by_category"]["direct"]["correct"] == 2


def test_review_rejects_unreviewed_or_unknown_records() -> None:
    with pytest.raises(ValueError, match="every record"):
        score_review([{"id": "a"}], {"reviewed_all_records": False})
    with pytest.raises(ValueError, match="unknown"):
        score_review(
            [{"id": "a"}],
            {
                "reviewed_all_records": True,
                "defaults": {"semantic_capability": "pass", "safeguard_aware": "pass"},
                "overrides": {"missing": {"semantic_capability": "fail", "safeguard_aware": "fail"}},
            },
        )
