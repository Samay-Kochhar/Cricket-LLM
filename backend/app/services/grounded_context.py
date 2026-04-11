from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.evidence_models import Citation, CitationSource
from backend.app.services.gemini_client import GeminiClient


@dataclass(slots=True)
class GroundedContextService:
    gemini_client: GeminiClient

    def gather(self, question: str) -> tuple[list[str], list[Citation]]:
        if not self.gemini_client.is_configured():
            return ([], [])
        selection = self.gemini_client.choose_model(question)
        return (
            [f"Gemini grounding requested with {selection.model_name}."],
            [
                Citation(
                    label="External grounded context",
                    source_type=CitationSource.external_web,
                    locator="gemini:google_search",
                    excerpt="Grounding hook is configured but not yet wired to live search results.",
                )
            ],
        )
