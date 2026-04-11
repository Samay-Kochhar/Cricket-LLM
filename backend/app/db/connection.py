from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb


@contextmanager
def get_connection(db_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        yield conn
    finally:
        conn.close()
