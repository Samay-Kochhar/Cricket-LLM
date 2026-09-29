/**
 * CricAtlas backend routing policy (one policy for every page).
 *
 * Browser: requests use the same-origin `/api/...` proxy served by Next. The
 * only exception is an explicit `NEXT_PUBLIC_API_BASE_URL`, which names a
 * public backend on purpose. There is no guessed fallback host: a missing
 * optional value must never send a request to whatever happens to listen on a
 * common port such as 8000.
 *
 * Server (the Next proxy and any server-side fetch): the one documented
 * internal backend URL, `BACKEND_INTERNAL_URL`, defaulting to the local
 * CricAtlas backend at http://127.0.0.1:8000.
 *
 * The proxy only forwards responses that identify as CricAtlas through the
 * `x-cricatlas-backend` header, so an unrelated service at the internal URL
 * fails clearly instead of answering.
 */

export const SAME_ORIGIN = "";
export const DEFAULT_INTERNAL_BACKEND_URL = "http://127.0.0.1:8000";
export const BACKEND_IDENTITY_HEADER = "x-cricatlas-backend";

function trimTrailingSlash(value: string) {
  return value.replace(/\/$/, "");
}

/** Explicit public backend for browser requests, or same-origin when unset. */
export function publicApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  return configured ? trimTrailingSlash(configured) : SAME_ORIGIN;
}

/** The documented internal backend URL used by server-side code. */
export function internalBackendUrl(): string {
  const configured = process.env.BACKEND_INTERNAL_URL?.trim();
  return configured ? trimTrailingSlash(configured) : DEFAULT_INTERNAL_BACKEND_URL;
}
