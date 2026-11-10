"""Validation battery for data/cricket_all.duckdb.

Every check records what was expected and what was found. Hard checks fail the
build; "info" checks are measurements published for transparency. Results go
into ``analytics.validation_checks`` and docs/data-validation.md, and the
user-facing limitation statements into ``analytics.data_limitations`` and
docs/data-coverage.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "data" / "build"

ESPN_LENGTHS = ("YORKER", "FULL_TOSS", "FULL", "GOOD_LENGTH", "SHORT_OF_A_GOOD_LENGTH", "SHORT")
ESPN_LINES = ("OUTSIDE_OFFSTUMP", "ON_THE_STUMPS", "WIDE_OUTSIDE_OFFSTUMP", "DOWN_LEG", "WIDE_DOWN_LEG")


@dataclass
class Check:
    family: str
    name: str
    expected: str
    actual: str
    passed: bool
    hard: bool = True

    @property
    def status(self) -> str:
        if self.passed:
            return "PASS"
        return "FAIL" if self.hard else "INFO"


def _one(conn: duckdb.DuckDBPyConnection, sql: str):
    return conn.execute(sql).fetchone()


def _checks(conn: duckdb.DuckDBPyConnection) -> list[Check]:
    checks: list[Check] = []

    def add(family, name, expected, actual, passed, hard=True):
        checks.append(Check(family, name, expected, str(actual), bool(passed), hard))

    # --- Integrity -------------------------------------------------------
    dup, total = _one(conn, "SELECT count(*) - count(DISTINCT (match_id, innings_no, innings_delivery_seq)), count(*) FROM analytics.deliveries")
    add("Integrity", "No duplicate deliveries", "0", f"{dup} of {total:,}", dup == 0)
    dup_m = _one(conn, "SELECT count(*) - count(DISTINCT match_id) FROM analytics.matches")[0]
    add("Integrity", "No duplicate matches", "0", dup_m, dup_m == 0)
    orphans = _one(conn, "SELECT count(*) FROM analytics.deliveries WHERE match_id NOT IN (SELECT match_id FROM analytics.matches)")[0]
    add("Integrity", "Every delivery belongs to a match", "0 orphans", orphans, orphans == 0)
    empty = _one(conn, "SELECT count(*) FROM analytics.matches WHERE match_id NOT IN (SELECT DISTINCT match_id FROM analytics.deliveries)")[0]
    add("Integrity", "Every match has deliveries", "0 empty matches", empty, empty == 0)
    src_cs = _one(conn, f"SELECT count(*) FROM '{BUILD / 'cs_deliveries.parquet'}'")[0]
    pub_cs = _one(conn, "SELECT count(*) FROM analytics.deliveries WHERE score_source = 'cricsheet'")[0]
    add("Integrity", "Every Cricsheet delivery published once", f"{src_cs:,}", f"{pub_cs:,}", src_cs == pub_cs)
    diff = _one(
        conn,
        f"""
        WITH s AS (SELECT match_id, innings_no, sum(runs_total) r, sum(wicket_count) w FROM '{BUILD / 'cs_deliveries.parquet'}' GROUP BY ALL),
             p AS (SELECT match_id, innings_no, sum(runs_total) r FROM analytics.deliveries WHERE score_source = 'cricsheet' GROUP BY ALL)
        SELECT count(*) FROM s FULL JOIN p USING (match_id, innings_no) WHERE s.r IS DISTINCT FROM p.r
        """,
    )[0]
    add("Integrity", "Cricsheet innings totals unchanged by enrichment", "0 innings differ", diff, diff == 0)

    # --- Known scorecards --------------------------------------------------
    for label, mid, inns, runs, wkts in [
        ("2023 ODI World Cup final, India", "1384439", 1, 240, 10),
        ("2023 ODI World Cup final, Australia", "1384439", 2, 241, 4),
        ("2024 T20 World Cup final, India", "1415755", 1, 176, 7),
        ("2024 T20 World Cup final, South Africa", "1415755", 2, 169, 8),
    ]:
        got = _one(conn, f"SELECT sum(runs_total), count(*) FILTER (is_wicket) FROM analytics.deliveries WHERE match_id = '{mid}' AND innings_no = {inns}")
        add("Known scorecards", label, f"{runs}/{wkts}", f"{got[0]}/{got[1]}", got == (runs, wkts))

    # --- Independent cross-check against TigZig -----------------------------
    # TigZig (tigzig.com/apis/database) republishes Cricsheet internationals and
    # the IPL. Its copy is downloaded separately, so agreement confirms our parse.
    tigzig = ROOT / "data" / "sources" / "tigzig" / "cricket_all_tables.duckdb"
    if tigzig.exists():
        conn.execute(f"ATTACH IF NOT EXISTS '{tigzig}' AS tigzig (READ_ONLY)")
        tz = _one(
            conn,
            """
            WITH t AS (SELECT CAST(match_id AS VARCHAR) AS match_id, innings, sum(runs_off_bat + extras) AS r,
                              count(*) AS balls
                       FROM tigzig.ball_by_ball GROUP BY ALL),
                 o AS (SELECT match_id, innings_no AS innings, sum(runs_total) AS r, count(*) AS balls
                       FROM analytics.deliveries WHERE score_source = 'cricsheet' GROUP BY ALL)
            SELECT count(*), count(*) FILTER (t.r = o.r AND t.balls = o.balls),
                   (SELECT count(DISTINCT match_id) FROM tigzig.ball_by_ball),
                   (SELECT count(DISTINCT CAST(match_id AS VARCHAR)) FROM tigzig.ball_by_ball
                     WHERE CAST(match_id AS VARCHAR) NOT IN (SELECT match_id FROM analytics.matches))
            FROM t JOIN o USING (match_id, innings)
            """,
        )
        add("TigZig cross-check", "Innings runs and ball counts identical to TigZig's copy of the same matches",
            ">= 99.9%", f"{tz[1]:,} of {tz[0]:,} innings ({tz[1] / tz[0]:.3%})", tz[1] >= 0.999 * tz[0])
        add("TigZig cross-check", "TigZig matches missing from CricAtlas (TigZig refreshes twice daily)",
            "only matches newer than our Cricsheet download", f"{tz[3]:,} of {tz[2]:,}", tz[3] <= 50)
    else:
        add("TigZig cross-check", "TigZig copy present at data/sources/tigzig/", "info", "not downloaded; skipped",
            True, hard=False)

    # --- Score source accuracy (measured) --------------------------------
    tgt = _one(
        conn,
        """
        WITH i1 AS (SELECT match_id, sum(runs_total) r FROM analytics.deliveries
                    WHERE score_source = 'cricsheet' AND innings_no = 1 GROUP BY 1),
             t AS (SELECT match_id, max(target_runs) tr FROM analytics.deliveries
                   WHERE score_source = 'cricsheet' AND innings_no = 2 GROUP BY 1)
        SELECT count(*), count(*) FILTER (i1.r + 1 = t.tr)
        FROM i1 JOIN t USING (match_id) JOIN analytics.matches m USING (match_id)
        WHERE m.method IS NULL AND t.tr IS NOT NULL AND m.format IN ('ODI', 'T20I', 'T20 domestic', 'The Hundred')
        """,
    )
    rate = tgt[1] / tgt[0] if tgt[0] else 0
    add("Score accuracy", "Cricsheet first-innings total + 1 equals the official target (no DLS)",
        ">= 99%", f"{rate:.2%} of {tgt[0]:,} matches", rate >= 0.99)

    # --- Canonical vocabulary --------------------------------------------
    bad_len = _one(conn, f"SELECT count(*) FROM analytics.deliveries WHERE length IS NOT NULL AND length NOT IN {ESPN_LENGTHS}")[0]
    add("Line/length", "Canonical length uses the CricAtlas vocabulary", "0 other values", bad_len, bad_len == 0)
    bad_line = _one(conn, f"SELECT count(*) FROM analytics.deliveries WHERE line IS NOT NULL AND line NOT IN {ESPN_LINES}")[0]
    add("Line/length", "Canonical line uses the CricAtlas vocabulary", "0 other values", bad_line, bad_line == 0)
    no_src = _one(conn, "SELECT count(*) FROM analytics.deliveries WHERE (length IS NOT NULL OR line IS NOT NULL) AND ll_source IS NULL")[0]
    add("Line/length", "Every line/length value names its source", "0", no_src, no_src == 0)
    women = _one(conn, "SELECT count(*) FROM analytics.deliveries WHERE gender = 'female' AND (length IS NOT NULL OR line IS NOT NULL)")[0]
    add("Line/length", "No line/length attached to women's matches (no source has it)", "0", women, women == 0)

    # --- Alignment quality --------------------------------------------------
    prec = _one(conn, "SELECT min(precision), quantile_cont(precision, 0.01), count(*) FROM analytics.source_fixture_map WHERE accepted")
    add("Alignment", "Accepted source fixtures: share of their balls matched to a Cricsheet ball",
        "every fixture >= 80%", f"min {prec[0]:.1%}, 1st percentile {prec[1]:.1%}, {prec[2]:,} fixtures", prec[0] >= 0.8)
    agree = _one(
        conn,
        """
        SELECT count(*),
               avg((lower(regexp_extract(strip_accents(split_part(commentary, ' to ', 1)), '([A-Za-z]+)$', 1))
                    = lower(regexp_extract(strip_accents(bowler), '([A-Za-z]+)$', 1)))::INT)
        FROM analytics.deliveries
        WHERE ll_source IN ('aucb', 'odata') AND commentary LIKE '% to %' AND NOT feed_filled_from_commentary
          AND score_source = 'cricsheet' AND length(split_part(commentary, ' to ', 1)) < 40
          AND commentary NOT LIKE '%!%'
        """,
    )
    add("Alignment", "Attached AUCB ball names the same bowler as Cricsheet (surname, from commentary)",
        ">= 98%", f"{agree[1]:.2%} of {agree[0]:,} balls", agree[1] >= 0.98)
    runs = _one(
        conn,
        """
        WITH f AS (
          SELECT d.runs_batter, b.runs_bat
          FROM analytics.deliveries d
          JOIN work.enrich.ball_alignment a ON a.match_id = d.match_id AND a.innings_no = d.innings_no
           AND a.innings_delivery_seq = d.innings_delivery_seq AND a.src IN ('aucb', 'odata')
          JOIN work.enrich.balls b ON b.src = a.src AND b.fixture_id = a.fixture_id AND b.innings = a.innings AND b.seq = a.seq
          WHERE b.runs_bat IS NOT NULL
        )
        SELECT count(*), avg((runs_batter = runs_bat)::INT) FROM f
        """,
    )
    add("Alignment", "Attached AUCB ball has the same runs off the bat as Cricsheet",
        ">= 97%", f"{runs[1]:.2%} of {runs[0]:,} balls", runs[1] >= 0.97)

    feed = _one(
        conn,
        """
        WITH a AS (SELECT fixture_id, innings, sum(runs_bat + extras) r FROM work.enrich.balls WHERE src = 'aucb' GROUP BY ALL),
             m AS (SELECT fixture_id, match_id FROM work.enrich.fixture_match WHERE src = 'aucb' AND accepted),
             c AS (SELECT match_id, innings_no, sum(runs_total) r FROM analytics.deliveries
                   WHERE score_source = 'cricsheet' GROUP BY ALL)
        SELECT count(*), avg((a.r = c.r)::INT), avg((abs(a.r - c.r) <= 5)::INT)
        FROM a JOIN m USING (fixture_id) JOIN c ON c.match_id = m.match_id AND c.innings_no = a.innings
        """,
    )
    add("Score accuracy", "AUCB innings totals vs Cricsheet (applies to the AUCB-only matches)", "info",
        f"exact {feed[1]:.1%}, within 5 runs {feed[2]:.1%}, over {feed[0]:,} innings", True, hard=False)

    # --- Duplicates across sources ---------------------------------------
    dup_x = _one(
        conn,
        """
        SELECT count(*) FROM analytics.matches x JOIN analytics.matches c
          ON c.score_source = 'cricsheet' AND x.score_source <> 'cricsheet'
         AND c.gender = x.gender AND c.format = x.format
         AND abs(date_diff('day', c.start_date, x.start_date)) <= 1
         AND ((c.team1 = x.team1 AND c.team2 = x.team2) OR (c.team1 = x.team2 AND c.team2 = x.team1))
         AND (SELECT sum(runs_total) FROM analytics.deliveries d WHERE d.match_id = c.match_id AND d.innings_no = 1)
           = (SELECT sum(runs_total) FROM analytics.deliveries d WHERE d.match_id = x.match_id AND d.innings_no = 1)
        """,
    )[0]
    add("No double counting",
        "Non-Cricsheet matches that repeat a Cricsheet match (same teams, format, date +-1, first-innings total)",
        "0", dup_x, dup_x == 0)
    dup_e = _one(
        conn,
        """
        SELECT count(*) FROM analytics.matches x JOIN analytics.matches e
          ON e.score_source = 'espn' AND x.score_source IN ('aucb', 'odata') AND x.format = e.format
         AND abs(date_diff('day', e.start_date, x.start_date)) <= 1
         AND ((e.team1 = x.team1 AND e.team2 = x.team2) OR (e.team1 = x.team2 AND e.team2 = x.team1))
        """,
    )[0]
    add("No double counting", "AUCB-only matches that look like an ESPN-only ODI", "0", dup_e, dup_e == 0)

    # --- Player attributes -------------------------------------------------
    for unique_name, field, expected in [
        ("MA Starc", "bowling_style_group", "Left-arm pace"),
        ("PJ Cummins", "bowling_style_group", "Right-arm pace"),
        ("Kuldeep Yadav", "bowling_style_group", "Left-arm wrist spin"),
        ("Rashid Khan", "bowling_style_group", "Right-arm leg spin"),
        ("RA Jadeja", "bowling_style_group", "Left-arm orthodox"),
        ("TA Boult", "bowling_arm", "Left"),
        ("DA Warner", "batting_hand", "LHB"),
        ("V Kohli", "batting_hand", "RHB"),
    ]:
        got = _one(conn, f"SELECT {field} FROM analytics.players WHERE unique_name = '{unique_name}'")
        add("Player attributes", f"{unique_name} {field}", expected, got[0] if got else None, got and got[0] == expected)
    hand = _one(
        conn,
        """
        SELECT count(*), avg((aucb.bowling_arm = espn.bowling_arm)::INT)
        FROM analytics.players espn
        JOIN analytics.players aucb USING (player_id)
        WHERE espn.bowling_style_source = 'espn'
        """,
    )
    add("Player attributes", "Players with an ESPN bowling style", "info", f"{hand[0]:,}", True, hard=False)
    flip = _one(
        conn,
        """
        WITH fx AS (
          SELECT b.fixture_id, min(b.match_date) AS d, avg((b.bowling_hand_raw = p.bowling_arm)::INT) AS agree
          FROM work.enrich.ball_alignment a
          JOIN work.enrich.balls b USING (src, fixture_id, innings, seq)
          JOIN analytics.deliveries d ON d.match_id = a.match_id AND d.innings_no = a.innings_no
           AND d.innings_delivery_seq = a.innings_delivery_seq
          JOIN analytics.players p ON p.player_id = d.bowler_id AND p.bowling_style_source = 'espn'
          WHERE a.src = 'aucb' AND b.bowling_hand_raw IN ('Left', 'Right')
          GROUP BY 1 HAVING count(*) >= 30
        )
        SELECT count(*) FILTER (d <= DATE '2023-02-26'), count(*) FILTER (d <= DATE '2023-02-26' AND agree <= 0.25),
               count(*) FILTER (d > DATE '2023-02-26'), count(*) FILTER (d > DATE '2023-02-26' AND agree >= 0.75)
        FROM fx
        """,
    )
    add("Player attributes", "AUCB bowling-hand field inverted up to 2023-02-26 and correct after (vs ESPN styles)",
        "all fixtures follow the switch date",
        f"{flip[1]:,}/{flip[0]:,} earlier inverted, {flip[3]:,}/{flip[2]:,} later correct",
        flip[1] == flip[0] and flip[3] == flip[2])

    # --- Sanity for single-source matches ----------------------------------
    over_limit = _one(
        conn,
        """
        SELECT count(*) FROM (
          SELECT d.match_id, d.innings_no, m.format, count(*) FILTER (d.is_legal) AS legal
          FROM analytics.deliveries d JOIN analytics.matches m USING (match_id)
          WHERE m.score_source <> 'cricsheet' GROUP BY ALL
        ) WHERE ((format IN ('T20I', 'T20 domestic') AND legal > 120) OR (format = 'ODI' AND legal > 300)
             OR (format = 'The Hundred' AND legal > 100))
          AND match_id NOT IN (SELECT match_id FROM analytics.matches WHERE quality_note IS NOT NULL)
        """,
    )[0]
    add("Single-source matches", "Every innings over its legal-ball maximum carries a quality note", "0 unnoted", over_limit, over_limit == 0)
    noted = _one(conn, "SELECT count(*) FROM analytics.matches WHERE quality_note IS NOT NULL")[0]
    excluded = _one(conn, "SELECT count(*) FROM analytics.excluded_matches")[0]
    add("Single-source matches", "Matches kept with a quality note / excluded as corrupt", "info",
        f"{noted} noted, {excluded} excluded", True, hard=False)
    return checks


def _availability(field: str, frm, to, regular_from, pct, who: str, fmt: str) -> str:
    if frm is None:
        return f"{field} is not recorded for {who} {fmt} in any source."
    if regular_from is None:
        if frm == to:
            return f"{field} exists for only one match day ({frm:%d %b %Y}); treat it as unavailable."
        return f"{field} exists only sparsely ({frm:%b %Y} to {to:%b %Y}); treat it as unavailable."
    return f"{field} is available from {regular_from} to {to:%d %b %Y}, on {pct}% of deliveries in that period."


def _limitations(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """
        SELECT format, gender, matches, ball_by_ball_from, ball_by_ball_to,
               length_from, length_to, length_regular_from_year, length_pct_in_period,
               line_from, line_to, line_regular_from_year, line_pct_in_period
        FROM analytics.coverage_summary ORDER BY gender DESC, matches DESC
        """
    ).fetchall()
    out: list[tuple[str, str, str]] = []
    for (fmt, gender, matches, bbb_from, bbb_to, len_from, len_to, len_reg, len_pct,
         line_from, line_to, line_reg, line_pct) in rows:
        who = "men's" if gender == "male" else "women's"
        parts = [f"Ball-by-ball {who} {fmt} data covers {matches:,} matches from {bbb_from:%d %b %Y} to {bbb_to:%d %b %Y}."]
        if len_from is None and line_from is None:
            parts.append(f"Line and length are not recorded for {who} {fmt} in any source.")
        else:
            parts.append(_availability("Length", len_from, len_to, len_reg, len_pct, who, fmt))
            parts.append(_availability("Line", line_from, line_to, line_reg, line_pct, who, fmt))
        out.append((fmt, gender, " ".join(parts)))
    return out


def _yearly(conn: duckdb.DuckDBPyConnection, fmt: str) -> str:
    rows = conn.execute(
        f"""
        SELECT year, matches, length_pct, line_pct FROM analytics.coverage_by_year
        WHERE format = '{fmt}' AND gender = 'male' AND year >= 2012 ORDER BY year
        """
    ).fetchall()
    lines = ["| Year | Matches | Length % | Line % |", "|---|---|---|---|"]
    lines += [f"| {y} | {m:,} | {lp} | {li} |" for y, m, lp, li in rows]
    return "\n".join(lines)


def run(db_path: Path, docs: Path) -> int:
    conn = duckdb.connect(str(db_path))
    conn.execute(f"ATTACH '{BUILD / 'work.duckdb'}' AS work (READ_ONLY)")
    try:
        checks = _checks(conn)
        limitations = _limitations(conn)
        conn.execute(
            "CREATE OR REPLACE TABLE analytics.validation_checks (family VARCHAR, name VARCHAR, expected VARCHAR, actual VARCHAR, status VARCHAR)"
        )
        conn.executemany(
            "INSERT INTO analytics.validation_checks VALUES (?, ?, ?, ?, ?)",
            [(c.family, c.name, c.expected, c.actual, c.status) for c in checks],
        )
        conn.execute("CREATE OR REPLACE TABLE analytics.data_limitations (format VARCHAR, gender VARCHAR, statement VARCHAR)")
        conn.executemany("INSERT INTO analytics.data_limitations VALUES (?, ?, ?)", limitations)
        info = conn.execute("SELECT * FROM analytics.build_info").fetchone()
        summary = conn.execute(
            """
            SELECT format, gender, matches, ball_by_ball_from, ball_by_ball_to,
                   length_regular_from_year, length_to, length_pct_in_period,
                   line_regular_from_year, line_to, line_pct_in_period
            FROM analytics.coverage_summary ORDER BY gender DESC, matches DESC
            """
        ).fetchall()
        yearly = {fmt: _yearly(conn, fmt) for fmt in ["Test", "ODI", "T20I", "T20 domestic", "First-class domestic"]}
        competitions = conn.execute(
            """
            SELECT competition, format, matches, first_match, last_match, ll_pct, ll_first_match, ll_last_match
            FROM analytics.coverage
            WHERE gender = 'male' AND format IN ('T20 domestic', 'The Hundred') AND matches >= 30
            ORDER BY matches DESC
            """
        ).fetchall()
    finally:
        conn.close()

    failures = sum(1 for c in checks if c.status == "FAIL")
    _write_validation(docs / "data-validation.md", checks, info)
    _write_coverage(docs / "data-coverage.md", info, summary, limitations, yearly, competitions)
    for c in checks:
        print(f"  {c.status:4}  {c.family}: {c.name} -> {c.actual}")
    return failures


def _write_validation(path: Path, checks: list[Check], info) -> None:
    lines = [
        "# Multi-format data validation",
        "",
        f"Generated by `python -m ingestion.app.multiformat.build` on {info[0]:%Y-%m-%d %H:%M}.",
        "FAIL marks a broken expectation; INFO rows are measurements published for transparency.",
        "",
        "| Status | Family | Check | Expected | Actual |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {c.status} | {c.family} | {c.name} | {c.expected} | {c.actual} |" for c in checks]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_coverage(path: Path, info, summary, limitations, yearly, competitions) -> None:
    built, cs_latest, aucb_latest, espn_latest, matches, deliveries = info
    lines = [
        "# CricAtlas data coverage and limitations",
        "",
        f"Generated on {built:%Y-%m-%d}. The multi-format database (`data/cricket_all.duckdb`) holds "
        f"{matches:,} matches and {deliveries:,} deliveries.",
        "",
        f"- Latest Cricsheet match: {cs_latest:%d %b %Y}",
        f"- Latest AUCB (line/length) match: {aucb_latest:%d %b %Y}",
        f"- Latest ESPNcricinfo-style ODI: {espn_latest:%d %b %Y}",
        "",
        "## What to tell users",
        "",
        "Each statement below is also stored in `analytics.data_limitations` so the app can quote it.",
        "",
    ]
    lines += [f"- **{fmt} ({gender})**: {text}" for fmt, gender, text in limitations]
    lines += [
        "",
        "Line and length come only from the AUCB feed (2012-2026, men's) and the ESPNcricinfo-style",
        "ODI data (2014-2025). No source records them for women's cricket, for most associate",
        "matches, or for games older than these ranges. Analyses that need line or length must say",
        "so when a player's matches fall outside the covered period.",
        "",
        "## Summary by format",
        "",
        "| Format | Gender | Matches | Ball-by-ball from | Ball-by-ball to | Length from | Length to | Length % in period | Line from | Line to | Line % in period |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for fmt, gender, m, f, t, lf, lt, lp, nf, nt, np_ in summary:
        lines.append(
            f"| {fmt} | {gender} | {m:,} | {f} | {t} | {lf or '-'} | {lt if lf else '-'} | {lp if lf else '-'} "
            f"| {nf or '-'} | {nt if nf else '-'} | {np_ if nf else '-'} |"
        )
    lines += ["", "## Men's line/length coverage by year", ""]
    for fmt, table in yearly.items():
        lines += [f"### {fmt}", "", table, ""]
    lines += [
        "## Men's T20 leagues",
        "",
        "| Competition | Format | Matches | First | Last | % deliveries with line/length | Line/length first | Line/length last |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for comp, fmt, m, f, t, pct, lf, lt in competitions:
        lines.append(f"| {comp} | {fmt} | {m:,} | {f} | {t} | {pct} | {lf or '-'} | {lt or '-'} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(run(ROOT / "data" / "cricket_all.duckdb", ROOT / "docs"))
