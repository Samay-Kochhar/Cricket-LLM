"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SimpleChart } from "@/components/charts/simple-chart";
import { fetchApi } from "@/lib/api-client";
import type { VenueLeaderboardRow, VenueProfileResponse } from "@/lib/api-types";

type VenueExplorerProps = { venueName: string };
const formatRate = (value: number | null | undefined) => value == null ? "—" : value.toFixed(2);
const columns: [string, keyof VenueLeaderboardRow][] = [
  ["Bowler", "player_name"], ["Deliveries", "deliveries"], ["Matches", "matches"],
  ["Delivery rows", "delivery_rows"], ["Runs", "runs_conceded"], ["Wickets", "wickets"],
  ["Bowling average", "bowling_average"], ["Economy", "economy_rate"],
  ["Bowling strike rate", "bowling_strike_rate"], ["Dot %", "dot_percentage"],
  ["Boundary % conceded", "boundary_percentage"],
];

export function VenueExplorer({ venueName }: VenueExplorerProps) {
  const [data, setData] = useState<VenueProfileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [request, setRequest] = useState({ venue: venueName, query: "" });
  const [loading, setLoading] = useState(false);
  const [formVersion, setFormVersion] = useState(0);
  const [yearsEnabled, setYearsEnabled] = useState(false);

  useEffect(() => { setRequest({ venue: venueName, query: "" }); }, [venueName]);
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoading(true);
    fetchApi<VenueProfileResponse>(`/api/venues/${encodeURIComponent(request.venue)}${request.query}`)
      .then((payload) => { if (!cancelled) { setData(payload); setYearsEnabled(payload.filters.year_start != null); setFormVersion((value) => value + 1); } })
      .catch((failure) => { if (!cancelled) setError(failure instanceof Error ? failure.message : "Unable to load venue explorer"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [request]);

  const chart = data ? {
    kind: "chart" as const,
    title: `${data.ranking.label} at venue`, chart_type: "bar",
    series: data.bowling_leaderboard.slice(0, 6).map((row) => ({
      label: row.player_name, value: Number(Number(row[data.ranking.field]).toFixed(2)),
    })),
  } : null;

  return (
    <main className="explorer-page">
      <section className="panel hero-panel">
        <div className="brand-kicker">CricAtlas Venue Explorer</div>
        <h1 className="hero-title">{data?.venue_name ?? venueName}</h1>
        <p className="hero-copy">Ground-specific ODI bowling evidence for venue leaderboard questions and follow-up exploration.</p>
        <Link className="ghost-button inline-button" href="/">Back To Workbench</Link>
      </section>
      {error ? <section className="panel result-panel"><p role="alert" className="muted-copy">{error}</p></section> : null}
      {data ? <>
        <section className="panel result-panel">
          <h2 className="section-title">Filter bowlers</h2>
          <form key={`${data.venue_id}-${formVersion}`} onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const query = new URLSearchParams();
            for (const field of ["metric", "phase", "sample_unit", "minimum_sample"]) {
              const value = String(form.get(field) ?? "");
              if (value) query.set(field, value);
            }
            if (form.get("years_enabled")) {
              query.set("year_start", String(form.get("year_start")));
              query.set("year_end", String(form.get("year_end")));
            }
            setRequest({ venue: String(form.get("venue")), query: `?${query}` });
          }}>
            <div className="explorer-filters">
              <label className="matchup-field">Venue<select name="venue" defaultValue={data.venue_name}>{data.venue_options.map((venue) => <option key={venue}>{venue}</option>)}</select></label>
              <label className="matchup-field">Filter by<select name="sample_unit" defaultValue={data.filters.sample_unit}>{Object.entries(data.sample_units).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label className="matchup-field">Minimum number (0 = no minimum)<input name="minimum_sample" type="number" min={0} max={1000000} step={1} defaultValue={data.filters.minimum_sample} required /></label>
              <label className="matchup-field">Rank and chart by<select name="metric" defaultValue={data.filters.metric}>{data.metric_options.map((metric) => <option key={metric.metric} value={metric.metric}>{metric.label}</option>)}</select></label>
              <label className="matchup-field">Phase<select name="phase" defaultValue={data.filters.phase ?? ""}>{Object.entries(data.phase_options).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label className="matchup-field"><input name="years_enabled" type="checkbox" checked={yearsEnabled} onChange={(event) => setYearsEnabled(event.target.checked)} />Filter by year or inclusive year range</label>
              <label className="matchup-field">From year<input name="year_start" disabled={!yearsEnabled} type="number" min={1800} max={2200} step={1} defaultValue={data.filters.year_start ?? 2023} required /></label>
              <label className="matchup-field">Through year<input name="year_end" disabled={!yearsEnabled} type="number" min={1800} max={2200} step={1} defaultValue={data.filters.year_end ?? 2023} required /></label>
            </div>
            <button className="primary-button" disabled={loading} type="submit">Apply filter</button>{" "}
            <button className="ghost-button" disabled={loading} type="button" onClick={() => {
              setRequest({ venue: data.venue_name, query: "" });
            }}>Reset filter</button>
          </form>
          <p className="muted-copy">Active filters: {data.venue_name}; {data.phase_options[data.filters.phase ?? ""]}; {data.filters.year_start == null ? "All years" : `${data.filters.year_start}–${data.filters.year_end}`}; {data.filters.minimum_sample ? `at least ${data.filters.minimum_sample} ${data.sample_units[data.filters.sample_unit].toLowerCase()}` : "no minimum sample"}; top {data.filters.limit} by {data.ranking.label} ({data.ranking.direction}). Deliveries are legal balls.</p>
          <p className="muted-copy">{data.sample_policy}</p>
          {loading ? <p role="status" className="muted-copy">Loading venue explorer...</p> : null}
        </section>
        <div className="explorer-grid venue-leaderboard-grid">
          <section className="panel result-panel">
            <h2 className="section-title">{data.filters.metric === "wickets_taken" ? "Top Wicket Takers" : `${data.ranking.label} leaders`}</h2>
            {chart && data.bowling_leaderboard.length ? <SimpleChart chart={chart} /> : <p className="muted-copy">No bowlers qualify for the selected filters and metric.</p>}
          </section>
          <section className="panel result-panel">
            <h2 className="section-title">Bowling Leaderboard</h2>
            <div className="table-wrap"><table className="result-table">
              <thead><tr>{columns.map(([label]) => <th key={label}>{label}</th>)}</tr></thead>
              <tbody>{data.bowling_leaderboard.map((row) => <tr key={row.player_name}>{columns.map(([label, field], index) => <td key={field}>{index >= 6 ? formatRate(row[field] as number | null) : row[field] ?? "—"}</td>)}</tr>)}</tbody>
            </table></div>
          </section>
        </div>
      </> : !error ? <section className="panel result-panel"><p className="muted-copy">Loading venue explorer...</p></section> : null}
    </main>
  );
}
