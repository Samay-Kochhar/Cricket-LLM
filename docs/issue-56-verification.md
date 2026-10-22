# Issue #56 — contextual venue bowling leaderboard

Implemented on top of merged #52 (`e93a04d26b727d4c7ecff7038f2dff9cf23dd14a`).

The shared venue profile service returns canonical identity, supported options,
applied filters, ranking metadata and minimum-sample policy. Repository SQL applies
venue aliases, phase and inclusive year range before aggregation, sample eligibility,
selected-metric availability and top N. Both explorers use the same options and
payload. The selected metric controls order and chart values; the chart appears
above the expanded table. Existing explorer styling and Apply/Reset behavior are
retained. See `metric-catalog.md` for definitions and null/tie policies.

The eight metric choices cover wickets, bowling average, economy, bowling strike rate,
dot percentage, boundary percentage conceded, legal deliveries and runs conceded.
The last two are labeled descriptive totals. Minimum sample defaults to 24 legal
balls, with distinct matches and an explicit zero threshold also supported. Matches
are counted distinctly over the filtered union of venue aliases.

## Scope and ownership

The checkout started with unrelated uncommitted work. The existing venue-specific
minimum controls in `repository.py` and `streamlit_venue_explorer.py` are the minimal
shared foundation incorporated into this issue: 24-ball default, legal-ball/match
sample units, Apply/Reset, match counts and container sizing compatibility. Their
validation now lives in `VenueBowlingOptions`; all three surfaces share the service.

Generic chat ranking changes in `aggregate_builder.py`, `schemas.py`,
`semantic_service.py`, `evidence_models.py`, `streamlit_app.py`, and untracked
`ranking_controls.py` remain outside this patch. All other original untracked files
remain outside it too. Starting diff and SHA-256 records were retained locally;
unrelated original files were verified byte-for-byte unchanged before commit.
No source CSV/DuckDB, venue research/mapping changes, or #57 batting work is included.

## Validation

Release checks run against a clean export of the Git index, with local ignored
CSV/DuckDB files linked for data-dependent tests and frontend dependencies installed
using `npm ci`. Uncommitted chat work and untracked tests were excluded from this
release receipt.

- Focused backend/API, canonical identity and existing explorer tests: 198 passed.
- New Streamlit tests: 3 passed. These verify independent phase/year/metric/sample
  filters, stable draft state, Apply/Reset, invalid/empty results and chart order.
- New real-network browser integration test: 1 passed against the isolated export.
  It verifies alias links/current selector names, selected economy ordering/chart,
  full columns, samples, inclusive years, disabling years independently and Reset.
- Production Next.js build: passed in the isolated export.
- App TypeScript check: passed; Python entry-point compilation: passed.
- Full isolated Python suite: 1,586 passed, 3 warnings, in 615.34 seconds.

The full `npx tsc --noEmit` also checks existing E2E fixtures and reports the
pre-existing `e2e/explorer.spec.ts:232` null-assignment inference error. That file is
unchanged. Production build's TypeScript check and the separate app check pass.
An initial isolated Python run was interrupted because dataset links had not yet
been mounted; it is excluded from the release counts above.

Real-data visual checks covered both Next.js and Streamlit, confirming the approved
explorer styling, canonical venue, new controls, full table and chart-before-table
order. T3 preview navigation worked, but snapshot calls twice timed out with
`Preview automation snapshot timed out after 15000ms.` Chrome via the available
computer-use fallback was used for the visual inspection. The browser integration
test uses installed Chrome through `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`; Python
uses the compatible temporary Streamlit 1.55 environment.
