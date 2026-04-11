from backend.app.domain.evidence_models import (
    Citation,
    CitationSource,
    EvidenceNote,
    EvidenceStatus,
    QueryInterpretation,
    QueryResponse,
)
from backend.app.services.answer_composer import AnswerComposer


def test_answer_composer_appends_grounded_notes_and_citations() -> None:
    response = QueryResponse(
        status=EvidenceStatus.supported,
        interpretation=QueryInterpretation(original_question="Test", query_class="role_comparison"),
        evidence_notes=[EvidenceNote(title="Base", detail="Database only")],
        citations=[],
    )

    composed = AnswerComposer().compose(
        base_response=response,
        grounded_notes=["Grounded with Gemini."],
        grounded_citations=[
            Citation(
                label="External grounded context",
                source_type=CitationSource.external_web,
                locator="gemini:google_search",
            )
        ],
        follow_ups=["Compare the player against peers."],
    )

    assert len(composed.evidence_notes) == 3
    assert len(composed.citations) == 1
