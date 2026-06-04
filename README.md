# CricAtlas

ODI-first, evidence-first cricket analysis workbench.

- **Database is the truth.** ODI ball-by-ball data is loaded into DuckDB and all
  statistics come from there.
- **Gemini assists, it does not decide.** It handles query interpretation,
  grounded external context, narrative wording, and follow-up suggestions — never
  the numbers.
- **Workbench, not a chatbot.** Hybrid chat + structured evidence views, charts,
  player/venue explorers, and browser-local sessions (no auth, no server DB).

> **New here / taking over the project?** Start with **[HANDOFF.md](HANDOFF.md)**.
> The full architecture and roadmap live in **[docs/plan.md](docs/plan.md)**.

## Current Status
- Waves 1–4 implemented; app runs end-to-end (mostly working, polish remaining).
- ODI-only scope with database-first truth.
- Source dataset expected at `data/odi_bbb-25.csv` (not committed — see below).

---

## Run it now (local, no Docker)

This is the quickest way to run it on your own machine.

### 0. Get the dataset
`data/odi_bbb-25.csv` (~464 MB) is **not in git** (intentionally). Get the file
from Pragnesh and place it at:

```text
data/odi_bbb-25.csv
```

### 1. Create the Conda environment
```powershell
conda env create -f environment.yml
conda activate odi-analyst-workbench
```

### 2. Install frontend dependencies
```powershell
cd frontend
npm install
cd ..
```

### 3. (Optional) Configure environment variables
For a **local run you do NOT need a `.env` file** — the backend defaults are
correct (`DUCKDB_PATH` resolves to `data/odi_analytics.duckdb`, and a missing
Gemini key just disables grounding/narrative; database answers still work).

Only create one if you want Gemini features:
```powershell
copy .env.example .env
# then open .env and set:
#   GEMINI_API_KEY=your_key_here
```
See [docs/deployment.md](docs/deployment.md) for every variable.

### 4. Generate the analytical DuckDB file
```powershell
python ingestion/app/load_odi_csv.py
python ingestion/app/profile_dataset.py
```
This creates `data/odi_analytics.duckdb` (gitignored) and refreshes
`docs/data-profile.md`.

### 5. Run the backend (terminal 1)
```powershell
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```
Health check: open `http://localhost:8000/health`.

### 6. Run the frontend (terminal 2)
```powershell
cd frontend
npm run dev
```
Open `http://localhost:3000`.

### Copy-paste summary (local)
```powershell
# 0. Place data/odi_bbb-25.csv first, then:
conda env create -f environment.yml
conda activate odi-analyst-workbench
cd frontend; npm install; cd ..
python ingestion/app/load_odi_csv.py
python ingestion/app/profile_dataset.py
# terminal 1:
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
# terminal 2:
cd frontend; npm run dev
```

---

## Run with Docker (full stack)

For Docker the `.env` file **is required** — `docker compose` reads it.

```powershell
# 0. Place data/odi_bbb-25.csv first
copy .env.example .env
# open .env and set GEMINI_API_KEY if you have one (optional)
docker compose up --build
```

The compose stack:
1. `ingestion` builds `data/odi_analytics.duckdb` and refreshes `docs/data-profile.md`
2. `backend` serves the FastAPI API on port `8000`
3. `frontend` serves the Next.js app on port `3000`

Open `http://localhost:3000`.

---

## Open it from your phone (same Wi-Fi)

Find your laptop's LAN IP (`ipconfig` → IPv4, e.g. `192.168.1.42`) and open
`http://192.168.1.42:3000` on your phone. Full instructions and troubleshooting:
[docs/lan-usage.md](docs/lan-usage.md).

---

## Environment variables

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `APP_ENV` | no | App mode, usually `development` |
| `DUCKDB_PATH` | no (local) / set in Docker | Path to the generated DuckDB file; local default is `data/odi_analytics.duckdb` |
| `GEMINI_API_KEY` | optional | Enables Gemini interpretation, grounding, and narrative; DB answers work without it |
| `GEMINI_DEFAULT_MODEL` | no | Low-latency model (default `gemini-2.5-flash`) |
| `GEMINI_COMPLEX_MODEL` | no | Higher-reasoning model (default `gemini-2.5-pro`) |
| `BACKEND_INTERNAL_URL` | Docker only | Internal URL the Next.js proxy uses to reach the backend container |
| `NEXT_PUBLIC_API_BASE_URL` | optional | Browser override for direct API calls; leave blank for same-origin proxy |

Template: [`.env.example`](.env.example).

---

## Verification

Backend and ingestion:
```powershell
pytest tests
python tests/evals/run_golden_queries.py
```

Frontend:
```powershell
cd frontend
npm run build
npm run test:e2e
```

The golden-query set pins down **trust behavior** (unsupported questions must
return `insufficient_evidence`, never invented analysis), not coverage. See
[tests/evals/expected_behaviors.md](tests/evals/expected_behaviors.md).

---

## Stack
- Python + FastAPI + DuckDB
- Next.js (App Router) + TypeScript
- Gemini API for interpretation and grounded external context
- Browser-local session persistence

## Notes
- V1 is ODI-only.
- Database-derived stats are the primary truth source.
- The CSV and the generated DuckDB are intentionally not committed; place the CSV
  in `data/` before running.
- The preferred product name is `CricAtlas`; rename the GitHub repository
  (`Cricket-LLM`) when convenient.
