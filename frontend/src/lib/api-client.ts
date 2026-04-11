const DEFAULT_REQUEST_TIMEOUT_MS = 10000;
const LONG_REQUEST_TIMEOUT_MS = 25000;

function configuredApiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "";
}

function unique(values: string[]) {
  return values.filter((value, index) => values.indexOf(value) === index);
}

function getClientApiCandidates() {
  const configured = configuredApiBaseUrl();

  if (typeof window === "undefined") {
    return unique(
      [configured, "http://127.0.0.1:8000", "http://localhost:8000"].filter(Boolean),
    );
  }

  const { hostname, protocol } = window.location;
  const sameHostBackend = `${protocol}//${hostname}:8000`;

  return unique(
    [
      "",
      configured,
      sameHostBackend,
      "http://localhost:8000",
      "http://127.0.0.1:8000",
    ].filter(Boolean),
  );
}

function joinUrl(baseUrl: string, path: string) {
  if (!baseUrl) {
    return path;
  }
  return `${baseUrl}${path}`;
}

export function getApiBaseUrl() {
  return getClientApiCandidates()[0];
}

export function getApiCandidates() {
  return getClientApiCandidates();
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const candidates = getClientApiCandidates();
  let lastError: Error | null = null;
  const timeoutMs = path === "/api/chat" || path === "/api/query" ? LONG_REQUEST_TIMEOUT_MS : DEFAULT_REQUEST_TIMEOUT_MS;

  for (const candidate of candidates) {
    const requestUrl = joinUrl(candidate, path);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(requestUrl, {
        cache: "no-store",
        signal: controller.signal,
        ...init,
      });

      if (!response.ok) {
        const errorBody = await response.text();
        lastError = new Error(
          `Request failed with status ${response.status} at ${requestUrl}${
            errorBody ? `: ${errorBody}` : ""
          }`,
        );
        continue;
      }

      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        lastError = new Error(`Request timed out after ${timeoutMs}ms at ${requestUrl}`);
      } else {
        lastError =
          error instanceof Error ? error : new Error(`Unknown request failure at ${requestUrl}`);
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  throw lastError ?? new Error(`Request failed for ${path}`);
}

export async function fetchApi<T>(path: string): Promise<T> {
  return requestJson<T>(path);
}

export async function postApi<T>(path: string, payload: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}
