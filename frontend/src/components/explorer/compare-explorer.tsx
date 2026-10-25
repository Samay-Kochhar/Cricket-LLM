"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { SimpleChart } from "@/components/charts/simple-chart";
import { fetchApi } from "@/lib/api-client";
import type { CompareResponse, VenueLeaderboardRow } from "@/lib/api-types";

const battingColumns: [string, keyof VenueLeaderboardRow][] = [
  ["Player", "player_name"], ["Runs", "runs_scored"], ["Balls", "balls_faced"], ["Dismissals", "dismissals"],
  ["Matches", "matches"], ["Control balls", "control_balls"], ["Batting average", "average"],
  ["Strike Rate", "strike_rate"], ["Boundary %", "boundary_percentage"], ["Control %", "control_percentage"], ["Dot %", "dot_percentage"],
];
const bowlingColumns: typeof battingColumns = [
  ["Player", "player_name"], ["Legal balls", "deliveries"], ["Runs conceded", "runs_conceded"], ["Wickets", "wickets"],
  ["Matches", "matches"], ["Delivery rows", "delivery_rows"], ["Bowling average", "bowling_average"],
  ["Economy", "economy_rate"], ["Bowling strike rate", "bowling_strike_rate"], ["Dot %", "dot_percentage"], ["Boundary % conceded", "boundary_percentage"],
];
export function CompareExplorer({ players }: { players: string[] }) {
  const [data, setData] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState("batting");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [yearsEnabled, setYearsEnabled] = useState(false);
  const [version, setVersion] = useState(0);
  const playerKey = players.slice(0, 2).join("\u0000");
  useEffect(() => {
    let cancelled = false;
    setError(null); setLoading(true);
    const params = new URLSearchParams(query);
    for (const player of playerKey.split("\u0000")) params.append("player", player);
    fetchApi<CompareResponse>(`/api/compare?${params}`)
      .then(payload => { if (!cancelled) { setData(payload); setSelectedMode(payload.mode ?? "batting"); setYearsEnabled(payload.filters.year_start != null); setVersion(v => v + 1); } })
      .catch(failure => { if (!cancelled) { setSelectedMode(data?.mode ?? "batting"); setError(failure instanceof Error ? failure.message : "Unable to load comparison"); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [playerKey, query]);
  const columns = data?.mode === "bowling" ? bowlingColumns : battingColumns;
  const chart = data ? { kind: "chart" as const, title: `${data.ranking.label} comparison`, chart_type: "bar",
    series: data.players.filter(p => p[data.ranking.field] != null).map(p => ({ label: p.player_name, value: Number(Number(p[data.ranking.field]).toFixed(2)) })) } : null;
  return <main className="explorer-page">
    <section className="panel hero-panel">
      <div className="brand-kicker">CricAtlas Compare Explorer</div>
      <h1 className="hero-title">{players.join(" vs ") || "Comparison"}</h1>
      <p className="hero-copy">Side-by-side ODI batting and bowling evidence for role comparison questions pulled from the same database-backed API used by the workbench.</p>
      <Link className="ghost-button inline-button" href="/">Back To Workbench</Link>
    </section>
    {error ? <section className="panel result-panel"><p role="alert" className="muted-copy">{error}</p></section> : null}
    {data ? <>
      <section className="panel result-panel">
        <fieldset className="explorer-mode"><legend>Mode</legend>{["batting", "bowling"].map(mode => <label key={mode}>
          <input type="radio" name="compare-mode" value={mode} checked={selectedMode === mode} disabled={loading} onChange={() => {
                setSelectedMode(mode);
            const params = new URLSearchParams({ mode });
            if (data.filters.phase) params.set("phase", data.filters.phase);
            if (data.filters.venue) params.set("venue", data.filters.venue);
            if (data.filters.year_start != null) { params.set("year_start", String(data.filters.year_start)); params.set("year_end", String(data.filters.year_end)); }
            setQuery(params.toString());
          }} />{mode === "batting" ? "Batting" : "Bowling"}
        </label>)}</fieldset>
        <h2 className="section-title">Comparison context</h2>
        <form key={version} onSubmit={event => {
          event.preventDefault(); const form = new FormData(event.currentTarget);
          const params = new URLSearchParams({ mode: data.mode });
          for (const key of ["metric", "phase", "venue"]) { const value = String(form.get(key) ?? ""); if (value) params.set(key, value); }
          if (form.get("years_enabled")) { params.set("year_start", String(form.get("year_start"))); params.set("year_end", String(form.get("year_end"))); }
          setQuery(params.toString());
        }}><div className="explorer-filters">
          <label className="matchup-field">Phase<select name="phase" defaultValue={data.filters.phase ?? ""}>{Object.entries(data.phase_options).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
          <label className="matchup-field">Venue<select name="venue" defaultValue={data.filters.venue ?? ""}><option value="">All venues</option>{data.venue_options.map(v => <option key={v}>{v}</option>)}</select></label>
          <label className="matchup-field">Chart metric<select name="metric" defaultValue={data.ranking.metric}>{data.metric_options.map(m => <option key={m.metric} value={m.metric}>{m.label}</option>)}</select></label>
          <label className="matchup-field"><input type="checkbox" name="years_enabled" checked={yearsEnabled} onChange={e => setYearsEnabled(e.target.checked)} />Filter by year or inclusive year range</label>
          <label className="matchup-field">From year<input type="number" name="year_start" min={1800} max={2200} defaultValue={data.filters.year_start ?? 2023} disabled={!yearsEnabled} required /></label>
          <label className="matchup-field">Through year<input type="number" name="year_end" min={1800} max={2200} defaultValue={data.filters.year_end ?? 2023} disabled={!yearsEnabled} required /></label>
        </div><button className="primary-button" type="submit" disabled={loading}>Apply filter</button>{" "}
          <button className="ghost-button" type="button" disabled={loading} onClick={() => setQuery(`mode=${data.mode}`)}>Reset filter</button>
        </form>
        <p className="muted-copy">Active filters: {data.mode}; {data.phase_options[data.filters.phase ?? ""]}; {data.filters.year_start == null ? "All years" : `${data.filters.year_start}–${data.filters.year_end}`}; {data.filters.venue ?? "All venues"}. {data.ranking.preference}.</p>
        <p className="muted-copy">{data.sample_policy}</p>
        {loading ? <p role="status" className="muted-copy">Loading comparison...</p> : null}
        {data.players.filter(p => p.small_sample).map(p => <p key={p.player_name} className="muted-copy">{p.player_name}: small sample (fewer than 24 balls).</p>)}
      </section>
      <div className="explorer-grid"><section className="panel result-panel">
        <h2 className="section-title">Comparison Table</h2>
        <div className="table-wrap"><table className="result-table"><thead><tr>{columns.map(([label]) => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{data.players.map(p => <tr key={p.player_name}>{columns.map(([label, field], i) => <td key={label}>{p[field] == null ? "—" : i >= 6 ? Number(p[field]).toFixed(2) : String(p[field])}</td>)}</tr>)}</tbody>
        </table></div>
      </section><section className="panel result-panel">
        <h2 className="section-title">{data.ranking.label}</h2>
        {chart?.series.length ? <SimpleChart chart={chart} /> : <p className="muted-copy">The selected metric is unavailable for both players.</p>}
        {data.players.filter(p => p[data.ranking.field] == null).map(p => <p className="muted-copy" key={p.player_name}>{p.player_name}: {data.ranking.label} unavailable.</p>)}
      </section></div>
    </> : !error ? <section className="panel result-panel"><p className="muted-copy">Loading comparison explorer...</p></section> : null}
  </main>;
}
