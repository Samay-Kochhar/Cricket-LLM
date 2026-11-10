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
    competition: str | None = None  # exact name, or an ILIKE pattern when it contains '%'
    year_from: int | None = None
    year_to: int | None = None
    formats: tuple[str, ...] | None = None  # any of these formats
    venue: str | None = None

    def sql(self) -> tuple[str, list[Any]]:
        clauses, params = [], []
        for column in FILTER_COLUMNS:
            value = getattr(self, column)
            if value is not None:
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
        return (" AND ".join(clauses) or "TRUE"), params


def _clean(value: Any) -> Any:
    # Percentages over empty sets come back as NaN, which JSON cannot carry.
    return None if isinstance(value, float) and math.isnan(value) else value


def _rows(conn: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params or [])
    names = [d[0] for d in cursor.description]
    return [{n: _clean(v) for n, v in zip(names, row)} for row in cursor.fetchall()]


_BATTING_AGG = """
  count(DISTINCT d.match_id) AS matches,
  count(*) FILTER (d.wides IS NULL) AS balls,
  sum(d.runs_batter) AS runs,
  count(*) FILTER (d.runs_batter = 4 AND NOT d.non_boundary) AS fours,
  count(*) FILTER (d.runs_batter = 6) AS sixes,
  count(*) FILTER (d.wides IS NULL AND d.runs_batter = 0) AS dot_balls,
  count(*) FILTER (d.is_wicket AND d.player_out_id = d.batter_id) AS dismissals
"""

_BOWLING_AGG = """
  count(DISTINCT d.match_id) AS matches,
  count(*) FILTER (d.is_legal) AS balls,
  sum(d.runs_batter + COALESCE(d.wides, 0) + COALESCE(d.noballs, 0)) AS runs_conceded,
  count(*) FILTER (d.is_bowler_wicket) AS wickets,
  count(*) FILTER (d.is_legal AND d.runs_total = 0) AS dot_balls,
  count(*) FILTER (d.runs_batter IN (4, 6)) AS boundaries
"""


def _batting_rates(row: dict[str, Any]) -> dict[str, Any]:
    balls, runs, outs = row.get("balls") or 0, row.get("runs") or 0, row.get("dismissals") or 0
    row["strike_rate"] = round(100 * runs / balls, 2) if balls else None
    row["average"] = round(runs / outs, 2) if outs else None
    row["dot_ball_pct"] = round(100 * (row.get("dot_balls") or 0) / balls, 1) if balls else None
    return row


def _bowling_rates(row: dict[str, Any]) -> dict[str, Any]:
    balls, runs, wkts = row.get("balls") or 0, row.get("runs_conceded") or 0, row.get("wickets") or 0
    row["economy"] = round(6 * runs / balls, 2) if balls else None
    row["strike_rate"] = round(balls / wkts, 2) if wkts else None
    row["average"] = round(runs / wkts, 2) if wkts else None
    row["dot_ball_pct"] = round(100 * (row.get("dot_balls") or 0) / balls, 1) if balls else None
    return row


class MultiFormatService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

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
            summary = _rows(conn, "SELECT * FROM analytics.coverage_summary ORDER BY gender DESC, matches DESC")
            limitations = _rows(conn, "SELECT * FROM analytics.data_limitations")
        return {"build": build, "formats": summary, "limitations": limitations}

    def competitions(self, format: str | None = None, gender: str | None = None) -> list[dict[str, Any]]:
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
            rows = _rows(conn, "SELECT * FROM analytics.players WHERE player_id = ?", [player_id])
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

    def players_by_surname(self, surname: str, flt: "DeliveryFilter", limit: int = 5) -> list[dict[str, Any]]:
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

    def leaderboard(self, role: Role, metric: str, flt: "DeliveryFilter", min_balls: int = 60, limit: int = 10) -> list[dict[str, Any]]:
        """Ranking within the filter; rate metrics need ``min_balls`` (CONTEXT.md default 60)."""
        where, params = flt.sql()
        if role == "batting":
            key, agg, rates = "batter_id", _BATTING_AGG, _batting_rates
            orders = {"runs": "runs DESC", "strike_rate": "strike_rate DESC", "average": "average DESC"}
        else:
            key, agg, rates = "bowler_id", _BOWLING_AGG, _bowling_rates
            orders = {"wickets": "wickets DESC", "economy": "economy ASC", "strike_rate": "strike_rate ASC",
                      "average": "average ASC"}
        if metric not in orders:
            raise ValueError(f"Unsupported {role} ranking metric {metric!r}")
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"""
                SELECT d.{key} AS player_id, any_value(p.name) AS name, {agg}
                FROM analytics.deliveries d JOIN analytics.players p ON p.player_id = d.{key}
                WHERE {where}
                GROUP BY 1
                """,
                params,
            )
        ranked = [rates(r) for r in rows if (r["balls"] or 0) >= min_balls]
        column, direction = orders[metric].split()
        ranked = [r for r in ranked if r.get(column) is not None]
        ranked.sort(key=lambda r: r[column], reverse=direction == "DESC")
        return ranked[:limit]

    # ------------------------------------------------------------------ stats
    def player_stats(self, player_id: str, role: Role, flt: DeliveryFilter) -> list[dict[str, Any]]:
        """Career numbers per format and gender for the filter."""
        where, params = flt.sql()
        key, agg, rates = (
            ("batter_id", _BATTING_AGG, _batting_rates) if role == "batting" else ("bowler_id", _BOWLING_AGG, _bowling_rates)
        )
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"""
                SELECT d.format, d.gender, min(d.match_date) AS first_match, max(d.match_date) AS last_match, {agg}
                FROM analytics.deliveries d
                WHERE d.{key} = ? AND {where}
                GROUP BY ALL ORDER BY matches DESC
                """,
                [player_id, *params],
            )
        return [rates(row) for row in rows]

    def line_length(self, player_id: str, role: Role, dimension: Dimension, flt: DeliveryFilter) -> dict[str, Any]:
        """Breakdown by length or line, with the coverage it rests on.

        ``coverage`` reports how many of the selected deliveries carry the
        dimension, so callers can say e.g. "line/length is recorded for 62% of
        these balls (2019 onwards)". ``limitations`` holds the stored statement
        for each format involved.
        """
        where, params = flt.sql()
        key, agg, rates = (
            ("batter_id", _BATTING_AGG, _batting_rates) if role == "batting" else ("bowler_id", _BOWLING_AGG, _bowling_rates)
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
                r for r in _rows(conn, "SELECT * FROM analytics.data_limitations")
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
    def _coverage_note(dimension: str, total: int, covered: int, coverage: list[dict[str, Any]]) -> str:
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
            for c in coverage if c[f"with_{dimension}"]
        )
        return (
            f"{dimension.capitalize()} is recorded for {covered:,} of {total:,} deliveries "
            f"({100 * covered / total:.1f}%): {spans}. Figures describe only those deliveries."
        )

    # ------------------------------------------------------------------ explorer views
    def player_year_trend(self, player_id: str, role: Role, flt: DeliveryFilter) -> list[dict[str, Any]]:
        where, params = flt.sql()
        key, agg, rates = (
            ("batter_id", _BATTING_AGG, _batting_rates) if role == "batting" else ("bowler_id", _BOWLING_AGG, _bowling_rates)
        )
        with self._connect() as conn:
            rows = _rows(
                conn,
                f"SELECT d.year, {agg} FROM analytics.deliveries d WHERE d.{key} = ? AND {where} GROUP BY ALL ORDER BY d.year",
                [player_id, *params],
            )
        return [rates(row) for row in rows]

    def pitch_cells(self, player_id: str, role: Role, flt: DeliveryFilter) -> dict[str, Any]:
        """Line × length cells (deliveries with both coded) plus the coverage they rest on.

        Cells carry runs off the bat per ball faced and dismissals of the batter
        (batting), or runs conceded and bowler wickets (bowling), so the same
        heatmap reads "how productive was this zone for the batter".
        """
        where, params = flt.sql()
        key = "batter_id" if role == "batting" else "bowler_id"
        dismissal = (
            "d.is_wicket AND d.player_out_id = d.batter_id" if role == "batting" else "d.is_bowler_wicket"
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
            cell["strike_rate"] = round(100 * cell["runs"] / cell["balls"], 2) if cell["balls"] else None
        return {
            "cells": [c for c in cells if c["balls"]],
            "handedness": hand if role == "batting" else None,
            "coverage": {
                "total_balls": total,
                "covered_balls": covered,
                "coverage_percentage": round(100 * covered / total, 2) if total else 0.0,
            },
        }

    def matchup(self, batter_id: str, bowler_id: str, flt: DeliveryFilter) -> dict[str, Any]:
        """Batter against bowler: totals by format and how the batter got out."""
        where, params = flt.sql()
        with self._connect() as conn:
            by_format = _rows(
                conn,
                f"""
                SELECT d.format, d.gender, min(d.match_date) AS first_match, max(d.match_date) AS last_match,
                       {_BATTING_AGG}, count(*) FILTER (d.is_bowler_wicket) AS bowler_wickets
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
        return {"by_format": [_batting_rates(r) for r in by_format], "dismissal_kinds": dismissals}

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
        self, venue: str, role: Role, metric: str, flt: DeliveryFilter, min_balls: int = 60, limit: int = 15
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
            role, metric, venue_flt, min_balls=min_balls, limit=limit
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


def player_options(service: MultiFormatService, role: Role, flt: DeliveryFilter) -> list[dict[str, Any]]:
    """Players who batted (or bowled) inside the filter, most matches first."""
    where, params = flt.sql()
    with service._connect() as conn:
        return _rows(conn, _player_options_sql("batter_id" if role == "batting" else "bowler_id", where), params)
