# Deployment

## Baseline

CricAtlas is packaged for local laptop hosting first. The official full-stack path is Docker Compose:

1. Copy `.env.example` to `.env`
2. Place the ODI CSV at `data/odi_bbb-25.csv`
3. Run:

```bash
docker compose up --build
```

The compose stack does three things:

1. `ingestion` generates `data/odi_analytics.duckdb` and refreshes `docs/data-profile.md`
2. `backend` serves the FastAPI API on port `8000`
3. `frontend` serves the Next.js app on port `3000`

## Environment Variables

- `APP_ENV`: app mode, usually `development`
- `DUCKDB_PATH`: backend path to the generated DuckDB file
- `GEMINI_API_KEY`: optional Gemini API key for grounded external context
- `GEMINI_DEFAULT_MODEL`: default low-latency Gemini model
- `GEMINI_COMPLEX_MODEL`: higher-reasoning Gemini model for harder questions
- `BACKEND_INTERNAL_URL`: internal URL used by the Next.js proxy route inside the frontend container
- `NEXT_PUBLIC_API_BASE_URL`: optional browser override for direct API calls; leave blank for same-origin proxy mode

## Local Development Without Docker

Backend:

```bash
conda activate odi-analyst-workbench
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm run dev
```

The frontend now defaults to same-origin API proxying through Next.js, so LAN/browser access does not depend on browser-side `127.0.0.1` API calls.

## Notes

- The CSV is intentionally not committed. Anyone cloning the repo must place it in `data/`.
- The generated DuckDB is also local by default.
- If ingestion fails, the backend will not become healthy because the derived DuckDB file is required.
