from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.odi_correctness_gate import load_benchmark
from scripts.replay_planner_capture import replay_capture

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "tests/evals/results/releases/issue-35"
BENCHMARK = ROOT / "tests/benchmarks/odi_unseen_paraphrases_v1.yaml"


def test_family_selection_keeps_original_frozen_questions():
    full = load_benchmark(BENCHMARK)
    selected = load_benchmark(BENCHMARK, families={"direct", "ranking"})
    assert selected["cases"] == [
        c for c in full["cases"] if c["family"] in {"direct", "ranking"}
    ]
    assert len(selected["cases"]) == 44


def test_final_live_and_offline_evidence_reconcile():
    live = json.loads((RELEASE / "production-targets.summary.json").read_text())
    offline = json.loads((RELEASE / "offline-replay.summary.json").read_text())
    executed = json.loads((RELEASE / "executed-replay.summary.json").read_text())
    impact = json.loads((RELEASE / "impact-replay.summary.json").read_text())
    prior = json.loads(
        (
            ROOT
            / "tests/evals/results/releases/issue-26/cricatlas-issue26-impact-replay.summary.json"
        ).read_text()
    )
    assert live == offline == executed
    assert live["families"]["direct"]["passed"] == 20
    assert live["families"]["ranking"]["passed"] == 24
    assert live["model_call_reasons"] == {"initial_meaning_extraction": 44}
    assert impact["families"] == prior["families"]
    assert impact["regressions"] == []
    for record in map(
        json.loads, (RELEASE / "production-targets.jsonl").read_text().splitlines()
    ):
        for turn in record["turns"]:
            attempts = turn["trace"]["planner_attempts"]
            assert len(attempts) == 1
            assert "flash" in attempts[0]["selected_model"]
            assert attempts[0]["attempt"] == "meaning_extraction"
            assert turn["trace"]["parsed_json_plan"] is None
            assert turn["trace"]["canonical_meaning"]


def test_saved_model_output_reexecutes_through_chat_and_database_offline(tmp_path):
    benchmark = load_benchmark(BENCHMARK, families={"direct"})
    benchmark["cases"] = benchmark["cases"][:1]
    selected = tmp_path / "one-case.yaml"
    selected.write_text(yaml.safe_dump(benchmark))
    output = tmp_path / "replayed.jsonl"
    summary = replay_capture(selected, RELEASE / "production-targets.jsonl", output)
    assert summary["strict_accuracy"]["passed"] == 1
    assert summary["stage_accuracy"]["extraction_contract"]["passed"] == 1
    trace = json.loads(output.read_text())["turns"][0]["trace"]
    assert trace["planner_attempts"][0]["parse_outcome"] == "parsed"
    assert trace["canonical_meaning"]["metric"] == "runs_scored"
    assert trace["selected_executor"]
