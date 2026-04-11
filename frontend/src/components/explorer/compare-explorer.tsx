"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SimpleChart } from "@/components/charts/simple-chart";
import { fetchApi } from "@/lib/api-client";
import type { CompareResponse } from "@/lib/api-types";


type CompareExplorerProps = {
  players: string[];
};


export function CompareExplorer({ players }: CompareExplorerProps) {
  const [data, setData] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setError(null);
      try {
        const params = new URLSearchParams();
        for (const player of players.slice(0, 2)) {
          params.append("player", player);
        }
        const payload = await fetchApi<CompareResponse>(`/api/compare?${params.toString()}`);
        if (!cancelled) {
          setData(payload);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load comparison");
        }
      }
    }

    if (players.length > 0) {
      void load();
    }
    return () => {
      cancelled = true;
    };
  }, [players]);

  const chart = data
    ? {
        kind: "chart" as const,
        title: "Strike rate comparison",
        chart_type: "bar",
        series: data.players.map((player) => ({
          label: player.player_name,
          value: player.strike_rate ?? 0,
        })),
      }
    : null;

  return (
    <main className="explorer-page">
      <section className="panel hero-panel">
        <div className="brand-kicker">CricAtlas Compare Explorer</div>
        <h1 className="hero-title">{players.join(" vs ") || "Comparison"}</h1>
        <p className="hero-copy">
          Side-by-side ODI batting evidence for role comparison questions pulled from the same
          database-backed API used by the workbench.
        </p>
        <Link className="ghost-button inline-button" href="/">
          Back To Workbench
        </Link>
      </section>

      {error ? <section className="panel result-panel"><p className="muted-copy">{error}</p></section> : null}

      {data ? (
        <div className="explorer-grid">
          <section className="panel result-panel">
            <h2 className="section-title">Comparison Table</h2>
            <div className="table-wrap">
              <table className="result-table">
                <thead>
                  <tr>
                    <th>Player</th>
                    <th>Runs</th>
                    <th>Balls</th>
                    <th>Strike Rate</th>
                    <th>Boundary %</th>
                    <th>Control %</th>
                  </tr>
                </thead>
                <tbody>
                  {data.players.map((player) => (
                    <tr key={player.player_name}>
                      <td>{player.player_name}</td>
                      <td>{player.runs_scored}</td>
                      <td>{player.balls_faced}</td>
                      <td>{(player.strike_rate ?? 0).toFixed(2)}</td>
                      <td>{(player.boundary_percentage ?? 0).toFixed(2)}</td>
                      <td>{(player.control_percentage ?? 0).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel result-panel">
            <h2 className="section-title">Strike Rate</h2>
            {chart && data.players.length > 0 ? (
              <SimpleChart chart={chart} />
            ) : (
              <p className="muted-copy">No comparison data is available for this pair.</p>
            )}
          </section>
        </div>
      ) : !error ? (
        <section className="panel result-panel">
          <p className="muted-copy">Loading comparison explorer...</p>
        </section>
      ) : null}
    </main>
  );
}
