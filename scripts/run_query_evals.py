from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from backend.app.bootstrap import get_services
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.query_planner import SemanticQueryPlanner
from backend.app.cricket_analytics.trace import QueryTrace


def main() -> int:
    parser = argparse.ArgumentParser(description="Run semantic cricket query evals.")
    parser.add_argument("--file", default="tests/eval_questions.yaml", help="Eval YAML path.")
    parser.add_argument("--execute", action="store_true", help="Execute supported aggregate queries through the semantic service.")
    args = parser.parse_args()

    services = get_services()
    repository = services["repository"]
    gemini_client = services["query_interpreter"].gemini_client
    semantic_service = services["semantic_service"]
    planner = SemanticQueryPlanner(gemini_client, repository.list_player_names())

    eval_path = Path(args.file)
    cases = yaml.safe_load(eval_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise SystemExit(f"{eval_path} must contain a YAML list")

    failures: list[str] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            failures.append(f"{index}: case is not a mapping")
            continue
        question = str(case["question"])
        trace = QueryTrace(original_user_question=question)
        result = planner.plan(question, trace)
        plan = result.plan
        if plan is None:
            failures.append(f"{index}: no plan for {question}")
            continue
        validation = validate_plan(plan, question)
        mismatches = _check_plan(case, plan.model_dump(mode="json"))
        if not validation.valid:
            mismatches.extend(validation.errors)
        if args.execute and plan.operation == "aggregate":
            response = semantic_service.answer_question(question)
            columns = response.tables[0].columns if response.tables else []
            for expected_column in case.get("must_have_columns", []):
                label = str(expected_column).replace("_", " ").title()
                if label not in columns and expected_column not in columns:
                    mismatches.append(f"missing result column {expected_column}")
            for forbidden_column in case.get("must_not_have_columns", []):
                label = str(forbidden_column).replace("_", " ").title()
                if label in columns or forbidden_column in columns:
                    mismatches.append(f"forbidden result column {forbidden_column}")
        if mismatches:
            failures.append(f"{index}: {question} -> {'; '.join(mismatches)}")

    passed = len(cases) - len(failures)
    print(f"Semantic query evals: {passed}/{len(cases)} passed")
    for failure in failures:
        print(f"FAIL {failure}")
    return 1 if failures else 0


def _check_plan(case: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key, expected_key in {
        "expected_operation": "operation",
        "expected_entity": "entity",
        "expected_metric": "metric",
    }.items():
        if key in case and plan.get(expected_key) != case[key]:
            mismatches.append(f"{expected_key} expected {case[key]!r}, got {plan.get(expected_key)!r}")
    if "expected_group_by" in case:
        expected = list(case["expected_group_by"] or [])
        actual = list(plan.get("group_by") or [])
        if actual != expected:
            mismatches.append(f"group_by expected {expected!r}, got {actual!r}")
    if "expected_filters" in case:
        filters = plan.get("filters") if isinstance(plan.get("filters"), dict) else {}
        for key, expected in case["expected_filters"].items():
            if filters.get(key) != expected:
                mismatches.append(f"filter {key} expected {expected!r}, got {filters.get(key)!r}")
    if "minimum_sample_expected" in case:
        sample = plan.get("minimum_sample") if isinstance(plan.get("minimum_sample"), dict) else {}
        for key, expected in case["minimum_sample_expected"].items():
            if sample.get(key) != expected:
                mismatches.append(f"minimum_sample {key} expected {expected!r}, got {sample.get(key)!r}")
    return mismatches


if __name__ == "__main__":
    raise SystemExit(main())
