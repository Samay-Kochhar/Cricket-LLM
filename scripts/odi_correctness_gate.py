from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

from backend.app.bootstrap import get_services
from backend.app.main import app


DEFAULT_BENCHMARK = ROOT / "tests" / "benchmarks" / "odi_correctness_v1.yaml"
ORDER_INSENSITIVE_LISTS = {"group_by", "compare_players", "comparison_metrics", "clarification_labels"}


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    family: str
    prompt: str
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.errors


@dataclass
class GateReport:
    version: int
    name: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    def format(self) -> str:
        passed = sum(result.passed for result in self.results)
        lines = [f"{self.name} v{self.version}: {passed}/{len(self.results)} passed"]
        grouped: dict[str, list[CaseResult]] = defaultdict(list)
        for result in self.results:
            grouped[result.family].append(result)
        for family in sorted(grouped):
            family_results = grouped[family]
            family_passed = sum(result.passed for result in family_results)
            lines.append(f"- {family}: {family_passed}/{len(family_results)} passed")
        for result in self.results:
            if result.passed:
                continue
            lines.append(f"FAIL [{result.family}] {result.prompt}")
            lines.extend(f"  - {error}" for error in result.errors)
        return "\n".join(lines)


def load_benchmark(path: Path = DEFAULT_BENCHMARK) -> dict[str, Any]:
    benchmark = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("cases"), list):
        raise ValueError(f"Invalid ODI benchmark: {path}")
    return benchmark


def run_gate(path: Path = DEFAULT_BENCHMARK) -> GateReport:
    benchmark = load_benchmark(path)
    report = GateReport(version=int(benchmark["version"]), name=str(benchmark["name"]))
    for case in benchmark["cases"]:
        report.results.append(_run_case(case))
    return report


def _run_case(case: dict[str, Any]) -> CaseResult:
    prompts: list[str] = []
    errors: list[str] = []
    history: list[dict[str, str]] = []
    conversation_state: dict[str, Any] | None = None
    planner_mode = str(case.get("planner_mode", "development_fallback"))
    with _chat_client(planner_mode) as client:
        for turn_index, turn in enumerate(case["turns"], start=1):
            prompt = str(turn["prompt"])
            prompts.append(prompt)
            response = client.post(
                "/api/chat",
                json={
                    "message": prompt,
                    "history": history,
                    "conversation_state": conversation_state,
                },
            )
            if response.status_code != 200:
                errors.append(f"turn {turn_index}: HTTP {response.status_code}")
                continue
            payload = response.json()
            turn_errors = score_turn(payload, turn["expected"])
            errors.extend(f"turn {turn_index}: {error}" for error in turn_errors)
            history.extend(
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": str(payload.get("message", ""))},
                ]
            )
            conversation_state = payload.get("conversation_state") or conversation_state
    return CaseResult(
        case_id=str(case["id"]),
        family=str(case["family"]),
        prompt=" -> ".join(prompts),
        errors=tuple(errors),
    )


@contextmanager
def _chat_client(planner_mode: str) -> Iterator[TestClient]:
    production = planner_mode == "production_unavailable"
    updates = {
        "APP_ENV": "production" if production else "development",
        "USE_SEMANTIC_ANALYTICS_V2": "true",
        "SEMANTIC_V2_DEV_FALLBACK": "false" if production else "true",
        "GEMINI_API_KEY": "",
    }
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    get_services.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        get_services.cache_clear()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def score_turn(payload: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _expect_equal(errors, "mode", payload.get("mode"), expected.get("mode"))
    response = payload.get("query_response") or {}
    _expect_equal(errors, "status", response.get("status"), expected.get("status"))
    _expect_equal(errors, "failure_state", response.get("failure_state"), expected.get("failure_state"))

    for fragment in expected.get("message_contains", []):
        if str(fragment).lower() not in str(payload.get("message", "")).lower():
            errors.append(f"displayed answer does not contain {fragment!r}")
    for fragment in expected.get("resolved_input_contains", []):
        if str(fragment).lower() not in str(payload.get("resolved_input", "")).lower():
            errors.append(f"resolved input does not contain {fragment!r}")

    if "clarification_labels" in expected:
        actual_labels = [option.get("label") for option in payload.get("clarification_options", [])]
        errors.extend(semantic_mismatches(actual_labels, expected["clarification_labels"], "clarification_labels"))

    if "plan" in expected:
        plan = _semantic_plan(response)
        if plan is None:
            errors.append("Semantic V2 trace does not contain a normalized plan")
        else:
            errors.extend(semantic_mismatches(plan, expected["plan"], "plan"))

    if "result" in expected:
        errors.extend(_score_result(response, expected["result"]))

    if expected.get("evidence") == "required":
        if not response.get("evidence_queries"):
            errors.append("supported answer has no database evidence query")
        if not any(note.get("title") == "Semantic V2 trace" for note in response.get("evidence_notes", [])):
            errors.append("supported answer has no Semantic V2 evidence trace")
    return errors


def semantic_mismatches(actual: Any, expected: Any, path: str = "value") -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path} expected an object, got {actual!r}"]
        errors: list[str] = []
        for key, value in expected.items():
            if key not in actual:
                errors.append(f"{path}.{key} is missing")
            else:
                errors.extend(semantic_mismatches(actual[key], value, f"{path}.{key}"))
        return errors
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path} expected a list, got {actual!r}"]
        leaf = path.rsplit(".", maxsplit=1)[-1]
        if leaf in ORDER_INSENSITIVE_LISTS:
            if Counter(_stable_value(item) for item in actual) != Counter(_stable_value(item) for item in expected):
                return [f"{path} expected semantic set {expected!r}, got {actual!r}"]
            return []
        if len(actual) != len(expected):
            return [f"{path} expected {expected!r}, got {actual!r}"]
        errors: list[str] = []
        for index, value in enumerate(expected):
            errors.extend(semantic_mismatches(actual[index], value, f"{path}[{index}]"))
        return errors
    if actual != expected:
        return [f"{path} expected {expected!r}, got {actual!r}"]
    return []


def _score_result(response: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    tables = response.get("tables") or []
    if not tables:
        return ["expected a database result table, got none"]
    table = tables[0]
    columns = table.get("columns") or []
    errors: list[str] = []
    for expected_column in expected.get("columns", []):
        if _column_key(expected_column) not in {_column_key(column) for column in columns}:
            errors.append(f"result column {expected_column!r} is missing from {columns!r}")

    actual_rows = [
        {_column_key(column): value for column, value in zip(columns, row, strict=False)}
        for row in table.get("rows", [])
    ]
    for expected_row in expected.get("rows", []):
        normalized_expected = {_column_key(key): value for key, value in expected_row.items()}
        if not any(not semantic_mismatches(row, normalized_expected, "row") for row in actual_rows):
            errors.append(f"database result is missing semantic row {expected_row!r}")
    return errors


def _semantic_plan(response: dict[str, Any]) -> dict[str, Any] | None:
    for note in response.get("evidence_notes", []):
        if note.get("title") != "Semantic V2 trace":
            continue
        try:
            trace = json.loads(note["detail"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        plan = trace.get("normalized_plan")
        return plan if isinstance(plan, dict) else None
    return None


def _column_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _stable_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _expect_equal(errors: list[str], label: str, actual: Any, expected: Any) -> None:
    if expected is not None and actual != expected:
        errors.append(f"{label} expected {expected!r}, got {actual!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the versioned ODI real-chat correctness gate.")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    args = parser.parse_args()
    logging.disable(logging.INFO)
    report = run_gate(args.benchmark)
    print(report.format())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
