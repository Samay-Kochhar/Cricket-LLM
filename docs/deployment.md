# Deployment

## Baseline

CricAtlas is packaged for local laptop hosting first. The official full-stack path is Docker Compose:

1. Copy `.env.example` to `.env`
2. Optionally place the ODI CSV at `data/odi_bbb-25.csv`; otherwise the verified
   publisher file is downloaded automatically
3. Run:

```bash
docker compose up --build
```

The compose stack does three things:

1. `ingestion` reuses existing data or downloads the configured source, then
   generates `data/odi_analytics.duckdb` and refreshes `docs/data-profile.md`
2. `backend` serves the FastAPI API on port `8000`
3. `frontend` serves the Next.js app on port `3000`

## Environment Variables

- `APP_ENV`: app mode, usually `development`
- `DUCKDB_PATH`: backend path to the generated DuckDB file
- `GEMINI_API_KEY`: optional Gemini API key for grounded external context
- `GEMINI_DEFAULT_MODEL`: default Gemini model for interpretation and concise narrative; defaults to `gemini-2.5-pro`
- `GEMINI_COMPLEX_MODEL`: higher-reasoning Gemini model for harder questions; defaults to `gemini-2.5-pro`
- `BACKEND_INTERNAL_URL`: internal URL used by the Next.js proxy route inside the frontend container
- `NEXT_PUBLIC_API_BASE_URL`: optional browser override for direct API calls; leave blank for same-origin proxy mode
- `CRICATLAS_DATA_URL`: optional direct CSV/ZIP override
- `CRICATLAS_DATA_SHA256`: optional checksum of the downloaded artifact
- `CRICATLAS_DATA_ARCHIVE_MEMBER`: CSV path/name inside a multi-file ZIP

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

- The CSV is intentionally not committed. Fresh clones can download it through
  the configured source URL; manual placement in `data/` remains supported.
- The generated DuckDB is also local by default.
- If ingestion fails, the backend will not become healthy because the derived DuckDB file is required.
- The hosted Streamlit demo is separate from the full Next.js application; see
  [streamlit-deployment.md](streamlit-deployment.md).
