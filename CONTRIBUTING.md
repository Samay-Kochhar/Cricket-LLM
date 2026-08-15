# Contributing to CricAtlas

Thank you for helping build an evidence-first cricket analysis workbench.

## Start with Docker

1. Clone the repository.
2. Copy `.env.example` to `.env`.
3. Set `CRICATLAS_DATA_URL` to the verified direct dataset download URL, or
   place `odi_bbb-25.csv` in `data/`.
4. Optionally set `GEMINI_API_KEY`; database-backed analysis works without it.
5. Run:

```bash
docker compose up --build
```

The ingestion container downloads the source data only when it is absent,
builds `data/odi_analytics.duckdb`, and then starts the API and web app. Open
`http://localhost:3000`.

See [Data setup](docs/data-setup.md) for download, attribution, checksum and
refresh details. See [Streamlit deployment](docs/streamlit-deployment.md) for
the separate public demo.

## Development checks

Run the smallest relevant checks while working, followed by the complete
available suite before opening a pull request:

```bash
pytest tests
cd frontend
npm ci
npm run build
```

Tests that exercise real analytical answers require the generated DuckDB.

## Pull requests

- Keep statistics database-backed and deterministic.
- Do not commit API keys, `.env` files, CSVs or DuckDB files.
- Add or update tests for changed behaviour.
- State the supported question family, dataset assumptions and limitations.
- Preserve explicit insufficient-evidence behaviour instead of guessing.
- Keep unrelated changes out of the pull request.

## Issues

Use an issue to describe the user question, expected evidence, data fields,
metric definition and acceptance checks. Security-sensitive reports should
not include credentials or private data in a public issue.

By contributing, you agree that your contribution is licensed under the MIT
License included in this repository.
