from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.evidence_models import Citation, EvidenceNote, QueryResponse


@dataclass(slots=True)
class AnswerComposer:
    def compose(
        self,
        base_response: QueryResponse,
        grounded_notes: list[str],
        grounded_citations: list[Citation],
        follow_ups: list[str],
    ) -> QueryResponse:
        notes = list(base_response.evidence_notes)
        if grounded_notes:
            notes.append(EvidenceNote(title="External context", detail=" ".join(grounded_notes)))
        if follow_ups:
            notes.append(EvidenceNote(title="Follow-up suggestions", detail=" | ".join(follow_ups)))
        citations = list(base_response.citations) + grounded_citations
        return base_response.model_copy(update={"evidence_notes": notes, "citations": citations})
