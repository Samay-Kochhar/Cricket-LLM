import type { Citation } from "@/lib/api-types";


type CitationListProps = {
  citations: Citation[];
};


export function CitationList({ citations }: CitationListProps) {
  if (citations.length === 0) {
    return <p className="muted-copy">No citations returned for this response.</p>;
  }

  return (
    <div className="citation-list">
      {citations.map((citation) => (
        <article className="citation-card" key={`${citation.source_type}-${citation.locator}-${citation.label}`}>
          <div className="citation-meta">
            <span className="chip">{citation.source_type}</span>
          </div>
          <h4 className="card-title">{citation.label}</h4>
          <p className="muted-copy">{citation.locator}</p>
          {citation.excerpt ? <p className="muted-copy">{citation.excerpt}</p> : null}
        </article>
      ))}
    </div>
  );
}
