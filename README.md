# CricAtlas

ODI-first, evidence-first cricket analysis workbench.

## Current Status
- Waves 1-4 scaffolded
- ODI-only scope with database-first truth
- Source dataset expected at `data/odi_bbb-25.csv`

## Local Bootstrap

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

### 3. Generate the analytical DuckDB file
```powershell
python ingestion/app/load_odi_csv.py
python ingestion/app/profile_dataset.py
```

### 4. Run the backend
```powershell
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### 5. Run the frontend
```powershell
cd frontend
npm run dev
```

## Docker Bootstrap

```bash
copy .env.example .env
docker compose up --build
```

See [deployment.md](C:/Users/ppk_2/Desktop/Projects/Cricket-LLM/docs/deployment.md:1) and [lan-usage.md](C:/Users/ppk_2/Desktop/Projects/Cricket-LLM/docs/lan-usage.md:1).

## Stack
- Python + FastAPI + DuckDB
- Next.js + TypeScript
- Gemini API for interpretation and grounded external context
- Browser-local session persistence

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

## Notes
- V1 is ODI-only.
- Database-derived stats are the primary truth source.
- The preferred product name is `CricAtlas`; rename the GitHub repository when convenient.
