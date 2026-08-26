from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EvidenceStatus(str, Enum):
    supported = "supported"
    insufficient_evidence = "insufficient_evidence"
    unsupported = "unsupported"


class CitationSource(str, Enum):
    database = "database"
    external_web = "external_web"


class Citation(BaseModel):
    label: str
    source_type: CitationSource
    locator: str
    excerpt: str | None = None


class MetricReference(BaseModel):
    metric_id: str
    label: str
    formula: str
    unit: str | None = None


class SummaryBlock(BaseModel):
    kind: Literal["summary"] = "summary"
    title: str
    body: str


class TableBlock(BaseModel):
    kind: Literal["table"] = "table"
    title: str
    columns: list[str]
    rows: list[list[str | int | float | None]]


class EvidenceQueryBlock(BaseModel):
    kind: Literal["evidence_query"] = "evidence_query"
    title: str
    description: str
    sql: str
    parameters: list[str | int | float | None] = Field(default_factory=list)
    table: TableBlock


class ChartBlock(BaseModel):
    kind: Literal["chart"] = "chart"
    title: str
    chart_type: str
    series: list[dict[str, object]] = Field(default_factory=list)


class EvidenceNote(BaseModel):
    title: str
    detail: str


class InsufficientEvidenceBlock(BaseModel):
    kind: Literal["insufficient_evidence"] = "insufficient_evidence"
    title: str
    detail: str
    missing_inputs: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class VisualCoverage(BaseModel):
    total_balls: int
    covered_balls: int
    coverage_percentage: float
    detail: str


class PitchMapCell(BaseModel):
    line: str
    length: str
    balls: int
    runs: int
    strike_rate: float | None = None
    dismissals: int
    boundary_balls: int
    dot_balls: int = 0
    singles: int = 0
    doubles: int = 0
    triples: int = 0
    fours: int = 0
    sixes: int = 0
    wicket_balls: int = 0
    control_percentage: float | None = None


class PitchMapBlock(BaseModel):
    kind: Literal["pitch_map"] = "pitch_map"
    handedness: str | None = None
    coverage: VisualCoverage
    cells: list[PitchMapCell] = Field(default_factory=list)


class WagonWheelPoint(BaseModel):
    x: float
    y: float
    outcome: Literal["dot", "single", "double", "triple", "four", "six", "wicket"]
    runs: int


class WagonWheelSector(BaseModel):
    zone_id: int
    label: str
    balls: int
    runs: int
    dismissals: int
    strike_rate: float | None = None
    run_share_percentage: float = 0
    singles: int = 0
    doubles: int = 0
    triples: int = 0
    fours: int = 0
    sixes: int = 0
    wicket_balls: int = 0


class WagonWheelBlock(BaseModel):
    kind: Literal["wagon_wheel"] = "wagon_wheel"
    handedness: str | None = None
    coverage: VisualCoverage
    points: list[WagonWheelPoint] = Field(default_factory=list)
    sectors: list[WagonWheelSector] = Field(default_factory=list)


class ShotTypeMetric(BaseModel):
    shot: str
    balls: int
    runs: int
    run_share_percentage: float | None = None
    control_percentage: float | None = None
    false_shot_percentage: float | None = None
    dismissal_rate: float | None = None
    boundary_percentage: float | None = None


class ShotProfileBlock(BaseModel):
    kind: Literal["shot_profile"] = "shot_profile"
    coverage: VisualCoverage
    metrics: list[ShotTypeMetric] = Field(default_factory=list)


class FieldZoneMetric(BaseModel):
    zone_id: int
    label: str
    balls: int
    runs: int
    dismissals: int
    strike_rate: float | None = None
    run_share_percentage: float = 0
    singles: int = 0
    doubles: int = 0
    triples: int = 0
    fours: int = 0
    sixes: int = 0
    wicket_balls: int = 0


class FieldZoneBlock(BaseModel):
    kind: Literal["field_zones"] = "field_zones"
    handedness: str | None = None
    coverage: VisualCoverage
    zones: list[FieldZoneMetric] = Field(default_factory=list)


class RadarMetric(BaseModel):
    label: str
    subject: float
    benchmark: float


class RadarBlock(BaseModel):
    kind: Literal["radar"] = "radar"
    subject_label: str
    benchmark_label: str
    metrics: list[RadarMetric] = Field(default_factory=list)


class VisualPayload(BaseModel):
    pitch_map: PitchMapBlock | None = None
    wagon_wheel: WagonWheelBlock | None = None
    shot_profile: ShotProfileBlock | None = None
    field_zones: FieldZoneBlock | None = None
    radar: RadarBlock | None = None


class QueryInterpretation(BaseModel):
    original_question: str
    query_class: str
    entities: list[str] = Field(default_factory=list)
    filters: dict[str, object] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    status: EvidenceStatus
    failure_state: Literal["data_limitation", "unsupported_capability", "planner_uncertainty"] | None = None
    interpretation: QueryInterpretation
    summaries: list[SummaryBlock] = Field(default_factory=list)
    tables: list[TableBlock] = Field(default_factory=list)
    charts: list[ChartBlock] = Field(default_factory=list)
    visuals: VisualPayload | None = None
    metric_references: list[MetricReference] = Field(default_factory=list)
    evidence_queries: list[EvidenceQueryBlock] = Field(default_factory=list)
    evidence_notes: list[EvidenceNote] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    insufficiencies: list[InsufficientEvidenceBlock] = Field(default_factory=list)
