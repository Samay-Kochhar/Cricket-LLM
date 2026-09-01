from __future__ import annotations

import json

from backend.app.domain.evidence_models import (
    EvidenceNote,
    EvidenceStatus,
    QueryInterpretation,
    QueryResponse,
    SummaryBlock,
    TableBlock,
)
from scripts.run_cricatlas_benchmark import answer_semantic_matches, prediction_from_response


def test_prediction_extracts_normalized_plan_and_top_row() -> None:
    response = QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(
            original_question="How many runs?",
            query_class="aggregate",
        ),
        summaries=[SummaryBlock(title="Answer", body="Virat Kohli scored 13,950 runs.")],
        tables=[
            TableBlock(
                title="Result",
                columns=["Batter", "Runs Scored", "Balls Faced"],
                rows=[["Virat Kohli", 13950, 14918]],
            )
        ],
        evidence_notes=[
            EvidenceNote(
                title="Semantic V2 trace",
                detail=json.dumps(
                    {
                        "normalized_plan": {
                            "operation": "aggregate",
                            "entity": "batter",
                            "metric": "runs_scored",
                        },
                        "planner_outcome": {"selected_model": "gemini-test"},
                    }
                ),
            )
        ],
    )

    prediction = prediction_from_response("case-1", "single_metric", "How many runs?", response)

    assert prediction["predicted_status"] == "supported"
    assert prediction["predicted_plan"]["metric"] == "runs_scored"
    assert prediction["predicted_top_row"] == {
        "batter": "Virat Kohli",
        "runs_scored": 13950,
        "balls_faced": 14918,
    }
    assert prediction["planner_outcome"]["selected_model"] == "gemini-test"


def test_prediction_preserves_failure_state_without_a_table() -> None:
    response = QueryResponse(
        status=EvidenceStatus.unsupported,
        failure_state="unsupported_capability",
        interpretation=QueryInterpretation(
            original_question="Predict tomorrow",
            query_class="predictive_analysis",
        ),
        summaries=[SummaryBlock(title="Unavailable", body="Prediction is unsupported.")],
    )

    prediction = prediction_from_response("case-2", "unsupported", "Predict tomorrow", response)

    assert prediction["predicted_status"] == "unsupported"
    assert prediction["failure_state"] == "unsupported_capability"
    assert prediction["predicted_top_row"] is None


def test_answer_semantic_match_allows_display_rounding_but_not_wrong_values() -> None:
    case = {
        "answer_key": {
            "expected_top_row": {"batter": "Virat Kohli", "batting_strike_rate": 93.5112}
        },
        "answer_check_fields": ["batter", "batting_strike_rate"],
    }

    assert answer_semantic_matches(
        case,
        {"batter": "Virat Kohli", "batting_strike_rate": 93.51},
    )
    assert not answer_semantic_matches(
        case,
        {"batter": "Rohit Sharma", "batting_strike_rate": 93.51},
    )
