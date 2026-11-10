"""Fill blank enrichment fields from commentary text (flagged per row).

Measured on 165k aucb rows that carry both commentary and structured values:
when the parser returns a value it disagrees with the structured field on
0.00% of runs, 0.07% of lengths, 0.08% of lines and 0.24% of footwork.
"""

from __future__ import annotations

import duckdb
import pyarrow as pa

from ingestion.app.multiformat.commentary import parse


def run(conn: duckdb.DuckDBPyConnection) -> int:
    # aucb rows with neither player ID are blank placeholders: runs and extras
    # read 0 even when the ball went for four. Their run fields become NULL
    # (unknown) unless the commentary states them.
    conn.execute(
        """
        ALTER TABLE enrich.balls ADD COLUMN IF NOT EXISTS filled_from_commentary BOOLEAN DEFAULT FALSE;
        UPDATE enrich.balls SET runs_bat = NULL, extras = NULL
        WHERE src = 'aucb' AND batter_src_id IS NULL AND bowler_src_id IS NULL;
        """
    )
    rows = conn.execute(
        """
        SELECT src, fixture_id, innings, seq, commentary, batter IS NULL, bowler IS NULL,
               runs_bat IS NULL, length IS NULL, line IS NULL, footwork IS NULL
        FROM enrich.balls
        WHERE commentary IS NOT NULL
          AND (batter IS NULL OR bowler IS NULL OR runs_bat IS NULL OR length IS NULL)
        """
    ).fetchall()
    updates = {k: [] for k in ["src", "fixture_id", "innings", "seq", "batter", "bowler", "runs_bat",
                               "extras", "is_wide", "is_noball", "length", "line", "footwork"]}
    for src, fixture, inn, seq, text, no_bat, no_bowl, no_runs, no_len, no_line, no_foot in rows:
        parsed = parse(text)
        if parsed is None:
            continue
        runs_bat = extras = None
        if no_runs and parsed.runs is not None:
            if parsed.is_wide:
                runs_bat, extras = 0, parsed.runs
            elif not parsed.is_noball:
                runs_bat, extras = parsed.runs, 0
        values = {
            "batter": parsed.batter if no_bat else None,
            "bowler": parsed.bowler if no_bowl else None,
            "runs_bat": runs_bat,
            "extras": extras,
            "length": parsed.length if no_len else None,
            "line": parsed.line if no_line else None,
            "footwork": parsed.footwork if no_foot else None,
        }
        if not any(v is not None for v in values.values()):
            continue
        for key, value in (("src", src), ("fixture_id", fixture), ("innings", inn), ("seq", seq),
                           ("is_wide", parsed.is_wide), ("is_noball", parsed.is_noball), *values.items()):
            updates[key].append(value)
    if not updates["seq"]:
        return 0
    conn.register("fill_arrow", pa.table(updates))
    conn.execute(
        """
        UPDATE enrich.balls b SET
          batter = COALESCE(b.batter, f.batter),
          bowler = COALESCE(b.bowler, f.bowler),
          runs_bat = COALESCE(b.runs_bat, f.runs_bat),
          extras = COALESCE(b.extras, f.extras),
          is_wide = CASE WHEN b.runs_bat IS NULL THEN f.is_wide ELSE b.is_wide END,
          is_noball = CASE WHEN b.runs_bat IS NULL THEN f.is_noball ELSE b.is_noball END,
          length = COALESCE(b.length, f.length),
          line = COALESCE(b.line, f.line),
          footwork = COALESCE(b.footwork, f.footwork),
          filled_from_commentary = TRUE
        FROM fill_arrow f
        WHERE b.src = f.src AND b.fixture_id = f.fixture_id AND b.innings = f.innings AND b.seq = f.seq
        """
    )
    conn.unregister("fill_arrow")
    return len(updates["seq"])
