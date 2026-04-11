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


def main() -> int:
    cases = load_cases(Path(__file__).with_name("golden_queries.yaml"))
    failures: list[str] = []

    with TestClient(app) as client:
        for case in cases:
            case_id = str(case["id"])
            response = client.post("/api/query", json={"question": case["question"]})
            if response.status_code != 200:
                failures.append(f"{case_id}: query returned status {response.status_code}")
                continue

            body = response.json()
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

    if failures:
        print("Golden query evaluation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Golden query evaluation passed for {len(cases)} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
