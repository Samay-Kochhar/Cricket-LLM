"""Re-execute captured planner responses through the real chat/database path offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from backend.app.services.gemini_client import GeminiClient, GeminiStructuredResult
from scripts.accuracy_release import AccuracyArtifactStore, score_release
from scripts.odi_correctness_gate import _run_case_evidence, load_benchmark


def captured_responses(record: dict) -> list[GeminiStructuredResult]:
    """The recorded structured model responses of one captured case, in call order."""
    responses = []
    for turn in record.get("turns", []):
        trace = turn.get("trace") or {}
        legacy_responses = (trace.get("gemini_raw_response") or "").split(
            "\n\nREPAIR:\n"
        )
        for index, attempt in enumerate(trace.get("planner_attempts", [])):
            raw = attempt.get("raw_response")
            if "raw_response" not in attempt:
                raw = (
                    legacy_responses[index]
                    if index < len(legacy_responses)
                    else None
                )
            responses.append(
                GeminiStructuredResult(
                    text=raw,
                    selected_model=attempt.get("selected_model") or "captured",
                    model_version=attempt.get("model_version"),
                    finish_reason=(
                        str(attempt["finish_reason"]).upper().replace(" ", "_")
                        if attempt.get("finish_reason")
                        else None
                    ),
                    latency_ms=attempt.get("latency_ms", 0),
                    error_kind=attempt.get("error_kind"),
                    prompt_token_count=attempt.get("prompt_token_count"),
                    output_token_count=attempt.get("output_token_count"),
                    schema_constrained=attempt.get("schema_constrained", True),
                )
            )
    return responses


def replay_case(case: dict, responses: list[GeminiStructuredResult]) -> dict:
    """Run one benchmark case through the real chat/database path with recorded model output."""
    pending = list(responses)

    def generate(*args, **kwargs):
        if not pending:
            raise AssertionError(
                f"Replay requested an uncaptured model call: {case['id']}"
            )
        return pending.pop(0)

    with (
        patch.object(GeminiClient, "generate_structured", side_effect=generate),
        patch.object(GeminiClient, "generate_text", return_value=None),
        # Planner replay verifies database answers; web grounding is not captured.
        patch.object(GeminiClient, "ground_with_google_search", return_value=None),
        patch.object(GeminiClient, "is_configured", return_value=True),
        patch(
            "httpx.post",
            side_effect=AssertionError("Offline replay attempted network access"),
        ),
    ):
        return _run_case_evidence(case)


def replay_capture(
    benchmark_path: Path,
    capture_path: Path,
    output_path: Path,
    *,
    families: set[str] | None = None,
) -> dict:
    benchmark = load_benchmark(benchmark_path, families=families)
    captured = {r["case_id"]: r for r in AccuracyArtifactStore(capture_path).records}
    output = AccuracyArtifactStore(output_path)
    for case in benchmark["cases"]:
        if case["id"] in output.completed_ids:
            continue
        output.append(replay_case(case, captured_responses(captured[case["id"]])))
    return score_release(benchmark, output.records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--family", action="append")
    args = parser.parse_args()
    summary = replay_capture(
        args.benchmark,
        args.capture,
        args.output,
        families=set(args.family) if args.family else None,
    )
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "strict_accuracy": summary["strict_accuracy"],
                "families": summary["families"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
