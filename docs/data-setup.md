# Data setup

CricAtlas keeps large source CSV and DuckDB files out of Git. Website visitors
never need to download data themselves; the deployed application prepares it
on the server.

## Source and attribution

The enriched ODI delivery dataset used by the current development environment
was provided by Himanshu Ganjoo. Before the first public release, add the
verified original download URL, licence and checksum here and in the deployment
environment. Do not substitute a similarly named dataset without validating
the required schema, especially the `line`, `length`, `shot`, `control` and
wagon-wheel fields.

Required release metadata:

- Original source page: **pending verified link**
- Direct CSV/ZIP download: **pending verified link**
- Licence: **pending verification**
- SHA-256: **pending calculation from the published artifact**
- ZIP member: `odi_bbb-25.csv` unless the published archive uses another path

## Automatic bootstrap

The same script is used by Docker and Streamlit:

```bash
python scripts/bootstrap_data.py
```

It performs the following steps:

1. Reuse `data/odi_analytics.duckdb` when it already exists.
2. Reuse `data/odi_bbb-25.csv` when only the database is missing.
3. Download `CRICATLAS_DATA_URL` when both are missing.
4. Verify `CRICATLAS_DATA_SHA256` when configured.
5. Extract the configured CSV from ZIP archives.
6. Build DuckDB atomically from the validated CSV schema.

Supported environment variables:

| Variable | Meaning |
|---|---|
| `CRICATLAS_DATA_URL` | Direct HTTP(S) URL for the source CSV or ZIP |
| `CRICATLAS_DATA_SHA256` | Optional checksum of the downloaded artifact |
| `CRICATLAS_DATA_ARCHIVE_MEMBER` | CSV path/name inside a multi-file ZIP |

The URL must return the actual file rather than an HTML download page.

## Manual fallback

If the publisher blocks automated downloads, download the file manually and
place it at `data/odi_bbb-25.csv`. Docker and Streamlit will then skip the
download and build DuckDB from that file.

## Refreshing data

After the source dataset changes, run:

```bash
python scripts/bootstrap_data.py --force-download --force-rebuild
```

Back up any local derived database you need before forcing a rebuild.
