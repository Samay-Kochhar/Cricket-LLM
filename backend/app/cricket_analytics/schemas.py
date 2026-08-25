from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


OperationType = Literal[
    "aggregate",
    "player_compare",
    "split_compare",
    "event_window",
    "distribution_analysis",
    "matchup",
    "match_fact",
    "predictive_analysis",
    "tactical_recommendation",
]


class SortSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str
    direction: Literal["asc", "desc"]


class MinimumSampleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balls: int | None = None
    legal_balls: int | None = None
    innings: int | None = None

    def merged_with_defaults(self, defaults: dict[str, int]) -> "MinimumSampleSpec":
        return MinimumSampleSpec(
            balls=self.balls if self.balls is not None else defaults.get("balls"),
            legal_balls=self.legal_balls if self.legal_balls is not None else defaults.get("legal_balls"),
            innings=self.innings if self.innings is not None else defaults.get("innings"),
        )


class CricketQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: OperationType
    entity: str
    metric: str
    group_by: list[str] = Field(default_factory=list)
    filters: dict[str, object] = Field(default_factory=dict)
    split_by: str | None = None
    compare_values: list[str] | None = None
    event: str | None = None
    window: dict[str, object] | None = None
    sort: SortSpec | None = None
    limit: int | None = 10
    minimum_sample: MinimumSampleSpec | None = None
    minimum_sample_explicit: bool = False
    question_subject: str | None = None
    explanation_intent: str | None = None
    confidence: float | None = None
    unsupported_reason: str | None = None
    assumptions: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QueryBuildResult(BaseModel):
    sql: str
    params: list[str | int | float | None] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    metric_column: str
    sample_columns: list[str] = Field(default_factory=list)
    description: str


class ResultValidation(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
