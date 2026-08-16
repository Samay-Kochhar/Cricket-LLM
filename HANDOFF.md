# CricAtlas — Handoff

ODI-first, evidence-first cricket analysis workbench. This document is the
entry point for the developer taking over the project.

> TL;DR: the app is **mostly working end-to-end** (ingestion → analytics API →
> Gemini grounding → workbench UI). The remaining work is polish, bug-fixing,
> and finishing the rougher edges of the explorer/result views. Start by getting
> it running locally (you need the dataset — see below), then work through the
> "What's left" list.

---

## 1. What this is

- **Scope:** ODI cricket only, by design. The dataset is ball-by-ball ODI data.
- **Truth model:** database-derived stats (DuckDB) are the source of truth.
  Gemini is used for query interpretation, grounded external context, narrative
  wording, and follow-up suggestions — it **never** owns the statistics.
- **Shape:** FastAPI + DuckDB backend, Next.js (App Router) + TypeScript
  frontend, browser-local session persistence (no auth, no server DB).

Full architecture, design decisions, and the original 9-task implementation
plan are in **[docs/plan.md](docs/plan.md)** — read that for the "why" behind
each layer.

---

## 2. Current state (what works)

All four build waves are implemented, not just scaffolded:

| Layer | Status | Key files |
|-------|--------|-----------|
| Ingestion | Working | `ingestion/app/load_odi_csv.py`, `ingestion/app/profile_dataset.py` |
| Metrics & evidence contract | Working | `backend/app/services/metric_catalog.py`, `backend/app/domain/` |
| Analytics API & query router | Working | `backend/app/api/routes/query.py`, `backend/app/services/query_router.py`, `query_interpreter.py`, `analytics_service.py` |
| Gemini grounding & answer composition | Working | `gemini_client.py`, `grounded_context.py`, `answer_composer.py`, `follow_up_suggester.py` |
| Frontend workbench, result views, charts | Working | `frontend/src/app/workbench/page.tsx`, `frontend/src/components/results/`, `frontend/src/components/charts/` |
| Explorer routes (player/venue/compare) | Working | `frontend/src/app/players/[player]`, `venues/[venue]`, `compare/page.tsx` |
| Deployment (Docker + LAN) | Working | `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` |
| Golden-query evals + E2E | Present | `tests/evals/`, `frontend/e2e/` |

Supported query classes (frozen for v1):
- Role / position comparison
- Strengths and weaknesses
- Head-to-head matchup
- Venue / context leaderboard
- Trend / progression analysis

---

## 3. Setup — get it running

### Prerequisites
- Conda (for the Python env), Node.js + npm (for the frontend)
- **The dataset CSV** — see step 0. Nothing runs without it.
- Optional: a Gemini API key (the DB-only path still works without it; grounding
  and narrative quality degrade gracefully when the key is absent)

### Step 0 — Get the dataset
`data/odi_bbb-25.csv` (~464 MB) is **not in git** (intentionally — see
`.gitignore`). **Pragnesh will send you this file directly.** Place it at:

```
data/odi_bbb-25.csv
```

### Step 1 — Python environment
```powershell
conda env create -f environment.local.yml
conda activate odi-analyst-workbench
```

### Step 2 — Frontend deps
```powershell
cd frontend
npm install
cd ..
```

### Step 3 — Build the analytical DuckDB file
```powershell
python ingestion/app/load_odi_csv.py
python ingestion/app/profile_dataset.py
```
This generates `data/odi_analytics.duckdb` (also gitignored) and refreshes
`docs/data-profile.md`.

### Step 4 — Run backend + frontend
```powershell
# terminal 1
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# terminal 2
cd frontend
npm run dev
```

### Or use Docker (full stack)
```powershell
copy .env.example .env   # fill in GEMINI_API_KEY if you have one
docker compose up --build
```
Backend on `:8000`, frontend on `:3000`. Phone/LAN access is documented in
[docs/lan-usage.md](docs/lan-usage.md).

### Environment variables
See `.env.example` and [docs/deployment.md](docs/deployment.md). The important
one is `GEMINI_API_KEY`.

---

## 4. Verification

```powershell
# backend + ingestion
pytest tests
python tests/evals/run_golden_queries.py

# frontend
cd frontend
npm run build
npm run test:e2e
```

The golden-query set pins down **trust behavior**, not coverage — see
[tests/evals/expected_behaviors.md](tests/evals/expected_behaviors.md). The key
invariant: unsupported or low-evidence questions must return
`insufficient_evidence`, never invented analysis.

---

## 5. What's left (suggested next work)

> The app works; this is the "finish and polish" list. Confirm priorities with
> Pragnesh.

- [ ] **Polish result/visual views** — the radar-chart explanation copy was just
      revised (`frontend/src/components/results/visual-insights.tsx`); review the
      other chart explainer copy for the same clarity.
- [ ] **Harden the query router / interpreter** — verify edge cases route to the
      right query class and that ambiguous players surface candidate suggestions.
- [ ] **Expand golden-query coverage** in `tests/evals/golden_queries.yaml` for
      each supported query class.
- [ ] **Explorer + saved-analysis flows** — confirm player/venue deep-links from
      chat answers load the right evidence; check saved-analysis persistence.
- [ ] **Insufficient-evidence UX** — make sure every unsupported path renders the
      limitation state cleanly (no blank panels).
- [ ] **Gemini failure resilience** — confirm DB-only answers still return when
      the Gemini call fails or the key is missing.
- [ ] **Rename** — the product name is `CricAtlas`; the GitHub repo is still
      `Cricket-LLM`. Rename when convenient.

For acceptance criteria per task, see the **Tasks** section of
[docs/plan.md](docs/plan.md).

---

## 6. Repo map

```
backend/          FastAPI app — API routes, services, domain models, prompts
ingestion/        CSV → DuckDB loader + dataset profiler
frontend/         Next.js App Router workbench (chat + structured views + charts)
data/             Dataset CSV + generated DuckDB (both gitignored)
docs/             plan.md, deployment.md, lan-usage.md, metric-catalog.md, data-profile.md
tests/            backend pytest + evals (golden queries); frontend e2e under frontend/e2e/
docker-compose.yml
environment.local.yml   conda env (odi-analyst-workbench)
.env.example      environment variable template
```

---

## 7. Conventions / gotchas

- **ODI-only.** Don't add other formats without a scope decision.
- **DB is truth.** Any new metric must be defined in
  `backend/app/services/metric_catalog.py` and documented in
  [docs/metric-catalog.md](docs/metric-catalog.md). Don't let Gemini compute stats.
- **Unsupported is a first-class state**, not an error. Preserve the
  `insufficient_evidence` contract.
- The CSV and DuckDB files are intentionally untracked — never commit them.
- Frontend defaults to same-origin API proxying through Next.js, so LAN access
  doesn't depend on browser-side `127.0.0.1` calls.

---

## 8. Contact

Original author: Pragnesh. Reach out for the dataset file and any context not
captured here.
