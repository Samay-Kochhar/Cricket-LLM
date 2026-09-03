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
    "13": [
        Check(
            "named-matchup-real-chat-benchmark",
            "Verify Smith-Bumrah paraphrases, role order, database truth, sample wording, and pitch-map gating.",
            ("pytest", "tests/backend/test_named_matchup_paraphrases.py"),
        ),
        Check(
            "named-matchup-browser-flow",
            "Run the named Smith-Bumrah matchup through the browser and show its supported pitch map.",
            (
                "npm",
                "run",
                "test:e2e",
                "--",
                "odi-correctness-smoke.spec.ts",
                "--grep",
                "named matchup paraphrase",
            ),
        ),
    ],
    "14": [
        Check(
            "same-role-player-comparisons",
            "Verify batter and bowler comparison paraphrases, metrics, filters, samples, and tables.",
            (
                "pytest",
                "tests/backend/test_user_reported_query_capabilities.py",
                "tests/backend/test_gemini_structured_planner.py",
                "-k",
                "comparison or compare",
            ),
        ),
        Check(
            "comparison-browser-flow",
            "Run a player comparison through the real browser and chat API.",
            (
                "npm",
                "run",
                "test:e2e",
                "--",
                "odi-correctness-smoke.spec.ts",
                "--grep",
                "comparison question",
            ),
        ),
    ],
    "15": [
        Check(
            "line-length-style-breakdowns",
            "Verify line, length, and bowling-style ownership, metrics, filters, and chart contracts.",
            (
                "pytest",
                "tests/backend/test_user_reported_query_capabilities.py",
                "tests/backend/test_gemini_structured_planner.py",
                "-k",
                "length or bowling_style or style or off_spin or false_shot",
            ),
        ),
    ],
    "16": [
        Check(
            "ranking-intent-and-scope",
            "Verify ranking direction, metric meaning, filters, limits, and sample thresholds.",
            (
                "pytest",
                "tests/backend/test_user_reported_query_capabilities.py",
                "tests/backend/test_gemini_structured_planner.py",
                "-k",
                "ranking or minimum_sample or threshold or limit",
            ),
        ),
        Check(
            "ranking-browser-control",
            "Verify the browser exposes and applies the legal-ball threshold for bowling rankings.",
            (
                "npm",
                "run",
                "test:e2e",
                "--",
                "chat.spec.ts",
                "--grep",
                "bowling ranking",
            ),
        ),
    ],
    "17": [
        Check(
            "phase-and-handedness-splits",
            "Verify canonical phase boundaries, handedness, samples, insufficiency, and chart gating.",
            (
                "pytest",
                "tests/backend/test_split_compare_executor.py",
                "tests/backend/test_gemini_structured_planner.py",
                "-k",
                "split or phase or handedness",
            ),
        ),
    ],
    "18": [
        Check(
            "yearly-trend-contract",
            "Verify yearly plans, retained filters, database truth, evidence thresholds, matching charts, and cautious conclusions.",
            ("pytest", "tests/backend/test_issue_18_trends.py"),
        ),
        Check(
            "yearly-trend-browser-flow",
            "Run a filtered bowler trend through the real browser and chat API.",
            (
                "npm",
                "run",
                "test:e2e",
                "--",
                "odi-correctness-smoke.spec.ts",
                "--grep",
                "yearly trend question",
            ),
        ),
    ],
    "21": [
        Check(
            "player-explorer-lightweight-initialization",
            "Verify Player Explorer caches repository capabilities without initializing Gemini or chat services.",
            (
                "pytest",
                "tests/streamlit/test_issue_21_player_explorer_initialization.py",
                "tests/streamlit/test_player_explorer.py",
            ),
        ),
    ],
    "25": [
        Check(
            "production-accuracy-release-gate",
            "Verify atomic resume, offline replay, diagnostic evidence, immutable inputs, and release scoring.",
            (
                "pytest",
                "tests/evals/test_accuracy_release.py",
                "tests/backend/test_odi_correctness_gate.py",
                "tests/backend/test_gemini_structured_planner.py",
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
    installed_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    workspace_runtime = Path("/opt/anaconda3/envs/odi-analyst-workbench/bin")
    if command[0] == "npm":
        if workspace_runtime.is_dir():
            env["PATH"] = str(workspace_runtime) + os.pathsep + env.get("PATH", "")
        if "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH" not in env and installed_chrome.is_file():
            env["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = str(installed_chrome)
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
