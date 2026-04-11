from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.domain.evidence_models import Citation, CitationSource, QueryResponse
from backend.app.services.gemini_client import GeminiClient


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "grounded_context.txt"
    return prompt_path.read_text(encoding="utf-8")


@dataclass(slots=True)
class GroundedContextService:
    gemini_client: GeminiClient
    prompt_template: str = _load_prompt_template()

    def gather(self, question: str, base_response: QueryResponse) -> tuple[list[str], list[Citation]]:
        if not self._should_ground(question, base_response):
            return ([], [])

        prompt = self.prompt_template.format(
            question=question.strip(),
            database_context=self._build_database_context(base_response),
        )
        grounded = self.gemini_client.ground_with_google_search(question, prompt)
        if grounded is None:
            return ([], [])

        notes = []
        if grounded.text:
            notes.append(f"{grounded.text} (model: {grounded.model_name})")
        if grounded.queries:
            notes.append(f"Google Search grounding queries: {' | '.join(grounded.queries[:3])}")

        citations = [
            Citation(
                label=chunk.title,
                source_type=CitationSource.external_web,
                locator=chunk.uri,
                excerpt=chunk.excerpt,
            )
            for chunk in grounded.chunks
        ]
        return (notes, citations)

    def _should_ground(self, question: str, base_response: QueryResponse) -> bool:
        if not self.gemini_client.is_configured():
            return False
        if base_response.status.value != "supported":
            return True

        lowered = question.lower()
        grounding_triggers = (
            "suggest",
            "recommend",
            "should",
            "important",
            "context",
            "recent",
            "news",
            "today",
            "creative",
            "metric",
        )
        return any(token in lowered for token in grounding_triggers)

    @staticmethod
    def _build_database_context(base_response: QueryResponse) -> str:
        lines = [
            f"status={base_response.status.value}",
            f"query_class={base_response.interpretation.query_class}",
        ]
        if base_response.interpretation.entities:
            lines.append(f"entities={', '.join(base_response.interpretation.entities)}")
        if base_response.summaries:
            lines.extend(f"summary={block.body}" for block in base_response.summaries[:2])
        if base_response.insufficiencies:
            lines.extend(f"limitation={block.detail}" for block in base_response.insufficiencies[:2])
        if base_response.metric_references:
            metric_labels = ", ".join(metric.label for metric in base_response.metric_references[:6])
            lines.append(f"metrics={metric_labels}")
        return "\n".join(lines)
