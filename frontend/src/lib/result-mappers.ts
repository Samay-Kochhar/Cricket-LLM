import type { QueryResponse } from "@/lib/api-types";


export function normalizeQueryResponse(payload: QueryResponse): QueryResponse {
  return {
    ...payload,
    summaries: payload.summaries ?? [],
    tables: payload.tables ?? [],
    charts: payload.charts ?? [],
    visuals: payload.visuals ?? null,
    metric_references: payload.metric_references ?? [],
    evidence_queries: payload.evidence_queries ?? [],
    evidence_notes: payload.evidence_notes ?? [],
    citations: payload.citations ?? [],
    insufficiencies: payload.insufficiencies ?? [],
  };
}
