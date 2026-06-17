"use client";

import { CompactDataTable } from "@/components/results/compact-data-table";
import type { EvidenceQueryBlock } from "@/lib/api-types";

export function EvidenceQueryList({ queries }: { queries: EvidenceQueryBlock[] }) {
  if (queries.length === 0) {
    return <p className="muted-copy">No database evidence query was returned for this response.</p>;
  }

  return (
    <div className="evidence-query-list">
      {queries.map((query) => (
        <article className="panel result-panel" key={query.title}>
          <div className="panel-heading">
            <span className="eyebrow">ODI database</span>
            <h3 className="card-title">{query.title}</h3>
          </div>
          <p className="muted-copy">{query.description}</p>
          <div className="metric-list-item">
            <div>
              <strong>SQL shape</strong>
              <p className="muted-copy">
                <code>{query.sql}</code>
              </p>
            </div>
          </div>
          {query.parameters.length > 0 ? (
            <p className="muted-copy">
              Parameters:{" "}
              {query.parameters.map((parameter, index) => (
                <span key={`${query.title}-parameter-${index}`}>
                  {index > 0 ? ", " : null}
                  <code>{parameter ?? "null"}</code>
                </span>
              ))}
            </p>
          ) : null}
          <CompactDataTable table={query.table} />
        </article>
      ))}
    </div>
  );
}
