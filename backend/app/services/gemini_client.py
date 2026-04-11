from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GeminiSelection:
    model_name: str
    reason: str


@dataclass(slots=True)
class GeminiClient:
    api_key: str | None
    default_model: str
    complex_model: str

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def choose_model(self, question: str) -> GeminiSelection:
        lowered = question.lower()
        is_complex = any(token in lowered for token in ("compare", "trend", "versus", "creative", "correlation"))
        if is_complex:
            return GeminiSelection(self.complex_model, "Complex analytical query")
        return GeminiSelection(self.default_model, "Standard analytical query")
