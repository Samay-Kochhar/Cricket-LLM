"use client";

import { type SavedSession } from "@/lib/local-session-store";


type SessionListProps = {
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  sessions: SavedSession[];
};


export function SessionList({ activeSessionId, onSelectSession, sessions }: SessionListProps) {
  if (sessions.length === 0) {
    return <p className="muted-copy">No local sessions yet.</p>;
  }

  return (
    <div className="session-list">
      {sessions.map((session) => (
        <button
          className="session-item"
          data-active={session.id === activeSessionId}
          key={session.id}
          onClick={() => onSelectSession(session.id)}
          type="button"
        >
          <span className="session-title">{session.title}</span>
          <span className="session-meta">
            Updated {new Date(session.updatedAt).toLocaleString()}
          </span>
        </button>
      ))}
    </div>
  );
}
