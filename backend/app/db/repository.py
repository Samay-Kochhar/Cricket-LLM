from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.db.connection import get_connection
from backend.app.services.player_resolution import normalize_name

RIGHT_HAND_WAGON_LABELS = {
    1: "Deep Midwicket",
    2: "Long On",
    3: "Long Off",
    4: "Deep Cover",
    5: "Deep Point",
    6: "Third Man",
    7: "Deep Fine Leg",
    8: "Deep Square Leg",
}

LEFT_HAND_WAGON_LABELS = {
    1: "Deep Cover",
    2: "Long Off",
    3: "Long On",
    4: "Deep Midwicket",
    5: "Deep Square Leg",
    6: "Deep Fine Leg",
    7: "Third Man",
    8: "Deep Point",
}


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

    @staticmethod
    def _coverage_dict(total_balls: int, covered_balls: int, detail: str) -> dict[str, Any]:
        percentage = (covered_balls / total_balls * 100.0) if total_balls else 0.0
        return {
            "total_balls": int(total_balls),
            "covered_balls": int(covered_balls),
            "coverage_percentage": round(percentage, 2),
            "detail": detail,
        }

    @staticmethod
    def _sample_evenly(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        if len(rows) <= limit:
            return rows
        step = len(rows) / limit
        return [rows[int(index * step)] for index in range(limit)]

    @staticmethod
    def _wagon_labels_for_hand(handedness: str | None) -> dict[int, str]:
        return LEFT_HAND_WAGON_LABELS if handedness == "LHB" else RIGHT_HAND_WAGON_LABELS

    @staticmethod
    def _phase_clause(phase: str | None) -> tuple[str, list[Any]]:
        if phase == "powerplay":
            return " AND TRY_CAST(over AS DOUBLE) <= ?", [10.0]
        if phase == "middle":
            return " AND TRY_CAST(over AS DOUBLE) > ? AND TRY_CAST(over AS DOUBLE) <= ?", [10.0, 40.0]
        if phase == "death":
            return " AND TRY_CAST(over AS DOUBLE) > ?", [40.0]
        return "", []

    def _batter_where_clause(
        self,
        batter_name: str,
        bowler_name: str | None = None,
        phase: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses = ["bat = ?"]
        params: list[Any] = [batter_name]
        if bowler_name:
            clauses.append("bowl = ?")
            params.append(bowler_name)
        where_clause = " WHERE " + " AND ".join(clauses)
        phase_clause, phase_params = self._phase_clause(phase)
        return where_clause + phase_clause, params + phase_params

    def health(self) -> dict[str, Any]:
        row = self._fetchone("SELECT COUNT(*) FROM analytics.deliveries_v1")
        return {"database_available": row is not None, "delivery_rows": int(row[0]) if row else 0}

    def list_player_names(self) -> list[str]:
        rows = self._fetchall("SELECT DISTINCT player_name FROM analytics.player_lookup ORDER BY player_name")
        return [str(row[0]) for row in rows]

    def search_players(self, query: str, limit: int = 10) -> list[str]:
        normalized = normalize_name(query)
        condensed = normalized.replace(" ", "")
        query_tokens = self._tokenize(query)
        if not normalized:
            return []

        scored: list[tuple[float, str]] = []
        for player_name in self.list_player_names():
            normalized_player = normalize_name(player_name)
            condensed_player = normalized_player.replace(" ", "")
            player_tokens = self._tokenize(player_name)

            score = 0.0
            if normalized == normalized_player or condensed == condensed_player:
                score = 100.0
            elif query_tokens and query_tokens.issubset(player_tokens):
                score = 90.0 + len(query_tokens)
            elif len(query_tokens) == 1:
                query_token = next(iter(query_tokens))
                if query_token in player_tokens:
                    score = 80.0
                elif any(token.startswith(query_token) for token in player_tokens):
                    score = 72.0
            elif normalized in normalized_player or condensed in condensed_player:
                score = 70.0
            elif query_tokens:
                overlap = len(query_tokens & player_tokens)
                if overlap > 0:
                    score = (overlap / len(query_tokens)) * 60.0

            if score > 0:
                scored.append((score, player_name))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [player_name for _, player_name in scored[:limit]]

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

    def list_teams(self) -> list[str]:
        rows = self._fetchall(
            """
            SELECT DISTINCT team_name
            FROM (
              SELECT CAST(team_bat AS VARCHAR) AS team_name FROM analytics.deliveries_v1
              UNION
              SELECT CAST(team_bowl AS VARCHAR) AS team_name FROM analytics.deliveries_v1
            )
            WHERE NULLIF(TRIM(team_name), '') IS NOT NULL
            ORDER BY team_name
            """
        )
        return [str(row[0]) for row in rows]

    def search_teams(self, query: str, limit: int = 10) -> list[str]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[int, str]] = []
        for team in self.list_teams():
            team_tokens = self._tokenize(team)
            overlap = len(query_tokens & team_tokens)
            if overlap:
                scored.append((overlap, team))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [team for _, team in scored[:limit]]

    def get_team_available_years(self, team_name: str) -> list[int]:
        rows = self._fetchall(
            """
            SELECT DISTINCT TRY_CAST(year AS INTEGER) AS year_value
            FROM analytics.deliveries_v1
            WHERE (team_bat = ? OR team_bowl = ?)
              AND TRY_CAST(year AS INTEGER) IS NOT NULL
            ORDER BY year_value DESC
            """,
            [team_name, team_name],
        )
        return [int(row[0]) for row in rows if row[0] is not None]

    def get_team_year_squad(self, team_name: str, year: int) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            WITH squad AS (
              SELECT bat AS player_name
              FROM analytics.deliveries_v1
              WHERE team_bat = ? AND TRY_CAST(year AS INTEGER) = ?
              UNION
              SELECT bowl AS player_name
              FROM analytics.deliveries_v1
              WHERE team_bowl = ? AND TRY_CAST(year AS INTEGER) = ?
            ),
            batting AS (
              SELECT
                bat AS player_name,
                bat_hand,
                COUNT(*) AS usage_count,
                ROW_NUMBER() OVER (
                  PARTITION BY bat
                  ORDER BY COUNT(*) DESC, bat_hand
                ) AS row_num
              FROM analytics.deliveries_v1
              WHERE NULLIF(TRIM(CAST(bat_hand AS VARCHAR)), '') IS NOT NULL
              GROUP BY bat, bat_hand
            ),
            bowling AS (
              SELECT
                bowl AS player_name,
                bowl_style,
                COUNT(*) AS usage_count,
                ROW_NUMBER() OVER (
                  PARTITION BY bowl
                  ORDER BY COUNT(*) DESC, bowl_style
                ) AS row_num
              FROM analytics.deliveries_v1
              WHERE NULLIF(TRIM(CAST(bowl_style AS VARCHAR)), '') IS NOT NULL
              GROUP BY bowl, bowl_style
            )
            SELECT
              squad.player_name,
              batting.bat_hand,
              bowling.bowl_style
            FROM squad
            LEFT JOIN batting
              ON squad.player_name = batting.player_name AND batting.row_num = 1
            LEFT JOIN bowling
              ON squad.player_name = bowling.player_name AND bowling.row_num = 1
            ORDER BY squad.player_name
            """,
            [team_name, year, team_name, year],
        )
        squad = []
        for row in rows:
            player_name = str(row[0])
            bat_hand = str(row[1]) if row[1] is not None else None
            bowl_style = str(row[2]) if row[2] is not None else None
            summary_parts = []
            if bat_hand == "RHB":
                summary_parts.append("Right-hand bat")
            elif bat_hand == "LHB":
                summary_parts.append("Left-hand bat")
            if bowl_style:
                summary_parts.append(bowl_style)
            role_summary = " | ".join(summary_parts) if summary_parts else "Role data limited in ODI feed"
            squad.append(
                {
                    "player_name": player_name,
                    "role_summary": role_summary,
                    "bat_hand": bat_hand,
                    "bowl_style": bowl_style,
                }
            )
        return squad

    def get_player_batting_summary(self, player_name: str, phase: str | None = None) -> dict[str, Any] | None:
        where_clause, params = self._batter_where_clause(player_name, phase=phase)
        row = self._fetchone(
            """
            SELECT
              COUNT(*) AS balls_faced,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            """
            + where_clause,
            params,
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

    def get_player_shot_breakdown(self, player_name: str, limit: int = 8, phase: str | None = None) -> list[dict[str, Any]]:
        where_clause, params = self._batter_where_clause(player_name, phase=phase)
        rows = self._fetchall(
            """
            SELECT shot, COUNT(*) AS balls, SUM(TRY_CAST(batruns AS INTEGER)) AS runs
            FROM analytics.deliveries_v1
            """
            + where_clause
            + """
              AND NULLIF(TRIM(CAST(shot AS VARCHAR)), '') IS NOT NULL
            GROUP BY shot
            ORDER BY runs DESC, balls DESC
            LIMIT ?
            """,
            params + [limit],
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

    def get_matchup_summary(self, batter_name: str, bowler_name: str, phase: str | None = None) -> dict[str, Any] | None:
        where_clause, params = self._batter_where_clause(batter_name, bowler_name, phase=phase)
        row = self._fetchone(
            """
            SELECT
              COUNT(*) AS balls,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            """
            + where_clause,
            params,
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

    def get_primary_batting_hand(self, player_name: str, bowler_name: str | None = None, phase: str | None = None) -> str | None:
        where_clause, params = self._batter_where_clause(player_name, bowler_name, phase=phase)
        row = self._fetchone(
            f"""
            SELECT bat_hand, COUNT(*) AS usage_count
            FROM analytics.deliveries_v1
            {where_clause}
              AND NULLIF(TRIM(CAST(bat_hand AS VARCHAR)), '') IS NOT NULL
            GROUP BY bat_hand
            ORDER BY usage_count DESC
            LIMIT 1
            """,
            params,
        )
        return str(row[0]) if row and row[0] is not None else None

    def get_pitch_map(self, player_name: str, bowler_name: str | None = None, phase: str | None = None) -> dict[str, Any]:
        where_clause, params = self._batter_where_clause(player_name, bowler_name, phase=phase)
        total_row = self._fetchone(
            f"SELECT COUNT(*) FROM analytics.deliveries_v1 {where_clause}",
            params,
        )
        covered_row = self._fetchone(
            f"""
            SELECT COUNT(*)
            FROM analytics.deliveries_v1
            {where_clause}
              AND NULLIF(TRIM(CAST(line AS VARCHAR)), '') IS NOT NULL
              AND NULLIF(TRIM(CAST(length AS VARCHAR)), '') IS NOT NULL
            """,
            params,
        )
        rows = self._fetchall(
            f"""
            SELECT
              line,
              length,
              COUNT(*) AS balls,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 1 THEN 1 ELSE 0 END) AS singles,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 2 THEN 1 ELSE 0 END) AS doubles,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 3 THEN 1 ELSE 0 END) AS triples,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 4 THEN 1 ELSE 0 END) AS fours,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 6 THEN 1 ELSE 0 END) AS sixes,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS wicket_balls,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            {where_clause}
              AND NULLIF(TRIM(CAST(line AS VARCHAR)), '') IS NOT NULL
              AND NULLIF(TRIM(CAST(length AS VARCHAR)), '') IS NOT NULL
            GROUP BY line, length
            ORDER BY balls DESC, runs DESC
            """,
            params,
        )
        return {
            "coverage": self._coverage_dict(
                int(total_row[0] or 0),
                int(covered_row[0] or 0),
                "Pitch map uses coded line and length labels from the ODI dataset, not full tracked Hawk-Eye bounce coordinates.",
            ),
            "cells": [
                {
                    "line": str(row[0]),
                    "length": str(row[1]),
                    "balls": int(row[2]),
                    "runs": int(row[3] or 0),
                    "strike_rate": round((int(row[3] or 0) / int(row[2])) * 100.0, 2) if int(row[2]) else None,
                    "dismissals": int(row[4] or 0),
                    "boundary_balls": int(row[5] or 0),
                    "dot_balls": int(row[6] or 0),
                    "singles": int(row[7] or 0),
                    "doubles": int(row[8] or 0),
                    "triples": int(row[9] or 0),
                    "fours": int(row[10] or 0),
                    "sixes": int(row[11] or 0),
                    "wicket_balls": int(row[12] or 0),
                    "control_percentage": round(float(row[13]) * 100, 2) if row[13] is not None else None,
                }
                for row in rows
            ],
        }

    def get_wagon_wheel(
        self,
        player_name: str,
        bowler_name: str | None = None,
        point_limit: int = 160,
        phase: str | None = None,
    ) -> dict[str, Any]:
        where_clause, params = self._batter_where_clause(player_name, bowler_name, phase=phase)
        total_row = self._fetchone(f"SELECT COUNT(*) FROM analytics.deliveries_v1 {where_clause}", params)
        covered_row = self._fetchone(
            f"""
            SELECT COUNT(*)
            FROM analytics.deliveries_v1
            {where_clause}
              AND NULLIF(TRIM(CAST(wagonX AS VARCHAR)), '') IS NOT NULL
              AND NULLIF(TRIM(CAST(wagonY AS VARCHAR)), '') IS NOT NULL
              AND NOT (
                TRY_CAST(wagonX AS DOUBLE) = 0
                AND TRY_CAST(wagonY AS DOUBLE) = 0
              )
            """,
            params,
        )
        point_rows = self._fetchall(
            f"""
            SELECT
              TRY_CAST(wagonX AS DOUBLE) AS wagon_x,
              TRY_CAST(wagonY AS DOUBLE) AS wagon_y,
              TRY_CAST(batruns AS INTEGER) AS batruns,
              LOWER(CAST(out AS VARCHAR)) AS out_flag
            FROM analytics.deliveries_v1
            {where_clause}
              AND NULLIF(TRIM(CAST(wagonX AS VARCHAR)), '') IS NOT NULL
              AND NULLIF(TRIM(CAST(wagonY AS VARCHAR)), '') IS NOT NULL
              AND NOT (
                TRY_CAST(wagonX AS DOUBLE) = 0
                AND TRY_CAST(wagonY AS DOUBLE) = 0
              )
            ORDER BY TRY_CAST(ball_id AS DOUBLE)
            """,
            params,
        )
        sampled_points = self._sample_evenly(
            [
                {
                    "x": round(float(row[0]), 2),
                    "y": round(float(row[1]), 2),
                    "runs": int(row[2] or 0),
                    "outcome": (
                        "wicket"
                        if str(row[3]) == "true"
                        else "six"
                        if int(row[2] or 0) == 6
                        else "four"
                        if int(row[2] or 0) == 4
                        else "triple"
                        if int(row[2] or 0) == 3
                        else "double"
                        if int(row[2] or 0) == 2
                        else "single"
                        if int(row[2] or 0) == 1
                        else "dot"
                    ),
                }
                for row in point_rows
            ],
            point_limit,
        )

        handedness = self.get_primary_batting_hand(player_name, bowler_name, phase=phase)
        label_map = self._wagon_labels_for_hand(handedness)
        sector_rows = self._fetchall(
            f"""
            SELECT
              TRY_CAST(wagonZone AS INTEGER) AS zone_id,
              COUNT(*) AS balls,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 1 THEN 1 ELSE 0 END) AS singles,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 2 THEN 1 ELSE 0 END) AS doubles,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 3 THEN 1 ELSE 0 END) AS triples,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 4 THEN 1 ELSE 0 END) AS fours,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 6 THEN 1 ELSE 0 END) AS sixes,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS wicket_balls
            FROM analytics.deliveries_v1
            {where_clause}
              AND TRY_CAST(wagonZone AS INTEGER) BETWEEN 1 AND 8
            GROUP BY zone_id
            ORDER BY zone_id
            """,
            params,
        )
        total_sector_runs = sum(int(row[2] or 0) for row in sector_rows)
        sectors = [
            {
                "zone_id": int(row[0]),
                "label": label_map.get(int(row[0]), f"Zone {int(row[0])}"),
                "balls": int(row[1]),
                "runs": int(row[2] or 0),
                "dismissals": int(row[3] or 0),
                "strike_rate": round((int(row[2] or 0) / int(row[1])) * 100.0, 2) if int(row[1]) else None,
                "run_share_percentage": round((int(row[2] or 0) / total_sector_runs * 100.0), 2) if total_sector_runs else 0.0,
                "singles": int(row[4] or 0),
                "doubles": int(row[5] or 0),
                "triples": int(row[6] or 0),
                "fours": int(row[7] or 0),
                "sixes": int(row[8] or 0),
                "wicket_balls": int(row[9] or 0),
            }
            for row in sector_rows
        ]
        return {
            "handedness": handedness,
            "coverage": self._coverage_dict(
                int(total_row[0] or 0),
                int(covered_row[0] or 0),
                "Wagon wheel uses wagonX, wagonY, and wagonZone. Zero-zero coordinates are treated as unavailable.",
            ),
            "points": sampled_points,
            "sectors": sectors,
        }

    def get_shot_type_profile(
        self,
        player_name: str,
        bowler_name: str | None = None,
        limit: int = 10,
        phase: str | None = None,
    ) -> dict[str, Any]:
        where_clause, params = self._batter_where_clause(player_name, bowler_name, phase=phase)
        total_row = self._fetchone(f"SELECT COUNT(*) FROM analytics.deliveries_v1 {where_clause}", params)
        covered_row = self._fetchone(
            f"""
            SELECT COUNT(*)
            FROM analytics.deliveries_v1
            {where_clause}
              AND NULLIF(TRIM(CAST(shot AS VARCHAR)), '') IS NOT NULL
              AND UPPER(CAST(shot AS VARCHAR)) <> 'NO_SHOT'
            """,
            params,
        )
        rows = self._fetchall(
            f"""
            SELECT
              shot,
              COUNT(*) AS balls,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
            FROM analytics.deliveries_v1
            {where_clause}
              AND NULLIF(TRIM(CAST(shot AS VARCHAR)), '') IS NOT NULL
              AND UPPER(CAST(shot AS VARCHAR)) <> 'NO_SHOT'
            GROUP BY shot
            ORDER BY runs DESC, balls DESC
            LIMIT ?
            """,
            params + [limit],
        )
        total_runs = sum(int(row[2] or 0) for row in rows)
        metrics = []
        for row in rows:
            balls = int(row[1])
            control_percentage = round(float(row[3]) * 100, 2) if row[3] is not None else None
            metrics.append(
                {
                    "shot": str(row[0]),
                    "balls": balls,
                    "runs": int(row[2] or 0),
                    "run_share_percentage": round((int(row[2] or 0) / total_runs) * 100.0, 2) if total_runs else None,
                    "control_percentage": control_percentage,
                    "false_shot_percentage": round(100 - control_percentage, 2) if control_percentage is not None else None,
                    "dismissal_rate": round((int(row[4] or 0) / balls) * 100.0, 2) if balls else None,
                    "boundary_percentage": round((int(row[5] or 0) / balls) * 100.0, 2) if balls else None,
                }
            )
        return {
            "coverage": self._coverage_dict(
                int(total_row[0] or 0),
                int(covered_row[0] or 0),
                "Shot profile uses recorded shot labels and binary control values from the ODI dataset.",
            ),
            "metrics": metrics,
        }

    def get_field_zone_profile(self, player_name: str, bowler_name: str | None = None, phase: str | None = None) -> dict[str, Any]:
        wagon = self.get_wagon_wheel(player_name, bowler_name, point_limit=0, phase=phase)
        where_clause, params = self._batter_where_clause(player_name, bowler_name, phase=phase)
        total_row = self._fetchone(f"SELECT COUNT(*) FROM analytics.deliveries_v1 {where_clause}", params)
        covered_row = self._fetchone(
            f"""
            SELECT COUNT(*)
            FROM analytics.deliveries_v1
            {where_clause}
              AND TRY_CAST(wagonZone AS INTEGER) BETWEEN 1 AND 8
            """,
            params,
        )
        return {
            "handedness": wagon["handedness"],
            "coverage": self._coverage_dict(
                int(total_row[0] or 0),
                int(covered_row[0] or 0),
                "Field-zone map uses wagonZone sectors from the ODI dataset. Zone 0 or blank means the field area was not recorded.",
            ),
            "zones": wagon["sectors"],
        }

    def get_player_split_summary(self, player_name: str, phase: str | None = None) -> dict[str, float | None]:
        where_clause, params = self._batter_where_clause(player_name, phase=phase)
        rows = self._fetchall(
            """
            SELECT
              bowl_kind,
              COUNT(*) AS balls,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            """
            + where_clause
            + """
              AND bowl_kind IN ('pace bowler', 'spin bowler')
            GROUP BY bowl_kind
            """,
            params,
        )
        output: dict[str, float | None] = {
            "pace_strike_rate": None,
            "spin_strike_rate": None,
            "pace_control_percentage": None,
            "spin_control_percentage": None,
        }
        for row in rows:
            key_prefix = "pace" if row[0] == "pace bowler" else "spin"
            balls = int(row[1] or 0)
            runs = int(row[2] or 0)
            output[f"{key_prefix}_strike_rate"] = round((runs / balls) * 100.0, 2) if balls else None
            output[f"{key_prefix}_control_percentage"] = round(float(row[3]) * 100.0, 2) if row[3] is not None else None
        return output

    def get_global_batting_baseline(self, phase: str | None = None) -> dict[str, float | None]:
        phase_clause, params = self._phase_clause(phase)
        row = self._fetchone(
            """
            SELECT
              COUNT(*) AS balls,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control,
              SUM(CASE WHEN bowl_kind = 'pace bowler' THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END) AS pace_runs,
              SUM(CASE WHEN bowl_kind = 'pace bowler' THEN 1 ELSE 0 END) AS pace_balls,
              SUM(CASE WHEN bowl_kind = 'spin bowler' THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END) AS spin_runs,
              SUM(CASE WHEN bowl_kind = 'spin bowler' THEN 1 ELSE 0 END) AS spin_balls
            FROM analytics.deliveries_v1
            WHERE 1 = 1
            """
            + phase_clause,
            params,
        )
        if row is None:
            return {}
        balls = int(row[0] or 0)
        dismissals = int(row[2] or 0)
        return {
            "strike_rate": round((int(row[1] or 0) / balls) * 100.0, 2) if balls else None,
            "boundary_percentage": round((int(row[3] or 0) / balls) * 100.0, 2) if balls else None,
            "control_percentage": round(float(row[4]) * 100.0, 2) if row[4] is not None else None,
            "dismissal_resistance": round(100.0 - ((dismissals / balls) * 100.0), 2) if balls else None,
            "pace_strike_rate": round((int(row[5] or 0) / int(row[6])) * 100.0, 2) if row[6] else None,
            "spin_strike_rate": round((int(row[7] or 0) / int(row[8])) * 100.0, 2) if row[8] else None,
        }
