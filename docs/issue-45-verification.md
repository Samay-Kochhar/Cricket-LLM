# Issue 45 verification: browser routing through the same-origin API proxy

Issue 45 fixes how the browser reaches the CricAtlas backend. The approved UI
is unchanged: no layout, styling, controls, labels, metrics or interactions were
touched.

## Defect

`frontend/src/lib/api-client.ts` built the browser candidate list as
`["", configured, <host>:8000, localhost:8000, 127.0.0.1:8000].filter(Boolean)`.
The intentional same-origin value `""` is falsy, so the filter removed it. The
browser therefore called port 8000 directly. When an unrelated application
occupied that port, CORS blocked the request and Chat, Matchups and Workbench
showed "Failed to fetch".

## Routing policy

The policy is defined in one place: `frontend/src/lib/backend-routing.ts`.

- **Browser.** Every request uses the same-origin `/api/...` proxy. An
  explicitly configured `NEXT_PUBLIC_API_BASE_URL` is the only override. There
  are no guessed fallback hosts, and the same-origin value is preserved as an
  intentional empty base URL rather than filtered out.
- **Server.** The Next proxy, and any server-side fetch, uses the one
  documented internal URL `BACKEND_INTERNAL_URL`. Its default is the local
  CricAtlas API at `http://127.0.0.1:8000`; Compose sets `http://backend:8000`.
- **Identity.** The API adds `x-cricatlas-backend: 1` to every response. The
  proxy forwards only responses carrying it.
- **Clear failure.** The proxy returns HTTP 502 with "CricAtlas backend is
  unavailable" and the configured URL in either case:
  - no service answers at the internal URL;
  - a different service answers there.

## Verification

Local conditions: an unrelated service (`flight_finder`) was listening on
`127.0.0.1:8000` throughout. The CricAtlas API ran on port 8765, with
`NEXT_PUBLIC_API_BASE_URL` empty and `GEMINI_API_KEY` empty (no model calls).

### Real browser integration (Playwright project `integration`, no endpoint interception)

`e2e/routing.integration.spec.ts` records every `/api/` request and asserts
that each one is same-origin and that no request fails or logs a CORS or
"Failed to fetch" error:

| Surface | Request | Evidence |
| --- | --- | --- |
| Chat | `POST /api/chat` | 200; "94.0 … 2518 balls" for Kohli v Australia |
| Matchups | `POST /api/matchups` | 200; "Steven Smith scored 103 runs from 121 balls" |
| Workbench | `POST /api/workbench/search` | 200; Hardik Pandya result |

`e2e/odi-correctness-smoke.spec.ts` never intercepted the API, so it was
renamed `odi-correctness-smoke.integration.spec.ts` and now reports under the
integration project. `scripts/verify_issues.py` references the new name.

Result: 10 integration tests passed.

### Mocked UI tests (Playwright project `mocked`)

`chat.spec.ts` and `explorer.spec.ts` keep intercepting `/api` responses for
speed. They are reported under a separate `mocked` project and are not
treated as evidence of backend connectivity.

Result: 14 mocked tests passed.

Scripts:

- `npm run test:e2e:mocked`
- `npm run test:e2e:integration`
- `npm run test:e2e` (both projects)

### Proxy failure behavior

Checked against temporary dev servers:

| `BACKEND_INTERNAL_URL` | Proxy response |
| --- | --- |
| `http://127.0.0.1:8000` (unrelated service) | 502: "The service at BACKEND_INTERNAL_URL (http://127.0.0.1:8000) did not identify as the CricAtlas API…" |
| `http://127.0.0.1:8799` (nothing listening) | 502: "No response from BACKEND_INTERNAL_URL (http://127.0.0.1:8799)…" |

### Other checks

- `npm run build` succeeds.
- `tests/backend/test_backend_identity_header.py` checks that the header is
  present on health, API and 404 responses.
- The full backend suite passes.

## Notes

- The installed Playwright expects a Chromium headless-shell build that was not
  downloaded locally. Runs used the cached newer shell through the existing
  `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` option; no browsers were downloaded.
- `e2e/explorer.spec.ts` has a pre-existing TypeScript type error in its mock
  payload (line 232). It is unrelated to this change and does not affect
  Playwright execution.
