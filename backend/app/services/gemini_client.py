from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class GeminiSelection:
    model_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class GroundedChunk:
    title: str
    uri: str
    excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class GeminiGroundedResult:
    model_name: str
    text: str
    queries: tuple[str, ...]
    chunks: tuple[GroundedChunk, ...]


@dataclass(slots=True)
class GeminiClient:
    api_key: str | None
    default_model: str
    complex_model: str
    api_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    timeout_seconds: float = 20.0

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def choose_model(self, question: str) -> GeminiSelection:
        lowered = question.lower()
        is_complex = any(token in lowered for token in ("compare", "trend", "versus", "creative", "correlation"))
        if is_complex:
            return GeminiSelection(self.complex_model, "Complex analytical query")
        return GeminiSelection(self.default_model, "Standard analytical query")

    def ground_with_google_search(self, question: str, prompt: str) -> GeminiGroundedResult | None:
        if not self.is_configured():
            return None

        selection = self.choose_model(question)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 240},
        }

        try:
            response = httpx.post(
                f"{self.api_base_url}/models/{selection.model_name}:generateContent",
                headers={"x-goog-api-key": self.api_key or "", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        return self.parse_grounded_result(response.json(), selection.model_name)

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        if not self.is_configured():
            return None

        model_name = self.complex_model if prefer_complex else self.default_model
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 360},
        }

        try:
            response = httpx.post(
                f"{self.api_base_url}/models/{model_name}:generateContent",
                headers={"x-goog-api-key": self.api_key or "", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        candidates = response.json().get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            return None
        content = candidate.get("content")
        if not isinstance(content, dict):
            return None
        parts = content.get("parts")
        if not isinstance(parts, list):
            return None
        text = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text.append(part["text"].strip())
        joined = "\n".join(segment for segment in text if segment)
        return joined or None

    @staticmethod
    def parse_grounded_result(payload: dict[str, object], model_name: str) -> GeminiGroundedResult | None:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None

        candidate = candidates[0]
        if not isinstance(candidate, dict):
            return None

        content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else []
        text_segments: list[str] = []
        for part in parts if isinstance(parts, list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_segments.append(part["text"].strip())
        text = "\n".join(segment for segment in text_segments if segment)

        grounding_metadata = candidate.get("groundingMetadata")
        if not isinstance(grounding_metadata, dict):
            grounding_metadata = {}

        queries = tuple(
            query
            for query in grounding_metadata.get("webSearchQueries", [])
            if isinstance(query, str) and query.strip()
        )

        excerpt_map = GeminiClient._build_excerpt_map(grounding_metadata.get("groundingSupports"))
        chunks: list[GroundedChunk] = []
        for index, chunk in enumerate(grounding_metadata.get("groundingChunks", [])):
            if not isinstance(chunk, dict):
                continue
            web_chunk = chunk.get("web")
            if not isinstance(web_chunk, dict):
                continue
            uri = web_chunk.get("uri")
            if not isinstance(uri, str) or not uri.strip():
                continue
            title = web_chunk.get("title") if isinstance(web_chunk.get("title"), str) else uri
            excerpt = excerpt_map.get(index)
            chunks.append(GroundedChunk(title=title, uri=uri, excerpt=excerpt))

        if not text and not queries and not chunks:
            return None

        return GeminiGroundedResult(
            model_name=model_name,
            text=text,
            queries=queries,
            chunks=tuple(chunks),
        )

    @staticmethod
    def _build_excerpt_map(raw_supports: object) -> dict[int, str]:
        if not isinstance(raw_supports, list):
            return {}

        excerpts_by_chunk: dict[int, list[str]] = {}
        for support in raw_supports:
            if not isinstance(support, dict):
                continue
            segment = support.get("segment")
            if not isinstance(segment, dict):
                continue
            segment_text = segment.get("text")
            if not isinstance(segment_text, str) or not segment_text.strip():
                continue
            for chunk_index in support.get("groundingChunkIndices", []):
                if isinstance(chunk_index, int):
                    excerpts_by_chunk.setdefault(chunk_index, []).append(segment_text.strip())

        return {
            chunk_index: " ".join(dict.fromkeys(excerpts))
            for chunk_index, excerpts in excerpts_by_chunk.items()
        }
