"use client";

import Link from "next/link";
import { useState } from "react";

import { CitationList } from "@/components/citations/citation-list";
import { SimpleChart } from "@/components/charts/simple-chart";
import { VisualInsights } from "@/components/results/visual-insights";
import type { Citation, QueryResponse } from "@/lib/api-types";
import { deriveExplorerLinks } from "@/lib/explorer-links";

type ResultViewProps = {
  error: string | null;
  isLoading: boolean;
  onSaveAnalysis?: (() => void) | null;
  result: QueryResponse | null;
};

function SummaryWithCitationLinks({
  body,
  citations,
  onOpenCitation,
}: {
  body: string;
  citations: Citation[];
  onOpenCitation: (citation: Citation) => void;
}) {
  return (
    <div className="summary-copy">
      <p className="muted-copy">{body}</p>
      {citations.length > 0 ? (
        <p className="inline-citation-row">
          Backed by{" "}
          {citations.map((citation, index) => (
            <span key={`${citation.label}-${citation.locator}`}>
              <button
                className="inline-citation-link"
                onClick={() => onOpenCitation(citation)}
                type="button"
              >
                {citation.label}
              </button>
              {index < citations.length - 1 ? ", " : "."}
            </span>
          ))}
        </p>
      ) : null}
    </div>
  );
}

export function ResultView({ error, isLoading, onSaveAnalysis, result }: ResultViewProps) {
  const [selectedCitationIndex, setSelectedCitationIndex] = useState<number | null>(null);
  const [showEvidenceRail, setShowEvidenceRail] = useState(false);

  if (isLoading) {
    return <p className="muted-copy">Running ODI analysis...</p>;
  }

  if (error) {
    return <p className="muted-copy">Query error: {error}</p>;
  }

  if (!result) {
    return (
      <div className="result-empty">
        <div className="brand-kicker">Analyst mode</div>
        <h3 className="section-title">Run a question to unlock the workbench</h3>
        <p className="muted-copy">
          The redesigned canvas will surface pitch maps, wagon wheels, shot-type views, field
          sectors, metric notes, and citations from the same query flow once you submit an ODI
          question.
        </p>
      </div>
    );
  }

  const explorerLinks = deriveExplorerLinks(result);
  const visibleCitations = result.citations;

  function handleOpenCitation(citation: Citation) {
    const index = visibleCitations.findIndex(
      (item) =>
        item.label === citation.label &&
        item.locator === citation.locator &&
        item.source_type === citation.source_type,
    );
    setSelectedCitationIndex(index >= 0 ? index : 0);
  }

  return (
    <div className="result-workbench">
      <div className="result-main-column">
        <section className="panel briefing-panel">
          <div className="briefing-topline">
            <span className="eyebrow">Evidence briefing</span>
            <div className="briefing-actions">
              <span className={`status-pill ${result.status}`}>{result.status.replaceAll("_", " ")}</span>
              <button
                className="ghost-button inline-button"
                onClick={() => setShowEvidenceRail((current) => !current)}
                type="button"
              >
                {showEvidenceRail ? "Hide evidence" : "Evidence"}
              </button>
            </div>
          </div>
          <h2 className="briefing-title">{result.interpretation.original_question}</h2>
          <p className="muted-copy">
            Query class: <strong>{result.interpretation.query_class}</strong>
          </p>
          <div className="chip-row">
            {result.interpretation.entities.map((entity) => (
              <span className="chip" key={entity}>
                {entity}
              </span>
            ))}
            {result.metric_references.slice(0, 4).map((metric) => (
              <span className="chip accent" key={metric.metric_id}>
                {metric.label}
              </span>
            ))}
          </div>
          <div className="action-row">
            {onSaveAnalysis ? (
              <button className="primary-button inline-button" onClick={onSaveAnalysis} type="button">
                Save analysis
              </button>
            ) : null}
            {explorerLinks.map((link) => (
              <Link className="ghost-button inline-button" href={link.href} key={link.href}>
                {link.label}
              </Link>
            ))}
          </div>
        </section>

        <VisualInsights result={result} />

        <section className="result-grid">
          <div className="result-column">
            {result.summaries.map((summary, index) => (
              <section className="panel result-panel editorial-card" key={summary.title}>
                <div className="panel-heading">
                  <span className="eyebrow">Summary {index + 1}</span>
                  <h3 className="card-title">{summary.title}</h3>
                </div>
                <SummaryWithCitationLinks
                  body={summary.body}
                  citations={visibleCitations.slice(index, index + 2)}
                  onOpenCitation={handleOpenCitation}
                />
              </section>
            ))}

            {result.insufficiencies.map((item) => (
              <section className="panel result-panel warning-card" key={item.title}>
                <div className="panel-heading">
                  <span className="eyebrow">Insufficient evidence</span>
                  <h3 className="card-title">{item.title}</h3>
                </div>
                <p className="muted-copy">{item.detail}</p>
                <ul className="evidence-list">
                  {item.suggestions.map((suggestion) => (
                    <li key={suggestion}>{suggestion}</li>
                  ))}
                </ul>
              </section>
            ))}

            {result.tables.map((table) => (
              <section className="panel result-panel" key={table.title}>
                <div className="panel-heading">
                  <span className="eyebrow">Table view</span>
                  <h3 className="card-title">{table.title}</h3>
                </div>
                <div className="table-wrap">
                  <table className="result-table">
                    <thead>
                      <tr>
                        {table.columns.map((column) => (
                          <th key={column}>{column}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows.map((row, index) => (
                        <tr key={`${table.title}-${index}`}>
                          {row.map((cell, cellIndex) => (
                            <td key={`${table.title}-${index}-${cellIndex}`}>{cell ?? "-"}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>

          <div className="result-column">
            {result.charts.map((chart) => (
              <section className="panel result-panel" key={chart.title}>
                <div className="panel-heading">
                  <span className="eyebrow">Derived chart</span>
                  <h3 className="card-title">{chart.title}</h3>
                </div>
                <SimpleChart chart={chart} />
              </section>
            ))}

            <section className="panel result-panel clay-panel">
              <div className="panel-heading">
                <span className="eyebrow">Metric references</span>
                <h3 className="card-title">Tracked formulas</h3>
              </div>
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

            <section className="panel result-panel">
              <div className="panel-heading">
                <span className="eyebrow">Evidence thresholds</span>
                <h3 className="card-title">Notes and caveats</h3>
              </div>
              <ul className="evidence-list">
                {result.evidence_notes.map((note) => (
                  <li key={`${note.title}-${note.detail}`}>
                    <strong>{note.title}</strong>: {note.detail}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </section>
      </div>

      {showEvidenceRail ? (
        <aside className="panel evidence-rail">
          <div className="panel-heading">
            <span className="eyebrow">Evidence rail</span>
            <h3 className="card-title">Inline sources</h3>
          </div>
          <p className="muted-copy">
            Highlighted phrases in the summaries open this rail. Database evidence remains primary;
            web context is supplemental only.
          </p>
          <CitationList
            citations={visibleCitations}
            onSelect={setSelectedCitationIndex}
            selectedIndex={selectedCitationIndex}
          />
        </aside>
      ) : null}
    </div>
  );
}
