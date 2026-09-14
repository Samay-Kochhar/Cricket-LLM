from __future__ import annotations

from collections import Counter

from scripts.build_odi_stability_pack import FAMILIES, REPETITIONS, build_stability_pack


def test_stability_pack_repeats_every_release_family_three_times() -> None:
    pack = build_stability_pack()
    cases = pack["cases"]

    assert REPETITIONS == 3
    assert len(cases) == len(FAMILIES) * REPETITIONS
    assert len({case["id"] for case in cases}) == len(cases)
    assert Counter(case["family"] for case in cases) == {
        family: REPETITIONS for family in FAMILIES
    }
    assert all(case["planner_mode"] == "production_live" for case in cases)
