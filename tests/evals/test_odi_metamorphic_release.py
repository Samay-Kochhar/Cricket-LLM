from __future__ import annotations

from scripts.competitive_release_gate import REQUIRED_METAMORPHIC_TRANSFORMATIONS
from scripts.odi_metamorphic_release import evaluate_metamorphic_pack


def test_metamorphic_pack_preserves_equivalent_meanings_and_separates_distinct_ones() -> None:
    report = evaluate_metamorphic_pack()

    assert set(report["covered_transformations"]) == REQUIRED_METAMORPHIC_TRANSFORMATIONS
    assert report["equivalent"]["passed"] == report["equivalent"]["total"]
    assert report["distinct"]["passed"] == report["distinct"]["total"]
    assert report["lost_constraints"] == []
