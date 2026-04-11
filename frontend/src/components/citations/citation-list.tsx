import type { Citation } from "@/lib/api-types";


type CitationListProps = {
  citations: Citation[];
  onSelect?: (index: number) => void;
  selectedIndex?: number | null;
};


export function CitationList({ citations, onSelect, selectedIndex = null }: CitationListProps) {
  if (citations.length === 0) {
    return <p className="muted-copy">No citations returned for this response.</p>;
  }

  return (
    <div className="citation-list">
      {citations.map((citation, index) => (
        <article
          className="citation-card"
          data-active={selectedIndex === index}
          key={`${citation.source_type}-${citation.locator}-${citation.label}`}
        >
          <div className="citation-meta">
            <span className="chip">{citation.source_type}</span>
            {onSelect ? (
              <button className="ghost-button citation-open" onClick={() => onSelect(index)} type="button">
                Open
              </button>
            ) : null}
          </div>
          <h4 className="card-title">{citation.label}</h4>
          <p className="muted-copy">{citation.locator}</p>
          {citation.excerpt ? <p className="muted-copy">{citation.excerpt}</p> : null}
        </article>
      ))}
    </div>
  );
}
