from __future__ import annotations

from backend.app.domain.evidence_models import EvidenceStatus, QueryInterpretation, QueryResponse, SummaryBlock
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.grounded_context import GroundedContextService


def test_gemini_client_parses_grounding_metadata() -> None:
    payload = {
        "candidates": [
            {
                "content": {"parts": [{"text": "External context about ODI form."}]},
                "groundingMetadata": {
                    "webSearchQueries": ["virat kohli odi recent form"],
                    "groundingChunks": [
                        {"web": {"uri": "https://example.com/article", "title": "Example Article"}}
                    ],
                    "groundingSupports": [
                        {"segment": {"text": "Virat Kohli has remained consistent in ODI cricket."}, "groundingChunkIndices": [0]}
                    ],
                },
            }
        ]
    }

    result = GeminiClient.parse_grounded_result(payload, "gemini-2.5-flash")

    assert result is not None
    assert result.model_name == "gemini-2.5-flash"
    assert result.queries == ("virat kohli odi recent form",)
    assert result.chunks[0].uri == "https://example.com/article"
    assert "consistent" in (result.chunks[0].excerpt or "")


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return True

    def ground_with_google_search(self, question: str, prompt: str):
        return None


def test_grounded_context_gracefully_skips_failed_grounding() -> None:
    response = QueryResponse(
        status=EvidenceStatus.insufficient_evidence,
        interpretation=QueryInterpretation(original_question="Test", query_class="role_comparison"),
        summaries=[SummaryBlock(title="Base", body="Database answer.")],
    )

    notes, citations = GroundedContextService(FakeGeminiClient()).gather("Test question", response)

    assert notes == []
    assert citations == []
