from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def score_review(records: list[dict[str, Any]], review: dict[str, Any]) -> dict[str, Any]:
    if not review.get("reviewed_all_records"):
        raise ValueError("External benchmark cannot be scored until every record has been reviewed.")
    overrides = review.get("overrides") or {}
    defaults = review.get("defaults") or {}
    ids = [str(record["id"]) for record in records]
    unknown = sorted(set(overrides) - set(ids))
    if unknown:
        raise ValueError(f"Review contains unknown record ids: {unknown}")
    if len(ids) != len(set(ids)):
        raise ValueError("External benchmark records must contain unique ids.")

    totals: Counter[str] = Counter()
    correct: dict[str, Counter[str]] = defaultdict(Counter)
    failures: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        case_id = str(record["id"])
        category = str(record.get("category", "uncategorized"))
        totals[category] += 1
        decision = {**defaults, **(overrides.get(case_id) or {})}
        for dimension in ("semantic_capability", "safeguard_aware"):
            status = decision.get(dimension)
            if status not in {"pass", "fail"}:
                raise ValueError(f"{case_id} has invalid {dimension} decision: {status!r}")
            if status == "pass":
                correct[dimension][category] += 1
            else:
                failures[dimension].append(
                    {"id": case_id, "category": category, "reason": str(decision.get("reason", ""))}
                )

    total = len(records)
    return {
        "benchmark": review.get("benchmark"),
        "source": review.get("source"),
        "records": total,
        "semantic_capability": _dimension_report(correct["semantic_capability"], totals, total),
        "safeguard_aware": _dimension_report(correct["safeguard_aware"], totals, total),
        "failures": failures,
        "review_method": "complete human review of stored visible responses; no numeric equality across datasets",
    }


def _dimension_report(correct: Counter[str], totals: Counter[str], total: int) -> dict[str, Any]:
    correct_total = sum(correct.values())
    return {
        "correct": correct_total,
        "total": total,
        "rate": correct_total / total if total else 0.0,
        "by_category": {
            category: {
                "correct": correct[category],
                "total": count,
                "rate": correct[category] / count,
            }
            for category, count in sorted(totals.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a stored external benchmark review.")
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = load_jsonl(args.responses)
    review = yaml.safe_load(args.review.read_text(encoding="utf-8"))
    report = score_review(records, review)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "failures"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
