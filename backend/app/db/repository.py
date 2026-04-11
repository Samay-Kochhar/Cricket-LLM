from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.db.connection import get_connection
from backend.app.services.player_resolution import normalize_name


@dataclass(slots=True)
class AnalyticsRepository:
    db_path: Path

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) >= 3}

    def _fetchall(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        with get_connection(self.db_path) as conn:
            return conn.execute(sql, params or []).fetchall()

    def _fetchone(self, sql: str, params: list[Any] | None = None) -> tuple[Any, ...] | None:
        with get_connection(self.db_path) as conn:
            return conn.execute(sql, params or []).fetchone()

    def health(self) -> dict[str, Any]:
        row = self._fetchone("SELECT COUNT(*) FROM analytics.deliveries_v1")
        return {"database_available": row is not None, "delivery_rows": int(row[0]) if row else 0}

    def list_player_names(self) -> list[str]:
        rows = self._fetchall("SELECT DISTINCT player_name FROM analytics.player_lookup ORDER BY player_name")
        return [str(row[0]) for row in rows]

    def search_players(self, query: str, limit: int = 10) -> list[str]:
        normalized = normalize_name(query)
        rows = self._fetchall(
            """
            SELECT DISTINCT player_name
            FROM analytics.player_lookup
            WHERE normalized_name LIKE ?
            ORDER BY player_name
            LIMIT ?
            """,
            [f"%{normalized}%", limit],
        )
        return [str(row[0]) for row in rows]

    def list_venues(self) -> list[str]:
        rows = self._fetchall(
            """
            SELECT DISTINCT ground
            FROM analytics.deliveries_v1
            WHERE NULLIF(TRIM(CAST(ground AS VARCHAR)), '') IS NOT NULL
            ORDER BY ground
            """
        )
        return [str(row[0]) for row in rows]

    def get_player_batting_summary(self, player_name: str) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT
              COUNT(*) AS balls_faced,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            WHERE bat = ?
            """,
            [player_name],
        )
        if row is None or row[0] == 0:
            return None
        balls_faced, runs_scored, dismissals, boundary_balls, avg_control = row
        strike_rate = float(runs_scored) / float(balls_faced) * 100 if balls_faced else None
        boundary_percentage = float(boundary_balls) / float(balls_faced) * 100 if balls_faced else None
        return {
            "player_name": player_name,
            "balls_faced": int(balls_faced),
            "runs_scored": int(runs_scored or 0),
            "dismissals": int(dismissals or 0),
            "strike_rate": strike_rate,
            "boundary_percentage": boundary_percentage,
            "control_percentage": float(avg_control) * 100 if avg_control is not None else None,
        }

    def get_player_shot_breakdown(self, player_name: str, limit: int = 8) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT shot, COUNT(*) AS balls, SUM(TRY_CAST(batruns AS INTEGER)) AS runs
            FROM analytics.deliveries_v1
            WHERE bat = ? AND NULLIF(TRIM(CAST(shot AS VARCHAR)), '') IS NOT NULL
            GROUP BY shot
            ORDER BY runs DESC, balls DESC
            LIMIT ?
            """,
            [player_name, limit],
        )
        return [{"shot": row[0], "balls": int(row[1]), "runs": int(row[2] or 0)} for row in rows]

    def get_player_year_trend(self, player_name: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT year, balls_faced, runs_scored, avg_control
            FROM analytics.player_year_batting
            WHERE player_name = ?
            ORDER BY year
            """,
            [player_name],
        )
        return [
            {
                "year": int(row[0]),
                "balls_faced": int(row[1]),
                "runs_scored": int(row[2]),
                "control_percentage": float(row[3]) * 100 if row[3] is not None else None,
            }
            for row in rows
        ]

    def get_matchup_summary(self, batter_name: str, bowler_name: str) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT
              COUNT(*) AS balls,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            WHERE bat = ? AND bowl = ?
            """,
            [batter_name, bowler_name],
        )
        if row is None or row[0] == 0:
            return None
        balls, runs_scored, dismissals, avg_control = row
        return {
            "batter_name": batter_name,
            "bowler_name": bowler_name,
            "balls": int(balls),
            "runs_scored": int(runs_scored or 0),
            "dismissals": int(dismissals or 0),
            "strike_rate": float(runs_scored) / float(balls) * 100 if balls else None,
            "control_percentage": float(avg_control) * 100 if avg_control is not None else None,
        }

    def get_venue_bowling_leaderboard(self, venue_name: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT
              bowl,
              COUNT(*) AS deliveries,
              SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS wickets
            FROM analytics.deliveries_v1
            WHERE ground = ?
            GROUP BY bowl
            HAVING COUNT(*) >= 24
            ORDER BY wickets DESC, runs_conceded ASC
            LIMIT ?
            """,
            [venue_name, limit],
        )
        return [
            {
                "player_name": row[0],
                "deliveries": int(row[1]),
                "runs_conceded": int(row[2] or 0),
                "wickets": int(row[3] or 0),
                "economy_rate": (float(row[2] or 0) / (float(row[1]) / 6.0)) if row[1] else None,
            }
            for row in rows
        ]

    def search_venues(self, query: str, limit: int = 10) -> list[str]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[int, str]] = []
        for venue in self.list_venues():
            venue_tokens = self._tokenize(venue)
            overlap = len(query_tokens & venue_tokens)
            if overlap:
                scored.append((overlap, venue))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [venue for _, venue in scored[:limit]]
