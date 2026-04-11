# ODI Analyst Workbench

ODI-first, evidence-first cricket analysis workbench.

## Current Status
- Clean-slate rebuild in progress
- Wave 1 scaffold complete
- Source dataset retained in `data/odi_bbb-25.csv`

## Bootstrap

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

### 4. Run the frontend
```powershell
cd frontend
npm run dev
```

## Planned Stack
- Python + FastAPI + DuckDB
- Next.js + TypeScript
- Gemini API for interpretation and grounded external context
- Browser-local session persistence

## Notes
- V1 is ODI-only.
- Database-derived stats are the primary truth source.
- Rename the GitHub repository later once the new identity is finalized.
