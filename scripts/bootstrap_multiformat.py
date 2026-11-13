"""Fetch the prepared all-format records once; never rebuild existing databases."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from scripts.bootstrap_data import DataBootstrapError, _download, _sha256

_LOCK = threading.Lock()
MANIFEST = Path(__file__).resolve().parents[1] / "data" / "multiformat-download.json"


def ensure_multiformat_database(db_path: Path, manifest_path: Path = MANIFEST) -> Path:
    """Reuse existing records, or verify and atomically place a downloaded copy."""
    if db_path.is_file():
        return db_path
    with _LOCK:
        if db_path.is_file():
            return db_path
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cricatlas-records-", dir=db_path.parent) as work:
            archive = Path(work) / "records.gz"
            prepared = Path(work) / "records.duckdb"
            _download(manifest["url"], archive)
            if _sha256(archive) != manifest["sha256"]:
                raise DataBootstrapError("The cricket records download was incomplete or changed. Please retry.")
            with gzip.open(archive, "rb") as source, prepared.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            if prepared.stat().st_size != manifest["database_bytes"]:
                raise DataBootstrapError("The cricket records file has an unexpected size. Please retry.")
            import duckdb

            connection = duckdb.connect(str(prepared), read_only=True)
            try:
                connection.execute("SELECT format, gender FROM analytics.coverage_summary LIMIT 1").fetchall()
                connection.execute("SELECT match_id FROM analytics.deliveries LIMIT 1").fetchall()
            finally:
                connection.close()
            # Another process may have finished while this one was downloading.
            if not db_path.exists():
                os.replace(prepared, db_path)
        return db_path
