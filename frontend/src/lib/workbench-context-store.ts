export type WorkbenchContext = {
  subject?: string | null;
  query?: string | null;
  source?: "atlas" | "workbench" | null;
  threadId?: string | null;
};

const CONTEXT_KEY = "cricatlas:workbench-context";
const PENDING_ATLAS_PROMPT_KEY = "cricatlas:pending-atlas-prompt";

export function saveWorkbenchContext(context: WorkbenchContext) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(CONTEXT_KEY, JSON.stringify(context));
}

export function loadWorkbenchContext(): WorkbenchContext | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(CONTEXT_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as WorkbenchContext;
  } catch {
    return null;
  }
}

export function savePendingAtlasPrompt(prompt: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(PENDING_ATLAS_PROMPT_KEY, prompt);
}

export function consumePendingAtlasPrompt(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const prompt = window.localStorage.getItem(PENDING_ATLAS_PROMPT_KEY);
  if (prompt) {
    window.localStorage.removeItem(PENDING_ATLAS_PROMPT_KEY);
  }
  return prompt;
}
