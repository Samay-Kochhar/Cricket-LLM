from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
FROZEN_SHA256 = "d783a9e0f323345b76ad560a5857a9f4eadb2fb0688be6aa78baa03ef0b32b38"


def test_issue34_holdout_is_separate_frozen_and_balanced() -> None:
    path = ROOT / "tests/benchmarks/odi_issue34_holdout_v1.yaml"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FROZEN_SHA256
    benchmark = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = benchmark["cases"]

    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    assert all(case["planner_mode"] == "production_live" for case in cases)
    assert Counter(case["family"] for case in cases) == {
        "direct": 3,
        "ranking": 3,
        "breakdown": 2,
        "matchup": 2,
        "comparison": 2,
        "split": 2,
        "trend": 2,
        "context": 2,
        "behavior": 2,
    }
