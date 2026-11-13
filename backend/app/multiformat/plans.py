"""The shared reading contract. Planners propose; validation never rewrites intent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScopePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    format: str | None = None
    formats: list[str] = Field(default_factory=list)
    competition: str | None = None
    competitions: list[str] = Field(default_factory=list)
    excluded_competitions: list[str] = Field(default_factory=list)
    gender: Literal["male", "female"] | None = None


class UnderstandingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal[
        "stats", "ranking", "coverage", "matchup", "comparison", "partnership", "venue"
    ] = "stats"
    players: list[str] = Field(default_factory=list)
    role: Literal["batting", "bowling"] = "batting"
    metrics: list[str] = Field(default_factory=list)
    scopes: list[ScopePlan] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    phase: Literal["powerplay", "middle", "death"] | None = None
    over_from: int | None = None
    over_to: int | None = None
    bowler_styles: list[str] = Field(default_factory=list)
    bowler_arm: str | None = None
    bowler_kind: str | None = None
    dimensions: list[Literal["line", "length"]] = Field(default_factory=list)
    lengths: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)
    venue: str | None = None
    opponent: str | None = None
    min_balls: int = Field(default=60, ge=0)
    limit: int = Field(default=10, ge=1, le=100)
    descending: bool | None = None
    partnership_min_runs: int | None = None
    unsupported: list[str] = Field(default_factory=list)
