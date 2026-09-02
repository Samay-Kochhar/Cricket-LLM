from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any


ARTIFACT_SCHEMA_VERSION = 1
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credentials",
    "password",
    "refresh_token",
    "access_token",
    "secret",
    "token",
}


class AccuracyArtifactStore:
    """Owns the durable, resumable evidence artifact for an accuracy run."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records = load_artifact(path)
        self.completed_ids = {str(record["case_id"]) for record in self.records}

    def append(self, record: dict[str, Any]) -> None:
        case_id = str(record["case_id"])
        if case_id in self.completed_ids:
            raise ValueError(f"Duplicate completed case id: {case_id}")
        stored = redact_secrets(
            {"artifact_schema_version": ARTIFACT_SCHEMA_VERSION, **record, "case_id": case_id}
        )
        next_records = [*self.records, stored]
        _atomic_write_jsonl(self.path, next_records)
        self.records = next_records
        self.completed_ids.add(case_id)

    def reset(self) -> None:
        _atomic_write_jsonl(self.path, [])
        self.records = []
        self.completed_ids = set()


def load_artifact(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        case_id = str(record["case_id"])
        if case_id in seen:
            raise ValueError(f"Duplicate case id {case_id!r} in {path} at line {line_number}")
        seen.add(case_id)
        records.append(record)
    return records


def validate_unique_case_ids(cases: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for case in cases:
        case_id = str(case["id"])
        if case_id in seen:
            raise ValueError(f"Duplicate benchmark case id: {case_id}")
        seen.add(case_id)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            is_secret = (
                normalized in _SECRET_KEYS
                or normalized.startswith("authorization_")
                or normalized.endswith(
                    (
                        "_authorization",
                        "_api_key",
                        "_access_token",
                        "_refresh_token",
                        "_password",
                        "_secret",
                    )
                )
            )
            redacted[str(key)] = "[REDACTED]" if is_secret else redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
        return re.sub(
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*([=:])\s*[^\s,;]+",
            r"\1\2[REDACTED]",
            value,
        )
    return value


def score_release(
    benchmark: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    previous_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cases = benchmark.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Benchmark must contain a cases list")
    validate_unique_case_ids(cases)
    indexed = _index_records(records)
    previous = _index_records(previous_records or [])

    family_results: dict[str, list[bool]] = defaultdict(list)
    strict_by_id: dict[str, bool] = {}
    semantic_passed = 0
    safeguard_passed = 0
    failures: list[dict[str, Any]] = []
    overlap = {"both_pass": 0, "production_only": 0, "deterministic_only": 0, "both_fail": 0}
    overlap_total = 0

    for case in cases:
        case_id = str(case["id"])
        family = str(case.get("family", "uncategorized"))
        record = indexed.get(case_id)
        strict_pass = bool(record) and _record_passed(record)
        strict_by_id[case_id] = strict_pass
        family_results[family].append(strict_pass)
        semantic_passed += int(bool(record) and bool(record.get("semantic_pass", strict_pass)))
        safeguard_passed += int(bool(record) and bool(record.get("safeguard_pass", strict_pass)))

        if not strict_pass:
            failures.append(
                {
                    "case_id": case_id,
                    "family": family,
                    "first_failing_stage": (
                        str(record.get("first_failing_stage"))
                        if record and record.get("first_failing_stage")
                        else classify_first_failing_stage(record)
                    ),
                    "errors": _record_errors(record),
                }
            )

        deterministic_pass = _deterministic_passed(record)
        if deterministic_pass is not None:
            overlap_total += 1
            production_planner_pass = _production_planner_passed(record, fallback=strict_pass)
            if production_planner_pass and deterministic_pass:
                overlap["both_pass"] += 1
            elif production_planner_pass:
                overlap["production_only"] += 1
            elif deterministic_pass:
                overlap["deterministic_only"] += 1
            else:
                overlap["both_fail"] += 1

    total = len(cases)
    strict_passed = sum(strict_by_id.values())
    families = {
        family: _score(sum(results), len(results))
        for family, results in sorted(family_results.items())
    }
    pairs: dict[str, list[bool]] = defaultdict(list)
    for case_id, passed in strict_by_id.items():
        pairs[re.sub(r"-[ab]$", "", case_id)].append(passed)
    complete_pairs = [results for results in pairs.values() if len(results) == 2]

    report: dict[str, Any] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "scoring_version": 1,
        "benchmark": str(benchmark.get("name", "accuracy release gate")),
        "benchmark_version": benchmark.get("version"),
        "strict_accuracy": _score(strict_passed, total),
        "semantic_capability": _score(semantic_passed, total),
        "safeguard_aware_accuracy": _score(safeguard_passed, total),
        "families": families,
        "paraphrase_pair_consistency": {
            "consistent_pairs": sum(len(set(results)) == 1 for results in complete_pairs),
            "both_pass": sum(all(results) for results in complete_pairs),
            "one_pass": sum(sum(results) == 1 for results in complete_pairs),
            "both_fail": sum(not any(results) for results in complete_pairs),
            "total_pairs": len(complete_pairs),
        },
        "planner_overlap": {**overlap, "total": overlap_total},
        "regressions": sorted(
            case_id
            for case_id, passed in strict_by_id.items()
            if case_id in previous and _record_passed(previous[case_id]) and not passed
        ),
        "improvements": sorted(
            case_id
            for case_id, passed in strict_by_id.items()
            if case_id in previous and not _record_passed(previous[case_id]) and passed
        ),
        "failures": failures,
    }
    reconcile_summary(report)
    return report


def reconcile_summary(summary: dict[str, Any]) -> None:
    strict = summary["strict_accuracy"]
    family_total = sum(int(item["total"]) for item in summary["families"].values())
    family_passed = sum(int(item["passed"]) for item in summary["families"].values())
    if family_total != int(strict["total"]) or family_passed != int(strict["passed"]):
        raise ValueError("Family totals do not reconcile with strict accuracy")
    if len(summary["failures"]) != int(strict["total"]) - int(strict["passed"]):
        raise ValueError("Failure total does not reconcile with strict accuracy")
    overlap = summary["planner_overlap"]
    overlap_sum = sum(
        int(overlap[key])
        for key in ("both_pass", "production_only", "deterministic_only", "both_fail")
    )
    if overlap_sum != int(overlap["total"]):
        raise ValueError("Planner overlap totals do not reconcile")


def classify_first_failing_stage(record: dict[str, Any] | None) -> str:
    if record is None:
        return "meaning extraction"
    turns = record.get("turns") or []
    for turn_index, turn in enumerate(turns):
        if not turn.get("errors"):
            continue
        if turn_index > 0 and turn.get("conversation_state_applied") is False:
            return "conversation-state application"
        trace = turn.get("trace") or {}
        metadata = trace.get("final_answer_metadata") or {}
        status = str(metadata.get("status", ""))
        validation = trace.get("validation_result") or {}
        expected_plan = (turn.get("canonical_meaning") or {}).get("plan")
        raw_candidate = turn.get("raw_structured_candidate") or trace.get("parsed_json_plan")
        compiled_plan = turn.get("compiled_plan") or trace.get("normalized_plan")
        if not raw_candidate:
            return "meaning extraction"
        if expected_plan and not _contains_meaning(raw_candidate, expected_plan):
            return "meaning extraction"
        if expected_plan and not _contains_meaning(compiled_plan, expected_plan):
            return "canonicalization"
        if validation.get("valid") is False:
            return "validation"
        if status in {"query_execution_failed", "comparison_failed", "tactical_workup_failed"}:
            return "execution"
        if "validation" in status or status.startswith("no_") or status.endswith("_no_rows"):
            return "result validation"
        if not compiled_plan:
            return "canonicalization"
        if not trace.get("selected_executor") or (
            turn.get("response", {}).get("status") == "supported"
            and not trace.get("final_sql_or_method")
            and not turn.get("database_evidence")
        ):
            return "compilation"
        return "response policy"
    return "response policy"


def _index_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = str(record["case_id"])
        if case_id in indexed:
            raise ValueError(f"Duplicate case id: {case_id}")
        indexed[case_id] = record
    return indexed


def _record_passed(record: dict[str, Any]) -> bool:
    turns = record.get("turns") or []
    return bool(turns) and all(not turn.get("errors") for turn in turns)


def _deterministic_passed(record: dict[str, Any] | None) -> bool | None:
    if not record:
        return None
    turns = record.get("turns") or []
    if not turns or any("deterministic_errors" not in turn for turn in turns):
        return None
    return all(not turn["deterministic_errors"] for turn in turns)


def _production_planner_passed(record: dict[str, Any] | None, *, fallback: bool) -> bool:
    if not record:
        return False
    turns = record.get("turns") or []
    if not turns or any("production_planner_errors" not in turn for turn in turns):
        return fallback
    return all(not turn["production_planner_errors"] for turn in turns)


def _record_errors(record: dict[str, Any] | None) -> list[str]:
    if record is None:
        return ["missing completed artifact"]
    return [str(error) for turn in record.get("turns") or [] for error in turn.get("errors") or []]


def _score(passed: int, total: int) -> dict[str, int | float]:
    return {"passed": passed, "total": total, "rate": passed / total if total else 0.0}


def _contains_meaning(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains_meaning(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return sorted(_stable_value(item) for item in actual) == sorted(
            _stable_value(item) for item in expected
        )
    return actual == expected


def _stable_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _atomic_write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
