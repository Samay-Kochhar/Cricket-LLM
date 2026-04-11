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


class QueryInterpretation(BaseModel):
    original_question: str
    query_class: str
    entities: list[str] = Field(default_factory=list)
    filters: dict[str, object] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    status: EvidenceStatus
    interpretation: QueryInterpretation
    summaries: list[SummaryBlock] = Field(default_factory=list)
    tables: list[TableBlock] = Field(default_factory=list)
    charts: list[ChartBlock] = Field(default_factory=list)
    metric_references: list[MetricReference] = Field(default_factory=list)
    evidence_notes: list[EvidenceNote] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    insufficiencies: list[InsufficientEvidenceBlock] = Field(default_factory=list)
