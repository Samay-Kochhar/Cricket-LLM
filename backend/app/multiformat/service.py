"""Read-only access to the multi-format database (data/cricket_all.duckdb).

Covers every format in the database (Tests, ODIs, T20Is, IPL and other T20
leagues, The Hundred, domestic cricket, men's and women's). Line/length
answers always carry how much of the selected deliveries have line/length and
the stored limitation statement for the format, so a caller can tell users
what the data cannot show.

Metric definitions follow CONTEXT.md:
- batting strike rate: runs off the bat per 100 balls faced (wides are not
  balls faced; no-balls are);
- bowling: legal balls bowled, runs conceded = runs off the bat + wides +
  no-balls, wickets = bowler-credited dismissals, strike rate = balls per
  wicket, economy = runs per 6 legal balls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb

Role = Literal["batting", "bowling"]
Dimension = Literal["length", "line"]

FILTER_COLUMNS = ("format", "gender", "competition", "venue")


@dataclass(frozen=True, slots=True)
class DeliveryFilter:
    format: str | None = None
    gender: str | None = None
    competition: str | None = (
        None  # exact name, or an ILIKE pattern when it contains '%'
    )
    year_from: int | None = None
    year_to: int | None = None
    formats: tuple[str, ...] | None = None  # any of these formats
    venue: str | None = None
    competitions: tuple[str, ...] = ()
    excluded_competitions: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    phase: str | None = None
    over_from: int | None = None
    over_to: int | None = None
    bowler_styles: tuple[str, ...] = ()
    bowler_arm: str | None = None
    bowler_kind: str | None = None
    lengths: tuple[str, ...] = ()
    lines: tuple[str, ...] = ()
    opponent: str | None = None
    role: str = "batting"

    def sql(self) -> tuple[str, list[Any]]:
        clauses, params = [], []
        for column in FILTER_COLUMNS:
            value = getattr(self, column)
            if value is not None:
                if column == "venue" and "|" in value:
                    venues = value.split("|")
                    clauses.append(
                        "d.venue IN (" + ", ".join("?" for _ in venues) + ")"
                    )
                    params.extend(venues)
                    continue
                operator = "ILIKE" if column == "competition" and "%" in value else "="
                clauses.append(f"d.{column} {operator} ?")
                params.append(value)
        if self.formats:
            clauses.append("d.format IN (" + ", ".join("?" for _ in self.formats) + ")")
            params.extend(self.formats)
        if self.year_from is not None:
            clauses.append("d.year >= ?")
            params.append(self.year_from)
        if self.year_to is not None:
            clauses.append("d.year <= ?")
            params.append(self.year_to)
        for column, values, negate in (
            ("competition", self.competitions, False),
            ("competition", self.excluded_competitions, True),
            ("year", self.years, False),
            ("bowler_style_code", self.bowler_styles, False),
            ("length", self.lengths, False),
            ("line", self.lines, False),
        ):
            if values:
                clauses.append(
                    f"d.{column} {'NOT IN' if negate else 'IN'} ({', '.join('?' for _ in values)})"
                )
                params.extend(values)
        for column, value in (
            ("bowler_arm", self.bowler_arm),
            ("bowler_kind", self.bowler_kind),
        ):
            if value:
                clauses.append(f"lower(d.{column}) = lower(?)")
                params.append(value)
        if self.opponent:
            clauses.append(
                f"d.{'bowling_team' if self.role == 'batting' else 'batting_team'} = ?"
            )
            params.append(self.opponent)
        if self.over_from is not None:
            clauses.append("d.over_no >= ?")
            params.append(self.over_from - 1)
        if self.over_to is not None:
            clauses.append("d.over_no < ?")
            params.append(self.over_to)
        if self.phase:
            # over_no is zero based. Hundred phases use legal-ball count,
            # including all extras attached to the current legal ball.
            phase = "CASE WHEN d.format = 'The Hundred' THEN CASE WHEN (d.over_no * 5 + greatest(coalesce(d.legal_ball_in_over, 1), 1)) <= 25 THEN 'powerplay' WHEN (d.over_no * 5 + greatest(coalesce(d.legal_ball_in_over, 1), 1)) <= 75 THEN 'middle' ELSE 'death' END WHEN d.format = 'ODI' THEN CASE WHEN d.over_no < 10 THEN 'powerplay' WHEN d.over_no < 40 THEN 'middle' ELSE 'death' END ELSE CASE WHEN d.over_no < 6 THEN 'powerplay' WHEN d.over_no < 15 THEN 'middle' ELSE 'death' END END"
            clauses.append(f"({phase}) = ?")
            params.append(self.phase)
        return (" AND ".join(clauses) or "TRUE"), params


def _clean(value: Any) -> Any:
    # Percentages over empty sets come back as NaN, which JSON cannot carry.
    return None if isinstance(value, float) and math.isnan(value) else value


def _rows(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params or [])
    names = [d[0] for d in cursor.description]
    return [{n: _clean(v) for n, v in zip(names, row)} for row in cursor.fetchall()]


# A batter's dismissals include run-outs at the non-striker's end, which sit on
# a ball someone else faced. _BAT_SOURCE adds those balls a second time keyed
# to the run-out batter (faced = FALSE), so balls and runs come only from balls
# faced and dismissals from every time the batter was out. Retired hurt and
# retired not out are not dismissals.
_BAT_SOURCE = """(
  SELECT d.*, d.batter_id AS bat_key, TRUE AS faced FROM analytics.deliveries d
  UNION ALL BY NAME
  SELECT d.*, d.player_out_id AS bat_key, FALSE AS faced FROM analytics.deliveries d
  WHERE d.is_wicket AND d.player_out_id IS NOT NULL AND d.player_out_id <> d.batter_id
) d"""

_BATTING_AGG = """
  count(DISTINCT d.match_id) AS matches,
  count(*) FILTER (d.faced AND d.wides IS NULL) AS balls,
  coalesce(sum(d.runs_batter) FILTER (d.faced), 0) AS runs,
  count(*) FILTER (d.faced AND d.runs_batter = 4 AND NOT coalesce(d.non_boundary, FALSE)) AS fours,
  count(*) FILTER (d.faced AND d.runs_batter = 6 AND NOT coalesce(d.non_boundary, FALSE)) AS sixes,
  count(*) FILTER (d.faced AND d.wides IS NULL AND d.runs_batter = 0) AS dot_balls,
  count(*) FILTER (d.is_wicket AND d.player_out_id = d.bat_key
                   AND coalesce(d.wicket_kind, '') NOT IN ('retired hurt', 'retired not out', 'retired not out (hurt)', 'not out')) AS dismissals
"""

# Per-ball breakdowns (line, length, matchups) describe the balls the batter
# faced, so a non-striker run-out does not belong to any of them.
_BALL_BATTING_AGG = (
    _BATTING_AGG.replace("d.faced AND ", "")
    .replace("FILTER (d.faced)", "")
    .replace("d.bat_key", "d.batter_id")
)

_BOWLING_AGG = """
  count(DISTINCT d.match_id) AS matches,
  count(*) FILTER (d.is_legal) AS balls,
  sum(d.runs_batter + COALESCE(d.wides, 0) + COALESCE(d.noballs, 0)) AS runs_conceded,
  count(*) FILTER (d.is_bowler_wicket) AS wickets,
  count(*) FILTER (d.is_legal AND d.runs_total = 0) AS dot_balls,
  count(*) FILTER (d.runs_batter IN (4, 6) AND NOT coalesce(d.non_boundary, FALSE)) AS boundaries
"""


def _role_parts(role: str) -> tuple[str, str, str, Any]:
    """(source, player key, aggregate SQL, rate function) for career-style totals."""
    if role == "batting":
        return _BAT_SOURCE, "bat_key", _BATTING_AGG, _batting_rates
    return "analytics.deliveries d", "bowler_id", _BOWLING_AGG, _bowling_rates


def _batting_rates(row: dict[str, Any]) -> dict[str, Any]:
    balls, runs, outs = (
        row.get("balls") or 0,
        row.get("runs") or 0,
        row.get("dismissals") or 0,
    )
    row["strike_rate"] = round(100 * runs / balls, 2) if balls else None
    row["average"] = round(runs / outs, 2) if outs else None
    row["dot_ball_pct"] = (
        round(100 * (row.get("dot_balls") or 0) / balls, 1) if balls else None
    )
    return row


def _bowling_rates(row: dict[str, Any]) -> dict[str, Any]:
    balls, runs, wkts = (
        row.get("balls") or 0,
        row.get("runs_conceded") or 0,
        row.get("wickets") or 0,
    )
    row["economy"] = round(6 * runs / balls, 2) if balls else None
    row["strike_rate"] = round(balls / wkts, 2) if wkts else None
    row["average"] = round(runs / wkts, 2) if wkts else None
    row["dot_ball_pct"] = (
        round(100 * (row.get("dot_balls") or 0) / balls, 1) if balls else None
    )
    return row


class MultiFormatService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Multi-format database not found at {self.db_path}. "
                "Build it with: python -m ingestion.app.multiformat.build"
            )
        return duckdb.connect(str(self.db_path), read_only=True)

    # ------------------------------------------------------------------ coverage
    def coverage(self) -> dict[str, Any]:
        with self._connect() as conn:
            build = _rows(conn, "SELECT * FROM analytics.build_info")[0]
            summary = _rows(
                conn,
                "SELECT * FROM analytics.coverage_summary ORDER BY gender DESC, matches DESC",
            )
            limitations = _rows(conn, "SELECT * FROM analytics.data_limitations")
        return {"build": build, "formats": summary, "limitations": limitations}

    def competitions(
        self, format: str | None = None, gender: str | None = None
    ) -> list[dict[str, Any]]:
        where, params = DeliveryFilter(format=format, gender=gender).sql()
        with self._connect() as conn:
            return _rows(
                conn,
                f"SELECT * FROM analytics.coverage d WHERE {where} ORDER BY matches DESC",
                params,
            )

    # ------------------------------------------------------------------ players
    def search_players(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        with self._connect() as conn:
            return _rows(
                conn,
                """
                SELECT p.player_id, p.name, p.unique_name, p.batting_hand, p.bowling_style_group,
                       (SELECT count(DISTINCT match_id) FROM analytics.deliveries d
                         WHERE d.batter_id = p.player_id OR d.bowler_id = p.player_id) AS matches
                FROM analytics.players p
                WHERE p.name ILIKE ? OR p.unique_name ILIKE ?
                ORDER BY matches DESC, p.name
                LIMIT ?
                """,
                [pattern, pattern, limit],
            )

    def player(self, player_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            rows = _rows(
                conn, "SELECT * FROM analytics.players WHERE player_id = ?", [player_id]
            )
        return rows[0] if rows else None

    def resolve_names(self, names: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Candidate players for each name (exact, case-insensitive), most-capped first."""
        if not names:
            return {}
        keys = sorted({n.lower() for n in names})
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"""
                SELECT n.name_key, p.player_id, p.name, p.unique_name,
                       (SELECT count(DISTINCT match_id) FROM analytics.deliveries d
                         WHERE d.batter_id = p.player_id OR d.bowler_id = p.player_id) AS matches
                FROM analytics.player_names n JOIN analytics.players p USING (player_id)
                WHERE n.name_key IN ({", ".join("?" for _ in keys)})
                """,
                keys,
            )
        out: dict[str, list[dict[str, Any]]] = {}
        for row in sorted(rows, key=lambda r: -(r["matches"] or 0)):
            bucket = out.setdefault(row.pop("name_key"), [])
            if all(c["player_id"] != row["player_id"] for c in bucket):
                bucket.append(row)
        return out

    def players_by_surname(
        self, surname: str, flt: "DeliveryFilter", limit: int = 5
    ) -> list[dict[str, Any]]:
        """Players whose name ends in the surname, ranked by matches in the filter."""
        where, params = flt.sql()
        with self._connect() as conn:
            return _rows(
                conn,
                f"""
                SELECT p.player_id, p.name, p.unique_name, count(DISTINCT d.match_id) AS matches
                FROM analytics.players p
                JOIN analytics.deliveries d ON (d.batter_id = p.player_id OR d.bowler_id = p.player_id)
                WHERE (lower(p.name) LIKE ? OR lower(p.unique_name) LIKE ?) AND {where}
                GROUP BY ALL ORDER BY matches DESC LIMIT ?
                """,
                [f"% {surname.lower()}", f"% {surname.lower()}", *params, limit],
            )

    def limitations(self, flt: "DeliveryFilter") -> list[dict[str, Any]]:
        where, params = flt.sql()
        with self._connect() as conn:
            return _rows(
                conn,
                f"""
                SELECT l.* FROM analytics.data_limitations l
                WHERE (l.format, l.gender) IN (
                  SELECT DISTINCT (d.format, d.gender) FROM analytics.coverage d WHERE {where.replace('d.year', 'year(d.first_match)')}
                )
                """,
                params,
            )

    def leaderboard(
        self,
        role: Role,
        metric: str,
        flt: "DeliveryFilter",
        min_balls: int = 60,
        limit: int = 10,
        min_matches: int | None = None,
    ) -> list[dict[str, Any]]:
        """Ranking within the filter; rate metrics need ``min_balls`` (CONTEXT.md default 60).

        ``min_matches`` replaces the ball threshold with a distinct-match one.
        """
        where, params = flt.sql()
        source, key, agg, rates = _role_parts(role)
        if role == "batting":
            orders = {
                "runs": "runs DESC",
                "strike_rate": "strike_rate DESC",
                "average": "average DESC",
                "sixes": "sixes DESC",
                "fours": "fours DESC",
                "dot_ball_pct": "dot_ball_pct ASC",
            }
        else:
            orders = {
                "wickets": "wickets DESC",
                "economy": "economy ASC",
                "strike_rate": "strike_rate ASC",
                "average": "average ASC",
                "dot_ball_pct": "dot_ball_pct DESC",
            }
        if metric not in orders:
            raise ValueError(f"Unsupported {role} ranking metric {metric!r}")
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"""
                SELECT d.{key} AS player_id, any_value(p.name) AS name, {agg}
                FROM {source} JOIN analytics.players p ON p.player_id = d.{key}
                WHERE {where}
                GROUP BY 1
                """,
                params,
            )
        ranked = [
            rates(r)
            for r in rows
            if (
                (r["matches"] or 0) >= min_matches
                if min_matches is not None
                else (r["balls"] or 0) >= min_balls
            )
        ]
        column, direction = orders[metric].split()
        ranked = [r for r in ranked if r.get(column) is not None]
        ranked.sort(key=lambda r: r[column], reverse=direction == "DESC")
        return ranked[:limit]

    # ------------------------------------------------------------------ stats
    def player_stats(
        self, player_id: str, role: Role, flt: DeliveryFilter
    ) -> list[dict[str, Any]]:
        """Career numbers per format and gender for the filter."""
        where, params = flt.sql()
        source, key, agg, rates = _role_parts(role)
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"""
                SELECT d.format, d.gender, min(d.match_date) AS first_match, max(d.match_date) AS last_match, {agg}
                FROM {source}
                WHERE d.{key} = ? AND {where}
                GROUP BY ALL ORDER BY matches DESC
                """,
                [player_id, *params],
            )
        return [rates(row) for row in rows]

    def line_length(
        self, player_id: str, role: Role, dimension: Dimension, flt: DeliveryFilter
    ) -> dict[str, Any]:
        """Breakdown by length or line, with the coverage it rests on.

        ``coverage`` reports how many of the selected deliveries carry the
        dimension, so callers can say e.g. "line/length is recorded for 62% of
        these balls (2019 onwards)". ``limitations`` holds the stored statement
        for each format involved.
        """
        where, params = flt.sql()
        key, agg, rates = (
            ("batter_id", _BALL_BATTING_AGG, _batting_rates)
            if role == "batting"
            else ("bowler_id", _BOWLING_AGG, _bowling_rates)
        )
        with self._connect() as conn:
            coverage = _rows(
                conn,
                f"""
                SELECT d.format, d.gender, count(*) AS deliveries,
                       count(*) FILTER (d.{dimension} IS NOT NULL) AS with_{dimension},
                       round(100.0 * count(*) FILTER (d.{dimension} IS NOT NULL) / count(*), 1) AS pct,
                       min(d.match_date) FILTER (d.{dimension} IS NOT NULL) AS first_with,
                       max(d.match_date) FILTER (d.{dimension} IS NOT NULL) AS last_with,
                       list(DISTINCT d.ll_source ORDER BY d.ll_source) FILTER (d.ll_source IS NOT NULL) AS sources
                FROM analytics.deliveries d
                WHERE d.{key} = ? AND {where}
                GROUP BY ALL ORDER BY deliveries DESC
                """,
                [player_id, *params],
            )
            rows = _rows(
                conn,
                f"""
                SELECT d.{dimension} AS {dimension}, {agg}
                FROM analytics.deliveries d
                WHERE d.{key} = ? AND {where} AND d.{dimension} IS NOT NULL
                GROUP BY ALL ORDER BY balls DESC
                """,
                [player_id, *params],
            )
            formats = sorted({(c["format"], c["gender"]) for c in coverage})
            limitations = [
                r
                for r in _rows(conn, "SELECT * FROM analytics.data_limitations")
                if (r["format"], r["gender"]) in formats
            ]
        total = sum(c["deliveries"] for c in coverage)
        covered = sum(c[f"with_{dimension}"] for c in coverage)
        return {
            "dimension": dimension,
            "role": role,
            "rows": [rates(row) for row in rows],
            "coverage": {
                "deliveries": total,
                f"with_{dimension}": covered,
                "pct": round(100 * covered / total, 1) if total else None,
                "by_format": coverage,
            },
            "complete": bool(total) and covered == total,
            "limitations": limitations,
            "note": self._coverage_note(dimension, total, covered, coverage),
        }

    @staticmethod
    def _coverage_note(
        dimension: str, total: int, covered: int, coverage: list[dict[str, Any]]
    ) -> str:
        if not total:
            return "No deliveries match this player and filter."
        if covered == 0:
            return (
                f"{dimension.capitalize()} is not recorded for any of these {total:,} deliveries; "
                "see the limitations for when it is available."
            )
        if covered == total:
            return f"{dimension.capitalize()} is recorded for all {total:,} deliveries."
        spans = "; ".join(
            f"{c['format']} {c['pct']}% ({c['first_with']:%b %Y} to {c['last_with']:%b %Y})"
            for c in coverage
            if c[f"with_{dimension}"]
        )
        return (
            f"{dimension.capitalize()} is recorded for {covered:,} of {total:,} deliveries "
            f"({100 * covered / total:.1f}%): {spans}. Figures describe only those deliveries."
        )

    # ------------------------------------------------------------------ explorer views
    def player_year_trend(
        self, player_id: str, role: Role, flt: DeliveryFilter
    ) -> list[dict[str, Any]]:
        where, params = flt.sql()
        source, key, agg, rates = _role_parts(role)
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"SELECT d.year, {agg} FROM {source} WHERE d.{key} = ? AND {where} GROUP BY ALL ORDER BY d.year",
                [player_id, *params],
            )
        return [rates(row) for row in rows]

    def pitch_cells(
        self, player_id: str, role: Role, flt: DeliveryFilter
    ) -> dict[str, Any]:
        """Line × length cells (deliveries with both coded) plus the coverage they rest on.

        Cells carry runs off the bat per ball faced and dismissals of the batter
        (batting), or runs conceded and bowler wickets (bowling), so the same
        heatmap reads "how productive was this zone for the batter".
        """
        where, params = flt.sql()
        key = "batter_id" if role == "batting" else "bowler_id"
        dismissal = (
            "d.is_wicket AND d.player_out_id = d.batter_id"
            if role == "batting"
            else "d.is_bowler_wicket"
        )
        with self._connect() as conn:
            cells = _rows(
                conn,
                f"""
                SELECT d.line, d.length,
                       count(*) FILTER (d.wides IS NULL) AS balls,
                       sum(d.runs_batter) AS runs,
                       count(*) FILTER ({dismissal}) AS dismissals
                FROM analytics.deliveries d
                WHERE d.{key} = ? AND {where} AND d.line IS NOT NULL AND d.length IS NOT NULL
                GROUP BY ALL
                """,
                [player_id, *params],
            )
            total, covered, hand = conn.execute(
                f"""
                SELECT count(*), count(*) FILTER (d.line IS NOT NULL AND d.length IS NOT NULL),
                       mode(d.batter_hand)
                FROM analytics.deliveries d WHERE d.{key} = ? AND {where}
                """,
                [player_id, *params],
            ).fetchone()
        for cell in cells:
            cell["strike_rate"] = (
                round(100 * cell["runs"] / cell["balls"], 2) if cell["balls"] else None
            )
        return {
            "cells": [c for c in cells if c["balls"]],
            "handedness": hand if role == "batting" else None,
            "coverage": {
                "total_balls": total,
                "covered_balls": covered,
                "coverage_percentage": (
                    round(100 * covered / total, 2) if total else 0.0
                ),
            },
        }

    def matchup(
        self, batter_id: str, bowler_id: str, flt: DeliveryFilter
    ) -> dict[str, Any]:
        """Batter against bowler: totals by format and how the batter got out."""
        where, params = flt.sql()
        with self._connect() as conn:
            by_format = _rows(
                conn,
                f"""
                SELECT d.format, d.gender, min(d.match_date) AS first_match, max(d.match_date) AS last_match,
                       {_BALL_BATTING_AGG}, count(*) FILTER (d.is_bowler_wicket) AS bowler_wickets
                FROM analytics.deliveries d
                WHERE d.batter_id = ? AND d.bowler_id = ? AND {where}
                GROUP BY ALL ORDER BY balls DESC
                """,
                [batter_id, bowler_id, *params],
            )
            dismissals = _rows(
                conn,
                f"""
                SELECT d.wicket_kind, count(*) AS dismissals
                FROM analytics.deliveries d
                WHERE d.batter_id = ? AND d.bowler_id = ? AND {where} AND d.is_bowler_wicket
                GROUP BY ALL ORDER BY dismissals DESC
                """,
                [batter_id, bowler_id, *params],
            )
        return {
            "by_format": [_batting_rates(r) for r in by_format],
            "dismissal_kinds": dismissals,
        }

    def batting_control(
        self, player_id: str, flt: DeliveryFilter, bowler_id: str | None = None
    ) -> dict[str, Any]:
        """Balls faced, how many carry a recorded control judgement, and how many were in control."""
        where, params = flt.sql()
        bowler = "AND d.bowler_id = ?" if bowler_id else ""
        with self._connect() as conn:
            balls, recorded, controlled = conn.execute(
                f"""
                SELECT count(*), count(*) FILTER (d.in_control IS NOT NULL),
                       count(*) FILTER (d.in_control)
                FROM analytics.deliveries d
                WHERE d.batter_id = ? {bowler} AND d.wides IS NULL AND {where}
                """,
                [player_id, *([bowler_id] if bowler_id else []), *params],
            ).fetchone()
        return {
            "balls": balls,
            "recorded_balls": recorded,
            "control_balls": controlled,
            "control_percentage": round(100 * controlled / recorded, 2) if recorded else None,
            "false_shot_percentage": (
                round(100 * (recorded - controlled) / recorded, 2) if recorded else None
            ),
        }

    def shot_profile(
        self, player_id: str, flt: DeliveryFilter, limit: int = 12
    ) -> dict[str, Any]:
        """Recorded shot labels for a batter's balls faced, with the share of balls that carry one."""
        where, params = flt.sql()
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"""
                SELECT d.shot, count(*) AS balls, sum(d.runs_batter) AS runs,
                       count(*) FILTER (d.in_control IS NOT NULL) AS control_known,
                       count(*) FILTER (d.in_control) AS control_balls,
                       count(*) FILTER (d.is_wicket AND d.player_out_id = d.batter_id
                         AND coalesce(d.wicket_kind, '') NOT IN ('retired hurt', 'retired not out', 'retired not out (hurt)', 'not out')) AS dismissals
                FROM analytics.deliveries d
                WHERE d.batter_id = ? AND d.wides IS NULL AND d.shot IS NOT NULL AND {where}
                GROUP BY ALL ORDER BY runs DESC, balls DESC
                """,
                [player_id, *params],
            )
            total = conn.execute(
                f"SELECT count(*) FROM analytics.deliveries d WHERE d.batter_id = ? AND d.wides IS NULL AND {where}",
                [player_id, *params],
            ).fetchone()[0]
        covered = sum(r["balls"] for r in rows)
        covered_runs = sum(r["runs"] or 0 for r in rows)
        metrics = [
            {
                "shot": r["shot"],
                "balls": r["balls"],
                "runs": r["runs"] or 0,
                "run_share_percentage": round(100 * (r["runs"] or 0) / covered_runs, 2) if covered_runs else None,
                "strike_rate": round(100 * (r["runs"] or 0) / r["balls"], 2) if r["balls"] else None,
                "control_percentage": round(100 * r["control_balls"] / r["control_known"], 2) if r["control_known"] else None,
                "dismissals": r["dismissals"],
                "dismissal_rate": round(100 * r["dismissals"] / r["balls"], 2) if r["balls"] else None,
            }
            for r in rows[:limit]
        ]
        return {
            "metrics": metrics,
            "coverage": {
                "total_balls": total,
                "covered_balls": covered,
                "coverage_percentage": round(100 * covered / total, 2) if total else 0.0,
                "detail": "Only balls with a recorded shot label are included.",
            },
        }

    def matchup_pitch(
        self, batter_id: str, bowler_id: str, flt: DeliveryFilter
    ) -> dict[str, Any]:
        """Line × length cells for one batter against one bowler, with boundaries and dismissals."""
        where, params = flt.sql()
        with self._connect() as conn:
            cells = _rows(
                conn,
                f"""
                SELECT d.line, d.length, count(*) FILTER (d.wides IS NULL) AS balls,
                       sum(d.runs_batter) AS runs,
                       count(*) FILTER (d.runs_batter = 4 AND NOT coalesce(d.non_boundary, FALSE)) AS fours,
                       count(*) FILTER (d.runs_batter = 6 AND NOT coalesce(d.non_boundary, FALSE)) AS sixes,
                       count(*) FILTER (d.is_wicket AND d.player_out_id = d.batter_id
                         AND coalesce(d.wicket_kind, '') NOT IN ('retired hurt', 'retired not out', 'retired not out (hurt)', 'not out')) AS dismissals
                FROM analytics.deliveries d
                WHERE d.batter_id = ? AND d.bowler_id = ? AND {where}
                  AND d.line IS NOT NULL AND d.length IS NOT NULL
                GROUP BY ALL
                """,
                [batter_id, bowler_id, *params],
            )
            hand = conn.execute(
                f"SELECT mode(d.batter_hand) FROM analytics.deliveries d WHERE d.batter_id = ? AND {where}",
                [batter_id, *params],
            ).fetchone()[0]
        for cell in cells:
            cell["wicket_balls"] = cell["dismissals"]
            cell["strike_rate"] = round(100 * cell["runs"] / cell["balls"], 2) if cell["balls"] else None
        return {"handedness": hand, "cells": [c for c in cells if c["balls"]]}

    def venues(self, flt: DeliveryFilter) -> list[dict[str, Any]]:
        where, params = flt.sql()
        with self._connect() as conn:
            return _rows(
                conn,
                f"""
                SELECT d.venue, count(DISTINCT d.match_id) AS matches
                FROM analytics.deliveries d WHERE {where} AND d.venue IS NOT NULL
                GROUP BY ALL ORDER BY matches DESC, d.venue
                """,
                params,
            )

    def venue_profile(
        self,
        venue: str,
        role: Role,
        metric: str,
        flt: DeliveryFilter,
        min_balls: int = 60,
        limit: int = 15,
        min_matches: int | None = None,
    ) -> dict[str, Any]:
        """Ground summary (first-innings scoring, run rate) and the player leaderboard at it."""
        venue_flt = DeliveryFilter(**{**_filter_fields(flt), "venue": venue})
        where, params = venue_flt.sql()
        with self._connect() as conn:
            summary = _rows(
                conn,
                f"""
                WITH innings AS (
                  SELECT d.match_id, d.innings_no, sum(d.runs_total) AS runs,
                         count(*) FILTER (d.is_wicket) AS wickets, count(*) FILTER (d.is_legal) AS balls
                  FROM analytics.deliveries d
                  WHERE {where} AND NOT coalesce(d.is_super_over, FALSE)
                  GROUP BY ALL
                )
                SELECT count(DISTINCT match_id) AS matches,
                       round(avg(runs) FILTER (innings_no = 1), 1) AS avg_first_innings_runs,
                       round(avg(runs) FILTER (innings_no = 2), 1) AS avg_second_innings_runs,
                       round(6.0 * sum(runs) / nullif(sum(balls), 0), 2) AS run_rate,
                       round(sum(runs) / nullif(sum(wickets), 0), 2) AS runs_per_wicket
                FROM innings
                """,
                params,
            )[0]
        leaders = self.leaderboard(
            role, metric, venue_flt, min_balls=min_balls, limit=limit, min_matches=min_matches
        )
        return {"venue": venue, "summary": summary, "leaders": leaders}


def _filter_fields(flt: DeliveryFilter) -> dict[str, Any]:
    return {name: getattr(flt, name) for name in DeliveryFilter.__dataclass_fields__}


def _player_options_sql(key: str, where: str) -> str:
    return f"""
        SELECT d.{key} AS player_id, any_value(p.name) AS name, count(DISTINCT d.match_id) AS matches
        FROM analytics.deliveries d JOIN analytics.players p ON p.player_id = d.{key}
        WHERE {where}
        GROUP BY 1 ORDER BY matches DESC, name
    """


def player_options(
    service: MultiFormatService, role: Role, flt: DeliveryFilter
) -> list[dict[str, Any]]:
    """Players who batted (or bowled) inside the filter, most matches first."""
    where, params = flt.sql()
    with service._connect() as conn:
        return _rows(
            conn,
            _player_options_sql(
                "batter_id" if role == "batting" else "bowler_id", where
            ),
            params,
        )
