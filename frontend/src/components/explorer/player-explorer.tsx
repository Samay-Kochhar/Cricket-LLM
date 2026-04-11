"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SimpleChart } from "@/components/charts/simple-chart";
import { fetchApi } from "@/lib/api-client";
import type { PlayerProfileResponse } from "@/lib/api-types";


type PlayerExplorerProps = {
  playerName: string;
};


export function PlayerExplorer({ playerName }: PlayerExplorerProps) {
  const [data, setData] = useState<PlayerProfileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setError(null);
      try {
        const payload = await fetchApi<PlayerProfileResponse>(
          `/api/players/${encodeURIComponent(playerName)}`,
        );
        if (!cancelled) {
          setData(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load player explorer");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [playerName]);

  const chart = data
    ? {
        kind: "chart" as const,
        title: "Runs by year",
        chart_type: "line",
        series: data.trend.map((item) => ({ label: String(item.year), value: item.runs_scored })),
      }
    : null;

  return (
    <main className="explorer-page">
      <section className="panel hero-panel">
        <div className="brand-kicker">CricAtlas Player Explorer</div>
        <h1 className="hero-title">{playerName}</h1>
        <p className="hero-copy">
          Structured ODI evidence for a single batter profile, including high-level output and a
          year-by-year trend view.
        </p>
        <Link className="ghost-button inline-button" href="/">
          Back To Workbench
        </Link>
      </section>

      {error ? <section className="panel result-panel"><p className="muted-copy">{error}</p></section> : null}

      {data ? (
        <div className="explorer-grid">
          <section className="panel result-panel">
            <h2 className="section-title">Batting Snapshot</h2>
            {data.summary ? (
              <div className="stats-grid">
                <div className="stat-card">
                  <span className="stat-label">Runs</span>
                  <strong>{data.summary.runs_scored}</strong>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Balls</span>
                  <strong>{data.summary.balls_faced}</strong>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Strike Rate</span>
                  <strong>{(data.summary.strike_rate ?? 0).toFixed(2)}</strong>
                </div>
                <div className="stat-card">
                  <span className="stat-label">Control %</span>
                  <strong>{(data.summary.control_percentage ?? 0).toFixed(2)}</strong>
                </div>
              </div>
            ) : (
              <p className="muted-copy">No ODI batting summary is available for this player.</p>
            )}
          </section>

          <section className="panel result-panel">
            <h2 className="section-title">Trend View</h2>
            {chart && data.trend.length > 0 ? (
              <SimpleChart chart={chart} />
            ) : (
              <p className="muted-copy">No year trend is available for this player.</p>
            )}
          </section>

          <section className="panel result-panel">
            <h2 className="section-title">Resolution Notes</h2>
            {data.suggestions.length > 0 ? (
              <ul className="evidence-list">
                {data.suggestions.map((suggestion) => (
                  <li key={suggestion}>{suggestion}</li>
                ))}
              </ul>
            ) : (
              <p className="muted-copy">No alias suggestions were needed for this player route.</p>
            )}
          </section>
        </div>
      ) : !error ? (
        <section className="panel result-panel">
          <p className="muted-copy">Loading player explorer...</p>
        </section>
      ) : null}
    </main>
  );
}
