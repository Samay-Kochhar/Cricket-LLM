import Link from "next/link";


const trendRows = [
  { label: "Virat Kohli", value: "98.4 SR", tone: "warm" },
  { label: "Steven Smith", value: "85.1 SR", tone: "cool" },
  { label: "Control Rate", value: "80.2%", tone: "neutral" },
];

const citations = [
  "analytics.deliveries_v1",
  "analytics.player_year_batting",
  "https://example.com/context-source",
];

const radarAxes = [
  { label: "Control", value: 82 },
  { label: "Boundary", value: 74 },
  { label: "Pace", value: 88 },
  { label: "Spin", value: 71 },
  { label: "Death", value: 66 },
  { label: "Chase", value: 91 },
];

function buildRadarPolygon(points: typeof radarAxes, radius: number, center: number) {
  return points
    .map((point, index) => {
      const angle = (-Math.PI / 2) + (index * 2 * Math.PI) / points.length;
      const scaledRadius = (point.value / 100) * radius;
      const x = center + Math.cos(angle) * scaledRadius;
      const y = center + Math.sin(angle) * scaledRadius;
      return `${x},${y}`;
    })
    .join(" ");
}

function buildRadarAxisPoint(index: number, total: number, radius: number, center: number) {
  const angle = (-Math.PI / 2) + (index * 2 * Math.PI) / total;
  return {
    x: center + Math.cos(angle) * radius,
    y: center + Math.sin(angle) * radius,
  };
}


export default function MockupPage() {
  const radarCenter = 120;
  const radarRadius = 82;
  const polygon = buildRadarPolygon(radarAxes, radarRadius, radarCenter);

  return (
    <main className="mockup-page">
      <section className="mockup-shell">
        <aside className="mockup-sidebar panel">
          <div className="brand-kicker">CricAtlas Concept</div>
          <h1 className="mockup-brand">CricAtlas</h1>
          <p className="muted-copy">
            ODI intelligence workspace with database-first evidence, cited context, and structured
            analyst views.
          </p>

          <div className="mockup-nav">
            <button className="mockup-nav-item is-active" type="button">
              Analyst Chat
            </button>
            <button className="mockup-nav-item" type="button">
              Player Explorer
            </button>
            <button className="mockup-nav-item" type="button">
              Venue Atlas
            </button>
            <button className="mockup-nav-item" type="button">
              Saved Cards
            </button>
          </div>

          <div className="mockup-session-card">
            <span className="session-title">India vs Australia Prep</span>
            <span className="session-meta">8 evidence cards saved</span>
          </div>
          <div className="mockup-session-card">
            <span className="session-title">Powerplay Role Comparison</span>
            <span className="session-meta">Updated 12 mins ago</span>
          </div>
        </aside>

        <section className="mockup-main">
          <section className="panel mockup-hero">
            <div>
              <div className="brand-kicker">ODI-only, evidence-first</div>
              <h2 className="mockup-title">Hybrid analyst workspace, not a generic cricket chatbot</h2>
              <p className="hero-copy">
                Chat to ask the question, then move directly into structured comparison, trend, and
                venue views without losing the evidence trail.
              </p>
            </div>
            <div className="chip-row">
              <span className="chip">DuckDB truth layer</span>
              <span className="chip">Gemini-grounded context</span>
              <span className="chip">Phone + laptop</span>
            </div>
          </section>

          <div className="mockup-grid">
            <section className="panel mockup-query">
              <div className="mockup-query-header">
                <div>
                  <h3 className="section-title">Question Workspace</h3>
                  <p className="muted-copy">
                    Compare ODI roles, weaknesses, venue leaders, and year-by-year trends.
                  </p>
                </div>
                <span className="chip">role_comparison</span>
              </div>

              <div className="mockup-composer">
                <p className="mockup-prompt">
                  What is the better ODI use-case for Virat Kohli and Steven Smith, and which one
                  gives more control against quality pace attacks?
                </p>
                <div className="action-row">
                  <button className="primary-button inline-button" type="button">
                    Run Analysis
                  </button>
                  <button className="ghost-button inline-button" type="button">
                    Save Card
                  </button>
                </div>
              </div>

              <div className="mockup-suggestions">
                <span className="mockup-suggestion">Compare by year split</span>
                <span className="mockup-suggestion">Open player explorer</span>
                <span className="mockup-suggestion">Check venue effect</span>
              </div>
            </section>

            <section className="panel mockup-results">
              <div className="mockup-results-header">
                <div className="brand-kicker">Supported Response</div>
                <h3 className="section-title">Evidence Workspace</h3>
              </div>

              <div className="mockup-summary">
                Virat Kohli leads strike rate and scoring volume, while Steven Smith maintains a
                steadier control profile in lower-risk ODI phases.
              </div>

              <div className="mockup-stats">
                {trendRows.map((row) => (
                  <div className={`mockup-stat tone-${row.tone}`} key={row.label}>
                    <span className="stat-label">{row.label}</span>
                    <strong>{row.value}</strong>
                  </div>
                ))}
              </div>

              <div className="mockup-chart">
                <div className="mockup-chart-row">
                  <span>Virat Kohli</span>
                  <div className="chart-bar-track">
                    <div className="chart-bar-fill" style={{ width: "78%" }} />
                  </div>
                  <span>98.4</span>
                </div>
                <div className="mockup-chart-row">
                  <span>Steven Smith</span>
                  <div className="chart-bar-track">
                    <div className="chart-bar-fill alt" style={{ width: "67%" }} />
                  </div>
                  <span>85.1</span>
                </div>
              </div>
            </section>

            <section className="panel mockup-sidepanel">
              <h3 className="section-title">Insight Rail</h3>
              <div className="mockup-side-section">
                <span className="brand-kicker">Role Radar</span>
                <div className="mockup-radar">
                  <svg viewBox="0 0 240 240" aria-label="Role radar">
                    {[0.25, 0.5, 0.75, 1].map((scale) => (
                      <polygon
                        className="mockup-radar-ring"
                        key={scale}
                        points={radarAxes
                          .map((_, index) => {
                            const point = buildRadarAxisPoint(
                              index,
                              radarAxes.length,
                              radarRadius * scale,
                              radarCenter,
                            );
                            return `${point.x},${point.y}`;
                          })
                          .join(" ")}
                      />
                    ))}
                    {radarAxes.map((axis, index) => {
                      const point = buildRadarAxisPoint(index, radarAxes.length, radarRadius, radarCenter);
                      const labelPoint = buildRadarAxisPoint(index, radarAxes.length, radarRadius + 22, radarCenter);
                      return (
                        <g key={axis.label}>
                          <line
                            className="mockup-radar-axis"
                            x1={radarCenter}
                            y1={radarCenter}
                            x2={point.x}
                            y2={point.y}
                          />
                          <text
                            className="mockup-radar-label"
                            x={labelPoint.x}
                            y={labelPoint.y}
                            textAnchor="middle"
                          >
                            {axis.label}
                          </text>
                        </g>
                      );
                    })}
                    <polygon className="mockup-radar-shape" points={polygon} />
                  </svg>
                </div>
              </div>
              <div className="mockup-side-section">
                <span className="brand-kicker">Metrics Used</span>
                <ul className="evidence-list">
                  <li>Runs scored</li>
                  <li>Batting strike rate</li>
                  <li>Control percentage</li>
                  <li>Boundary percentage</li>
                </ul>
              </div>
              <div className="mockup-side-section">
                <span className="brand-kicker">Citations</span>
                <ul className="evidence-list">
                  {citations.map((citation) => (
                    <li key={citation}>{citation}</li>
                  ))}
                </ul>
              </div>
            </section>
          </div>

          <section className="panel mockup-footer-strip">
            <span className="brand-kicker">Structured Views</span>
            <div className="mockup-footer-links">
              <Link href="/">Workbench</Link>
              <Link href="/players/Virat%20Kohli">Player Explorer</Link>
              <Link href="/compare?player=Virat%20Kohli&player=Steven%20Smith">Comparison</Link>
              <Link href="/venues/M%20Chinnaswamy%20Stadium">Venue Atlas</Link>
            </div>
          </section>
        </section>
      </section>
    </main>
  );
}
