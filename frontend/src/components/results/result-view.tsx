import { CitationList } from "@/components/citations/citation-list";
import { SimpleChart } from "@/components/charts/simple-chart";
import type { QueryResponse } from "@/lib/api-types";


type ResultViewProps = {
  error: string | null;
  isLoading: boolean;
  result: QueryResponse | null;
};


export function ResultView({ error, isLoading, result }: ResultViewProps) {
  if (isLoading) {
    return <p className="muted-copy">Running ODI analysis...</p>;
  }

  if (error) {
    return <p className="muted-copy">Query error: {error}</p>;
  }

  if (!result) {
    return <p className="muted-copy">Submit a question to inspect the structured ODI evidence view.</p>;
  }

  return (
    <div className="result-stack">
      <section className="panel result-panel">
        <div className="brand-kicker">{result.status}</div>
        <h2 className="section-title">Interpretation</h2>
        <p className="muted-copy">{result.interpretation.original_question}</p>
        <div className="chip-row">
          <span className="chip">{result.interpretation.query_class}</span>
          {result.interpretation.entities.map((entity) => (
            <span className="chip" key={entity}>
              {entity}
            </span>
          ))}
        </div>
      </section>

      {result.summaries.map((summary) => (
        <section className="panel result-panel" key={summary.title}>
          <h3 className="card-title">{summary.title}</h3>
          <p className="muted-copy">{summary.body}</p>
        </section>
      ))}

      {result.insufficiencies.map((item) => (
        <section className="panel result-panel" key={item.title}>
          <h3 className="card-title">{item.title}</h3>
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
          <h3 className="card-title">{table.title}</h3>
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

      {result.charts.map((chart) => (
        <section className="panel result-panel" key={chart.title}>
          <SimpleChart chart={chart} />
        </section>
      ))}

      <section className="panel result-panel">
        <h3 className="card-title">Metric References</h3>
        <ul className="evidence-list">
          {result.metric_references.map((metric) => (
            <li key={metric.metric_id}>
              <strong>{metric.label}</strong>: <code>{metric.formula}</code>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel result-panel">
        <h3 className="card-title">Evidence Notes</h3>
        <ul className="evidence-list">
          {result.evidence_notes.map((note) => (
            <li key={`${note.title}-${note.detail}`}>
              <strong>{note.title}</strong>: {note.detail}
            </li>
          ))}
        </ul>
      </section>

      <section className="panel result-panel">
        <h3 className="card-title">Citations</h3>
        <CitationList citations={result.citations} />
      </section>
    </div>
  );
}
