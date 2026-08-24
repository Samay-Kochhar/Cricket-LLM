from __future__ import annotations

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
