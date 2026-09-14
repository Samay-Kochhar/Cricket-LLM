from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.bootstrap import get_services
from backend.app.cricket_analytics.canonical_meaning import CanonicalMeaningResolver


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests/evals/results/releases/issue-34/metamorphic.summary.json"


def metamorphic_cases() -> list[dict[str, str]]:
    """Independent language transformations applied to canonical ODI meanings."""
    return [
        {"id": "alias", "transformation": "aliases", "base": "Virat Kohli ODI runs?", "variant": "Kohli ODI runs?"},
        {"id": "synonym", "transformation": "synonyms", "base": "Virat Kohli runs?", "variant": "Virat Kohli run tally?"},
        {"id": "abbreviation", "transformation": "abbreviations", "base": "Jasprit Bumrah bowling strike rate?", "variant": "Bumrah bowling SR?"},
        {"id": "punctuation", "transformation": "punctuation", "base": "Virat Kohli runs at Lord's?", "variant": "Virat Kohli runs — at Lord’s?"},
        {"id": "word-order", "transformation": "word_order", "base": "Virat Kohli runs against Australia?", "variant": "Against Australia, how many runs has Virat Kohli scored?"},
        {"id": "voice", "transformation": "active_passive_voice", "base": "How many wickets has Jasprit Bumrah taken?", "variant": "Wickets taken by Jasprit Bumrah?"},
        {"id": "over-range", "transformation": "explicit_over_ranges", "base": "Rohit Sharma batting strike rate in the powerplay?", "variant": "Rohit Sharma batting strike rate in overs 1-10?"},
        {"id": "participant-order", "transformation": "participant_order", "base": "Compare Virat Kohli and Rohit Sharma as batters.", "variant": "Compare Rohit Sharma and Virat Kohli as batters."},
        {"id": "filter-placement", "transformation": "filter_placement", "base": "Virat Kohli runs in the powerplay versus Australia?", "variant": "Against Australia in overs 1-10, Virat Kohli run tally?"},
        {"id": "temporal", "transformation": "equivalent_temporal_language", "base": "Mitchell Starc annual economy at the death since 2018?", "variant": "From 2018 onward, Mitchell Starc death-over economy year by year?"},
    ]


def distinction_cases() -> list[dict[str, str]]:
    return [
        {"id": "metric", "left": "Virat Kohli runs?", "right": "Virat Kohli batting strike rate?"},
        {"id": "count-rate", "left": "Virat Kohli dot-ball count?", "right": "Virat Kohli dot-ball percentage?"},
        {"id": "ownership", "left": "Jasprit Bumrah batting strike rate?", "right": "Jasprit Bumrah bowling strike rate?"},
        {"id": "sort-direction", "left": "Highest batting strike rate with at least 60 balls?", "right": "Lowest batting strike rate with at least 60 balls?"},
    ]


def _resolver() -> CanonicalMeaningResolver:
    planner = get_services()["semantic_service"].planner
    return CanonicalMeaningResolver(
        available_players=planner.available_players,
        available_venues=planner.available_venues,
        available_teams=planner.available_teams,
        player_participation=planner.player_roles.participation,
    )


def _meaning(resolver: CanonicalMeaningResolver, prompt: str) -> dict[str, Any] | None:
    resolution = resolver.resolve(prompt, None)
    return resolution.meaning.model_dump(mode="json", exclude_none=True) if resolution.meaning else None


def evaluate_metamorphic_pack() -> dict[str, Any]:
    resolver = _resolver()
    equivalent_results = []
    lost_constraints: list[str] = []
    for case in metamorphic_cases():
        base = _meaning(resolver, case["base"])
        variant = _meaning(resolver, case["variant"])
        passed = base is not None and base == variant
        if base and variant:
            for field in ("metric", "filters", "participants", "minimum_sample"):
                if base.get(field) != variant.get(field):
                    lost_constraints.append(f"{case['id']}:{field}")
        equivalent_results.append({**case, "passed": passed})

    distinct_results = []
    for case in distinction_cases():
        left = _meaning(resolver, case["left"])
        right = _meaning(resolver, case["right"])
        distinct_results.append({**case, "passed": left is not None and right is not None and left != right})

    return {
        "covered_transformations": sorted({case["transformation"] for case in metamorphic_cases()}),
        "equivalent": {
            "passed": sum(result["passed"] for result in equivalent_results),
            "total": len(equivalent_results),
            "results": equivalent_results,
        },
        "distinct": {
            "passed": sum(result["passed"] for result in distinct_results),
            "total": len(distinct_results),
            "results": distinct_results,
        },
        "lost_constraints": sorted(set(lost_constraints)),
        "critical_errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the issue 34 ODI metamorphic meaning pack.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate_metamorphic_pack()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["equivalent"]["passed"] == report["equivalent"]["total"] and report["distinct"]["passed"] == report["distinct"]["total"] and not report["lost_constraints"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
