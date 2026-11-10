"""Align AUCB fixtures that have no Cricsheet match onto ESPNcricinfo-only ODIs.

Cricsheet withholds Afghanistan matches, so ~350 ODIs exist only in the
ESPNcricinfo-style data and ~80 only in AUCB; most are the same games. Those
AUCB fixtures are aligned ball by ball onto the ESPNcricinfo ODI instead of
becoming duplicate matches.

The same-match test divides aligned balls by the shorter record, because
either record may be missing deliveries. The ESPN ODI stays the scoring record
unless it is missing more than 10% of the AUCB balls in some innings; then the
AUCB fixture scores the match and the ESPN copy is dropped
(``enrich.orphan_pairs.espn_incomplete``).
"""

from __future__ import annotations

from collections import defaultdict

import duckdb
import pyarrow as pa

from ingestion.app.multiformat.align import (
    MIN_MATCH_PRECISION,
    MIN_PRECISION_MARGIN,
    Ball,
    align_match,
    name_key,
)
from ingestion.app.multiformat.match_mapping_sql import SURNAME_SQL


def _innings(conn: duckdb.DuckDBPyConnection, where: str) -> dict[str, dict[int, list[Ball]]]:
    # Bowlers carry a Cricsheet identifier where one is known (ESPN via its
    # ESPNcricinfo ID, AUCB via the bowler alias table) so name variants align.
    rows = conn.execute(
        f"""
        SELECT b.fixture_id, b.innings, b.seq, b.over_1b - 1, b.batter, b.bowler, b.runs_bat, b.extras,
               COALESCE(b.is_wide, FALSE), COALESCE(b.is_noball, FALSE), COALESCE(b.is_wicket, FALSE),
               CASE WHEN b.src = 'espn'
                    THEN (SELECT min(k.cs_id) FROM cs_cricinfo k WHERE k.cricinfo_id = b.bowler_src_id)
                    ELSE al.cs_id END
        FROM enrich.balls b
        LEFT JOIN enrich.bowler_alias al ON b.src <> 'espn' AND al.fam = 'aucb' AND al.name = b.bowler
        WHERE {where.replace('src', 'b.src').replace('fixture_id', 'b.fixture_id')}
        ORDER BY b.fixture_id, b.innings, b.seq
        """
    ).fetchall()
    out: dict[str, dict[int, list[Ball]]] = defaultdict(lambda: defaultdict(list))
    for fixture, inn, seq, over, batter, bowler, runs, extras, wide, noball, wicket, bowler_id in rows:
        out[fixture][inn].append(
            Ball(seq, over, name_key(batter), name_key(bowler), runs, extras, wide, noball, wicket, bowler_id)
        )
    return out


def run(conn: duckdb.DuckDBPyConnection) -> int:
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE orphan_fixtures AS
        SELECT src, fixture_id, min(match_date) AS d
        FROM enrich.balls
        WHERE src IN ('aucb', 'odata') AND src_format = 'ODI'
          AND (src, fixture_id) NOT IN (SELECT (src, fixture_id) FROM enrich.fixture_match WHERE accepted)
        GROUP BY ALL;
        CREATE OR REPLACE TEMP TABLE espn_only AS
        SELECT fixture_id, min(match_date) AS d
        FROM enrich.balls
        WHERE src = 'espn' AND fixture_id NOT IN (SELECT match_id FROM cs.matches)
        GROUP BY ALL;
        CREATE OR REPLACE TEMP TABLE orphan_candidates AS
        WITH s AS (
          SELECT DISTINCT src, fixture_id, {SURNAME_SQL.format(col='batter')} AS sn FROM enrich.balls WHERE src IN ('aucb','odata')
          UNION SELECT DISTINCT src, fixture_id, {SURNAME_SQL.format(col='bowler')} FROM enrich.balls WHERE src IN ('aucb','odata')
        ),
        e AS (
          SELECT DISTINCT fixture_id, {SURNAME_SQL.format(col='batter')} AS sn FROM enrich.balls WHERE src = 'espn'
          UNION SELECT DISTINCT fixture_id, {SURNAME_SQL.format(col='bowler')} FROM enrich.balls WHERE src = 'espn'
        )
        SELECT o.src, o.fixture_id, x.fixture_id AS espn_fixture,
               count(e.sn)::DOUBLE / count(*) AS overlap
        FROM orphan_fixtures o
        JOIN espn_only x ON abs(date_diff('day', o.d, x.d)) <= 1
        JOIN s ON s.src = o.src AND s.fixture_id = o.fixture_id AND s.sn IS NOT NULL
        LEFT JOIN e ON e.fixture_id = x.fixture_id AND e.sn = s.sn
        GROUP BY ALL
        HAVING count(e.sn)::DOUBLE / count(*) >= 0.6;
        """
    )
    pairs = conn.execute("SELECT src, fixture_id, espn_fixture FROM orphan_candidates").fetchall()
    conn.execute(
        "CREATE OR REPLACE TABLE enrich.orphan_pairs (src VARCHAR, fixture_id VARCHAR, espn_fixture VARCHAR, "
        "match_share DOUBLE, espn_incomplete BOOLEAN)"
    )
    if not pairs:
        conn.execute("CREATE OR REPLACE TABLE enrich.orphan_alignment (src VARCHAR, fixture_id VARCHAR, innings INTEGER, seq BIGINT, espn_fixture VARCHAR, espn_innings INTEGER, espn_seq BIGINT, align_score DOUBLE)")
        return 0
    src_fixtures = {f for _, f, _ in pairs}
    espn_fixtures = {e for _, _, e in pairs}
    src = _innings(conn, "src IN ('aucb','odata') AND fixture_id IN (" + ",".join(f"'{f}'" for f in src_fixtures) + ")")
    espn = _innings(conn, "src = 'espn' AND fixture_id IN (" + ",".join(f"'{f}'" for f in espn_fixtures) + ")")
    candidates: dict[tuple[str, str], list[str]] = defaultdict(list)
    for s, f, e in pairs:
        candidates[(s, f)].append(e)

    rows = {k: [] for k in ["src", "fixture_id", "innings", "seq", "espn_fixture", "espn_innings", "espn_seq", "align_score"]}
    taken: set[str] = set()
    results = []
    for (s, f), espn_ids in candidates.items():
        scored = []
        for e in espn_ids:
            result = align_match(e, dict(src[f]), dict(espn[e]))
            shorter = min(result.src_balls, result.cs_balls) or 1
            scored.append((len(result.pairs) / shorter, result))
        scored.sort(key=lambda r: -r[0])
        share, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if share >= MIN_MATCH_PRECISION and share - runner_up >= MIN_PRECISION_MARGIN:
            incomplete = any(
                len(espn[best.match_id].get(inn, [])) < 0.9 * len(balls) for inn, balls in src[f].items()
            )
            results.append((share, s, f, best, incomplete))
    pair_rows = []
    for share, s, f, best, incomplete in sorted(results, key=lambda r: -r[0]):
        if best.match_id in taken:
            continue
        taken.add(best.match_id)
        pair_rows.append((s, f, best.match_id, share, incomplete))
        if incomplete:
            continue  # the AUCB fixture becomes the scoring record; nothing to link
        for s_inn, s_key, c_inn, c_key, score in best.pairs:
            for key, value in (("src", s), ("fixture_id", f), ("innings", s_inn), ("seq", s_key),
                               ("espn_fixture", best.match_id), ("espn_innings", c_inn),
                               ("espn_seq", c_key), ("align_score", score)):
                rows[key].append(value)
    conn.executemany("INSERT INTO enrich.orphan_pairs VALUES (?, ?, ?, ?, ?)", pair_rows)
    conn.register("orphan_arrow", pa.table(rows))
    conn.execute("CREATE OR REPLACE TABLE enrich.orphan_alignment AS SELECT * FROM orphan_arrow")
    conn.unregister("orphan_arrow")
    return len(taken)
