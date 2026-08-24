from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


EXECUTABLE_PLAN_KEYS = (
    "operation",
    "entity",
    "metric",
    "group_by",
    "filters",
    "split_by",
    "compare_values",
    "event",
    "window",
    "sort",
    "limit",
    "minimum_sample",
    "minimum_sample_explicit",
)

PLAN_DEFAULTS: dict[str, Any] = {
    "group_by": [],
    "filters": {},
    "split_by": None,
    "compare_values": None,
    "event": None,
    "window": None,
    "sort": None,
    "limit": 10,
    "minimum_sample": {},
    "minimum_sample_explicit": False,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Score DL4NLP cricket query-generation predictions.")
    parser.add_argument("--gold", default="tests/evals/dl4nlp_cricket_analyst_supported_100.yaml", help="Gold YAML file.")
    parser.add_argument("--predictions", required=True, help="Prediction YAML/JSON/JSONL file.")
    args = parser.parse_args()

    gold_cases = load_records(Path(args.gold))
    predictions = {str(item["id"]): item for item in load_records(Path(args.predictions))}

    missing = [case["id"] for case in gold_cases if case["id"] not in predictions]
    supported_total = 0
    plan_correct = 0
    answer_correct = 0
    behavior_correct = 0
    answered = 0
    failures: list[str] = []

    for case in gold_cases:
        prediction = predictions.get(case["id"])
        if prediction is None:
            continue

        expected_status = case.get("expected_status", "supported")
        if expected_status != "supported":
            predicted_status = prediction.get("predicted_status")
            if predicted_status is None and isinstance(prediction.get("answer_key"), dict):
                predicted_status = prediction["answer_key"].get("status")
            if predicted_status == expected_status:
                behavior_correct += 1
            else:
                failures.append(f"{case['id']}: expected {expected_status}, got {predicted_status}")
            continue

        supported_total += 1
        predicted_plan = prediction.get("predicted_plan")
        if isinstance(predicted_plan, dict) and plan_matches(case["expected_plan"], predicted_plan):
            plan_correct += 1
        else:
            failures.append(f"{case['id']}: plan mismatch")

        predicted_top_row = prediction.get("predicted_top_row")
        if predicted_top_row is None and isinstance(prediction.get("answer_key"), dict):
            predicted_top_row = prediction["answer_key"].get("expected_top_row")
        if isinstance(predicted_top_row, dict):
            answered += 1
            if answer_matches(case, predicted_top_row):
                answer_correct += 1
                behavior_correct += 1
            else:
                failures.append(f"{case['id']}: answer mismatch")

    total = len(gold_cases)
    print(f"Gold cases: {total}")
    print(f"Predictions found: {len(predictions)}")
    print(f"Missing predictions: {len(missing)}")
    if supported_total:
        print(f"Supported cases: {supported_total}")
        print(f"Structured query accuracy: {plan_correct}/{supported_total} = {plan_correct / supported_total:.1%}")
        print(f"Final answer top-row accuracy: {answer_correct}/{supported_total} = {answer_correct / supported_total:.1%}")
    print(f"Overall behavior accuracy: {behavior_correct}/{total} = {behavior_correct / total:.1%}")
    if answered != supported_total:
        print(f"Supported cases with a predicted_top_row: {answered}/{supported_total}")
    if failures:
        print("First mismatches:")
        for failure in failures[:20]:
            print(f"- {failure}")
    return 1 if missing else 0


def load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, list):
        raise SystemExit(f"{path} must contain a list of records.")
    return loaded


def plan_matches(expected: dict[str, Any], predicted: dict[str, Any]) -> bool:
    return canonical_executable_plan(expected) == canonical_executable_plan(predicted)


def canonical_executable_plan(plan: dict[str, Any]) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key in EXECUTABLE_PLAN_KEYS:
        value = plan.get(key, PLAN_DEFAULTS.get(key))
        if key == "minimum_sample" and value is None:
            value = {}
        canonical[key] = comparable(value)
    return canonical


def answer_matches(case: dict[str, Any], predicted_top_row: dict[str, Any]) -> bool:
    expected_top_row = case["answer_key"]["expected_top_row"]
    for field in case.get("answer_check_fields", []):
        if comparable(expected_top_row.get(field)) != comparable(predicted_top_row.get(field)):
            return False
    return True


def comparable(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {key: comparable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
