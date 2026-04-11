from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class QueryClass(str, Enum):
    role_comparison = "role_comparison"
    strengths_weaknesses = "strengths_weaknesses"
    head_to_head_matchup = "head_to_head_matchup"
    venue_context_leaderboard = "venue_context_leaderboard"
    trend_progression = "trend_progression"


class MetricDefinition(BaseModel):
    metric_id: str
    label: str
    formula: str
    description: str
    unit: str | None = None
    supported_query_classes: list[QueryClass] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
