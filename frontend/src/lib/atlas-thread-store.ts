import type { ChatReply } from "@/lib/api-types";

export type AtlasMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  reply?: ChatReply | null;
};

export type AtlasThread = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: AtlasMessage[];
};

type AtlasLaunchState = {
  threads: AtlasThread[];
  activeThreadId: string;
};

const STORAGE_KEY = "cricatlas:atlas-threads";
const ACTIVE_THREAD_KEY = "cricatlas:atlas-active-thread";
const LAUNCH_KEY = "cricatlas:atlas-launch";

function nowIso() {
  return new Date().toISOString();
}

function createId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function createThread(title = "New Atlas thread"): AtlasThread {
  const timestamp = nowIso();
  return {
    id: createId(),
    title,
    createdAt: timestamp,
    updatedAt: timestamp,
    messages: [],
  };
}

export function createAtlasMessage(
  role: AtlasMessage["role"],
  content: string,
  reply?: ChatReply | null,
): AtlasMessage {
  return {
    id: createId(),
    role,
    content,
    createdAt: nowIso(),
    reply: reply ?? null,
  };
}

export function prepareAtlasLaunchState(): AtlasLaunchState {
  const restored = loadThreads().filter((thread) => thread.messages.length > 0);
  const activeThreadId = loadActiveThreadId();

  if (typeof window === "undefined") {
    const fresh = createThread();
    return { threads: [fresh], activeThreadId: fresh.id };
  }

  const alreadyLaunched = window.sessionStorage.getItem(LAUNCH_KEY) === "1";
  if (!alreadyLaunched) {
    const fresh = createThread();
    const threads = [fresh, ...restored].slice(0, 20);
    saveThreads(threads);
    saveActiveThreadId(fresh.id);
    window.sessionStorage.setItem(LAUNCH_KEY, "1");
    return { threads, activeThreadId: fresh.id };
  }

  if (restored.length === 0) {
    const fresh = createThread();
    saveThreads([fresh]);
    saveActiveThreadId(fresh.id);
    return { threads: [fresh], activeThreadId: fresh.id };
  }

  const resolvedActiveId =
    activeThreadId && restored.some((thread) => thread.id === activeThreadId)
      ? activeThreadId
      : restored[0].id;
  return { threads: restored, activeThreadId: resolvedActiveId };
}

export function loadThreads(): AtlasThread[] {
  if (typeof window === "undefined") {
    return [];
  }
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isAtlasThread) : [];
  } catch {
    return [];
  }
}

export function saveThreads(threads: AtlasThread[]): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(threads.slice(0, 20)));
}

export function loadActiveThreadId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(ACTIVE_THREAD_KEY);
}

export function saveActiveThreadId(threadId: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!threadId) {
    window.localStorage.removeItem(ACTIVE_THREAD_KEY);
    return;
  }
  window.localStorage.setItem(ACTIVE_THREAD_KEY, threadId);
}

function isAtlasMessage(value: unknown): value is AtlasMessage {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    (candidate.role === "user" || candidate.role === "assistant") &&
    typeof candidate.content === "string" &&
    typeof candidate.createdAt === "string"
  );
}

function isAtlasThread(value: unknown): value is AtlasThread {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.title === "string" &&
    typeof candidate.createdAt === "string" &&
    typeof candidate.updatedAt === "string" &&
    Array.isArray(candidate.messages) &&
    candidate.messages.every(isAtlasMessage)
  );
}
