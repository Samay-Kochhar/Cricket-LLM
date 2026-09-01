from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

from backend.app.bootstrap import get_services
from backend.app.domain.evidence_models import QueryResponse
from scripts.score_dl4nlp_predictions import answer_matches, plan_matches


DEFAULT_GOLD = Path("tests/evals/dl4nlp_cricket_analyst_supported_100.yaml")
DEFAULT_OUTPUT = Path("tests/evals/results/cricatlas_presentation_100_current.jsonl")


def prediction_from_response(
    case_id: str,
    category: str,
    question: str,
    response: QueryResponse,
) -> dict[str, Any]:
    trace = _semantic_trace(response)
    top_row: dict[str, Any] | None = None
    if response.tables and response.tables[0].rows:
        table = response.tables[0]
        top_row = {
            _column_key(column): value
            for column, value in zip(table.columns, table.rows[0], strict=False)
        }

    return {
        "id": case_id,
        "category": category,
        "question": question,
        "predicted_status": _enum_value(response.status),
        "failure_state": response.failure_state,
        "predicted_plan": trace.get("normalized_plan"),
        "predicted_top_row": top_row,
        "summary": "\n".join(summary.body for summary in response.summaries),
        "planner_outcome": trace.get("planner_outcome"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def _semantic_trace(response: QueryResponse) -> dict[str, Any]:
    for note in response.evidence_notes:
        if note.title != "Semantic V2 trace":
            continue
        try:
            value = json.loads(note.detail)
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _column_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def load_records(path: Path) -> list[dict[str, Any]]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise SystemExit(f"{path} must contain a YAML list.")
    return loaded


def load_completed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        records[str(record["id"])] = record
    return records


def score_predictions(
    gold: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    category_totals: Counter[str] = Counter()
    category_plan_correct: Counter[str] = Counter()
    category_answer_correct: Counter[str] = Counter()
    category_supported: Counter[str] = Counter()
    plan_correct = 0
    answer_correct = 0
    answer_semantic_correct = 0
    behavior_correct = 0
    failures: list[dict[str, str]] = []

    for case in gold:
        case_id = str(case["id"])
        category = str(case.get("category", "uncategorized"))
        category_totals[category] += 1
        prediction = predictions.get(case_id)
        if prediction is None:
            failures.append({"id": case_id, "category": category, "reason": "missing prediction"})
            continue

        expected_status = str(case.get("expected_status", "supported"))
        if prediction.get("predicted_status") == expected_status:
            behavior_correct += 1
            category_supported[category] += 1

        predicted_plan = prediction.get("predicted_plan")
        if isinstance(predicted_plan, dict) and plan_matches(case["expected_plan"], predicted_plan):
            plan_correct += 1
            category_plan_correct[category] += 1
        else:
            failures.append({"id": case_id, "category": category, "reason": "plan mismatch"})

        top_row = prediction.get("predicted_top_row")
        if isinstance(top_row, dict) and answer_matches(case, top_row):
            answer_correct += 1
        if isinstance(top_row, dict) and answer_semantic_matches(case, top_row):
            answer_semantic_correct += 1
            category_answer_correct[category] += 1

    total = len(gold)
    return {
        "benchmark": "presentation-supported-100",
        "gold_cases": total,
        "predictions": len(predictions),
        "plan_exact_match": {"correct": plan_correct, "total": total, "rate": plan_correct / total},
        "top_row_exact_match": {"correct": answer_correct, "total": total, "rate": answer_correct / total},
        "top_row_semantic_match": {
            "correct": answer_semantic_correct,
            "total": total,
            "rate": answer_semantic_correct / total,
        },
        "status_accuracy": {"correct": behavior_correct, "total": total, "rate": behavior_correct / total},
        "by_category": {
            category: {
                "correct": category_plan_correct[category],
                "total": category_totals[category],
                "rate": category_plan_correct[category] / category_totals[category],
                "answer_correct": category_answer_correct[category],
                "answer_rate": category_answer_correct[category] / category_totals[category],
                "supported": category_supported[category],
                "supported_rate": category_supported[category] / category_totals[category],
            }
            for category in sorted(category_totals)
        },
        "failures": failures,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
    }


def answer_semantic_matches(case: dict[str, Any], predicted_top_row: dict[str, Any]) -> bool:
    expected_top_row = case["answer_key"]["expected_top_row"]
    for field in case.get("answer_check_fields", []):
        if field not in predicted_top_row:
            return False
        expected = expected_top_row.get(field)
        actual = predicted_top_row.get(field)
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if not math.isclose(float(expected), float(actual), rel_tol=0.0005, abs_tol=0.011):
                return False
            continue
        if isinstance(expected, str) and isinstance(actual, str):
            expected_key = re.sub(r"[^a-z0-9]+", "", expected.lower())
            actual_key = re.sub(r"[^a-z0-9]+", "", actual.lower())
            if expected_key != actual_key:
                return False
            continue
        if expected != actual:
            return False
    return True


def _git_commit() -> str | None:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a frozen ODI benchmark through CricAtlas.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--fresh", action="store_true", help="Replace an existing result instead of resuming it.")
    args = parser.parse_args()

    gold = load_records(args.gold)
    if args.limit is not None:
        gold = gold[: args.limit]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.fresh and args.output.exists():
        args.output.unlink()
    completed = load_completed(args.output)

    services = get_services()
    gemini_client = services["query_interpreter"].gemini_client
    if not gemini_client.is_configured():
        raise SystemExit("Gemini is not configured; refusing to label an offline fallback run as the live benchmark.")
    semantic_service = services["semantic_service"]

    with args.output.open("a", encoding="utf-8") as stream:
        for index, case in enumerate(gold, start=1):
            case_id = str(case["id"])
            if case_id in completed:
                continue
            question = str(case["question"])
            print(f"[{index}/{len(gold)}] {case_id}", flush=True)
            try:
                response = semantic_service.answer_question(question)
                prediction = prediction_from_response(
                    case_id,
                    str(case.get("category", "uncategorized")),
                    question,
                    response,
                )
            except Exception as error:  # Keep a resumable audit record even if one case fails.
                prediction = {
                    "id": case_id,
                    "category": str(case.get("category", "uncategorized")),
                    "question": question,
                    "predicted_status": "runner_error",
                    "predicted_plan": None,
                    "predicted_top_row": None,
                    "error": f"{type(error).__name__}: {error}",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                }
            stream.write(json.dumps(prediction, sort_keys=True) + "\n")
            stream.flush()
            completed[case_id] = prediction
            if args.delay:
                time.sleep(args.delay)

    report = score_predictions(gold, completed)
    summary_path = args.summary or args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "failures"}, indent=2))
    print(f"Failures: {len(report['failures'])}")
    print(f"Saved predictions: {args.output}")
    print(f"Saved summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
