from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    command: tuple[str, ...]


ISSUE_CHECKS: dict[str, list[Check]] = {
    "01": [
        Check(
            "phase-1-contract",
            "Direct player-stat paraphrases keep the same grounded answer contract.",
            ("pytest", "tests/backend/test_semantic_phase1_contract.py", "tests/backend/test_semantic_phase1_paraphrases.py"),
        ),
        Check(
            "metric-registry",
            "Phase 1 metrics are registered and described consistently.",
            ("pytest", "tests/backend/test_metric_registry_phase1.py"),
        ),
    ],
    "02": [
        Check(
            "filtered-single-query",
            "Filtered single-query answers route and execute reliably.",
            ("pytest", "tests/backend/test_query_router.py", "tests/backend/test_analytics_service.py"),
        ),
    ],
    "03": [
        Check(
            "leaderboard-sample-size",
            "Leaderboard requests enforce and explain minimum samples.",
            (
                "pytest",
                "tests/backend/test_grounded_issue_completion_contract.py::test_leaderboard_minimum_sample_is_enforced_and_explained",
            ),
        ),
    ],
    "04": [
        Check(
            "player-comparison",
            "Player comparison plans execute through the split comparison executor.",
            ("pytest", "tests/backend/test_split_compare_executor.py"),
        ),
    ],
    "05": [
        Check(
            "batter-bowler-matchup",
            "Batter-bowler matchup queries return the expected evidence tables.",
            ("pytest", "tests/backend/test_matchup_executor.py"),
        ),
    ],
    "06": [
        Check(
            "failure-state-contract",
            "Unsupported, data-limited, and uncertain planner states are distinct.",
            (
                "pytest",
                "tests/backend/test_grounded_issue_completion_contract.py::test_failure_states_distinguish_data_limitation_unsupported_and_planner_uncertainty",
            ),
        ),
    ],
    "07": [
        Check(
            "database-backed-match-facts",
            "Match facts come from database metadata and innings rows.",
            (
                "pytest",
                "tests/backend/test_grounded_issue_completion_contract.py::test_database_backed_match_facts_use_match_metadata_and_innings_rows",
                "tests/backend/test_semantic_phase3_truth_sql.py",
                "tests/backend/test_golden_factual_chat.py",
            ),
        ),
    ],
    "08": [
        Check(
            "production-planner-safety",
            "Production LLM plans are validated, repaired, or rejected safely.",
            (
                "pytest",
                "tests/backend/test_grounded_issue_completion_contract.py::test_configured_llm_plan_executes_after_validation",
                "tests/backend/test_grounded_issue_completion_contract.py::test_invalid_llm_plan_can_be_repaired_before_execution",
                "tests/backend/test_grounded_issue_completion_contract.py::test_invalid_llm_plan_fails_when_repair_is_still_invalid",
                "tests/backend/test_grounded_issue_completion_contract.py::test_production_semantic_v2_disables_dev_fallback_by_default",
            ),
        ),
    ],
    "09": [
        Check(
            "starter-bowling-plan",
            "The starter tactical prompt returns checked bowling-plan evidence probes.",
            (
                "pytest",
                "tests/backend/test_grounded_issue_completion_contract.py::test_tactical_bowling_plan_returns_checked_evidence_probes",
            ),
        ),
    ],
    "10": [
        Check(
            "evidence-limitation-display-contract",
            "Chat responses carry evidence and limitation data for UI display.",
            ("pytest", "tests/backend/test_chat_phase2_contract.py"),
        ),
    ],
    "11": [
        Check(
            "real-chat-odi-correctness-gate",
            "Run the versioned ODI benchmark through the deployed chat and Semantic V2 contract.",
            ("pytest", "tests/backend/test_odi_correctness_gate.py"),
        ),
        Check(
            "odi-product-family-browser-smoke",
            "Run one complete browser chat flow for every product-ready ODI question family.",
            ("npm", "run", "test:e2e", "--", "odi-correctness-smoke.spec.ts"),
        ),
    ],
    "12": [
        Check(
            "typed-observable-gemini-planner",
            "Verify typed Gemini plans, one repair, safe planner telemetry, and live-chat tracer questions.",
            ("pytest", "tests/backend/test_gemini_structured_planner.py"),
        ),
        Check(
            "planner-failure-state-contract",
            "Verify planner, unsupported, ambiguity, and missing-data states remain distinct.",
            (
                "pytest",
                "tests/backend/test_grounded_issue_completion_contract.py::test_failure_states_distinguish_data_limitation_unsupported_and_planner_uncertainty",
                "tests/backend/test_chat_service.py::test_chat_service_asks_user_to_disambiguate_strike_rate_before_querying",
            ),
        ),
    ],
}

BACKEND_FULL_CHECKS = [
    Check(
        "backend-contract-suite",
        "Run the complete backend and ingestion pytest suite.",
        ("pytest", "tests"),
    )
]

FRONTEND_CHECKS = [
    Check(
        "frontend-build",
        "Build the Next.js app.",
        ("npm", "run", "build"),
    ),
    Check(
        "frontend-e2e",
        "Run Playwright browser checks.",
        ("npm", "run", "test:e2e"),
    ),
]


def command_environment(command: tuple[str, ...]) -> dict[str, str]:
    env = os.environ.copy()
    if command[0] != "npm" or shutil.which("npm", path=env.get("PATH")):
        return env

    nvm_node_bins = list((Path.home() / ".nvm" / "versions" / "node").glob("v*/bin"))
    nvm_node_bins.sort(key=node_version, reverse=True)
    for node_bin in nvm_node_bins:
        if (node_bin / "node").is_file() and (node_bin / "npm").is_file():
            env["PATH"] = str(node_bin) + os.pathsep + env.get("PATH", "")
            return env

    raise RuntimeError(
        "Frontend verification requires Node.js and npm. Install Node 22 or newer, "
        "then rerun this command."
    )


def node_version(node_bin: Path) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in node_bin.parent.name.removeprefix("v").split("."))
    except ValueError:
        return (0,)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify CricAtlas grounded ODI issue contracts.",
    )
    parser.add_argument(
        "--issue",
        action="append",
        choices=sorted(ISSUE_CHECKS),
        help="Run one issue contract by number. Repeat for multiple issues. Defaults to all issue contracts.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also run the complete backend and ingestion pytest suite.",
    )
    parser.add_argument(
        "--frontend",
        action="store_true",
        help="Also run frontend build and Playwright e2e checks.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available issue checks without running them.",
    )
    args = parser.parse_args()

    if args.list:
        list_checks()
        return 0

    issue_numbers = args.issue or sorted(ISSUE_CHECKS)
    checks: list[Check] = []
    for issue_number in issue_numbers:
        checks.extend(ISSUE_CHECKS[issue_number])
    if args.full:
        checks.extend(BACKEND_FULL_CHECKS)
    if args.frontend:
        checks.extend(FRONTEND_CHECKS)

    failures: list[str] = []
    for index, check in enumerate(checks, start=1):
        print(f"\n[{index}/{len(checks)}] {check.name}", flush=True)
        print(check.description, flush=True)
        print("$ " + " ".join(check.command), flush=True)
        cwd = ROOT / "frontend" if check.command[0] == "npm" else ROOT
        try:
            env = command_environment(check.command)
        except RuntimeError as error:
            print(f"ERROR: {error}", flush=True)
            failures.append(check.name)
            continue
        result = subprocess.run(check.command, cwd=cwd, env=env, check=False)
        if result.returncode != 0:
            failures.append(check.name)

    if failures:
        print("\nIssue verification failed:", flush=True)
        for failure in failures:
            print(f"- {failure}", flush=True)
        return 1

    print("\nIssue verification passed.", flush=True)
    return 0


def list_checks() -> None:
    for issue_number in sorted(ISSUE_CHECKS):
        print(f"Issue {issue_number}")
        for check in ISSUE_CHECKS[issue_number]:
            print(f"  - {check.name}: {check.description}")


if __name__ == "__main__":
    raise SystemExit(main())
