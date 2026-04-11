export type SavedSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  lastPrompt?: string;
};

const STORAGE_KEY = "odi-analyst-workbench:sessions";


function nowIso() {
  return new Date().toISOString();
}


export function createSession(title = "Untitled Session"): SavedSession {
  const timestamp = nowIso();
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  return {
    id,
    title,
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}


export function loadSessions(): SavedSession[] {
  if (typeof window === "undefined") {
    return [];
  }

  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(isSavedSession);
  } catch {
    return [];
  }
}


export function saveSessions(sessions: SavedSession[]): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
}


function isSavedSession(value: unknown): value is SavedSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.title === "string" &&
    typeof candidate.createdAt === "string" &&
    typeof candidate.updatedAt === "string"
  );
}
