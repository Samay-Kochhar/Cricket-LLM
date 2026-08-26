"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { CompactDataTable } from "@/components/results/compact-data-table";
import { VisualInsights } from "@/components/results/visual-insights";
import { postApi } from "@/lib/api-client";
import type { MatchupPageResponse, QueryResponse, TableBlock } from "@/lib/api-types";

type MatchupExplorerProps = {
  initialBatter: string;
  initialBowler: string;
  initialPhase: string;
  initialVenue: string;
  initialYear: string;
};

type MatchupFilters = {
  batter: string;
  bowler: string;
  phase: string;
  venue: string;
  year: string;
};

const STAT_COLUMNS = [
  ["runs", "Runs"],
  ["balls", "Balls"],
  ["dismissals", "Dismissals"],
  ["strike-rate", "Batting Strike Rate"],
  ["dot-ball-rate", "Batter Dot Ball Percentage"],
  ["boundary-rate", "Boundary Percentage"],
  ["false-shot-rate", "False Shot Percentage"],
] as const;

function firstRow(table: TableBlock | undefined) {
  if (!table?.rows[0]) {
    return new Map<string, string | number | null>();
  }
  return new Map(table.columns.map((column, index) => [column, table.rows[0][index]]));
}

function numberFrom(row: Map<string, string | number | null>, column: string) {
  const value = row.get(column);
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function displayValue(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return typeof value === "number" ? value.toLocaleString("en", { maximumFractionDigits: 2 }) : value;
}

function pageSummary(body: string) {
  return body
    .replace(/ The recorded ODI sample contains [^.]+\.$/, "")
    .replace(/ This is a low sample of [^.]+\.$/, "");
}

function currentYearIsValid(year: string) {
  if (!year) {
    return true;
  }
  const parsed = Number(year);
  return Number.isInteger(parsed) && parsed >= 1971 && parsed <= new Date().getFullYear();
}

export function MatchupExplorer({
  initialBatter,
  initialBowler,
  initialPhase,
  initialVenue,
  initialYear,
}: MatchupExplorerProps) {
  const router = useRouter();
  const [filters, setFilters] = useState<MatchupFilters>({
    batter: initialBatter,
    bowler: initialBowler,
    phase: initialPhase,
    venue: initialVenue,
    year: initialYear,
  });
  const [applied, setApplied] = useState(filters);
  const [matchup, setMatchup] = useState<QueryResponse | null>(null);
  const [baseline, setBaseline] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const payload = await postApi<MatchupPageResponse>("/api/matchups", {
          batter: applied.batter,
          bowler: applied.bowler,
          phase: applied.phase,
          year: applied.year ? Number(applied.year) : null,
          venue: applied.venue || null,
        });
        if (!cancelled) {
          setMatchup(payload.matchup);
          setBaseline(payload.baseline);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load this matchup");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [applied]);

  const matchupRow = useMemo(() => firstRow(matchup?.tables[0]), [matchup]);
  const baselineRow = useMemo(() => firstRow(baseline?.tables[0]), [baseline]);
  const balls = numberFrom(matchupRow, "Balls") ?? numberFrom(matchupRow, "Balls Faced");
  const matchupStrikeRate = numberFrom(matchupRow, "Batting Strike Rate");
  const baselineStrikeRate = numberFrom(baselineRow, "Batting Strike Rate");
  const resolvedBatter = typeof matchupRow.get("Batter") === "string" ? String(matchupRow.get("Batter")) : applied.batter;
  const resolvedBowler = typeof matchupRow.get("Bowler") === "string" ? String(matchupRow.get("Bowler")) : applied.bowler;
  const isLowSample =
    (balls !== null && balls < 12) ||
    matchup?.summaries.some((summary) => summary.body.toLowerCase().includes("low sample")) === true;

  function apply(next: MatchupFilters) {
    const normalized = {
      ...next,
      batter: next.batter.trim(),
      bowler: next.bowler.trim(),
      venue: next.venue.trim(),
      year: next.year.trim(),
    };
    setFilters(normalized);
    setApplied(normalized);
    const params = new URLSearchParams({ batter: normalized.batter, bowler: normalized.bowler });
    if (normalized.phase !== "all") params.set("phase", normalized.phase);
    if (normalized.year) params.set("year", normalized.year);
    if (normalized.venue) params.set("venue", normalized.venue);
    router.push(`/matchups?${params.toString()}`, { scroll: false });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (filters.batter.trim() && filters.bowler.trim() && currentYearIsValid(filters.year)) {
      apply(filters);
    }
  }

  return (
    <main className="explorer-page matchup-page">
      <header className="atlas-chat-topbar">
        <div>
          <div className="brand-kicker">CricAtlas</div>
          <h1 className="atlas-brand">Matchups</h1>
          <p className="muted-copy">Ask one practical ODI question: how did this batter perform against this bowler?</p>
        </div>
        <nav className="atlas-nav" aria-label="Primary">
          <Link className="atlas-nav-link" href="/">Atlas</Link>
          <Link className="atlas-nav-link is-active" href="/matchups">Matchups</Link>
          <Link className="atlas-nav-link" href="/workbench">Workbench</Link>
        </nav>
      </header>

      <section className="panel matchup-controls">
        <form onSubmit={handleSubmit}>
          <div className="matchup-player-row">
            <label className="matchup-field">
              <span>Batter</span>
              <input
                aria-label="Batter"
                onChange={(event) => setFilters((current) => ({ ...current, batter: event.target.value }))}
                value={filters.batter}
              />
            </label>
            <button
              aria-label="Swap batter and bowler"
              className="ghost-button matchup-swap"
              onClick={() => setFilters((current) => ({ ...current, batter: current.bowler, bowler: current.batter }))}
              type="button"
            >
              ⇄ Swap
            </button>
            <label className="matchup-field">
              <span>Bowler</span>
              <input
                aria-label="Bowler"
                onChange={(event) => setFilters((current) => ({ ...current, bowler: event.target.value }))}
                value={filters.bowler}
              />
            </label>
          </div>
          <div className="matchup-filter-row">
            <label className="matchup-field">
              <span>Phase</span>
              <select
                aria-label="Phase"
                onChange={(event) => setFilters((current) => ({ ...current, phase: event.target.value }))}
                value={filters.phase}
              >
                <option value="all">All overs</option>
                <option value="powerplay">Powerplay</option>
                <option value="middle">Middle overs</option>
                <option value="death">Death overs</option>
              </select>
            </label>
            <label className="matchup-field">
              <span>Year</span>
              <input
                aria-label="Year"
                inputMode="numeric"
                max={new Date().getFullYear()}
                min="1971"
                onChange={(event) => setFilters((current) => ({ ...current, year: event.target.value }))}
                placeholder="All years"
                type="number"
                value={filters.year}
              />
            </label>
            <label className="matchup-field matchup-venue-field">
              <span>Venue</span>
              <input
                aria-label="Venue"
                onChange={(event) => setFilters((current) => ({ ...current, venue: event.target.value }))}
                placeholder="All venues"
                value={filters.venue}
              />
            </label>
            <button
              className="primary-button matchup-run-button"
              disabled={!filters.batter.trim() || !filters.bowler.trim() || !currentYearIsValid(filters.year) || isLoading}
              type="submit"
            >
              {isLoading ? "Checking…" : "Show matchup"}
            </button>
          </div>
          {!currentYearIsValid(filters.year) ? <p className="error-copy">Enter an ODI year from 1971 to today.</p> : null}
        </form>
      </section>

      <section className="panel hero-panel matchup-answer">
        <span className="eyebrow">ODI head to head</span>
        <h2 className="hero-title">{resolvedBatter} vs {resolvedBowler}</h2>
        {isLoading ? <p className="hero-copy">Checking the ODI ball-by-ball evidence…</p> : null}
        {!isLoading && matchup?.summaries[0] ? <p className="hero-copy">{pageSummary(matchup.summaries[0].body)}</p> : null}
        {error ? <p className="error-copy">{error}</p> : null}
        {!isLoading && !error && matchup?.status !== "supported" ? (
          <p className="muted-copy">
            No recorded ODI balls were found between {applied.batter} and {applied.bowler} for these filters. Try another bowler or broaden the filters.
          </p>
        ) : null}
      </section>

      {!isLoading && matchup?.status === "supported" && matchup.tables[0] ? (
        <>
          <section className="matchup-stat-grid" aria-label="Matchup statistics">
            {STAT_COLUMNS.map(([id, column]) => (
              <article className="panel stat-card matchup-stat" data-testid={`matchup-stat-${id}`} key={id}>
                <span className="stat-label">{column.replace("Batter ", "").replace(" Percentage", " %")}</span>
                <strong>{displayValue(matchupRow.get(column))}</strong>
              </article>
            ))}
          </section>

          {matchupStrikeRate !== null && baselineStrikeRate !== null ? (
            <section className="panel baseline-card">
              <div>
                <span className="eyebrow">Compared with the batter's normal ODI rate</span>
                <h3 className="section-title">{matchupStrikeRate.toFixed(2)} vs {baselineStrikeRate.toFixed(2)}</h3>
              </div>
              <p className="muted-copy">
                Against {resolvedBowler}, {resolvedBatter}'s strike rate is {Math.abs(matchupStrikeRate - baselineStrikeRate).toFixed(2)} points {matchupStrikeRate >= baselineStrikeRate ? "higher" : "lower"} than the matching overall baseline.
              </p>
            </section>
          ) : null}

          {matchup.visuals?.pitch_map && !isLowSample ? (
            <VisualInsights result={matchup} />
          ) : (
            <section className="panel result-panel">
              <span className="eyebrow">Pitch map</span>
              <h3 className="card-title">No pitch map shown</h3>
              <p className="muted-copy">This sample does not have enough reliable line-and-length coverage for a useful map.</p>
            </section>
          )}

          <section className="panel result-panel">
            <div className="panel-heading">
              <span className="eyebrow">Full answer</span>
              <h3 className="card-title">Matchup evidence</h3>
            </div>
            <CompactDataTable table={matchup.tables[0]} />
          </section>

          {isLowSample ? (
            <p className="matchup-low-sample-note">
              Small sample: only {displayValue(balls)} recorded balls, so treat these numbers as descriptive.
            </p>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
