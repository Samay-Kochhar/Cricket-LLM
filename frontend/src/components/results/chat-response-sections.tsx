"use client";

import { CitationList } from "@/components/citations/citation-list";
import { SimpleChart } from "@/components/charts/simple-chart";
import { CompactDataTable } from "@/components/results/compact-data-table";
import { EvidenceQueryList } from "@/components/results/evidence-query-list";
import { SemanticDebugTrace, nonTraceEvidenceNotes } from "@/components/results/semantic-debug-trace";
import { VisualInsights } from "@/components/results/visual-insights";
import type { QueryResponse } from "@/lib/api-types";

type ChatResponseSectionsProps = {
  hideCharts?: boolean;
  result: QueryResponse;
};

export function ChatResponseSections({ hideCharts = false, result }: ChatResponseSectionsProps) {
  const visibleEvidenceNotes = nonTraceEvidenceNotes(result.evidence_notes);

  return (
    <div className="chat-response-sections">
      <details className="chat-details" open>
        <summary>Evidence and visuals</summary>
        <div className="chat-details-body">
          <VisualInsights result={result} />
        </div>
      </details>

      {result.tables.length > 0 ? (
        <details className="chat-details">
          <summary>Tables</summary>
          <div className="chat-details-body">
            {result.tables.map((table) => (
              <section className="panel result-panel" key={table.title}>
                <h3 className="card-title">{table.title}</h3>
                <CompactDataTable table={table} />
              </section>
            ))}
          </div>
        </details>
      ) : null}

      {result.evidence_queries.length > 0 ? (
        <details className="chat-details">
          <summary>ODI database evidence</summary>
          <div className="chat-details-body">
            <EvidenceQueryList queries={result.evidence_queries} />
          </div>
        </details>
      ) : null}

      <SemanticDebugTrace result={result} />

      {!hideCharts && result.charts.length > 0 ? (
        <details className="chat-details">
          <summary>Derived charts</summary>
          <div className="chat-details-body">
            {result.charts.map((chart) => (
              <section className="panel result-panel" key={chart.title}>
                <SimpleChart chart={chart} />
              </section>
            ))}
          </div>
        </details>
      ) : null}

      <details className="chat-details">
        <summary>Metrics, notes, and citations</summary>
        <div className="chat-details-body">
          {result.metric_references.length > 0 ? (
            <section className="panel result-panel clay-panel">
              <h3 className="card-title">Metric references</h3>
              <ul className="metric-list">
                {result.metric_references.map((metric) => (
                  <li className="metric-list-item" key={metric.metric_id}>
                    <div>
                      <strong>{metric.label}</strong>
                      <p className="muted-copy">
                        <code>{metric.formula}</code>
                      </p>
                    </div>
                    {metric.unit ? <span className="chip">{metric.unit}</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {visibleEvidenceNotes.length > 0 ? (
            <section className="panel result-panel">
              <h3 className="card-title">Evidence notes</h3>
              <ul className="evidence-list">
                {visibleEvidenceNotes.map((note) => (
                  <li key={`${note.title}-${note.detail}`}>
                    <strong>{note.title}</strong>: {note.detail}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="panel result-panel">
            <h3 className="card-title">Citations</h3>
            <CitationList citations={result.citations} />
          </section>
        </div>
      </details>
    </div>
  );
}
