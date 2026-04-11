import type { QueryResponse } from "@/lib/api-types";
import { derivePrimaryExplorerHref } from "@/lib/explorer-links";


export type SavedAnalysis = {
  id: string;
  title: string;
  question: string;
  queryClass: string;
  status: QueryResponse["status"];
  entities: string[];
  href: string | null;
  createdAt: string;
  updatedAt: string;
};

const STORAGE_KEY = "cricatlas:saved-analyses";


function nowIso() {
  return new Date().toISOString();
}


function createId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


export function createSavedAnalysis(question: string, result: QueryResponse): SavedAnalysis {
  const timestamp = nowIso();
  const derivedTitle = result.summaries[0]?.title ?? question.slice(0, 48);
  return {
    id: createId(),
    title: derivedTitle || "Saved analysis",
    question,
    queryClass: result.interpretation.query_class,
    status: result.status,
    entities: result.interpretation.entities,
    href: derivePrimaryExplorerHref(result),
    createdAt: timestamp,
    updatedAt: timestamp,
  };
}


export function loadSavedAnalyses(): SavedAnalysis[] {
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
    return parsed.filter(isSavedAnalysis);
  } catch {
    return [];
  }
}


export function saveSavedAnalyses(items: SavedAnalysis[]): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, 20)));
}


function isSavedAnalysis(value: unknown): value is SavedAnalysis {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.title === "string" &&
    typeof candidate.question === "string" &&
    typeof candidate.queryClass === "string" &&
    typeof candidate.status === "string" &&
    Array.isArray(candidate.entities) &&
    typeof candidate.createdAt === "string" &&
    typeof candidate.updatedAt === "string"
  );
}
