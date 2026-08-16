# Data setup

CricAtlas keeps large source CSV and DuckDB files out of Git. Website visitors
never need to download data themselves; the deployed application prepares it
on the server.

## Source and attribution

The enriched ODI delivery dataset is published by Himanish Ganjoo for use by
the wider cricket community. The publisher says the stable links are updated
periodically. CricAtlas downloads the original file directly and does not
redistribute it in this repository or its container image.

- Original source page: <https://himanishganjoo.com/cricket-data/>
- Direct CSV: <https://www.dropbox.com/scl/fi/ld7wj5wtyekke7h9zdtgv/odi_bbb.csv?rlkey=a9fgdu2qrma6w3w6fpcz3s2f7&dl=1>
- Publisher: Himanish Ganjoo
- Dataset licence: no formal licence is stated on the source page as of
  16 August 2026. The page permits community use, but that is not the same as
  an OSI or Creative Commons licence. CricAtlas's MIT licence covers the code,
  not this third-party dataset.
- SHA-256: not pinned because the publisher updates the file behind the stable
  link. A release can pin a checksum when reproducibility is more important
  than receiving publisher updates automatically.

## Automatic bootstrap

The same script is used by Docker and Streamlit:

```bash
python scripts/bootstrap_data.py
```

It performs the following steps:

1. Reuse `data/odi_analytics.duckdb` when it already exists.
2. Reuse `data/odi_bbb-25.csv` when only the database is missing.
3. Download Himanish Ganjoo's published ODI CSV when both are missing.
4. Verify `CRICATLAS_DATA_SHA256` when configured.
5. Extract the configured CSV from ZIP archives.
6. Build DuckDB atomically from the validated CSV schema.

Supported environment variables:

| Variable | Meaning |
|---|---|
| `CRICATLAS_DATA_URL` | Optional direct CSV/ZIP override; the published ODI CSV is the default |
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
