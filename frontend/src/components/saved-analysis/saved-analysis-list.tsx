"use client";

import Link from "next/link";

import type { SavedAnalysis } from "@/lib/saved-analysis-store";


type SavedAnalysisListProps = {
  items: SavedAnalysis[];
};


export function SavedAnalysisList({ items }: SavedAnalysisListProps) {
  if (items.length === 0) {
    return <p className="muted-copy">No saved explorer cards yet.</p>;
  }

  return (
    <div className="saved-analysis-list">
      {items.map((item) => (
        <article className="saved-analysis-card" key={item.id}>
          <div className="saved-analysis-header">
            <span className="chip">{item.queryClass}</span>
            <span className="chip">{item.status}</span>
          </div>
          <h3 className="card-title">{item.title}</h3>
          <p className="muted-copy">{item.question}</p>
          <div className="chip-row">
            {item.entities.map((entity) => (
              <span className="chip" key={`${item.id}-${entity}`}>
                {entity}
              </span>
            ))}
          </div>
          <div className="saved-analysis-footer">
            <span className="session-meta">
              Saved {new Date(item.updatedAt).toLocaleString()}
            </span>
            {item.href ? (
              <Link className="ghost-button inline-button" href={item.href}>
                Open
              </Link>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  );
}
