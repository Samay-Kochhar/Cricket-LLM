from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb


@contextmanager
def get_connection(db_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        from backend.app.cricket_analytics.dismissal_sql import batting_events_sql

        available = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'analytics' AND table_name = 'deliveries_v1'"
        ).fetchone()
        if available:
            columns = {
                row[0]
                for row in conn.execute("DESCRIBE analytics.deliveries_v1").fetchall()
            }
            required = {
                "p_out",
                "p_bat",
                "out",
                "dismissal",
                "bat",
                "ballfaced",
                "batruns",
            }
            # Batting answers need to know who was dismissed (p_out). Without
            # those columns the batting view is not created, so any batting
            # query fails loudly instead of guessing from the striker's out
            # flag; bowling, venue and match queries do not need it.
            if required <= columns:
                conn.execute(
                    "CREATE TEMP VIEW batting_events_v1 AS " + batting_events_sql(columns)
                )
        yield conn
    finally:
        conn.close()
