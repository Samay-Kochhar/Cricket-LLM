# Implementation Plan: ODI Analyst Workbench MVP

**Branch:** main
**Created:** 2026-04-11T17:50:00+02:00
**Status:** active
**Phase:** single

## Architecture Overview
The MVP should be built as a clean ODI-first full-stack application with four layers:

1. **Ingestion**
   Reads `data/odi_bbb-25.csv`, normalizes the schema, resolves obvious entity issues, and generates a local analytical DuckDB file plus derived views.

2. **Analytics backend**
   Owns metric definitions, query routing, database access, evidence contracts, and unsupported/insufficient-evidence handling.

3. **Gemini orchestration**
   Uses Gemini for intent help, grounded external context, follow-up suggestions, and answer wording. It does not own database truth.

4. **Frontend workbench**
   Provides hybrid chat + structured views, cricket-specific visualizations, explorer routes, and browser-local session persistence.

High-level flow:

User question -> query classifier -> structured query plan -> DuckDB evidence -> optional Gemini grounding/context -> normalized response payload -> frontend evidence views

## Design Decisions
| Decision | Choice | Rationale | Alternatives Considered |
|----------|--------|-----------|-------------------------|
| Scope | ODI-only | Matches the real retained dataset and keeps the app honest | Multi-format cricket scope |
| Analytical store | DuckDB derived from CSV | Fast local analytics without separate infra | Querying raw CSV only, Postgres |
| Backend | FastAPI + Python | Typed APIs and clean analytics ergonomics | Flask, Node backend |
| Frontend | Next.js App Router + TypeScript | Strong responsive UX, PWA path, self-hosting | Vite SPA |
| LLM vendor | Gemini API | Matches intended API keys and model routing preference | Vendor-neutral first pass |
| External web context | Gemini `google_search` behind an abstraction | Same-vendor grounding with citations, future-swappable | Hard-coded external search provider |
| Persistence | Browser-local sessions | No auth complexity in v1 | Accounts, server persistence |
| Deployment baseline | Local dev + LAN + Docker Compose | Matches intended usage and OSS distribution | Cloud-first rollout |

## Dependency Graph

Wave 1: [Task 1: Ingestion and Data Profile], [Task 2: Metric and Evidence Contract], [Task 3: Frontend Shell and Local Sessions]
Wave 2: [Task 4: Analytics API and Query Router] (<- 1, 2), [Task 5: Gemini Grounding and Answer Composition] (<- 2, 4), [Task 6: Result Views and Chart System] (<- 3, 4, 5)
Wave 3: [Task 7: Explorer Views and Saved Analysis], [Task 8: Deployment Packaging and LAN Usage] (<- 3, 4, 6)
Wave 4: [Task 9: Feature E2E and Golden Query Evaluation] (<- 5, 6, 7, 8)

## Tasks

### Task 1: Ingestion and Data Profile
**Agent:** implementer
**Model:** sonnet
**UI:** no
**Files owned:** `ingestion/pyproject.toml`, `ingestion/app/load_odi_csv.py`, `ingestion/app/profile_dataset.py`, `ingestion/sql/base_schema.sql`, `ingestion/sql/derived_views.sql`, `docs/data-profile.md`, `tests/ingestion/test_profile_dataset.py`

**Context:**
The product has only a raw ODI CSV. The first step is a repeatable ingestion path and an explicit profile of what the data can and cannot support.

**Spec:**
- Build a CLI command to generate a local DuckDB file from `data/odi_bbb-25.csv`
- Remove or normalize the unnamed leading CSV column
- Create typed columns and derived views needed by v1 query classes
- Produce a profile report with year range, field coverage, and known naming anomalies
- Make ingestion deterministic and rerunnable

**Test Cases:**
1. [unit] ingest valid CSV -> DuckDB file and base tables created
2. [unit] profile command -> field coverage and year range emitted
3. [integration] derived view query -> core views are queryable after ingestion

**Acceptance Criteria:**
- [ ] One command builds the analytical store from the CSV
- [ ] Data limitations are documented early
- [ ] Derived views exist for the first query classes

### Task 2: Metric and Evidence Contract
**Agent:** implementer
**Model:** sonnet
**UI:** no
**Files owned:** `backend/app/domain/evidence_models.py`, `backend/app/domain/metric_models.py`, `backend/app/services/metric_catalog.py`, `backend/app/services/query_classes.py`, `backend/app/services/player_resolution.py`, `docs/metric-catalog.md`, `tests/backend/test_metric_catalog.py`, `tests/backend/test_player_resolution.py`

**Context:**
Trust is the product. Supported query classes, metric formulas, and insufficient-evidence behavior must be explicit before the first endpoint.

**Spec:**
- Define typed response blocks for summaries, tables, charts, citations, evidence notes, and insufficient-evidence states
- Freeze v1 query classes:
  - role and position comparison
  - strengths and weaknesses
  - head-to-head matchup
  - venue/context leaderboard
  - trend/progression analysis
- Create explicit metric formulas and dependencies
- Add player alias resolution and approximate-match suggestions

**Test Cases:**
1. [unit] known metric -> formula and dependencies returned
2. [unit] player alias lookup -> canonical identity or suggestion list returned
3. [integration] insufficient-evidence contract -> standardized unsupported response payload returned

**Acceptance Criteria:**
- [ ] Metric formulas are explicit and versioned
- [ ] Supported query classes are frozen for v1
- [ ] Unsupported cases are a first-class contract

### Task 3: Frontend Shell and Local Sessions
**Agent:** implementer
**Model:** sonnet
**UI:** yes
**Files owned:** `frontend/package.json`, `frontend/next.config.ts`, `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`, `frontend/src/app/globals.css`, `frontend/src/components/app-shell.tsx`, `frontend/src/components/chat-entry.tsx`, `frontend/src/components/session-list.tsx`, `frontend/src/lib/local-session-store.ts`

**Context:**
The product is a workbench, not a backend demo. The shell and local session model should exist from the start.

**Spec:**
- Build a responsive app shell for laptop and phone
- Add local browser session create/load/delete behavior
- Add placeholders for chat input, result panel, and citation/evidence rail
- Keep the shell workbench-oriented rather than marketing-page oriented

**Test Cases:**
1. [unit] local session create/read works
2. [unit] shell renders on initial route
3. [integration] switching sessions updates visible workspace state

**Acceptance Criteria:**
- [ ] The shell is usable on laptop and phone
- [ ] Browser-local session persistence exists
- [ ] The result workspace is ready for API integration

### Task 4: Analytics API and Query Router
**Agent:** implementer
**Model:** sonnet
**UI:** no
**Files owned:** `backend/pyproject.toml`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/db/connection.py`, `backend/app/api/routes/query.py`, `backend/app/api/routes/explore.py`, `backend/app/services/query_router.py`, `backend/app/services/analytics_service.py`, `tests/backend/test_query_route.py`

**Context:**
The backend must convert natural-language ODI questions into deterministic analytics operations over declared metrics and views.

**Spec:**
- Implement:
  - `POST /api/query`
  - `GET /api/players/search`
  - `GET /api/players/{player_id}`
  - `GET /api/venues/{venue_id}`
  - `GET /api/compare`
- Parse supported questions into query classes
- Execute only declared database-backed analytics
- Return structured evidence payloads, not chat text only

**Test Cases:**
1. [unit] supported ODI comparison question -> structured evidence payload
2. [unit] unsupported intent -> supported-intents guidance response
3. [integration] ambiguous player search -> candidate suggestions returned

**Acceptance Criteria:**
- [ ] Supported ODI queries execute through one consistent API
- [ ] Unsupported and ambiguous cases are explicit
- [ ] DB-backed evidence is deterministic

### Task 5: Gemini Grounding and Answer Composition
**Agent:** implementer
**Model:** opus
**UI:** no
**Files owned:** `backend/app/services/gemini_client.py`, `backend/app/services/grounded_context.py`, `backend/app/services/answer_composer.py`, `backend/app/services/follow_up_suggester.py`, `backend/app/prompts/`, `tests/backend/test_answer_composer.py`

**Context:**
Gemini should improve interpretation and explanation, but it must not become the source of truth for statistics.

**Spec:**
- Add Gemini client wrapper with Flash default and Pro escalation
- Add grounded web context retrieval using Gemini `google_search`
- Compose final responses from:
  - DB evidence
  - optional grounded external context
  - generated narrative
- Ensure failures in grounding do not break DB-only answers

**Test Cases:**
1. [unit] model routing -> simple uses Flash, complex uses Pro
2. [unit] grounded citation normalization -> citation objects returned
3. [integration] grounding failure with valid DB evidence -> answer still returns

**Acceptance Criteria:**
- [ ] Gemini is integrated without owning the truth layer
- [ ] Grounded citations are UI-ready
- [ ] DB-only answers still work when Gemini fails

### Task 6: Result Views and Chart System
**Agent:** implementer
**Model:** sonnet
**UI:** yes
**Files owned:** `frontend/src/components/results/`, `frontend/src/components/charts/`, `frontend/src/components/citations/`, `frontend/src/hooks/use-query.ts`, `frontend/src/lib/result-mappers.ts`, `frontend/src/app/page.tsx`

**Context:**
The answer must be inspectable. The app succeeds only if users can see the evidence, not just the prose.

**Spec:**
- Render summaries, metrics, tables, charts, and citations from one normalized payload
- Provide explicit insufficient-evidence rendering
- Support standard charts first and cricket-specific visuals where the data supports them
- Keep citations visible and understandable

**Test Cases:**
1. [unit] mixed result payload -> summary, table, chart, citations render
2. [unit] insufficient-evidence payload -> limitation state renders
3. [integration] query response -> full evidence-first result view shown

**Acceptance Criteria:**
- [ ] Answers render as evidence-first views
- [ ] Citations are visible
- [ ] Unsupported cases stay coherent in the UI

### Task 7: Explorer Views and Saved Analysis
**Agent:** implementer
**Model:** sonnet
**UI:** yes
**Files owned:** `frontend/src/app/players/[player]/page.tsx`, `frontend/src/app/venues/[venue]/page.tsx`, `frontend/src/app/compare/page.tsx`, `frontend/src/components/explorer/`, `frontend/src/components/saved-analysis/`

**Context:**
Chat is the entry point, but the product also needs structured exploration and repeatable local analysis flows.

**Spec:**
- Add player and venue explorer routes
- Add comparison route
- Allow useful analyses to be saved locally
- Link chat answers into deeper structured views

**Test Cases:**
1. [unit] explorer route renders for valid player
2. [unit] result card can be saved locally
3. [integration] chat result deep-link loads explorer evidence

**Acceptance Criteria:**
- [ ] Structured exploration exists beyond chat
- [ ] Saved local analysis exists
- [ ] Player and venue exploration work in v1

### Task 8: Deployment Packaging and LAN Usage
**Agent:** devops
**Model:** sonnet
**UI:** no
**Files owned:** `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`, `.env.example`, `docs/deployment.md`, `docs/lan-usage.md`

**Context:**
The intended usage is laptop hosting plus same-Wi-Fi phone access, with OSS-friendly distribution.

**Spec:**
- Add backend and frontend Dockerfiles
- Add `docker compose` as the official full-stack run path
- Document environment variables, Gemini keys, and generated DB path
- Document LAN usage from a second device

**Test Cases:**
1. [unit] backend and frontend images build
2. [integration] compose boots full stack with health checks
3. [integration] documented LAN path works from another device on the same network

**Acceptance Criteria:**
- [ ] Official container-based run path exists
- [ ] LAN usage is documented
- [ ] Config is externalized

## Feature E2E Task

### Task 9: Feature E2E and Golden Query Evaluation
**Agent:** implementer
**Model:** sonnet
**UI:** no
**Files owned:** `frontend/e2e/chat.spec.ts`, `frontend/e2e/explorer.spec.ts`, `tests/evals/golden_queries.yaml`, `tests/evals/run_golden_queries.py`, `tests/evals/expected_behaviors.md`

**Context:**
This product needs both browser-level checks and a fixed set of ODI analyst questions to prevent regressions in trust and evidence quality.

**Spec:**
- Add Playwright E2E coverage for core user journeys
- Add a golden-query evaluation set of real ODI analyst prompts
- Validate supported answers, citations, and insufficient-evidence behavior

**Test Cases:**
1. [e2e] supported ODI chat question -> narrative, metrics, charts, citations shown
2. [e2e] unsupported/low-evidence question -> limitation state shown without hallucinated content
3. [eval] golden ODI prompts -> expected answer class and evidence presence validated

**Acceptance Criteria:**
- [ ] Core browser journeys pass
- [ ] Unsupported cases are tested explicitly
- [ ] Golden ODI query evaluation exists for future development
