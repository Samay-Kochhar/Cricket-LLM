from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


LOGGER = logging.getLogger("cricatlas.semantic_v2")


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


@dataclass(slots=True)
class QueryTrace:
    original_user_question: str
    gemini_raw_response: str | None = None
    planner_attempts: list[dict[str, Any]] = field(default_factory=list)
    planner_outcome: dict[str, Any] = field(default_factory=dict)
    parsed_json_plan: dict[str, Any] | None = None
    normalized_plan: dict[str, Any] | None = None
    canonical_meaning: dict[str, Any] | None = None
    meaning_resolution: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    operation_type: str | None = None
    selected_executor: str | None = None
    final_sql_or_method: str | None = None
    result_columns: list[str] = field(default_factory=list)
    final_answer_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return _jsonable(
            {
                "original_user_question": self.original_user_question,
                "gemini_raw_response": self.gemini_raw_response,
                "planner_attempts": self.planner_attempts,
                "planner_outcome": self.planner_outcome,
                "parsed_json_plan": self.parsed_json_plan,
                "normalized_plan": self.normalized_plan,
                "canonical_meaning": self.canonical_meaning,
                "meaning_resolution": self.meaning_resolution,
                "validation_result": self.validation_result,
                "operation_type": self.operation_type,
                "selected_executor": self.selected_executor,
                "final_sql_or_method": self.final_sql_or_method,
                "result_columns": self.result_columns,
                "final_answer_metadata": self.final_answer_metadata,
            }
        )

    def log(self) -> None:
        LOGGER.info("semantic_v2_query_trace=%s", json.dumps(self.as_dict(), sort_keys=True, default=str))

    def compact_json(self, max_chars: int = 3500) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, default=str)
        if len(payload) <= max_chars:
            return payload
        return payload[: max_chars - 3] + "..."
