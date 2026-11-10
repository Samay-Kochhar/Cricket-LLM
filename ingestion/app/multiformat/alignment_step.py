"""Run ball-level alignment for every AUCB fixture and store the results.

Two passes. Bowler identity is compared by Cricsheet identifier where a source
name is known to belong to one, so name variants ("Mehidy Hasan" for
"Mehedi Hasan Miraz", "Wanindu Hasaranga" for "PWH de Silva") still align:

1. Aliases come from Cricsheet's names.csv (names that point at one
   identifier). Every fixture is aligned.
2. In accepted fixtures, each source over's bowler is paired with the bowler
   of the Cricsheet over it aligned to. A name that maps to one identifier on
   at least 98% of at least 3 overs becomes an alias, and alignment reruns.
"""

from __future__ import annotations

from collections import defaultdict

import duckdb
import pyarrow as pa

from ingestion.app.multiformat.align import (
    MIN_MATCH_PRECISION,
    MIN_PRECISION_MARGIN,
    Ball,
    Innings,
    name_key,
    run_alignment,
)

CANDIDATE_MIN_OVERLAP = 0.6
ALIAS_MIN_PURITY = 0.98
ALIAS_MIN_OVERS = 3

NAMES_ALIAS_SQL = """
CREATE OR REPLACE TABLE enrich.bowler_alias AS
SELECT fam, name, cs_id, 'names.csv' AS origin
FROM (SELECT DISTINCT bowler AS name FROM enrich.balls WHERE bowler IS NOT NULL) b
CROSS JOIN (SELECT 'aucb' AS fam UNION ALL SELECT 'espn') f
JOIN (
  SELECT name, any_value(identifier) AS cs_id FROM read_csv('{names}', all_varchar = true, header = true)
  GROUP BY name HAVING count(DISTINCT identifier) = 1
) n USING (name);
"""

LEARNED_ALIAS_SQL = f"""
CREATE OR REPLACE TABLE enrich.bowler_alias AS
WITH off AS (
  SELECT a.src, a.fixture_id, a.innings, mode(d.over_no - (b.over_1b - 1)) AS over_offset
  FROM enrich.ball_alignment a
  JOIN enrich.balls b USING (src, fixture_id, innings, seq)
  JOIN cs.deliveries d USING (match_id, innings_no, innings_delivery_seq)
  GROUP BY ALL
),
src_over AS (
  SELECT src, fixture_id, innings, over_1b - 1 AS over0, any_value(bowler) AS bowler
  FROM enrich.balls WHERE bowler IS NOT NULL GROUP BY ALL HAVING count(DISTINCT bowler) = 1
),
cs_over AS (
  SELECT match_id, innings_no, over_no, any_value(bowler_id) AS bowler_id
  FROM cs.deliveries WHERE bowler_id IS NOT NULL GROUP BY ALL HAVING count(DISTINCT bowler_id) = 1
),
pairs AS (
  SELECT CASE WHEN s.src = 'espn' THEN 'espn' ELSE 'aucb' END AS fam, s.bowler AS name, c.bowler_id AS cs_id,
         count(*) AS n
  FROM src_over s
  JOIN off o USING (src, fixture_id, innings)
  JOIN enrich.fixture_match f ON f.src = s.src AND f.fixture_id = s.fixture_id AND f.accepted
  JOIN cs_over c ON c.match_id = f.match_id AND c.innings_no = s.innings AND c.over_no = s.over0 + o.over_offset
  GROUP BY ALL
),
learned AS (
  SELECT fam, name, arg_max(cs_id, n) AS cs_id
  FROM pairs GROUP BY ALL
  HAVING max(n)::DOUBLE / sum(n) >= {ALIAS_MIN_PURITY} AND sum(n) >= {ALIAS_MIN_OVERS}
)
SELECT fam, name, cs_id, 'learned' AS origin FROM learned
UNION ALL
SELECT a.fam, a.name, a.cs_id, a.origin FROM enrich.bowler_alias a
WHERE NOT EXISTS (SELECT 1 FROM learned l WHERE l.fam = a.fam AND l.name = a.name);
"""


def _load_src(conn: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], Innings]:
    rows = conn.execute(
        """
        SELECT b.src, b.fixture_id, b.innings, b.seq, b.over_1b - 1, b.batter, b.bowler,
               b.runs_bat, b.extras, COALESCE(b.is_wide, FALSE),
               COALESCE(b.is_noball, FALSE), COALESCE(b.is_wicket, FALSE), al.cs_id
        FROM enrich.balls b
        LEFT JOIN enrich.bowler_alias al
          ON al.fam = CASE WHEN b.src = 'espn' THEN 'espn' ELSE 'aucb' END AND al.name = b.bowler
        WHERE (b.src, b.fixture_id) IN (
          SELECT (src, fixture_id) FROM enrich.map_candidates WHERE overlap >= ?
        )
        ORDER BY b.src, b.fixture_id, b.innings, b.seq
        """,
        [CANDIDATE_MIN_OVERLAP],
    ).fetchall()
    out: dict[tuple[str, str], Innings] = defaultdict(lambda: defaultdict(list))
    for src, fixture, inn, seq, over, batter, bowler, runs, extras, wide, noball, wicket, bowler_id in rows:
        out[(src, fixture)][inn].append(
            Ball(seq, over, name_key(batter), name_key(bowler), runs, extras, wide, noball, wicket, bowler_id)
        )
    return out


def _load_cs(conn: duckdb.DuckDBPyConnection) -> dict[str, Innings]:
    rows = conn.execute(
        """
        SELECT d.match_id, d.innings_no, d.innings_delivery_seq, d.over_no, d.batter, d.bowler,
               d.runs_batter, d.runs_extras, d.wides IS NOT NULL, d.noballs IS NOT NULL,
               d.wicket_count > 0, d.bowler_id
        FROM cs.deliveries d
        WHERE d.match_id IN (SELECT match_id FROM enrich.map_candidates WHERE overlap >= ?)
        ORDER BY d.match_id, d.innings_no, d.innings_delivery_seq
        """,
        [CANDIDATE_MIN_OVERLAP],
    ).fetchall()
    out: dict[str, Innings] = defaultdict(lambda: defaultdict(list))
    for mid, inn, seq, over, batter, bowler, runs, extras, wide, noball, wicket, bowler_id in rows:
        out[mid][inn].append(
            Ball(seq, over, name_key(batter), name_key(bowler), runs, extras, wide, noball, wicket, bowler_id)
        )
    return out


def run(conn: duckdb.DuckDBPyConnection, names_csv, workers: int = 8) -> dict[str, int]:
    conn.execute(NAMES_ALIAS_SQL.format(names=names_csv))
    cs = _load_cs(conn)
    first = _align_pass(conn, cs, workers)
    conn.execute(LEARNED_ALIAS_SQL)
    second = _align_pass(conn, cs, workers)
    aliases = conn.execute("SELECT origin, count(*) FROM enrich.bowler_alias GROUP BY 1 ORDER BY 1").fetchall()
    return {**second, "first_pass_accepted": first["fixtures_accepted"], "bowler_aliases": dict(aliases)}


def _align_pass(conn: duckdb.DuckDBPyConnection, cs: dict[str, Innings], workers: int) -> dict[str, int]:
    src = _load_src(conn)
    candidates: dict[tuple[str, str], list[str]] = defaultdict(list)
    for s, fixture, mid in conn.execute(
        "SELECT src, fixture_id, match_id FROM enrich.map_candidates WHERE overlap >= ? ORDER BY ALL",
        [CANDIDATE_MIN_OVERLAP],
    ).fetchall():
        candidates[(s, fixture)].append(mid)

    jobs = [
        (s, fixture, dict(src[(s, fixture)]), {mid: dict(cs[mid]) for mid in mids if mid in cs})
        for (s, fixture), mids in candidates.items()
        if (s, fixture) in src
    ]

    choice_rows: list[dict] = []
    pair_rows: dict[tuple[str, str], list[tuple]] = {}
    for s, fixture, best, agreements in run_alignment(jobs, workers=workers):
        if best is None:
            continue
        ranked = sorted(agreements.values(), reverse=True)
        choice_rows.append(
            {
                "src": s,
                "fixture_id": fixture,
                "match_id": best.match_id,
                "precision": best.precision,
                "coverage": best.coverage,
                "runner_up_precision": ranked[1] if len(ranked) > 1 else None,
                "candidates": len(agreements),
                "src_balls": best.src_balls,
                "cs_balls": best.cs_balls,
                "aligned_balls": len(best.pairs),
            }
        )
        pair_rows[(s, fixture)] = best.pairs

    conn.register(
        "choice_arrow",
        pa.Table.from_pylist(
            choice_rows,
            schema=pa.schema(
                [
                    ("src", pa.string()),
                    ("fixture_id", pa.string()),
                    ("match_id", pa.string()),
                    ("precision", pa.float64()),
                    ("coverage", pa.float64()),
                    ("runner_up_precision", pa.float64()),
                    ("candidates", pa.int32()),
                    ("src_balls", pa.int32()),
                    ("cs_balls", pa.int32()),
                    ("aligned_balls", pa.int32()),
                ]
            ),
        ),
    )
    # A fixture is accepted when its best candidate is precise and clearly ahead
    # of the runner-up; a Cricsheet match then takes its most precise fixture
    # per source family (AUCB feed: aucb/odata; ESPNcricinfo: espn).
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE enrich.fixture_match AS
        SELECT *,
               precision >= {MIN_MATCH_PRECISION}
               AND precision - COALESCE(runner_up_precision, 0) >= {MIN_PRECISION_MARGIN}
               AND row_number() OVER (
                     PARTITION BY match_id, src = 'espn'
                     ORDER BY precision DESC, coverage DESC, src, fixture_id
                   ) = 1
               AS accepted
        FROM choice_arrow
        """
    )
    conn.unregister("choice_arrow")

    accepted = {
        (s, f)
        for s, f in conn.execute("SELECT src, fixture_id FROM enrich.fixture_match WHERE accepted").fetchall()
    }
    flat = {
        "src": [],
        "fixture_id": [],
        "innings": [],
        "seq": [],
        "match_id": [],
        "innings_no": [],
        "innings_delivery_seq": [],
        "align_score": [],
    }
    match_of = {(r["src"], r["fixture_id"]): r["match_id"] for r in choice_rows}
    for key, pairs in pair_rows.items():
        if key not in accepted:
            continue
        for s_inn, s_key, c_inn, c_key, score in pairs:
            flat["src"].append(key[0])
            flat["fixture_id"].append(key[1])
            flat["innings"].append(s_inn)
            flat["seq"].append(s_key)
            flat["match_id"].append(match_of[key])
            flat["innings_no"].append(c_inn)
            flat["innings_delivery_seq"].append(c_key)
            flat["align_score"].append(score)
    conn.register("pairs_arrow", pa.table(flat))
    conn.execute("CREATE OR REPLACE TABLE enrich.ball_alignment AS SELECT * FROM pairs_arrow")
    conn.unregister("pairs_arrow")
    return {
        "fixtures_aligned": len(choice_rows),
        "fixtures_accepted": len(accepted),
        "balls_aligned": len(flat["seq"]),
    }
