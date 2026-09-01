from __future__ import annotations

import json

import yaml

from scripts import odi_correctness_gate
from scripts.odi_correctness_gate import CaseResult, GateReport, run_gate, semantic_mismatches


def test_semantic_plan_comparison_ignores_harmless_ordering() -> None:
    actual = {
        "operation": "player_compare",
        "group_by": ["phase", "batter"],
        "filters": {"compare_players": ["Rohit Sharma", "Virat Kohli"]},
    }
    expected = {
        "operation": "player_compare",
        "group_by": ["batter", "phase"],
        "filters": {"compare_players": ["Virat Kohli", "Rohit Sharma"]},
    }

    assert semantic_mismatches(actual, expected, "plan") == []


def test_gate_report_groups_families_and_identifies_failing_prompt() -> None:
    report = GateReport(
        version=1,
        name="ODI gate",
        results=[
            CaseResult("passing", "standalone", "Passing prompt"),
            CaseResult("failing", "matchup", "Failing prompt", ("wrong metric",)),
        ],
    )

    rendered = report.format()

    assert "standalone: 1/1 passed" in rendered
    assert "matchup: 0/1 passed" in rendered
    assert "FAIL [matchup] Failing prompt" in rendered
    assert "wrong metric" in rendered


def test_versioned_odi_benchmark_passes_through_real_chat_contract() -> None:
    report = run_gate()

    assert report.passed, report.format()


def test_gate_persists_each_case_and_resumes_without_repeating_it(tmp_path, monkeypatch) -> None:
    benchmark_path = tmp_path / "benchmark.yaml"
    output_path = tmp_path / "results.jsonl"
    benchmark_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "name": "Resumable gate",
                "cases": [
                    {"id": "one", "family": "direct", "turns": [{"prompt": "First"}]},
                    {"id": "two", "family": "ranking", "turns": [{"prompt": "Second"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_run_case(case):
        calls.append(case["id"])
        return CaseResult(case["id"], case["family"], case["turns"][0]["prompt"])

    monkeypatch.setattr(odi_correctness_gate, "_run_case", fake_run_case)

    first = run_gate(benchmark_path, output_path=output_path)
    second = run_gate(benchmark_path, output_path=output_path)

    records = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert first.passed and second.passed
    assert calls == ["one", "two"]
    assert [record["case_id"] for record in records] == ["one", "two"]
