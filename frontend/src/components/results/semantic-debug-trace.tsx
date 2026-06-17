"use client";

import type { EvidenceNote, QueryResponse } from "@/lib/api-types";
import type { ReactNode } from "react";

type SemanticTrace = {
  original_user_question?: string;
  gemini_raw_response?: string | null;
  parsed_json_plan?: Record<string, unknown> | null;
  normalized_plan?: {
    operation?: string;
    entity?: string;
    metric?: string;
    group_by?: string[];
    filters?: Record<string, unknown>;
    sort?: { by?: string; direction?: string } | null;
    minimum_sample?: Record<string, unknown> | null;
    limit?: number | null;
    confidence?: number | null;
  } | null;
  validation_result?: {
    valid?: boolean;
    errors?: string[];
    warnings?: string[];
  } | null;
  operation_type?: string | null;
  selected_executor?: string | null;
  final_sql_or_method?: string | null;
  result_columns?: string[];
  final_answer_metadata?: Record<string, unknown>;
};

type SemanticDebugTraceProps = {
  result: QueryResponse;
};

export function isSemanticTraceNote(note: EvidenceNote) {
  return note.title === "Semantic V2 trace";
}

export function nonTraceEvidenceNotes(notes: EvidenceNote[]) {
  return notes.filter((note) => !isSemanticTraceNote(note));
}

export function hasSemanticTrace(result: QueryResponse | null | undefined) {
  return Boolean(result?.evidence_notes.some(isSemanticTraceNote));
}

export function SemanticDebugTrace({ result }: SemanticDebugTraceProps) {
  const trace = parseSemanticTrace(result.evidence_notes);

  if (!trace) {
    return null;
  }

  const plan = trace.normalized_plan ?? trace.parsed_json_plan ?? {};
  const filters = asRecord(plan.filters);
  const sort = asRecord(plan.sort);
  const validation = trace.validation_result;

  return (
    <details className="semantic-trace panel result-panel">
      <summary>
        <span>
          <span className="eyebrow">Debug trace</span>
          <strong>Semantic plan</strong>
        </span>
        <span className={`trace-status ${validation?.valid === false ? "invalid" : "valid"}`}>
          {validation?.valid === false ? "validation failed" : "validated"}
        </span>
      </summary>

      <div className="semantic-trace-body">
        <div className="trace-grid">
          <TraceField label="Operation" value={valueText(plan.operation ?? trace.operation_type)} />
          <TraceField label="Entity" value={valueText(plan.entity)} />
          <TraceField label="Metric" value={valueText(plan.metric)} />
          <TraceField label="Group by" value={listText(plan.group_by)} />
          <TraceField label="Sort" value={sortText(sort)} />
          <TraceField label="Limit" value={valueText(plan.limit)} />
        </div>

        <TraceSection title="Filters">
          <KeyValueBlock value={filters} emptyText="No filters" />
        </TraceSection>

        <TraceSection title="Validation">
          <KeyValueBlock
            value={{
              valid: validation?.valid ?? null,
              errors: validation?.errors ?? [],
              warnings: validation?.warnings ?? [],
            }}
            emptyText="No validation result"
          />
        </TraceSection>

        {trace.selected_executor || trace.result_columns?.length ? (
          <TraceSection title="Executor">
            <KeyValueBlock
              value={{
                selected_executor: trace.selected_executor ?? null,
                result_columns: trace.result_columns ?? [],
              }}
              emptyText="No executor metadata"
            />
          </TraceSection>
        ) : null}

        <TraceSection title="Gemini raw plan">
          <pre className="trace-code">
            <code>{trace.gemini_raw_response || "Gemini was not configured or did not return a raw planner response; deterministic semantic fallback was used."}</code>
          </pre>
        </TraceSection>

        {trace.final_sql_or_method ? (
          <TraceSection title="SQL or method">
            <pre className="trace-code">
              <code>{trace.final_sql_or_method}</code>
            </pre>
          </TraceSection>
        ) : null}

        <details className="trace-raw">
          <summary>Raw trace JSON</summary>
          <pre className="trace-code">
            <code>{JSON.stringify(trace, null, 2)}</code>
          </pre>
        </details>
      </div>
    </details>
  );
}

function parseSemanticTrace(notes: EvidenceNote[]): SemanticTrace | null {
  const note = notes.find(isSemanticTraceNote);
  if (!note) {
    return null;
  }
  try {
    return JSON.parse(note.detail) as SemanticTrace;
  } catch {
    return {
      final_answer_metadata: {
        parse_error: "Semantic trace note was not valid JSON.",
        raw_detail: note.detail,
      },
    };
  }
}

function TraceField({ label, value }: { label: string; value: string }) {
  return (
    <div className="trace-field">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TraceSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="trace-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function KeyValueBlock({ emptyText, value }: { emptyText: string; value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([, item]) => item !== undefined);
  if (entries.length === 0) {
    return <p className="muted-copy">{emptyText}</p>;
  }
  return (
    <dl className="trace-kv">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{formatUnknown(item)}</dd>
        </div>
      ))}
    </dl>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function sortText(sort: Record<string, unknown>) {
  if (!sort.by && !sort.direction) {
    return "-";
  }
  return [sort.by, sort.direction].filter(Boolean).join(" ");
}

function listText(value: unknown) {
  if (!Array.isArray(value) || value.length === 0) {
    return "-";
  }
  return value.map(String).join(", ");
}

function valueText(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatUnknown(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.map(formatUnknown).join(", ") : "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}
