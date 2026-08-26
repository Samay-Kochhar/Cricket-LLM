from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.cricket_analytics.cricket_definitions import (
    BOWLER_WICKET_PREDICATE,
    LEGAL_BALL_PREDICATE,
    phase_filter_clause,
    public_label,
)
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
    def _field_zone_condition(field_zone: str) -> str:
        zone_pairs = {
            "midwicket": (1, 4),
            "cover": (4, 1),
            "point": (5, 8),
            "third_man": (6, 7),
            "fine_leg": (7, 6),
            "square_leg": (8, 5),
            "long_on": (2, 3),
            "long_off": (3, 2),
        }
        right_zone, left_zone = zone_pairs.get(field_zone, zone_pairs["midwicket"])
        return (
            "((bat_hand = 'RHB' AND TRY_CAST(wagonZone AS INTEGER) = "
            f"{right_zone}) OR (bat_hand = 'LHB' AND TRY_CAST(wagonZone AS INTEGER) = {left_zone}))"
        )

    @staticmethod
    def _field_zone_label(field_zone: str) -> str:
        return str(public_label(field_zone))

    @staticmethod
    def _phase_clause(phase: str | None) -> tuple[str, list[Any]]:
        return phase_filter_clause(phase, prefix=" AND ")

    @staticmethod
    def _over_range_clause(over_range: list[int] | None) -> tuple[str, list[Any]]:
        if not over_range:
            return "", []
        start = max(0, int(over_range[0]))
        end = max(start, int(over_range[-1]))
        return " AND TRY_CAST(over AS DOUBLE) >= ? AND TRY_CAST(over AS DOUBLE) < ?", [float(start - 1), float(end)]

    @staticmethod
    def _bowling_style_group_clause(style_group: str | None) -> tuple[str, list[Any]]:
        if style_group == "left_arm_pace":
            return " AND bowl_style IN ('LF', 'LFM', 'LMF', 'LM')", []
        if style_group == "leg_spin":
            return " AND bowl_style IN ('LBG', 'LB', 'LWS')", []
        return "", []

    def _batter_where_clause(
        self,
        batter_name: str,
        bowler_name: str | None = None,
        phase: str | None = None,
        years: list[int] | None = None,
        venue: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses = ["bat = ?"]
        params: list[Any] = [batter_name]
        if bowler_name:
            clauses.append("bowl = ?")
            params.append(bowler_name)
        if years:
            clauses.append(f"TRY_CAST(year AS INTEGER) IN ({', '.join('?' for _ in years)})")
            params.extend(years)
        if venue:
            clauses.append("ground = ?")
            params.append(venue)
        where_clause = " WHERE " + " AND ".join(clauses)
        phase_clause, phase_params = self._phase_clause(phase)
        return where_clause + phase_clause, params + phase_params

    def _bowler_where_clause(self, bowler_name: str, phase: str | None = None) -> tuple[str, list[Any]]:
        phase_clause, phase_params = self._phase_clause(phase)
        return " WHERE bowl = ?" + phase_clause, [bowler_name, *phase_params]

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
              SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) AS balls_faced,
              SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END) AS runs_scored,
              SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              AVG(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(control AS DOUBLE) ELSE NULL END) AS avg_control
            FROM analytics.deliveries_v1
            """
            + where_clause,
            params,
        )
        if row is None or row[0] == 0:
            return None
        balls_faced, runs_scored, dismissals, boundary_balls, dot_balls, avg_control = row
        strike_rate = float(runs_scored) / float(balls_faced) * 100 if balls_faced else None
        boundary_percentage = float(boundary_balls) / float(balls_faced) * 100 if balls_faced else None
        dot_percentage = float(dot_balls) / float(balls_faced) * 100 if balls_faced else None
        return {
            "player_name": player_name,
            "balls_faced": int(balls_faced),
            "runs_scored": int(runs_scored or 0),
            "dismissals": int(dismissals or 0),
            "boundary_balls": int(boundary_balls or 0),
            "dot_balls": int(dot_balls or 0),
            "average": (float(runs_scored or 0) / float(dismissals)) if dismissals else None,
            "strike_rate": strike_rate,
            "boundary_percentage": boundary_percentage,
            "dot_percentage": dot_percentage,
            "control_percentage": float(avg_control) * 100 if avg_control is not None else None,
        }

    def get_player_bowling_summary(self, player_name: str, phase: str | None = None) -> dict[str, Any] | None:
        where_clause, params = self._bowler_where_clause(player_name, phase=phase)
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        row = self._fetchone(
            f"""
            SELECT
              COUNT(DISTINCT
                CAST(p_match AS VARCHAR) || ':' ||
                CAST(inns AS VARCHAR) || ':' ||
                CAST(team_bowl AS VARCHAR)
              ) AS innings,
              SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
              COUNT(*) AS delivery_rows,
              SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
              SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls
            FROM analytics.deliveries_v1
            """
            + where_clause,
            params,
        )
        if row is None or row[1] == 0:
            return None

        innings, legal_balls, delivery_rows, runs_conceded, wickets, boundary_balls, dot_balls = row
        balls = int(legal_balls or 0)
        runs = int(runs_conceded or 0)
        wicket_count = int(wickets or 0)
        boundaries = int(boundary_balls or 0)
        dots = int(dot_balls or 0)
        overs = balls / 6.0 if balls else None
        return {
            "player_name": player_name,
            "innings": int(innings or 0),
            "balls_bowled": balls,
            "delivery_rows": int(delivery_rows or 0),
            "overs": overs,
            "runs_conceded": runs,
            "wickets": wicket_count,
            "economy_rate": (runs / overs) if overs else None,
            "bowling_average": (runs / wicket_count) if wicket_count else None,
            "balls_per_wicket": (balls / wicket_count) if wicket_count else None,
            "boundary_balls": boundaries,
            "balls_per_boundary": (balls / boundaries) if boundaries else None,
            "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
            "dot_balls": dots,
            "dot_percentage": (dots / balls * 100.0) if balls else None,
        }

    def get_player_match_metric(
        self,
        player_name: str,
        metric: str,
        *,
        competition: str | None = None,
        year: int | None = None,
        stage: str | None = None,
        teams: list[str] | None = None,
        match_id: str | None = None,
    ) -> dict[str, Any] | None:
        filters: list[str] = []
        params: list[Any] = []
        if match_id:
            filters.append("p_match = ?")
            params.append(match_id)
        if competition:
            filters.append("competition = ?")
            params.append(competition)
        if year:
            filters.append("TRY_CAST(year AS INTEGER) = ?")
            params.append(year)
        for team in teams or []:
            filters.append(
                "p_match IN ("
                "SELECT p_match FROM analytics.deliveries_v1 "
                "WHERE team_bat = ? OR team_bowl = ?"
                ")"
            )
            params.extend([team, team])
        where_clause = "WHERE " + " AND ".join(filters) if filters else ""
        stage_order = "DESC" if stage == "final" else "ASC"
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        row = self._fetchone(
            f"""
            WITH candidate_matches AS (
              SELECT
                p_match,
                MAX(TRY_CAST(date AS DATE)) AS match_date,
                ANY_VALUE(competition) AS competition,
                ANY_VALUE(ground) AS ground,
                STRING_AGG(DISTINCT CAST(team_bat AS VARCHAR), ', ') AS batting_teams,
                STRING_AGG(DISTINCT CAST(team_bowl AS VARCHAR), ', ') AS bowling_teams
              FROM analytics.deliveries_v1
              {where_clause}
              GROUP BY p_match
            ),
            selected_match AS (
              SELECT *
              FROM candidate_matches
              ORDER BY match_date {stage_order}, p_match {stage_order}
              LIMIT 1
            )
            SELECT
              selected_match.p_match,
              selected_match.match_date,
              selected_match.competition,
              selected_match.ground,
              selected_match.batting_teams,
              selected_match.bowling_teams,
              SUM(CASE WHEN d.bat = ? THEN 1 ELSE 0 END) AS balls_faced,
              SUM(CASE WHEN d.bat = ? THEN TRY_CAST(d.batruns AS INTEGER) ELSE 0 END) AS runs_scored,
              SUM(CASE WHEN d.bat = ? AND TRY_CAST(d.batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS batter_dot_balls,
              SUM(CASE WHEN d.bat = ? AND TRY_CAST(d.batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundaries,
              SUM(CASE WHEN d.bowl = ? AND {legal_ball_predicate} THEN 1 ELSE 0 END) AS balls_bowled,
              SUM(CASE WHEN d.bowl = ? THEN 1 ELSE 0 END) AS delivery_rows,
              SUM(CASE WHEN d.bowl = ? THEN TRY_CAST(d.bowlruns AS INTEGER) ELSE 0 END) AS runs_conceded,
              SUM(CASE WHEN d.bowl = ? AND {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
              SUM(CASE WHEN d.bowl = ? AND {legal_ball_predicate} AND TRY_CAST(d.bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS bowler_dot_balls,
              SUM(CASE WHEN d.bowl = ? AND {legal_ball_predicate} AND TRY_CAST(d.batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundaries_conceded
            FROM selected_match
            LEFT JOIN analytics.deliveries_v1 d
              ON d.p_match = selected_match.p_match
            GROUP BY
              selected_match.p_match,
              selected_match.match_date,
              selected_match.competition,
              selected_match.ground,
              selected_match.batting_teams,
              selected_match.bowling_teams
            """,
            [
                *params,
                player_name,
                player_name,
                player_name,
                player_name,
                player_name,
                player_name,
                player_name,
                player_name,
                player_name,
                player_name,
            ],
        )
        if row is None:
            return None
        balls_bowled = int(row[10] or 0)
        runs_conceded = int(row[12] or 0)
        balls_faced = int(row[6] or 0)
        runs_scored = int(row[7] or 0)
        values: dict[str, Any] = {
            "balls_faced": balls_faced,
            "runs_scored": runs_scored,
            "dot_balls": int(row[8] or 0),
            "boundaries": int(row[9] or 0),
            "balls_bowled": balls_bowled,
            "overs_bowled": balls_bowled / 6.0 if balls_bowled else 0.0,
            "delivery_rows": int(row[11] or 0),
            "runs_conceded": runs_conceded,
            "wickets_taken": int(row[13] or 0),
            "bowler_dot_balls": int(row[14] or 0),
            "boundaries_conceded": int(row[15] or 0),
            "economy_rate": (runs_conceded / (balls_bowled / 6.0)) if balls_bowled else None,
            "batting_strike_rate": (runs_scored / balls_faced * 100.0) if balls_faced else None,
        }
        return {
            "player_name": player_name,
            "metric": metric,
            "metric_value": values.get(metric),
            "match_id": str(row[0]),
            "date": str(row[1]) if row[1] is not None else None,
            "competition": str(row[2]) if row[2] is not None else None,
            "ground": str(row[3]) if row[3] is not None else None,
            "batting_teams": str(row[4]) if row[4] is not None else "",
            "bowling_teams": str(row[5]) if row[5] is not None else "",
            "values": values,
        }

    def get_player_best_bowling_figures(self, player_name: str, limit: int = 5) -> list[dict[str, Any]]:
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        rows = self._fetchall(
            f"""
            SELECT
              p_match,
              TRY_CAST(date AS DATE) AS match_date,
              competition,
              ground,
              team_bat AS opposition,
              inns,
              SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
              COUNT(*) AS delivery_rows,
              SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
              SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets
            FROM analytics.deliveries_v1
            WHERE bowl = ?
            GROUP BY p_match, match_date, competition, ground, opposition, inns
            HAVING SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) > 0
            ORDER BY wickets DESC, runs_conceded ASC, legal_balls ASC, match_date DESC
            LIMIT ?
            """,
            [player_name, limit],
        )
        return [
            {
                "player_name": player_name,
                "match_id": str(row[0]),
                "date": str(row[1]) if row[1] is not None else None,
                "competition": str(row[2]) if row[2] is not None else None,
                "ground": str(row[3]) if row[3] is not None else None,
                "opposition": str(row[4]) if row[4] is not None else None,
                "innings": int(row[5] or 0),
                "balls_bowled": int(row[6] or 0),
                "delivery_rows": int(row[7] or 0),
                "runs_conceded": int(row[8] or 0),
                "wickets": int(row[9] or 0),
            }
            for row in rows
        ]

    def get_player_bowling_opponent_summary(self, player_name: str, limit: int = 20) -> list[dict[str, Any]]:
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        rows = self._fetchall(
            f"""
            SELECT
              team_bat AS opponent,
              COUNT(DISTINCT p_match) AS matches,
              COUNT(DISTINCT
                CAST(p_match AS VARCHAR) || ':' ||
                CAST(inns AS VARCHAR) || ':' ||
                CAST(team_bowl AS VARCHAR)
              ) AS innings,
              SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
              COUNT(*) AS delivery_rows,
              SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
              SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
            FROM analytics.deliveries_v1
            WHERE bowl = ?
              AND NULLIF(TRIM(CAST(team_bat AS VARCHAR)), '') IS NOT NULL
            GROUP BY team_bat
            HAVING SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) > 0
            ORDER BY wickets DESC, runs_conceded / NULLIF(wickets, 0) ASC, legal_balls DESC
            LIMIT ?
            """,
            [player_name, limit],
        )
        output: list[dict[str, Any]] = []
        for row in rows:
            opponent, matches, innings, legal_balls, delivery_rows, runs_conceded, wickets, dot_balls, boundary_balls = row
            balls = int(legal_balls or 0)
            runs = int(runs_conceded or 0)
            wicket_count = int(wickets or 0)
            dots = int(dot_balls or 0)
            boundaries = int(boundary_balls or 0)
            overs = balls / 6.0 if balls else None
            output.append(
                {
                    "player_name": player_name,
                    "opponent": str(opponent),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "balls_bowled": balls,
                    "delivery_rows": int(delivery_rows or 0),
                    "overs": overs,
                    "runs_conceded": runs,
                    "wickets": wicket_count,
                    "economy_rate": (runs / overs) if overs else None,
                    "bowling_average": (runs / wicket_count) if wicket_count else None,
                    "balls_per_wicket": (balls / wicket_count) if wicket_count else None,
                    "dot_percentage": (dots / balls * 100.0) if balls else None,
                    "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
                    "balls_per_boundary": (balls / boundaries) if boundaries else None,
                }
            )
        return output

    def get_player_batting_venue_summary(self, player_name: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT
              ground AS venue,
              COUNT(DISTINCT p_match) AS matches,
              COUNT(DISTINCT
                CAST(p_match AS VARCHAR) || ':' ||
                CAST(inns AS VARCHAR) || ':' ||
                CAST(team_bat AS VARCHAR)
              ) AS innings,
              COUNT(*) AS balls_faced,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            WHERE bat = ?
              AND NULLIF(TRIM(CAST(ground AS VARCHAR)), '') IS NOT NULL
            GROUP BY ground
            HAVING COUNT(*) > 0
            ORDER BY runs_scored DESC, runs_scored / NULLIF(dismissals, 0) DESC, balls_faced DESC
            LIMIT ?
            """,
            [player_name, limit],
        )
        output: list[dict[str, Any]] = []
        for row in rows:
            venue, matches, innings, balls_faced, runs_scored, dismissals, boundary_balls, dot_balls, avg_control = row
            balls = int(balls_faced or 0)
            runs = int(runs_scored or 0)
            outs = int(dismissals or 0)
            boundaries = int(boundary_balls or 0)
            dots = int(dot_balls or 0)
            output.append(
                {
                    "player_name": player_name,
                    "venue": str(venue),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "balls_faced": balls,
                    "runs_scored": runs,
                    "dismissals": outs,
                    "average": (runs / outs) if outs else None,
                    "strike_rate": (runs / balls * 100.0) if balls else None,
                    "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
                    "dot_percentage": (dots / balls * 100.0) if balls else None,
                    "control_percentage": float(avg_control) * 100 if avg_control is not None else None,
                }
            )
        return output

    def get_player_bowling_venue_summary(self, player_name: str, limit: int = 20) -> list[dict[str, Any]]:
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        rows = self._fetchall(
            f"""
            SELECT
              ground AS venue,
              COUNT(DISTINCT p_match) AS matches,
              COUNT(DISTINCT
                CAST(p_match AS VARCHAR) || ':' ||
                CAST(inns AS VARCHAR) || ':' ||
                CAST(team_bowl AS VARCHAR)
              ) AS innings,
              SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
              COUNT(*) AS delivery_rows,
              SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
              SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
            FROM analytics.deliveries_v1
            WHERE bowl = ?
              AND NULLIF(TRIM(CAST(ground AS VARCHAR)), '') IS NOT NULL
            GROUP BY ground
            HAVING SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) > 0
            ORDER BY wickets DESC, runs_conceded / NULLIF(wickets, 0) ASC, legal_balls DESC
            LIMIT ?
            """,
            [player_name, limit],
        )
        output: list[dict[str, Any]] = []
        for row in rows:
            venue, matches, innings, legal_balls, delivery_rows, runs_conceded, wickets, dot_balls, boundary_balls = row
            balls = int(legal_balls or 0)
            runs = int(runs_conceded or 0)
            wicket_count = int(wickets or 0)
            dots = int(dot_balls or 0)
            boundaries = int(boundary_balls or 0)
            overs = balls / 6.0 if balls else None
            output.append(
                {
                    "player_name": player_name,
                    "venue": str(venue),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "balls_bowled": balls,
                    "delivery_rows": int(delivery_rows or 0),
                    "overs": overs,
                    "runs_conceded": runs,
                    "wickets": wicket_count,
                    "economy_rate": (runs / overs) if overs else None,
                    "bowling_average": (runs / wicket_count) if wicket_count else None,
                    "balls_per_wicket": (balls / wicket_count) if wicket_count else None,
                    "dot_percentage": (dots / balls * 100.0) if balls else None,
                    "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
                    "balls_per_boundary": (balls / boundaries) if boundaries else None,
                }
            )
        return output

    def get_player_batting_position_summary(
        self,
        player_name: str,
        positions: list[int],
        phase: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_positions = [position for position in positions if 1 <= position <= 11]
        if not normalized_positions:
            return None

        placeholders = ", ".join("?" for _ in normalized_positions)
        phase_clause, phase_params = self._phase_clause(phase)
        row = self._fetchone(
            f"""
            WITH batter_first_balls AS (
              SELECT
                p_match,
                inns,
                team_bat,
                bat,
                MIN(TRY_CAST(ball_id AS DOUBLE)) AS first_ball_id
              FROM analytics.deliveries_v1
              WHERE NULLIF(TRIM(CAST(bat AS VARCHAR)), '') IS NOT NULL
                AND TRY_CAST(ball_id AS DOUBLE) IS NOT NULL
              GROUP BY p_match, inns, team_bat, bat
            ),
            batting_order AS (
              SELECT
                p_match,
                inns,
                team_bat,
                bat,
                ROW_NUMBER() OVER (
                  PARTITION BY p_match, inns, team_bat
                  ORDER BY first_ball_id, bat
                ) AS batting_position
              FROM batter_first_balls
            )
            SELECT
              COUNT(DISTINCT
                CAST(d.p_match AS VARCHAR) || ':' ||
                CAST(d.inns AS VARCHAR) || ':' ||
                CAST(d.team_bat AS VARCHAR)
              ) AS innings,
              COUNT(*) AS balls_faced,
              SUM(TRY_CAST(d.batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(d.out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(d.batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              SUM(CASE WHEN TRY_CAST(d.batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              AVG(TRY_CAST(d.control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1 d
            JOIN batting_order bo
              ON d.p_match = bo.p_match
             AND d.inns = bo.inns
             AND d.team_bat = bo.team_bat
             AND d.bat = bo.bat
            WHERE d.bat = ?
              AND bo.batting_position IN ({placeholders})
            """
            + phase_clause,
            [player_name, *normalized_positions, *phase_params],
        )
        if row is None or row[1] == 0:
            return None

        innings, balls_faced, runs_scored, dismissals, boundary_balls, dot_balls, avg_control = row
        runs = int(runs_scored or 0)
        balls = int(balls_faced)
        wickets = int(dismissals or 0)
        return {
            "player_name": player_name,
            "positions": normalized_positions,
            "innings": int(innings or 0),
            "balls_faced": balls,
            "runs_scored": runs,
            "dismissals": wickets,
            "strike_rate": (runs / balls * 100.0) if balls else None,
            "average": (runs / wickets) if wickets else None,
            "boundary_percentage": (int(boundary_balls or 0) / balls * 100.0) if balls else None,
            "dot_percentage": (int(dot_balls or 0) / balls * 100.0) if balls else None,
            "control_percentage": float(avg_control) * 100 if avg_control is not None else None,
            "balls_per_dismissal": (balls / wickets) if wickets else None,
            "runs_per_innings": (runs / int(innings)) if innings else None,
        }

    @staticmethod
    def _rate_summary(row: tuple[Any, ...], label: str, player_name: str) -> dict[str, Any]:
        innings, balls_faced, runs_scored, dismissals, boundary_balls, dot_balls, avg_control = row
        innings_count = int(innings or 0)
        balls = int(balls_faced or 0)
        runs = int(runs_scored or 0)
        wickets = int(dismissals or 0)
        boundaries = int(boundary_balls or 0)
        dots = int(dot_balls or 0)
        return {
            "player_name": player_name,
            "split": label,
            "innings": innings_count,
            "balls_faced": balls,
            "runs_scored": runs,
            "dismissals": wickets,
            "average": (runs / wickets) if wickets else None,
            "strike_rate": (runs / balls * 100.0) if balls else None,
            "runs_per_innings": (runs / innings_count) if innings_count else None,
            "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
            "dot_percentage": (dots / balls * 100.0) if balls else None,
            "control_percentage": float(avg_control) * 100 if avg_control is not None else None,
        }

    def get_player_phase_summary(self, player_name: str) -> list[dict[str, Any]]:
        phases = [
            ("Powerplay (0-10)", "TRY_CAST(over AS DOUBLE) <= 10.0"),
            ("Middle overs (10-40)", "TRY_CAST(over AS DOUBLE) > 10.0 AND TRY_CAST(over AS DOUBLE) <= 40.0"),
            ("Death overs (40-50)", "TRY_CAST(over AS DOUBLE) > 40.0"),
        ]
        output = []
        for label, predicate in phases:
            row = self._fetchone(
                f"""
                SELECT
                  COUNT(DISTINCT
                    CAST(p_match AS VARCHAR) || ':' ||
                    CAST(inns AS VARCHAR) || ':' ||
                    CAST(team_bat AS VARCHAR)
                  ) AS innings,
                  COUNT(*) AS balls_faced,
                  SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
                  SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
                  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                  SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                  AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
                FROM analytics.deliveries_v1
                WHERE bat = ?
                  AND {predicate}
                """,
                [player_name],
            )
            if row is not None and row[1]:
                output.append(self._rate_summary(row, label, player_name))
        return output

    def get_player_bowling_kind_summary(self, player_name: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT
              CASE
                WHEN bowl_kind = 'pace bowler' THEN 'Pace'
                WHEN bowl_kind = 'spin bowler' THEN 'Spin'
                ELSE 'Other/unknown'
              END AS bowling_type,
              COUNT(DISTINCT
                CAST(p_match AS VARCHAR) || ':' ||
                CAST(inns AS VARCHAR) || ':' ||
                CAST(team_bat AS VARCHAR)
              ) AS innings,
              COUNT(*) AS balls_faced,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            WHERE bat = ?
              AND bowl_kind IN ('pace bowler', 'spin bowler')
            GROUP BY bowling_type
            ORDER BY bowling_type
            """,
            [player_name],
        )
        output = []
        for row in rows:
            label = str(row[0])
            output.append(self._rate_summary(row[1:], label, player_name))
        return output

    def get_player_bowling_style_summary(self, player_name: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT
              bowl_style,
              bowl_kind,
              COUNT(DISTINCT
                CAST(p_match AS VARCHAR) || ':' ||
                CAST(inns AS VARCHAR) || ':' ||
                CAST(team_bat AS VARCHAR)
              ) AS innings,
              COUNT(*) AS balls_faced,
              SUM(TRY_CAST(batruns AS INTEGER)) AS runs_scored,
              SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
              SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              AVG(TRY_CAST(control AS DOUBLE)) AS avg_control
            FROM analytics.deliveries_v1
            WHERE bat = ?
              AND NULLIF(TRIM(CAST(bowl_style AS VARCHAR)), '') IS NOT NULL
            GROUP BY bowl_style, bowl_kind
            ORDER BY balls_faced DESC, bowl_style
            """,
            [player_name],
        )
        output = []
        for row in rows:
            summary = self._rate_summary(row[2:], str(row[0]), player_name)
            summary["style_code"] = str(row[0])
            summary["bowling_kind"] = str(row[1]) if row[1] is not None else None
            output.append(summary)
        return output

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

    def get_player_bowling_year_trend(self, player_name: str, phase: str | None = None) -> list[dict[str, Any]]:
        phase_clause, phase_params = self._phase_clause(phase)
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        rows = self._fetchall(
            f"""
            SELECT
              TRY_CAST(year AS INTEGER) AS year_value,
              COUNT(DISTINCT p_match) AS matches,
              COUNT(DISTINCT
                CAST(p_match AS VARCHAR) || ':' ||
                CAST(inns AS VARCHAR) || ':' ||
                CAST(team_bowl AS VARCHAR)
              ) AS innings,
              SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
              COUNT(*) AS delivery_rows,
              SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
              SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
              SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
            FROM analytics.deliveries_v1
            WHERE bowl = ?
              AND TRY_CAST(year AS INTEGER) IS NOT NULL
            """
            + phase_clause
            + """
            GROUP BY year_value
            HAVING SUM(CASE WHEN COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0 THEN 1 ELSE 0 END) > 0
            ORDER BY year_value
            """,
            [player_name, *phase_params],
        )
        output = []
        for row in rows:
            year, matches, innings, legal_balls, delivery_rows, runs_conceded, wickets, dot_balls, boundary_balls = row
            balls = int(legal_balls or 0)
            runs = int(runs_conceded or 0)
            wicket_count = int(wickets or 0)
            dots = int(dot_balls or 0)
            boundaries = int(boundary_balls or 0)
            overs = balls / 6.0 if balls else None
            output.append(
                {
                    "player_name": player_name,
                    "year": int(year),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "balls_bowled": balls,
                    "delivery_rows": int(delivery_rows or 0),
                    "overs": overs,
                    "runs_conceded": runs,
                    "wickets": wicket_count,
                    "economy_rate": (runs / overs) if overs else None,
                    "bowling_average": (runs / wicket_count) if wicket_count else None,
                    "balls_per_wicket": (balls / wicket_count) if wicket_count else None,
                    "dot_balls": dots,
                    "dot_percentage": (dots / balls * 100.0) if balls else None,
                    "boundary_balls": boundaries,
                    "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
                    "balls_per_boundary": (balls / boundaries) if boundaries else None,
                }
            )
        return output

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

    def get_venue_bowling_leaderboard(
        self,
        venue_name: str,
        limit: int = 10,
        excluded_teams: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        params: list[Any] = [venue_name]
        team_exclusion_clause = ""
        if excluded_teams:
            placeholders = ", ".join("?" for _ in excluded_teams)
            team_exclusion_clause = f" AND team_bowl NOT IN ({placeholders})"
            params.extend(excluded_teams)
        params.append(limit)
        rows = self._fetchall(
            f"""
            SELECT
              bowl,
              SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
              COUNT(*) AS delivery_rows,
              SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
              SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets
            FROM analytics.deliveries_v1
            WHERE ground = ?
              {team_exclusion_clause}
            GROUP BY bowl
            HAVING SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) >= 24
            ORDER BY wickets DESC, runs_conceded / NULLIF(wickets, 0) ASC, legal_balls ASC
            LIMIT ?
            """,
            params,
        )
        return [
            {
                "player_name": row[0],
                "deliveries": int(row[1] or 0),
                "delivery_rows": int(row[2] or 0),
                "runs_conceded": int(row[3] or 0),
                "wickets": int(row[4] or 0),
                "economy_rate": (float(row[3] or 0) / (float(row[1]) / 6.0)) if row[1] else None,
            }
            for row in rows
        ]

    @staticmethod
    def _bowling_leaderboard_order(metric: str, rank_intent: str) -> tuple[str, str]:
        metric_expressions = {
            "economy_rate": "runs_conceded / NULLIF(legal_balls / 6.0, 0)",
            "wickets_taken": "wickets",
            "balls_per_wicket": "legal_balls / NULLIF(wickets, 0)",
            "balls_per_boundary": "legal_balls / NULLIF(boundary_balls, 0)",
        }
        expression = metric_expressions.get(metric, metric_expressions["economy_rate"])
        lower_is_better = metric in {"economy_rate", "balls_per_wicket"}
        if rank_intent == "worst":
            direction = "DESC" if lower_is_better else "ASC"
        else:
            direction = "ASC" if lower_is_better else "DESC"
        return expression, direction

    @staticmethod
    def _bowling_leaderboard_tiebreak(metric: str) -> str:
        if metric == "wickets_taken":
            return "runs_conceded / NULLIF(wickets, 0) ASC, legal_balls ASC"
        return "legal_balls DESC"

    def get_bowling_metric_leaderboard(
        self,
        metric: str = "economy_rate",
        phase: str | None = None,
        years: list[int] | None = None,
        year_mode: str | None = None,
        competition: str | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_legal_balls: int = 60,
    ) -> list[dict[str, Any]]:
        order_expression, order_direction = self._bowling_leaderboard_order(metric, rank_intent)
        tiebreak_expression = self._bowling_leaderboard_tiebreak(metric)
        phase_clause, phase_params = self._phase_clause(phase)
        year_clause = ""
        year_params: list[Any] = []
        if years:
            if year_mode == "after":
                year_clause = " AND TRY_CAST(year AS INTEGER) >= ?"
                year_params.append(min(years))
            elif year_mode == "before":
                year_clause = " AND TRY_CAST(year AS INTEGER) <= ?"
                year_params.append(max(years))
            else:
                placeholders = ", ".join("?" for _ in years)
                year_clause = f" AND TRY_CAST(year AS INTEGER) IN ({placeholders})"
                year_params.extend(years)
        competition_clause = ""
        competition_params: list[Any] = []
        if competition:
            competition_clause = " AND competition = ?"
            competition_params.append(competition)

        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        rows = self._fetchall(
            f"""
            WITH bowler_rows AS (
              SELECT
                bowl AS player_name,
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT
                  CAST(p_match AS VARCHAR) || ':' ||
                  CAST(inns AS VARCHAR) || ':' ||
                  CAST(team_bowl AS VARCHAR)
                ) AS innings,
                SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
                COUNT(*) AS delivery_rows,
                SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
                SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
                SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
              FROM analytics.deliveries_v1
              WHERE NULLIF(TRIM(CAST(bowl AS VARCHAR)), '') IS NOT NULL
            """
            + phase_clause
            + year_clause
            + competition_clause
            + f"""
              GROUP BY bowl
            )
            SELECT
              player_name,
              matches,
              innings,
              legal_balls,
              delivery_rows,
              runs_conceded,
              wickets,
              dot_balls,
              boundary_balls
            FROM bowler_rows
            WHERE legal_balls >= ?
            ORDER BY {order_expression} {order_direction}, {tiebreak_expression}
            LIMIT ?
            """,
            [*phase_params, *year_params, *competition_params, min_legal_balls, limit],
        )
        output = []
        for row in rows:
            player_name, matches, innings, legal_balls, delivery_rows, runs_conceded, wickets, dot_balls, boundary_balls = row
            balls = int(legal_balls or 0)
            runs = int(runs_conceded or 0)
            wicket_count = int(wickets or 0)
            dots = int(dot_balls or 0)
            boundaries = int(boundary_balls or 0)
            overs = balls / 6.0 if balls else None
            output.append(
                {
                    "player_name": str(player_name),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "balls_bowled": balls,
                    "delivery_rows": int(delivery_rows or 0),
                    "overs": overs,
                    "runs_conceded": runs,
                    "wickets": wicket_count,
                    "economy_rate": (runs / overs) if overs else None,
                    "bowling_average": (runs / wicket_count) if wicket_count else None,
                    "balls_per_wicket": (balls / wicket_count) if wicket_count else None,
                    "dot_percentage": (dots / balls * 100.0) if balls else None,
                    "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
                    "balls_per_boundary": (balls / boundaries) if boundaries else None,
                }
            )
        return output

    def get_bowling_economy_leaderboard(
        self,
        phase: str | None = None,
        years: list[int] | None = None,
        year_mode: str | None = None,
        competition: str | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_legal_balls: int = 60,
    ) -> list[dict[str, Any]]:
        return self.get_bowling_metric_leaderboard(
            metric="economy_rate",
            phase=phase,
            years=years,
            year_mode=year_mode,
            competition=competition,
            rank_intent=rank_intent,
            limit=limit,
            min_legal_balls=min_legal_balls,
        )

    def get_fielding_catches_coverage(self, competition: str | None = None, years: list[int] | None = None) -> dict[str, Any]:
        clauses = ["LOWER(CAST(dismissal AS VARCHAR)) = 'caught'"]
        params: list[Any] = []
        if competition:
            clauses.append("competition = ?")
            params.append(competition)
        if years:
            placeholders = ", ".join("?" for _ in years)
            clauses.append(f"TRY_CAST(year AS INTEGER) IN ({placeholders})")
            params.extend(years)
        where_sql = " WHERE " + " AND ".join(clauses)
        row = self._fetchone(
            f"""
            SELECT
              COUNT(*) AS caught_dismissals,
              COUNT(DISTINCT p_match) AS matches,
              COUNT(DISTINCT bat) AS dismissed_batters
            FROM analytics.deliveries_v1
            {where_sql}
            """,
            params,
        )
        return {
            "caught_dismissals": int(row[0] or 0) if row else 0,
            "matches": int(row[1] or 0) if row else 0,
            "dismissed_batters": int(row[2] or 0) if row else 0,
            "has_catcher_column": False,
            "available_dismissal_fields": ["dismissal", "p_out", "bat", "bowl"],
        }

    def get_analyst_bowling_leaderboard(
        self,
        metric: str,
        phase: str | None = None,
        over_range: list[int] | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_legal_balls: int = 60,
        length: str | None = None,
        line: str | None = None,
        batting_hand: str | None = None,
        bowling_kind: str | None = None,
        bowling_style_group: str | None = None,
        batter_name: str | None = None,
    ) -> list[dict[str, Any]]:
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        metric_expressions = {
            "economy_rate": "runs_conceded / NULLIF(legal_balls / 6.0, 0)",
            "wickets_taken": "wickets",
            "bowler_dot_balls": "dot_balls",
            "bowler_dot_percentage": "dot_balls / NULLIF(legal_balls, 0) * 100.0",
            "yorker_count": "yorker_balls",
            "yorker_percentage": "yorker_balls / NULLIF(legal_balls, 0) * 100.0",
            "yorker_success_rate": "yorker_successes / NULLIF(yorker_balls, 0) * 100.0",
            "boundaries_per_over": "boundary_balls / NULLIF(legal_balls / 6.0, 0)",
            "balls_per_boundary": "legal_balls / NULLIF(boundary_balls, 0)",
            "false_shot_percentage": "false_shots / NULLIF(legal_balls, 0) * 100.0",
        }
        lower_is_better = metric in {"economy_rate", "boundaries_per_over"}
        metric_expression = metric_expressions.get(metric, metric_expressions["wickets_taken"])
        if rank_intent == "worst":
            direction = "ASC" if not lower_is_better else "DESC"
        else:
            direction = "ASC" if lower_is_better else "DESC"

        phase_clause, phase_params = self._phase_clause(phase)
        over_clause, over_params = self._over_range_clause(over_range)
        style_clause, style_params = self._bowling_style_group_clause(bowling_style_group)
        clauses = ["NULLIF(TRIM(CAST(bowl AS VARCHAR)), '') IS NOT NULL"]
        params: list[Any] = []
        if length:
            clauses.append("length = ?")
            params.append(length)
        if line:
            clauses.append("line = ?")
            params.append(line)
        if batting_hand:
            clauses.append("bat_hand = ?")
            params.append(batting_hand)
        if bowling_kind:
            clauses.append("bowl_kind = ?")
            params.append(bowling_kind)
        if batter_name:
            clauses.append("bat = ?")
            params.append(batter_name)
        where_sql = " WHERE " + " AND ".join(clauses)

        rows = self._fetchall(
            f"""
            WITH bowler_rows AS (
              SELECT
                bowl AS player_name,
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bowl AS VARCHAR)) AS innings,
                SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
                COUNT(*) AS delivery_rows,
                SUM(TRY_CAST(bowlruns AS INTEGER)) AS runs_conceded,
                SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS wickets,
                SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN {legal_ball_predicate} AND length = 'YORKER' THEN 1 ELSE 0 END) AS yorker_balls,
                SUM(CASE WHEN {legal_ball_predicate} AND length = 'YORKER' AND (TRY_CAST(bowlruns AS INTEGER) = 0 OR {bowler_wicket_predicate} OR TRY_CAST(control AS DOUBLE) = 0) THEN 1 ELSE 0 END) AS yorker_successes,
                SUM(CASE WHEN {legal_ball_predicate} AND TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
              FROM analytics.deliveries_v1
            """
            + where_sql
            + phase_clause
            + over_clause
            + style_clause
            + f"""
              GROUP BY bowl
            )
            SELECT
              player_name,
              matches,
              innings,
              legal_balls,
              delivery_rows,
              runs_conceded,
              wickets,
              dot_balls,
              boundary_balls,
              yorker_balls,
              yorker_successes,
              false_shots,
              {metric_expression} AS metric_value
            FROM bowler_rows
            WHERE legal_balls >= ?
            ORDER BY metric_value {direction}, legal_balls DESC
            LIMIT ?
            """,
            [*params, *phase_params, *over_params, *style_params, min_legal_balls, limit],
        )
        return [self._analyst_bowling_row(row) for row in rows]

    @staticmethod
    def _analyst_bowling_row(row: tuple[Any, ...]) -> dict[str, Any]:
        (
            player_name,
            matches,
            innings,
            legal_balls,
            delivery_rows,
            runs_conceded,
            wickets,
            dot_balls,
            boundary_balls,
            yorker_balls,
            yorker_successes,
            false_shots,
            metric_value,
        ) = row
        balls = int(legal_balls or 0)
        runs = int(runs_conceded or 0)
        wicket_count = int(wickets or 0)
        boundaries = int(boundary_balls or 0)
        yorkers = int(yorker_balls or 0)
        yorker_success_count = int(yorker_successes or 0)
        false_shot_count = int(false_shots or 0)
        overs = balls / 6.0 if balls else None
        return {
            "player_name": str(player_name),
            "matches": int(matches or 0),
            "innings": int(innings or 0),
            "balls": balls,
            "delivery_rows": int(delivery_rows or 0),
            "overs": overs,
            "runs": runs,
            "wickets": wicket_count,
            "dot_balls": int(dot_balls or 0),
            "boundary_balls": boundaries,
            "yorker_balls": yorkers,
            "yorker_successes": yorker_success_count,
            "false_shots": false_shot_count,
            "economy_rate": (runs / overs) if overs else None,
            "dot_percentage": (int(dot_balls or 0) / balls * 100.0) if balls else None,
            "boundary_percentage": (boundaries / balls * 100.0) if balls else None,
            "boundaries_per_over": (boundaries / overs) if overs else None,
            "balls_per_boundary": (balls / boundaries) if boundaries else None,
            "yorker_success_rate": (yorker_success_count / yorkers * 100.0) if yorkers else None,
            "yorker_percentage": (yorkers / balls * 100.0) if balls else None,
            "false_shot_percentage": (false_shot_count / balls * 100.0) if balls else None,
            "metric_value": float(metric_value) if metric_value is not None else None,
        }

    def get_analyst_batting_leaderboard(
        self,
        metric: str,
        phase: str | None = None,
        over_range: list[int] | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_balls: int = 60,
        length: str | None = None,
        bowling_kind: str | None = None,
        bowling_style_group: str | None = None,
    ) -> list[dict[str, Any]]:
        metric_expressions = {
            "runs_scored": "runs",
            "batting_average": "runs / NULLIF(dismissals, 0)",
            "batting_strike_rate": "runs / NULLIF(balls, 0) * 100.0",
            "boundary_percentage": "boundary_balls / NULLIF(balls, 0) * 100.0",
            "dot_percentage": "dot_balls / NULLIF(balls, 0) * 100.0",
            "strike_rotation_percentage": "rotation_balls / NULLIF(balls, 0) * 100.0",
            "false_shot_percentage": "false_shots / NULLIF(balls, 0) * 100.0",
            "dismissals": "dismissals",
        }
        lower_is_better = metric in {"dot_percentage"}
        metric_expression = metric_expressions.get(metric, metric_expressions["batting_strike_rate"])
        if rank_intent == "worst":
            direction = "DESC" if lower_is_better else "ASC"
        else:
            direction = "ASC" if lower_is_better else "DESC"

        phase_clause, phase_params = self._phase_clause(phase)
        over_clause, over_params = self._over_range_clause(over_range)
        style_clause, style_params = self._bowling_style_group_clause(bowling_style_group)
        clauses = ["NULLIF(TRIM(CAST(bat AS VARCHAR)), '') IS NOT NULL"]
        params: list[Any] = []
        if length:
            clauses.append("length = ?")
            params.append(length)
        if bowling_kind:
            clauses.append("bowl_kind = ?")
            params.append(bowling_kind)
        where_sql = " WHERE " + " AND ".join(clauses)

        rows = self._fetchall(
            f"""
            WITH batter_rows AS (
              SELECT
                bat AS player_name,
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT CAST(p_match AS VARCHAR) || ':' || CAST(inns AS VARCHAR) || ':' || CAST(team_bat AS VARCHAR)) AS innings,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN 1 ELSE 0 END) AS balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 THEN TRY_CAST(batruns AS INTEGER) ELSE 0 END) AS runs,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(batruns AS INTEGER) IN (1, 2, 3) THEN 1 ELSE 0 END) AS rotation_balls,
                SUM(CASE WHEN TRY_CAST(ballfaced AS INTEGER) = 1 AND TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
              FROM analytics.deliveries_v1
            """
            + where_sql
            + phase_clause
            + over_clause
            + style_clause
            + f"""
              GROUP BY bat
            )
            SELECT
              player_name,
              matches,
              innings,
              balls,
              runs,
              dismissals,
              boundary_balls,
              dot_balls,
              rotation_balls,
              false_shots,
              {metric_expression} AS metric_value
            FROM batter_rows
            WHERE balls >= ?
            ORDER BY metric_value {direction}, balls DESC
            LIMIT ?
            """,
            [*params, *phase_params, *over_params, *style_params, min_balls, limit],
        )
        output = []
        for row in rows:
            player_name, matches, innings, balls, runs, dismissals, boundary_balls, dot_balls, rotation_balls, false_shots, metric_value = row
            ball_count = int(balls or 0)
            run_count = int(runs or 0)
            boundary_count = int(boundary_balls or 0)
            dot_count = int(dot_balls or 0)
            rotation_count = int(rotation_balls or 0)
            false_count = int(false_shots or 0)
            output.append(
                {
                    "player_name": str(player_name),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "balls": ball_count,
                    "runs": run_count,
                    "dismissals": int(dismissals or 0),
                    "average": (run_count / int(dismissals)) if int(dismissals or 0) else None,
                    "balls_per_dismissal": (ball_count / int(dismissals)) if int(dismissals or 0) else None,
                    "strike_rate": (run_count / ball_count * 100.0) if ball_count else None,
                    "boundary_percentage": (boundary_count / ball_count * 100.0) if ball_count else None,
                    "dot_percentage": (dot_count / ball_count * 100.0) if ball_count else None,
                    "strike_rotation_percentage": (rotation_count / ball_count * 100.0) if ball_count else None,
                    "false_shot_percentage": (false_count / ball_count * 100.0) if ball_count else None,
                    "metric_value": float(metric_value) if metric_value is not None else None,
                }
            )
        return output

    def get_batting_strike_rate_split_leaderboard(
        self,
        split_after_balls: int = 20,
        rank_intent: str = "best",
        limit: int = 10,
        min_first_balls: int = 200,
        min_after_balls: int = 120,
    ) -> list[dict[str, Any]]:
        direction = "ASC" if rank_intent == "worst" else "DESC"
        rows = self._fetchall(
            f"""
            WITH legal_batter_balls AS (
              SELECT
                bat AS player_name,
                p_match,
                CAST(p_match AS VARCHAR) || ':' ||
                  CAST(inns AS VARCHAR) || ':' ||
                  CAST(team_bat AS VARCHAR) || ':' ||
                  CAST(bat AS VARCHAR) AS batter_innings,
                TRY_CAST(cur_bat_bf AS INTEGER) AS ball_number,
                TRY_CAST(batruns AS INTEGER) AS runs
              FROM analytics.deliveries_v1
              WHERE NULLIF(TRIM(CAST(bat AS VARCHAR)), '') IS NOT NULL
                AND TRY_CAST(ballfaced AS INTEGER) = 1
                AND TRY_CAST(cur_bat_bf AS INTEGER) IS NOT NULL
            ),
            split_rows AS (
              SELECT
                player_name,
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT batter_innings) AS innings,
                COUNT(DISTINCT CASE WHEN ball_number > ? THEN batter_innings END) AS innings_past_split,
                SUM(CASE WHEN ball_number <= ? THEN 1 ELSE 0 END) AS first_balls,
                SUM(CASE WHEN ball_number <= ? THEN runs ELSE 0 END) AS first_runs,
                SUM(CASE WHEN ball_number > ? THEN 1 ELSE 0 END) AS after_balls,
                SUM(CASE WHEN ball_number > ? THEN runs ELSE 0 END) AS after_runs
              FROM legal_batter_balls
              GROUP BY player_name
            ),
            scored AS (
              SELECT
                player_name,
                matches,
                innings,
                innings_past_split,
                first_balls,
                first_runs,
                after_balls,
                after_runs,
                first_runs / NULLIF(first_balls, 0) * 100.0 AS first_strike_rate,
                after_runs / NULLIF(after_balls, 0) * 100.0 AS after_strike_rate,
                after_runs / NULLIF(after_balls, 0) * 100.0
                  - first_runs / NULLIF(first_balls, 0) * 100.0 AS metric_value
              FROM split_rows
            )
            SELECT
              player_name,
              matches,
              innings,
              innings_past_split,
              first_balls,
              first_runs,
              after_balls,
              after_runs,
              first_strike_rate,
              after_strike_rate,
              metric_value
            FROM scored
            WHERE first_balls >= ?
              AND after_balls >= ?
              AND metric_value IS NOT NULL
            ORDER BY metric_value {direction}, after_balls DESC
            LIMIT ?
            """,
            [
                split_after_balls,
                split_after_balls,
                split_after_balls,
                split_after_balls,
                split_after_balls,
                min_first_balls,
                min_after_balls,
                limit,
            ],
        )
        output = []
        for row in rows:
            (
                player_name,
                matches,
                innings,
                innings_past_split,
                first_balls,
                first_runs,
                after_balls,
                after_runs,
                first_strike_rate,
                after_strike_rate,
                metric_value,
            ) = row
            output.append(
                {
                    "player_name": str(player_name),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "innings_past_split": int(innings_past_split or 0),
                    "first_balls": int(first_balls or 0),
                    "first_runs": int(first_runs or 0),
                    "after_balls": int(after_balls or 0),
                    "after_runs": int(after_runs or 0),
                    "first_strike_rate": float(first_strike_rate) if first_strike_rate is not None else None,
                    "after_strike_rate": float(after_strike_rate) if after_strike_rate is not None else None,
                    "metric_value": float(metric_value) if metric_value is not None else None,
                }
            )
        return output

    def get_batting_field_zone_leaderboard(
        self,
        field_zone: str,
        limit: int = 50,
        min_balls: int = 20,
    ) -> list[dict[str, Any]]:
        zone_condition = self._field_zone_condition(field_zone)
        rows = self._fetchall(
            f"""
            WITH zone_rows AS (
              SELECT
                bat AS player_name,
                COUNT(DISTINCT p_match) AS matches,
                COUNT(DISTINCT
                  CAST(p_match AS VARCHAR) || ':' ||
                  CAST(inns AS VARCHAR) || ':' ||
                  CAST(team_bat AS VARCHAR)
                ) AS innings,
                COUNT(*) AS balls,
                SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
              FROM analytics.deliveries_v1
              WHERE NULLIF(TRIM(CAST(bat AS VARCHAR)), '') IS NOT NULL
                AND TRY_CAST(ballfaced AS INTEGER) = 1
                AND {zone_condition}
              GROUP BY bat
            )
            SELECT
              player_name,
              matches,
              innings,
              balls,
              runs,
              dot_balls,
              boundary_balls,
              false_shots
            FROM zone_rows
            WHERE balls >= ?
            ORDER BY runs DESC, balls DESC
            LIMIT ?
            """,
            [min_balls, limit],
        )
        output = []
        for row in rows:
            player_name, matches, innings, balls, runs, dot_balls, boundary_balls, false_shots = row
            ball_count = int(balls or 0)
            run_count = int(runs or 0)
            dot_count = int(dot_balls or 0)
            boundary_count = int(boundary_balls or 0)
            false_count = int(false_shots or 0)
            output.append(
                {
                    "player_name": str(player_name),
                    "matches": int(matches or 0),
                    "innings": int(innings or 0),
                    "balls": ball_count,
                    "runs": run_count,
                    "strike_rate": (run_count / ball_count * 100.0) if ball_count else None,
                    "dot_percentage": (dot_count / ball_count * 100.0) if ball_count else None,
                    "boundary_percentage": (boundary_count / ball_count * 100.0) if ball_count else None,
                    "false_shot_percentage": (false_count / ball_count * 100.0) if ball_count else None,
                    "metric_value": run_count,
                }
            )
        return output

    def get_milestone_vulnerability_leaderboard(
        self,
        post_milestone_balls: int = 12,
        rank_intent: str = "best",
        limit: int = 10,
        min_milestones: int = 5,
        min_post_balls: int = 24,
        min_baseline_balls: int = 60,
    ) -> list[dict[str, Any]]:
        direction = "ASC" if rank_intent == "worst" else "DESC"
        rows = self._fetchall(
            f"""
            WITH legal_batter_balls AS (
              SELECT
                bat AS player_name,
                p_match,
                CAST(p_match AS VARCHAR) || ':' ||
                  CAST(inns AS VARCHAR) || ':' ||
                  CAST(team_bat AS VARCHAR) || ':' ||
                  CAST(bat AS VARCHAR) AS batter_innings,
                TRY_CAST(cur_bat_bf AS INTEGER) AS ball_number,
                TRY_CAST(cur_bat_runs AS INTEGER) AS current_runs,
                TRY_CAST(batruns AS INTEGER) AS runs_on_ball,
                CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END AS dismissal,
                CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END AS dot_ball,
                CASE WHEN TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END AS false_shot
              FROM analytics.deliveries_v1
              WHERE NULLIF(TRIM(CAST(bat AS VARCHAR)), '') IS NOT NULL
                AND TRY_CAST(ballfaced AS INTEGER) = 1
                AND TRY_CAST(cur_bat_bf AS INTEGER) IS NOT NULL
                AND TRY_CAST(cur_bat_runs AS INTEGER) IS NOT NULL
            ),
            milestone_events AS (
              SELECT *, 50 AS milestone
              FROM legal_batter_balls
              WHERE current_runs - COALESCE(runs_on_ball, 0) < 50
                AND current_runs >= 50
              UNION ALL
              SELECT *, 100 AS milestone
              FROM legal_batter_balls
              WHERE current_runs - COALESCE(runs_on_ball, 0) < 100
                AND current_runs >= 100
            ),
            post_window_balls AS (
              SELECT
                m.player_name,
                m.batter_innings,
                m.ball_number AS milestone_ball,
                m.milestone,
                b.ball_number,
                b.dismissal,
                b.dot_ball,
                b.false_shot
              FROM milestone_events m
              JOIN legal_batter_balls b
                ON b.batter_innings = m.batter_innings
               AND b.ball_number > m.ball_number
               AND b.ball_number <= m.ball_number + ?
            ),
            post_by_player AS (
              SELECT
                player_name,
                COUNT(DISTINCT batter_innings || ':' || CAST(milestone AS VARCHAR) || ':' || CAST(milestone_ball AS VARCHAR)) AS milestones,
                COUNT(*) AS post_balls,
                SUM(dismissal) AS post_dismissals,
                SUM(dot_ball) AS post_dots,
                SUM(false_shot) AS post_false_shots
              FROM post_window_balls
              GROUP BY player_name
            ),
            post_keys AS (
              SELECT DISTINCT batter_innings, ball_number
              FROM post_window_balls
            ),
            baseline_by_player AS (
              SELECT
                b.player_name,
                COUNT(*) AS baseline_balls,
                SUM(b.dismissal) AS baseline_dismissals
              FROM legal_batter_balls b
              LEFT JOIN post_keys p
                ON p.batter_innings = b.batter_innings
               AND p.ball_number = b.ball_number
              WHERE b.ball_number > 20
                AND p.ball_number IS NULL
              GROUP BY b.player_name
            ),
            scored AS (
              SELECT
                p.player_name,
                p.milestones,
                p.post_balls,
                p.post_dismissals,
                p.post_dots,
                p.post_false_shots,
                base.baseline_balls,
                base.baseline_dismissals,
                p.post_dismissals / NULLIF(p.post_balls, 0) * 100.0 AS post_dismissal_percentage,
                base.baseline_dismissals / NULLIF(base.baseline_balls, 0) * 100.0 AS baseline_dismissal_percentage,
                p.post_dismissals / NULLIF(p.post_balls, 0) * 100.0
                  - base.baseline_dismissals / NULLIF(base.baseline_balls, 0) * 100.0 AS metric_value,
                p.post_dots / NULLIF(p.post_balls, 0) * 100.0 AS post_dot_percentage,
                p.post_false_shots / NULLIF(p.post_balls, 0) * 100.0 AS post_false_shot_percentage
              FROM post_by_player p
              JOIN baseline_by_player base
                ON base.player_name = p.player_name
            )
            SELECT
              player_name,
              milestones,
              post_balls,
              post_dismissals,
              post_dots,
              post_false_shots,
              baseline_balls,
              baseline_dismissals,
              post_dismissal_percentage,
              baseline_dismissal_percentage,
              metric_value,
              post_dot_percentage,
              post_false_shot_percentage
            FROM scored
            WHERE milestones >= ?
              AND post_balls >= ?
              AND baseline_balls >= ?
              AND metric_value IS NOT NULL
            ORDER BY metric_value {direction}, post_balls DESC
            LIMIT ?
            """,
            [post_milestone_balls, min_milestones, min_post_balls, min_baseline_balls, limit],
        )
        output = []
        for row in rows:
            (
                player_name,
                milestones,
                post_balls,
                post_dismissals,
                post_dots,
                post_false_shots,
                baseline_balls,
                baseline_dismissals,
                post_dismissal_percentage,
                baseline_dismissal_percentage,
                metric_value,
                post_dot_percentage,
                post_false_shot_percentage,
            ) = row
            output.append(
                {
                    "player_name": str(player_name),
                    "milestones": int(milestones or 0),
                    "post_balls": int(post_balls or 0),
                    "post_dismissals": int(post_dismissals or 0),
                    "post_dots": int(post_dots or 0),
                    "post_false_shots": int(post_false_shots or 0),
                    "baseline_balls": int(baseline_balls or 0),
                    "baseline_dismissals": int(baseline_dismissals or 0),
                    "post_dismissal_percentage": float(post_dismissal_percentage) if post_dismissal_percentage is not None else None,
                    "baseline_dismissal_percentage": float(baseline_dismissal_percentage)
                    if baseline_dismissal_percentage is not None
                    else None,
                    "metric_value": float(metric_value) if metric_value is not None else None,
                    "post_dot_percentage": float(post_dot_percentage) if post_dot_percentage is not None else None,
                    "post_false_shot_percentage": float(post_false_shot_percentage) if post_false_shot_percentage is not None else None,
                }
            )
        return output

    def get_matchup_leaderboard(
        self,
        metric: str,
        batter_name: str | None = None,
        bowler_name: str | None = None,
        subject: str = "bowler",
        rank_intent: str = "best",
        bowling_kind: str | None = None,
        bowling_style_group: str | None = None,
        length: str | None = None,
        limit: int = 10,
        min_balls: int = 12,
    ) -> list[dict[str, Any]]:
        group_col = "bowl" if subject == "bowler" else "bat"
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        metric_expressions = {
            "wickets_taken": "dismissals",
            "batting_strike_rate": "runs / NULLIF(balls, 0) * 100.0",
            "economy_rate": "runs / NULLIF(legal_balls / 6.0, 0)",
            "runs_scored": "runs",
            "false_shot_percentage": "false_shots / NULLIF(balls, 0) * 100.0",
            "dot_percentage": "dot_balls / NULLIF(balls, 0) * 100.0",
        }
        lower_is_better = metric in {"economy_rate", "false_shot_percentage", "dot_percentage"}
        metric_expression = metric_expressions.get(metric, metric_expressions["wickets_taken"])
        if rank_intent == "worst":
            direction = "DESC" if lower_is_better else "ASC"
        else:
            direction = "ASC" if lower_is_better else "DESC"

        clauses = [f"NULLIF(TRIM(CAST({group_col} AS VARCHAR)), '') IS NOT NULL"]
        params: list[Any] = []
        if batter_name:
            clauses.append("bat = ?")
            params.append(batter_name)
        if bowler_name:
            clauses.append("bowl = ?")
            params.append(bowler_name)
        if bowling_kind:
            clauses.append("bowl_kind = ?")
            params.append(bowling_kind)
        if length:
            clauses.append("length = ?")
            params.append(length)
        style_clause, style_params = self._bowling_style_group_clause(bowling_style_group)
        where_sql = " WHERE " + " AND ".join(clauses)

        rows = self._fetchall(
            f"""
            WITH matchup_rows AS (
              SELECT
                {group_col} AS player_name,
                MAX(NULLIF(TRIM(CAST(bowl_style AS VARCHAR)), '')) AS bowling_style,
                COUNT(*) AS balls,
                SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
                SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
                SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS dismissals,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
              FROM analytics.deliveries_v1
            """
            + where_sql
            + style_clause
            + f"""
              GROUP BY {group_col}
            )
            SELECT
              player_name,
              bowling_style,
              balls,
              legal_balls,
              runs,
              dismissals,
              dot_balls,
              boundary_balls,
              false_shots,
              {metric_expression} AS metric_value
            FROM matchup_rows
            WHERE balls >= ?
            ORDER BY metric_value {direction}, balls DESC
            LIMIT ?
            """,
            [*params, *style_params, min_balls, limit],
        )
        output = []
        for row in rows:
            player_name, bowling_style, balls, legal_balls, runs, dismissals, dot_balls, boundary_balls, false_shots, metric_value = row
            ball_count = int(balls or 0)
            legal_balls_count = int(legal_balls or 0)
            run_count = int(runs or 0)
            overs = legal_balls_count / 6.0 if legal_balls_count else None
            output.append(
                {
                    "player_name": str(player_name),
                    "bowling_style": str(bowling_style) if bowling_style is not None else None,
                    "balls": ball_count,
                    "legal_balls": legal_balls_count,
                    "runs": run_count,
                    "dismissals": int(dismissals or 0),
                    "dot_balls": int(dot_balls or 0),
                    "boundary_balls": int(boundary_balls or 0),
                    "false_shots": int(false_shots or 0),
                    "strike_rate": (run_count / ball_count * 100.0) if ball_count else None,
                    "economy_rate": (run_count / overs) if overs else None,
                    "dot_percentage": (int(dot_balls or 0) / ball_count * 100.0) if ball_count else None,
                    "false_shot_percentage": (int(false_shots or 0) / ball_count * 100.0) if ball_count else None,
                    "metric_value": float(metric_value) if metric_value is not None else None,
                }
            )
        return output

    def get_matchup_bowling_style_breakdown(
        self,
        metric: str,
        batter_name: str,
        bowling_kind: str | None = None,
        bowling_style_group: str | None = None,
        length: str | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_balls: int = 12,
    ) -> list[dict[str, Any]]:
        legal_ball_predicate = (
            "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 "
            "AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"
        )
        bowler_wicket_predicate = (
            "LOWER(CAST(dismissal AS VARCHAR)) IN "
            "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
        )
        metric_expressions = {
            "wickets_taken": "dismissals",
            "batting_strike_rate": "runs / NULLIF(balls, 0) * 100.0",
            "economy_rate": "runs / NULLIF(legal_balls / 6.0, 0)",
            "runs_scored": "runs",
            "false_shot_percentage": "false_shots / NULLIF(balls, 0) * 100.0",
            "dot_percentage": "dot_balls / NULLIF(balls, 0) * 100.0",
        }
        lower_is_better = metric in {"economy_rate", "false_shot_percentage", "dot_percentage"}
        metric_expression = metric_expressions.get(metric, metric_expressions["wickets_taken"])
        if rank_intent == "worst":
            direction = "DESC" if lower_is_better else "ASC"
        else:
            direction = "ASC" if lower_is_better else "DESC"

        clauses = [
            "bat = ?",
            "NULLIF(TRIM(CAST(bowl_style AS VARCHAR)), '') IS NOT NULL",
        ]
        params: list[Any] = [batter_name]
        if bowling_kind:
            clauses.append("bowl_kind = ?")
            params.append(bowling_kind)
        if length:
            clauses.append("length = ?")
            params.append(length)
        style_clause, style_params = self._bowling_style_group_clause(bowling_style_group)
        where_sql = " WHERE " + " AND ".join(clauses)

        rows = self._fetchall(
            f"""
            WITH style_rows AS (
              SELECT
                bowl_style,
                COUNT(DISTINCT bowl) AS bowlers,
                COUNT(*) AS balls,
                SUM(CASE WHEN {legal_ball_predicate} THEN 1 ELSE 0 END) AS legal_balls,
                SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
                SUM(CASE WHEN {bowler_wicket_predicate} THEN 1 ELSE 0 END) AS dismissals,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
              FROM analytics.deliveries_v1
            """
            + where_sql
            + style_clause
            + f"""
              GROUP BY bowl_style
            )
            SELECT
              bowl_style,
              bowlers,
              balls,
              legal_balls,
              runs,
              dismissals,
              dot_balls,
              boundary_balls,
              false_shots,
              {metric_expression} AS metric_value
            FROM style_rows
            WHERE balls >= ?
            ORDER BY metric_value {direction}, balls DESC
            LIMIT ?
            """,
            [*params, *style_params, min_balls, limit],
        )
        output = []
        for row in rows:
            style, bowlers, balls, legal_balls, runs, dismissals, dot_balls, boundary_balls, false_shots, metric_value = row
            ball_count = int(balls or 0)
            legal_balls_count = int(legal_balls or 0)
            run_count = int(runs or 0)
            overs = legal_balls_count / 6.0 if legal_balls_count else None
            output.append(
                {
                    "bowling_style": str(style),
                    "bowlers": int(bowlers or 0),
                    "balls": ball_count,
                    "legal_balls": legal_balls_count,
                    "runs": run_count,
                    "dismissals": int(dismissals or 0),
                    "dot_balls": int(dot_balls or 0),
                    "boundary_balls": int(boundary_balls or 0),
                    "false_shots": int(false_shots or 0),
                    "strike_rate": (run_count / ball_count * 100.0) if ball_count else None,
                    "economy_rate": (run_count / overs) if overs else None,
                    "dot_percentage": (int(dot_balls or 0) / ball_count * 100.0) if ball_count else None,
                    "false_shot_percentage": (int(false_shots or 0) / ball_count * 100.0) if ball_count else None,
                    "metric_value": float(metric_value) if metric_value is not None else None,
                }
            )
        return output

    def get_line_length_breakdown(
        self,
        batter_name: str,
        group_by: str,
        metric: str,
        phase: str | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_balls: int = 12,
    ) -> list[dict[str, Any]]:
        if group_by not in {"line", "length"}:
            group_by = "length"
        metric_expressions = {
            "wickets_taken": "dismissals",
            "batting_strike_rate": "runs / NULLIF(balls, 0) * 100.0",
            "bowler_dot_balls": "dot_balls",
            "dot_percentage": "dot_balls / NULLIF(balls, 0) * 100.0",
            "false_shot_percentage": "false_shots / NULLIF(balls, 0) * 100.0",
        }
        metric_expression = metric_expressions.get(metric, metric_expressions["wickets_taken"])
        if metric == "batting_strike_rate" and rank_intent == "worst":
            direction = "ASC"
        elif metric == "dot_percentage" and rank_intent == "worst":
            direction = "ASC"
        else:
            direction = "DESC"
        phase_clause, phase_params = self._phase_clause(phase)
        rows = self._fetchall(
            f"""
            WITH breakdown AS (
              SELECT
                {group_by} AS bucket,
                COUNT(*) AS balls,
                SUM(TRY_CAST(batruns AS INTEGER)) AS runs,
                SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
                SUM(CASE WHEN TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
                SUM(CASE WHEN TRY_CAST(control AS DOUBLE) = 0 THEN 1 ELSE 0 END) AS false_shots
              FROM analytics.deliveries_v1
              WHERE bat = ?
                AND NULLIF(TRIM(CAST({group_by} AS VARCHAR)), '') IS NOT NULL
            """
            + phase_clause
            + f"""
              GROUP BY {group_by}
            )
            SELECT
              bucket,
              balls,
              runs,
              dismissals,
              dot_balls,
              boundary_balls,
              false_shots,
              {metric_expression} AS metric_value
            FROM breakdown
            WHERE balls >= ?
            ORDER BY metric_value {direction}, balls DESC
            LIMIT ?
            """,
            [batter_name, *phase_params, min_balls, limit],
        )
        output = []
        for row in rows:
            bucket, balls, runs, dismissals, dot_balls, boundary_balls, false_shots, metric_value = row
            ball_count = int(balls or 0)
            run_count = int(runs or 0)
            output.append(
                {
                    "bucket": str(bucket),
                    "balls": ball_count,
                    "runs": run_count,
                    "dismissals": int(dismissals or 0),
                    "dot_balls": int(dot_balls or 0),
                    "boundary_balls": int(boundary_balls or 0),
                    "false_shots": int(false_shots or 0),
                    "strike_rate": (run_count / ball_count * 100.0) if ball_count else None,
                    "dot_percentage": (int(dot_balls or 0) / ball_count * 100.0) if ball_count else None,
                    "false_shot_percentage": (int(false_shots or 0) / ball_count * 100.0) if ball_count else None,
                    "metric_value": float(metric_value) if metric_value is not None else None,
                }
            )
        return output

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

    def get_pitch_map(
        self,
        player_name: str,
        bowler_name: str | None = None,
        phase: str | None = None,
        years: list[int] | None = None,
        venue: str | None = None,
    ) -> dict[str, Any]:
        where_clause, params = self._batter_where_clause(
            player_name,
            bowler_name,
            phase=phase,
            years=years,
            venue=venue,
        )
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
