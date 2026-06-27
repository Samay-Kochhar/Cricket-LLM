"use client";

import { type SavedSession } from "@/lib/local-session-store";


type SessionListProps = {
  activeSessionId: string | null;
  onDeleteSession?: (sessionId: string) => void;
  onSelectSession: (sessionId: string) => void;
  sessions: SavedSession[];
};


export function SessionList({ activeSessionId, onDeleteSession, onSelectSession, sessions }: SessionListProps) {
  if (sessions.length === 0) {
    return <p className="muted-copy">No local sessions yet.</p>;
  }

  return (
    <div className="session-list">
      {sessions.map((session) => (
        <div
          className="session-item"
          data-active={session.id === activeSessionId}
          key={session.id}
        >
          <button className="session-select" onClick={() => onSelectSession(session.id)} type="button">
            <span className="session-title">{session.title}</span>
            <span className="session-meta">
              Updated {new Date(session.updatedAt).toLocaleString()}
            </span>
          </button>
          {onDeleteSession ? (
            <button
              aria-label={`Delete ${session.title}`}
              className="session-delete"
              onClick={() => onDeleteSession(session.id)}
              title="Delete thread"
              type="button"
            >
              ×
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
