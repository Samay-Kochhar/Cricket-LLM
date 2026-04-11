"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ChatResponseSections } from "@/components/results/chat-response-sections";
import { useWorkbenchSearch } from "@/hooks/use-workbench-search";
import type { TeamSquadPlayer } from "@/lib/api-types";
import { loadWorkbenchContext, savePendingAtlasPrompt, saveWorkbenchContext } from "@/lib/workbench-context-store";

function AskAtlasWidget({
  prompt,
}: {
  prompt: string | null;
}) {
  const router = useRouter();

  if (!prompt) {
    return null;
  }

  return (
    <button
      className="primary-button workbench-atlas-widget"
      onClick={() => {
        savePendingAtlasPrompt(prompt);
        router.push("/");
      }}
      type="button"
    >
      Ask Atlas
    </button>
  );
}

function SquadList({ players }: { players: TeamSquadPlayer[] }) {
  return (
    <div className="workbench-squad-list">
      {players.map((player) => (
        <article className="panel workbench-squad-card" key={player.player_name}>
          <strong>{player.player_name}</strong>
          <p className="muted-copy">{player.role_summary}</p>
        </article>
      ))}
    </div>
  );
}

export default function WorkbenchPage() {
  const [query, setQuery] = useState("");
  const [yearPromptTeam, setYearPromptTeam] = useState<string | null>(null);
  const [yearOptions, setYearOptions] = useState<number[]>([]);
  const initializedRef = useRef(false);
  const { error, isLoading, result, search } = useWorkbenchSearch();

  useEffect(() => {
    if (initializedRef.current) {
      return;
    }
    initializedRef.current = true;
    const context = loadWorkbenchContext();
    if (!context) {
      return;
    }
    const initialQuery = context.subject || context.query;
    if (initialQuery) {
      setQuery(initialQuery);
      void search(initialQuery).catch(() => undefined);
    }
  }, [search]);

  useEffect(() => {
    if (result?.kind === "team_year_required") {
      setYearPromptTeam(result.team_name);
      setYearOptions(result.available_years);
      return;
    }
    setYearPromptTeam(null);
    setYearOptions([]);
  }, [result]);

  const atlasPrompt = useMemo(() => {
    if (!result) {
      return null;
    }
    if (result.kind === "player_result") {
      return `Tell me more about ${result.player_name} in ODIs.`;
    }
    if (result.kind === "team_squad") {
      return `Which player is most important for ${result.team_name} in ${result.year}?`;
    }
    return null;
  }, [result]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!query.trim()) {
      return;
    }
    saveWorkbenchContext({ source: "workbench", query });
    await search(query);
  }

  async function handleYearSelect(year: number) {
    if (!yearPromptTeam) {
      return;
    }
    const nextQuery = `${yearPromptTeam} ${year}`;
    setQuery(nextQuery);
    await search(nextQuery);
  }

  return (
    <main className="workbench-page">
      <header className="atlas-chat-topbar">
        <div>
          <div className="brand-kicker">CricAtlas</div>
          <h1 className="atlas-brand">Workbench</h1>
          <p className="muted-copy">
            Search by player, team, country, or comparison intent. Atlas context can hand off here asynchronously.
          </p>
        </div>
        <nav className="atlas-nav" aria-label="Primary">
          <Link className="atlas-nav-link" href="/">
            Atlas
          </Link>
          <Link className="atlas-nav-link is-active" href="/workbench">
            Workbench
          </Link>
        </nav>
      </header>

      <section className="panel workbench-hero">
        <span className="eyebrow">AI-powered workbench search</span>
        <h2 className="atlas-headline">Search naturally. Resolve into ODI evidence.</h2>
        <p className="muted-copy">
          Try `Virat Kohli`, `India 2019`, or `death over strike rate of Hardik Pandya`.
        </p>
        <form className="workbench-search-form" onSubmit={handleSubmit}>
          <input
            className="workbench-search-input"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search players, teams, countries, or ODI questions..."
            value={query}
          />
          <button className="primary-button" disabled={!query.trim() || isLoading} type="submit">
            {isLoading ? "Searching..." : "Search"}
          </button>
        </form>
      </section>

      {yearPromptTeam ? (
        <section className="panel workbench-year-modal">
          <div className="panel-heading">
            <span className="eyebrow">Year needed</span>
            <h3 className="section-title">{yearPromptTeam}</h3>
          </div>
          <p className="muted-copy">
            Workbench resolved a team or country. Pick a year to load the squad and continue.
          </p>
          <div className="chip-row">
            {yearOptions.map((year) => (
              <button className="suggestion-chip" key={year} onClick={() => void handleYearSelect(year)} type="button">
                {year}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {error ? (
        <section className="panel result-panel">
          <p className="muted-copy chat-error">{error}</p>
        </section>
      ) : null}

      {result?.kind === "player_result" ? (
        <section className="workbench-grid">
          <article className="panel workbench-card">
            <span className="eyebrow">Resolved player</span>
            <h3 className="section-title">{result.player_name}</h3>
            <p className="muted-copy">{result.role_summary}</p>
          </article>
          <ChatResponseSections result={result.query_response} />
          <details className="chat-details">
            <summary>Search trace</summary>
            <div className="chat-details-body">
              <ul className="evidence-list">
                {result.trace.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </details>
        </section>
      ) : null}

      {result?.kind === "team_squad" ? (
        <section className="workbench-grid">
          <article className="panel workbench-card">
            <span className="eyebrow">Resolved squad</span>
            <h3 className="section-title">
              {result.team_name} {result.year}
            </h3>
            <p className="muted-copy">
              Role summaries are derived from ODI batting hand and bowling style fields in the dataset.
            </p>
          </article>
          <SquadList players={result.players} />
          <details className="chat-details">
            <summary>Search trace</summary>
            <div className="chat-details-body">
              <ul className="evidence-list">
                {result.trace.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </details>
        </section>
      ) : null}

      {result?.kind === "unsupported" ? (
        <section className="panel result-panel">
          <p className="muted-copy">{result.message}</p>
        </section>
      ) : null}

      <AskAtlasWidget prompt={atlasPrompt} />
    </main>
  );
}
