from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/benchmarks/odi_unseen_paraphrases_v1.yaml"
DEFAULT_OUTPUT = ROOT / "tests/benchmarks/odi_issue34_stability_v1.yaml"
FAMILIES = ("direct", "ranking", "breakdown", "matchup", "comparison", "split", "trend", "context", "behavior")
REPETITIONS = 3


def build_stability_pack() -> dict[str, Any]:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    selected: dict[str, dict[str, Any]] = {}
    for case in source["cases"]:
        selected.setdefault(str(case["family"]), case)
    if set(selected) != set(FAMILIES):
        raise ValueError("The frozen unseen benchmark does not contain every release family")

    cases = []
    for repetition in range(1, REPETITIONS + 1):
        for family in FAMILIES:
            case = deepcopy(selected[family])
            case["id"] = f"stability-{family}-run-{repetition}"
            case["stability_source_id"] = selected[family]["id"]
            case["repetition"] = repetition
            cases.append(case)
    return {
        "version": 1,
        "name": "ODI issue 34 production stability pack",
        "design": "One frozen unseen case per family, independently executed three times",
        "repetitions": REPETITIONS,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the issue 34 production stability pack.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    pack = build_stability_pack()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(yaml.safe_dump(pack, sort_keys=False, width=120), encoding="utf-8")
    print(f"Wrote {len(pack['cases'])} stability cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
