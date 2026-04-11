"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SimpleChart } from "@/components/charts/simple-chart";
import { fetchApi } from "@/lib/api-client";
import type { VenueProfileResponse } from "@/lib/api-types";


type VenueExplorerProps = {
  venueName: string;
};


export function VenueExplorer({ venueName }: VenueExplorerProps) {
  const [data, setData] = useState<VenueProfileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setError(null);
      try {
        const payload = await fetchApi<VenueProfileResponse>(
          `/api/venues/${encodeURIComponent(venueName)}`,
        );
        if (!cancelled) {
          setData(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load venue explorer");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [venueName]);

  const chart = data
    ? {
        kind: "chart" as const,
        title: "Wickets at venue",
        chart_type: "bar",
        series: data.bowling_leaderboard.slice(0, 6).map((item) => ({
          label: item.player_name,
          value: item.wickets,
        })),
      }
    : null;

  return (
    <main className="explorer-page">
      <section className="panel hero-panel">
        <div className="brand-kicker">CricAtlas Venue Explorer</div>
        <h1 className="hero-title">{venueName}</h1>
        <p className="hero-copy">
          Ground-specific ODI bowling evidence for venue leaderboard questions and follow-up
          exploration.
        </p>
        <Link className="ghost-button inline-button" href="/">
          Back To Workbench
        </Link>
      </section>

      {error ? <section className="panel result-panel"><p className="muted-copy">{error}</p></section> : null}

      {data ? (
        <div className="explorer-grid">
          <section className="panel result-panel">
            <h2 className="section-title">Bowling Leaderboard</h2>
            <div className="table-wrap">
              <table className="result-table">
                <thead>
                  <tr>
                    <th>Bowler</th>
                    <th>Deliveries</th>
                    <th>Runs</th>
                    <th>Wickets</th>
                    <th>Economy</th>
                  </tr>
                </thead>
                <tbody>
                  {data.bowling_leaderboard.map((row) => (
                    <tr key={`${row.player_name}-${row.wickets}`}>
                      <td>{row.player_name}</td>
                      <td>{row.deliveries}</td>
                      <td>{row.runs_conceded}</td>
                      <td>{row.wickets}</td>
                      <td>{(row.economy_rate ?? 0).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel result-panel">
            <h2 className="section-title">Top Wicket Takers</h2>
            {chart && data.bowling_leaderboard.length > 0 ? (
              <SimpleChart chart={chart} />
            ) : (
              <p className="muted-copy">No venue leaderboard data is available.</p>
            )}
          </section>
        </div>
      ) : !error ? (
        <section className="panel result-panel">
          <p className="muted-copy">Loading venue explorer...</p>
        </section>
      ) : null}
    </main>
  );
}
