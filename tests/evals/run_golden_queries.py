from __future__ import annotations

import sys
from pathlib import Path

import yaml

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import app


def load_cases(path: Path) -> list[dict[str, object]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("golden_queries.yaml must contain a top-level list")
    return payload


def assert_required_evidence(case_id: str, body: dict[str, object], required_evidence: list[str]) -> list[str]:
    failures: list[str] = []
    for key in required_evidence:
        value = body.get(key)
        if not value:
            failures.append(f"{case_id}: missing required evidence block `{key}`")
    return failures


def assert_expected_values(case_id: str, body: dict[str, object], case: dict[str, object]) -> list[str]:
    failures: list[str] = []
    interpretation = body.get("interpretation", {})
    if not isinstance(interpretation, dict):
        failures.append(f"{case_id}: missing interpretation")
        return failures

    expected_entities = case.get("expected_entities")
    if isinstance(expected_entities, list) and interpretation.get("entities") != expected_entities:
        failures.append(
            f"{case_id}: expected entities {expected_entities}, got {interpretation.get('entities')}"
        )

    expected_filters = case.get("expected_filters")
    filters = interpretation.get("filters", {})
    if isinstance(expected_filters, dict) and isinstance(filters, dict):
        for key, value in expected_filters.items():
            if filters.get(key) != value:
                failures.append(f"{case_id}: expected filter {key}={value}, got {filters.get(key)}")

    table_titles = [
        str(table.get("title"))
        for table in body.get("tables", [])
        if isinstance(table, dict)
    ]
    required_table_titles = case.get("required_table_titles")
    if isinstance(required_table_titles, list):
        for title in required_table_titles:
            if str(title) not in table_titles:
                failures.append(f"{case_id}: missing table `{title}`")

    forbidden_table_titles = case.get("forbidden_table_titles")
    if isinstance(forbidden_table_titles, list):
        for title in forbidden_table_titles:
            if str(title) in table_titles:
                failures.append(f"{case_id}: forbidden table `{title}` was returned")

    sql_text = "\n".join(
        str(query.get("sql", ""))
        for query in body.get("evidence_queries", [])
        if isinstance(query, dict)
    )
    required_sql_fragments = case.get("required_sql_fragments")
    if isinstance(required_sql_fragments, list):
        for fragment in required_sql_fragments:
            if str(fragment) not in sql_text:
                failures.append(f"{case_id}: SQL missing `{fragment}`")

    return failures


def main() -> int:
    cases = load_cases(Path(__file__).with_name("golden_queries.yaml"))
    failures: list[str] = []

    with TestClient(app) as client:
        for case in cases:
            case_id = str(case["id"])
            if case.get("endpoint") == "chat":
                response = client.post(
                    "/api/chat",
                    json={
                        "message": case["message"],
                        "history": case.get("history", []),
                    },
                )
            else:
                response = client.post("/api/query", json={"question": case["question"]})
            if response.status_code != 200:
                failures.append(f"{case_id}: query returned status {response.status_code}")
                continue

            payload = response.json()
            body = payload.get("query_response") if case.get("endpoint") == "chat" else payload
            if not isinstance(body, dict):
                failures.append(f"{case_id}: missing query_response body")
                continue
            if body.get("status") != case["expected_status"]:
                failures.append(
                    f"{case_id}: expected status {case['expected_status']}, got {body.get('status')}"
                )
            interpretation = body.get("interpretation", {})
            if interpretation.get("query_class") != case["expected_query_class"]:
                failures.append(
                    f"{case_id}: expected query class {case['expected_query_class']}, got {interpretation.get('query_class')}"
                )

            required_evidence = case.get("required_evidence", [])
            if isinstance(required_evidence, list):
                failures.extend(assert_required_evidence(case_id, body, [str(item) for item in required_evidence]))
            failures.extend(assert_expected_values(case_id, body, case))

    if failures:
        print("Golden query evaluation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Golden query evaluation passed for {len(cases)} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
