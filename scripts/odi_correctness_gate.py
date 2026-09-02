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
from backend.app.cricket_analytics.trace import QueryTrace
from backend.app.main import app
from scripts.accuracy_release import (
    AccuracyArtifactStore,
    classify_first_failing_stage,
    score_release,
    validate_unique_case_ids,
)


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "prompt": self.prompt,
            "passed": self.passed,
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> "CaseResult":
        return cls(
            case_id=str(record["case_id"]),
            family=str(record["family"]),
            prompt=str(record["prompt"]),
            errors=tuple(str(error) for error in record.get("errors", [])),
        )


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

    def as_dict(self) -> dict[str, Any]:
        families: dict[str, dict[str, int]] = {}
        grouped: dict[str, list[CaseResult]] = defaultdict(list)
        for result in self.results:
            grouped[result.family].append(result)
        for family, results in sorted(grouped.items()):
            families[family] = {
                "passed": sum(result.passed for result in results),
                "total": len(results),
            }
        return {
            "version": self.version,
            "name": self.name,
            "passed": sum(result.passed for result in self.results),
            "total": len(self.results),
            "families": families,
            "failures": [result.as_dict() for result in self.results if not result.passed],
        }


def load_benchmark(path: Path = DEFAULT_BENCHMARK) -> dict[str, Any]:
    benchmark = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("cases"), list):
        raise ValueError(f"Invalid ODI benchmark: {path}")
    return benchmark


def run_gate(path: Path = DEFAULT_BENCHMARK, *, output_path: Path | None = None) -> GateReport:
    benchmark = load_benchmark(path)
    report = GateReport(version=int(benchmark["version"]), name=str(benchmark["name"]))
    completed = _load_case_results(output_path) if output_path else {}
    output_stream = None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_stream = output_path.open("a", encoding="utf-8")
    try:
        for index, case in enumerate(benchmark["cases"], start=1):
            case_id = str(case["id"])
            result = completed.get(case_id)
            if result is None:
                print(f"[{index}/{len(benchmark['cases'])}] {case_id}", flush=True)
                result = _run_case(case)
                if output_stream:
                    output_stream.write(json.dumps(result.as_dict(), ensure_ascii=False) + "\n")
                    output_stream.flush()
            report.results.append(result)
    finally:
        if output_stream:
            output_stream.close()
    return report


def run_accuracy_release(
    path: Path,
    *,
    output_path: Path,
    previous_path: Path | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    benchmark = load_benchmark(path)
    validate_unique_case_ids(benchmark["cases"])
    store = AccuracyArtifactStore(output_path)
    if fresh:
        store.reset()
    for index, case in enumerate(benchmark["cases"], start=1):
        case_id = str(case["id"])
        if case_id in store.completed_ids:
            continue
        print(f"[{index}/{len(benchmark['cases'])}] {case_id}", flush=True)
        try:
            record = _run_case_evidence(case)
        except Exception as error:  # A terminal record prevents repeating a completed model call on resume.
            runner_error = f"{type(error).__name__}: {error}"
            record = {
                "case_id": case_id,
                "family": str(case.get("family", "uncategorized")),
                "planner_mode": str(case.get("planner_mode", "development_fallback")),
                "turns": [
                    {
                        "turn": turn_index,
                        "user_input": str(turn.get("prompt", "")),
                        "response": {"status": "runner_error", "failure_state": "runner_error"},
                        "trace": {},
                        "errors": [runner_error],
                        "deterministic_errors": ["runner did not complete deterministic comparison"],
                        "production_planner_errors": ["runner did not capture the production plan"],
                    }
                    for turn_index, turn in enumerate(case.get("turns", []), start=1)
                ],
            }
        _assert_production_planner_health(record)
        record["first_failing_stage"] = (
            None if all(not turn["errors"] for turn in record["turns"]) else classify_first_failing_stage(record)
        )
        store.append(record)
    previous_records = AccuracyArtifactStore(previous_path).records if previous_path else None
    return score_release(benchmark, store.records, previous_records=previous_records)


def replay_accuracy_release(
    path: Path,
    *,
    output_path: Path,
    previous_path: Path | None = None,
) -> dict[str, Any]:
    benchmark = load_benchmark(path)
    records = AccuracyArtifactStore(output_path).records
    previous_records = AccuracyArtifactStore(previous_path).records if previous_path else None
    return score_release(benchmark, records, previous_records=previous_records)


def _assert_production_planner_health(record: dict[str, Any]) -> None:
    if record.get("planner_mode") != "production_live":
        return
    for turn in record.get("turns", []):
        trace = turn.get("trace") or {}
        attempts = trace.get("planner_attempts") or []
        if not attempts or trace.get("parsed_json_plan"):
            continue
        error_kinds = [attempt.get("error_kind") for attempt in attempts]
        if all(error_kinds):
            kinds = ", ".join(sorted({str(kind) for kind in error_kinds}))
            raise RuntimeError(
                "production planner unavailable; release case was not saved "
                f"and can be retried ({kinds})"
            )


def _load_case_results(path: Path | None) -> dict[str, CaseResult]:
    if path is None or not path.exists():
        return {}
    results: dict[str, CaseResult] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        result = CaseResult.from_dict(json.loads(line))
        results[result.case_id] = result
    return results


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


def _run_case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    history: list[dict[str, str]] = []
    conversation_state: dict[str, Any] | None = None
    planner_mode = str(case.get("planner_mode", "development_fallback"))
    turns: list[dict[str, Any]] = []
    with _chat_client(planner_mode) as client:
        semantic_service = get_services()["semantic_service"]
        for turn_index, turn in enumerate(case["turns"], start=1):
            prompt = str(turn["prompt"])
            state_input = conversation_state
            request = {
                "message": prompt,
                "history": history,
                "conversation_state": state_input,
            }
            response = client.post("/api/chat", json=request)
            if response.status_code == 200:
                payload = response.json()
                errors = score_turn(payload, turn["expected"])
            else:
                payload = {"mode": "http_error", "message": response.text}
                errors = [f"HTTP {response.status_code}"]
            resolved_input = str(payload.get("resolved_input") or prompt)
            deterministic_candidate, deterministic_validation = _deterministic_candidate(
                resolved_input, semantic_service
            )
            expected_plan = turn.get("expected", {}).get("plan")
            deterministic_errors = (
                semantic_mismatches(deterministic_candidate, expected_plan, "plan")
                if expected_plan is not None
                else []
            )
            query_response = payload.get("query_response") or {}
            trace = _semantic_trace(query_response)
            compiled_plan = trace.get("normalized_plan")
            production_planner_errors = (
                semantic_mismatches(compiled_plan, expected_plan, "plan")
                if expected_plan is not None
                else []
            )
            turns.append(
                {
                    "turn": turn_index,
                    "user_input": prompt,
                    "conversation_state_input": state_input,
                    "conversation_state_output": payload.get("conversation_state"),
                    "conversation_state_applied": (
                        True if turn_index == 1 else bool(state_input and resolved_input != prompt)
                    ),
                    "resolved_input": resolved_input,
                    "selected_planning_path": _planning_path(trace, mode=payload.get("mode")),
                    "safe_model_metadata": _safe_model_metadata(trace),
                    "raw_structured_candidate": trace.get("parsed_json_plan"),
                    "deterministic_candidate": deterministic_candidate,
                    "deterministic_validation": deterministic_validation,
                    "canonical_meaning": turn.get("expected"),
                    "compiled_plan": compiled_plan,
                    "normalization_validation": trace.get("validation_result"),
                    "selected_executor": trace.get("selected_executor"),
                    "database_evidence": query_response.get("evidence_queries") or [],
                    "response": {
                        "http_status": response.status_code,
                        "mode": payload.get("mode"),
                        "status": query_response.get("status"),
                        "failure_state": query_response.get("failure_state"),
                    },
                    "displayed_answer_evidence": {
                        "message": payload.get("message"),
                        "summaries": query_response.get("summaries") or [],
                        "tables": query_response.get("tables") or [],
                        "clarification_options": payload.get("clarification_options") or [],
                    },
                    "trace": trace,
                    "errors": errors,
                    "deterministic_errors": deterministic_errors,
                    "production_planner_errors": production_planner_errors,
                }
            )
            history.extend(
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": str(payload.get("message", ""))},
                ]
            )
            conversation_state = payload.get("conversation_state") or conversation_state
    return {
        "case_id": str(case["id"]),
        "family": str(case["family"]),
        "planner_mode": planner_mode,
        "turns": turns,
    }


def _deterministic_candidate(question: str, semantic_service: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    trace = QueryTrace(original_user_question=question)
    result = semantic_service.planner._plan_with_deterministic_fallback(question, trace)
    plan = result.plan.model_dump(mode="json") if result.plan is not None else None
    return plan, result.validation.model_dump(mode="json")


def _semantic_trace(response: dict[str, Any]) -> dict[str, Any]:
    for note in response.get("evidence_notes", []):
        if note.get("title") != "Semantic V2 trace":
            continue
        try:
            value = json.loads(note.get("detail", ""))
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _planning_path(trace: dict[str, Any], *, mode: object = None) -> str:
    if mode == "clarification":
        return "clarification_policy"
    outcome = trace.get("planner_outcome") or {}
    if outcome.get("selected_model"):
        return "production_model"
    if outcome.get("parse_outcome") == "structured_page_filters":
        return "structured_input"
    return "deterministic"


def _safe_model_metadata(trace: dict[str, Any]) -> dict[str, Any]:
    outcome = trace.get("planner_outcome") or {}
    return {
        key: outcome.get(key)
        for key in (
            "attempt_count",
            "selected_model",
            "finish_reason",
            "parse_outcome",
            "validation_outcome",
            "repair_outcome",
            "latency_ms",
        )
        if key in outcome
    }


@contextmanager
def _chat_client(planner_mode: str) -> Iterator[TestClient]:
    production = planner_mode in {"production_unavailable", "production_live"}
    live = planner_mode == "production_live"
    updates = {
        "APP_ENV": "production" if production else "development",
        "USE_SEMANTIC_ANALYTICS_V2": "true",
        "SEMANTIC_V2_DEV_FALLBACK": "false" if production else "true",
    }
    if not live:
        updates["GEMINI_API_KEY"] = ""
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
    for fragment in expected.get("message_not_contains", []):
        if str(fragment).lower() in str(payload.get("message", "")).lower():
            errors.append(f"displayed answer unexpectedly contains {fragment!r}")
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
    pitch_map_expectation = expected.get("pitch_map")
    pitch_map = (response.get("visuals") or {}).get("pitch_map")
    if pitch_map_expectation == "required" and not pitch_map:
        errors.append("expected a useful pitch map, got none")
    if pitch_map_expectation == "absent" and pitch_map:
        errors.append("expected no pitch map for this sample")
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
    parser.add_argument("--output", type=Path, help="Append each completed case as JSONL and resume it later.")
    parser.add_argument("--summary", type=Path, help="Write the compact final report as JSON.")
    release_mode = parser.add_mutually_exclusive_group()
    release_mode.add_argument(
        "--release", action="store_true", help="Capture the complete production replay artifact."
    )
    release_mode.add_argument(
        "--replay", action="store_true", help="Rescore an existing release artifact offline."
    )
    parser.add_argument("--previous", type=Path, help="Previous release artifact for regressions and improvements.")
    parser.add_argument("--fresh", action="store_true", help="Atomically replace the release artifact before running.")
    args = parser.parse_args()
    logging.disable(logging.INFO)
    if args.release or args.replay:
        if args.output is None:
            parser.error("--release and --replay require --output")
        try:
            report = (
                replay_accuracy_release(
                    args.benchmark,
                    output_path=args.output,
                    previous_path=args.previous,
                )
                if args.replay
                else run_accuracy_release(
                    args.benchmark,
                    output_path=args.output,
                    previous_path=args.previous,
                    fresh=args.fresh,
                )
            )
        except RuntimeError as error:
            parser.exit(2, f"error: {error}\n")
        if args.summary:
            args.summary.parent.mkdir(parents=True, exist_ok=True)
            args.summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["strict_accuracy"]["passed"] == report["strict_accuracy"]["total"] else 1
    report = run_gate(args.benchmark, output_path=args.output)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    print(report.format())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
