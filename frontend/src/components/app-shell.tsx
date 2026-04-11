"use client";

import { useEffect, useMemo, useState } from "react";

import { ChatEntry } from "@/components/chat-entry";
import { ResultView } from "@/components/results/result-view";
import { SessionList } from "@/components/session-list";
import { useQueryAnalysis } from "@/hooks/use-query";
import {
  createSession,
  loadSessions,
  saveSessions,
  type SavedSession,
} from "@/lib/local-session-store";


export function AppShell() {
  const [sessions, setSessions] = useState<SavedSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const { error, isLoading, result, runQuery } = useQueryAnalysis();

  useEffect(() => {
    const restored = loadSessions();
    if (restored.length > 0) {
      setSessions(restored);
      setActiveSessionId(restored[0].id);
      return;
    }

    const seeded = [createSession("ODI analyst session")];
    setSessions(seeded);
    setActiveSessionId(seeded[0].id);
    saveSessions(seeded);
  }, []);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? null,
    [activeSessionId, sessions],
  );

  function handleNewSession() {
    const next = [createSession(), ...sessions];
    setSessions(next);
    setActiveSessionId(next[0].id);
    saveSessions(next);
  }

  function handleSelectSession(sessionId: string) {
    setActiveSessionId(sessionId);
  }

  async function handleSubmitQuestion(question: string) {
    if (!activeSession) {
      return;
    }

    const nextSessions = sessions.map((session) =>
      session.id === activeSession.id
        ? {
            ...session,
            title: session.title === "Untitled Session" ? question.slice(0, 48) : session.title,
            updatedAt: new Date().toISOString(),
            lastPrompt: question,
          }
        : session,
    );
    setSessions(nextSessions);
    saveSessions(nextSessions);
    await runQuery(question);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="toolbar">
          <div>
            <div className="brand-kicker">Wave 1</div>
            <h2 className="section-title">Local Sessions</h2>
          </div>
          <button className="ghost-button" onClick={handleNewSession} type="button">
            New
          </button>
        </div>
        <SessionList
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          sessions={sessions}
        />
      </aside>

      <section className="content">
        <section className="panel hero-panel">
          <div className="brand-kicker">ODI-only, evidence-first</div>
          <h1 className="hero-title">ODI Analyst Workbench</h1>
          <p className="hero-copy">
            Ask ODI cricket questions in plain language, then inspect the evidence, filters, and
            visuals behind the answer. This shell stores sessions locally in your browser and is
            ready for the Wave 2 API wiring.
          </p>
          <div className="chip-row">
            <span className="chip">Database-first truth</span>
            <span className="chip">Gemini-grounded context later</span>
            <span className="chip">Phone + laptop layout</span>
          </div>
        </section>

        <div className="workspace-grid">
          <section className="panel workspace-panel">
            <h2 className="section-title">Question Workspace</h2>
            <ChatEntry
              defaultValue={activeSession?.lastPrompt ?? ""}
              isLoading={isLoading}
              onSubmit={handleSubmitQuestion}
            />
          </section>

          <section className="panel evidence-panel">
            <h2 className="section-title">Evidence Workspace</h2>
            {activeSession ? (
              <>
                <p className="muted-copy">
                  <strong>Title:</strong> {activeSession.title}
                </p>
                <p className="muted-copy">
                  <strong>Last prompt:</strong>{" "}
                  {activeSession.lastPrompt ?? "No ODI question saved yet."}
                </p>
              </>
            ) : (
              <p className="muted-copy">Create a session to begin.</p>
            )}

            <div style={{ marginTop: 24 }}>
              <ResultView error={error} isLoading={isLoading} result={result} />
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
