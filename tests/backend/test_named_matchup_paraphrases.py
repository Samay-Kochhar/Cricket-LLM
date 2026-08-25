from pathlib import Path

from scripts.odi_correctness_gate import run_gate


BENCHMARK = Path(__file__).parents[1] / "benchmarks" / "odi_matchup_paraphrases_v1.yaml"


def test_named_matchup_paraphrases_reach_database_backed_matchup_through_chat() -> None:
    report = run_gate(BENCHMARK)

    assert report.passed, report.format()
