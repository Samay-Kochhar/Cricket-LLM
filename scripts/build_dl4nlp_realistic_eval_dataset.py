from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from scripts.build_dl4nlp_eval_dataset import candidates, materialize_case
from backend.app.bootstrap import get_services


DEFAULT_OUTPUT = Path("tests/evals/dl4nlp_cricket_analyst_realistic_100.yaml")

SUPPORTED_QUOTAS = {
    "direct_batter_stat": 12,
    "direct_bowler_stat": 12,
    "leaderboard": 16,
    "batter_breakdown": 18,
    "bowler_breakdown": 10,
    "player_comparison": 6,
    "matchup": 5,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a realistic DL4NLP cricket analyst benchmark.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output YAML path.")
    args = parser.parse_args()

    repository = get_services()["repository"]
    selected: list[dict[str, Any]] = []
    used_by_category = {category: 0 for category in SUPPORTED_QUOTAS}
    skipped: list[str] = []

    for candidate in candidates():
        quota = SUPPORTED_QUOTAS.get(candidate.category)
        if quota is None or used_by_category[candidate.category] >= quota:
            continue
        try:
            case = materialize_case(candidate, repository)
        except Exception as exc:
            skipped.append(f"{candidate.case_id}: {exc}")
            continue
        if case["answer_key"]["row_count"] <= 0:
            skipped.append(f"{candidate.case_id}: empty answer")
            continue
        case["expected_status"] = "supported"
        selected.append(case)
        used_by_category[candidate.category] += 1

    selected.extend(unsupported_and_ambiguous_cases())

    if len(selected) != 100:
        raise SystemExit(f"Expected 100 cases, built {len(selected)}. Category counts: {used_by_category}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(selected, sort_keys=False, allow_unicode=False, width=110),
        encoding="utf-8",
    )
    print(f"Wrote {len(selected)} realistic analyst cases to {output_path}")
    if skipped:
        print(f"Skipped {len(skipped)} candidate supported cases while building gold answers.")
    return 0


def unsupported_and_ambiguous_cases() -> list[dict[str, Any]]:
    raw_cases = [
        (
            "ambiguous-strike-rate-kohli",
            "ambiguous",
            "What is Virat Kohli's strike rate?",
            "Strike rate can mean batting strike rate or bowling strike rate, so the system should ask for clarification.",
        ),
        (
            "ambiguous-best-stats-chinnaswamy",
            "ambiguous",
            "Which bowler has the best statistics at Chinnaswamy?",
            "Best statistics is underspecified because it does not name a metric such as wickets, economy, or strike rate.",
        ),
        (
            "ambiguous-pressure-batter",
            "ambiguous",
            "Which batter is best under pressure?",
            "Pressure is not defined as a database filter, so the system should ask for a precise definition.",
        ),
        (
            "ambiguous-effective-bowler",
            "ambiguous",
            "Who is the most effective ODI bowler?",
            "Effective is underspecified because the metric could be wickets, economy, average, dot-ball percentage, or another measure.",
        ),
        (
            "unsupported-catches-world-cup-2023",
            "unsupported",
            "Who took the most catches in the 2023 World Cup?",
            "The current database does not reliably expose fielder/catcher identity for catches.",
        ),
        (
            "unsupported-player-of-match",
            "unsupported",
            "Who was Player of the Match in the 2011 World Cup final?",
            "Player-of-the-match awards are not part of the local ODI ball-by-ball analytical schema.",
        ),
        (
            "unsupported-toss-winner",
            "unsupported",
            "Who won the toss in the 2019 World Cup final?",
            "Toss winner is not available in the current query layer.",
        ),
        (
            "unsupported-injury-current",
            "unsupported",
            "Is Jasprit Bumrah currently injured?",
            "Current injury status is external/live information and outside the local ODI database.",
        ),
        (
            "unsupported-future-prediction",
            "unsupported",
            "Which bowler will take the most wickets in the next World Cup?",
            "Future predictions are outside the evidence-backed query-generation task.",
        ),
        (
            "unsupported-longest-six",
            "unsupported",
            "Who hit the longest six in ODIs?",
            "Shot distance is not available in the local ODI database.",
        ),
        (
            "unsupported-sixes-count",
            "unsupported",
            "How many sixes has Virat Kohli hit in ODIs?",
            "Six-count is cricket-relevant, but it is not currently exposed as a supported metric in the structured query layer.",
        ),
        (
            "unsupported-mixed-role-comparison",
            "unsupported",
            "Compare Virat Kohli and Jasprit Bumrah.",
            "This mixes a batter and a bowler without specifying a common comparable metric.",
        ),
        (
            "unsupported-test-cricket",
            "unsupported",
            "What is Joe Root's Test batting average?",
            "CricAtlas is ODI-only, so Test cricket is outside the dataset scope.",
        ),
        (
            "unsupported-ipl",
            "unsupported",
            "Which batter has the best strike rate in the IPL?",
            "CricAtlas is ODI-only, so IPL/T20 franchise cricket is outside the dataset scope.",
        ),
        (
            "unsupported-ball-speed",
            "unsupported",
            "What is Mitchell Starc's fastest ball speed?",
            "Ball speed is not present in the local ODI analytical database.",
        ),
        (
            "unsupported-swing-bowling",
            "unsupported",
            "Which venue favors swing bowling the most?",
            "Swing movement is not represented as a supported database field.",
        ),
        (
            "unsupported-partnership-break",
            "unsupported",
            "Which batting partnership should teams try hardest to break?",
            "Partnership-level tactical targeting is not currently implemented in the structured query layer.",
        ),
        (
            "unsupported-morale",
            "unsupported",
            "Which team has the best morale before knockout matches?",
            "Morale is not a database-grounded cricket statistic in this dataset.",
        ),
        (
            "unsupported-weather",
            "unsupported",
            "How does rainy weather affect Rohit Sharma's strike rate?",
            "Weather is not available as a filter in the local ODI database.",
        ),
        (
            "unsupported-coach-tactical",
            "unsupported",
            "What exact field should Australia set to Heinrich Klaasen tomorrow?",
            "This asks for future tactical advice with external match context, beyond the current evidence-backed query task.",
        ),
        (
            "unsupported-video-technique",
            "unsupported",
            "Does Babar Azam's front-foot technique cause his dismissals?",
            "Video/technique analysis is outside the structured database fields.",
        ),
    ]
    return [
        {
            "id": case_id,
            "category": "ambiguous_or_unsupported",
            "question": question,
            "expected_status": status,
            "expected_behavior": reason,
            "answer_key": {
                "source": "curated_scope_label",
                "status": status,
                "expected_response": reason,
            },
        }
        for case_id, status, question, reason in raw_cases
    ]


if __name__ == "__main__":
    raise SystemExit(main())
