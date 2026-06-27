from backend.app.domain.intent_models import (
    AnswerShape,
    ContextScope,
    CricketIntentPlan,
    CricketMetric,
    IntentSubject,
    MatchContext,
    QueryType,
    SubjectRole,
)
from backend.app.domain.metric_models import QueryClass
from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.metric_catalog import MetricCatalog
from backend.app.services.query_router import QueryRoute


class StubRepository:
    def list_player_names(self) -> list[str]:
        return [
            "Virat Kohli",
            "Steven Smith",
            "Hardik Pandya",
            "Jasprit Bumrah",
            "Pat Cummins",
            "Mitchell Starc",
            "Tim Southee",
            "David Miller",
            "Heinrich Klaasen",
            "Glenn Maxwell",
            "James Anderson",
            "Kane Williamson",
            "MS Dhoni",
            "Rohit Sharma",
            "Travis Head",
            "Jos Buttler",
        ]

    def list_venues(self) -> list[str]:
        return ["M Chinnaswamy Stadium", "Lord's, London"]

    def get_player_batting_summary(self, player_name: str, phase: str | None = None) -> dict[str, object] | None:
        return {
            "player_name": player_name,
            "balls_faced": 100,
            "runs_scored": 120,
            "dismissals": 4,
            "average": 30.0,
            "strike_rate": 120.0,
            "boundary_percentage": 14.0,
            "dot_percentage": 36.0,
            "control_percentage": 78.0,
        }

    def get_player_bowling_summary(self, player_name: str, phase: str | None = None) -> dict[str, object] | None:
        if player_name == "Kane Williamson":
            return {
                "player_name": player_name,
                "innings": 2,
                "balls_bowled": 12,
                "delivery_rows": 12,
                "overs": 2.0,
                "runs_conceded": 14,
                "wickets": 0,
                "economy_rate": 7.0,
                "bowling_average": None,
                "balls_per_wicket": None,
                "boundary_balls": 1,
                "balls_per_boundary": 12.0,
                "boundary_percentage": 8.33,
                "dot_balls": 5,
                "dot_percentage": 41.67,
            }
        return {
            "player_name": player_name,
            "innings": 66,
            "balls_bowled": 1123,
            "delivery_rows": 1158,
            "overs": 187.17,
            "runs_conceded": 1081,
            "wickets": 70,
            "economy_rate": 5.78,
            "bowling_average": 15.44,
            "balls_per_wicket": 16.04,
            "boundary_balls": 99,
            "balls_per_boundary": 11.34,
            "boundary_percentage": 8.82,
            "dot_balls": 512,
            "dot_percentage": 45.59,
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
    ) -> dict[str, object] | None:
        if player_name != "MS Dhoni" or year != 2011 or stage != "final":
            return None
        values = {
            "balls_bowled": 0,
            "overs_bowled": 0.0,
            "balls_faced": 79,
            "runs_scored": 91,
            "runs_conceded": 0,
            "wickets_taken": 0,
            "dot_balls": 21,
            "bowler_dot_balls": 0,
            "boundaries": 10,
            "boundaries_conceded": 0,
            "economy_rate": None,
            "batting_strike_rate": 115.19,
        }
        return {
            "player_name": player_name,
            "metric": metric,
            "metric_value": values.get(metric),
            "match_id": "2011-final",
            "date": "2011-04-02",
            "competition": competition or "ICC Cricket World Cup",
            "ground": "Wankhede Stadium",
            "batting_teams": "Sri Lanka, India",
            "bowling_teams": "India, Sri Lanka",
            "values": values,
        }

    def get_player_best_bowling_figures(self, player_name: str, limit: int = 5) -> list[dict[str, object]]:
        return [
            {
                "player_name": player_name,
                "match_id": "123",
                "date": "2015-02-20",
                "competition": "ICC Cricket World Cup",
                "ground": "Wellington",
                "opposition": "England",
                "innings": 1,
                "balls_bowled": 54,
                "delivery_rows": 54,
                "runs_conceded": 33,
                "wickets": 7,
            },
            {
                "player_name": player_name,
                "match_id": "124",
                "date": "2014-01-01",
                "competition": "ODI",
                "ground": "Auckland",
                "opposition": "India",
                "innings": 2,
                "balls_bowled": 60,
                "delivery_rows": 60,
                "runs_conceded": 45,
                "wickets": 5,
            },
        ][:limit]

    def get_player_bowling_opponent_summary(self, player_name: str, limit: int = 20) -> list[dict[str, object]]:
        return [
            {
                "player_name": player_name,
                "opponent": "Australia",
                "matches": 38,
                "innings": 38,
                "balls_bowled": 1800,
                "delivery_rows": 1840,
                "overs": 300.0,
                "runs_conceded": 1320,
                "wickets": 50,
                "economy_rate": 4.4,
                "bowling_average": 26.4,
                "balls_per_wicket": 36.0,
                "dot_percentage": 58.0,
                "boundary_percentage": 6.8,
                "balls_per_boundary": 14.7,
            },
            {
                "player_name": player_name,
                "opponent": "India",
                "matches": 30,
                "innings": 30,
                "balls_bowled": 1500,
                "delivery_rows": 1535,
                "overs": 250.0,
                "runs_conceded": 1180,
                "wickets": 34,
                "economy_rate": 4.72,
                "bowling_average": 34.71,
                "balls_per_wicket": 44.12,
                "dot_percentage": 55.0,
                "boundary_percentage": 7.4,
                "balls_per_boundary": 13.5,
            },
        ][:limit]

    def get_player_batting_venue_summary(self, player_name: str, limit: int = 20) -> list[dict[str, object]]:
        return [
            {
                "player_name": player_name,
                "venue": "Seddon Park, Hamilton",
                "matches": 12,
                "innings": 12,
                "balls_faced": 720,
                "runs_scored": 640,
                "dismissals": 7,
                "average": 91.43,
                "strike_rate": 88.89,
                "boundary_percentage": 8.2,
                "dot_percentage": 42.0,
                "control_percentage": 88.0,
            },
            {
                "player_name": player_name,
                "venue": "Eden Park, Auckland",
                "matches": 10,
                "innings": 10,
                "balls_faced": 600,
                "runs_scored": 510,
                "dismissals": 8,
                "average": 63.75,
                "strike_rate": 85.0,
                "boundary_percentage": 7.6,
                "dot_percentage": 44.0,
                "control_percentage": 86.0,
            },
        ][:limit]

    def get_player_bowling_venue_summary(self, player_name: str, limit: int = 20) -> list[dict[str, object]]:
        return [
            {
                "player_name": player_name,
                "venue": "Lord's, London",
                "matches": 4,
                "innings": 4,
                "balls_bowled": 160,
                "delivery_rows": 164,
                "overs": 26.67,
                "runs_conceded": 130,
                "wickets": 8,
                "economy_rate": 4.87,
                "bowling_average": 16.25,
                "balls_per_wicket": 20.0,
                "dot_percentage": 60.0,
                "boundary_percentage": 7.5,
                "balls_per_boundary": 13.33,
            }
        ][:limit]

    def get_venue_bowling_leaderboard(
        self,
        venue_name: str,
        limit: int = 10,
        excluded_teams: list[str] | None = None,
    ) -> list[dict[str, object]]:
        if venue_name == "Lord's, London" and excluded_teams == ["England"]:
            return [
                {
                    "player_name": "Glenn McGrath",
                    "deliveries": 300,
                    "delivery_rows": 306,
                    "runs_conceded": 190,
                    "wickets": 14,
                    "economy_rate": 3.8,
                },
                {
                    "player_name": "Brett Lee",
                    "deliveries": 220,
                    "delivery_rows": 226,
                    "runs_conceded": 160,
                    "wickets": 13,
                    "economy_rate": 4.36,
                },
            ][:limit]
        if venue_name == "Lord's, London":
            return [
                {
                    "player_name": "Stuart Broad",
                    "deliveries": 330,
                    "delivery_rows": 336,
                    "runs_conceded": 210,
                    "wickets": 15,
                    "economy_rate": 3.82,
                },
                {
                    "player_name": "Glenn McGrath",
                    "deliveries": 300,
                    "delivery_rows": 306,
                    "runs_conceded": 190,
                    "wickets": 14,
                    "economy_rate": 3.8,
                },
            ][:limit]
        return [
            {
                "player_name": "Jasprit Bumrah",
                "deliveries": 60,
                "delivery_rows": 60,
                "runs_conceded": 42,
                "wickets": 6,
                "economy_rate": 4.2,
            }
        ][:limit]

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
    ) -> list[dict[str, object]]:
        if metric == "wickets_taken" and competition == "ICC Cricket World Cup" and years == [2011]:
            return [
                {
                    "player_name": "Shahid Afridi",
                    "matches": 8,
                    "innings": 8,
                    "balls_bowled": 447,
                    "delivery_rows": 455,
                    "overs": 74.5,
                    "runs_conceded": 240,
                    "wickets": 21,
                    "economy_rate": 3.21,
                    "bowling_average": 11.43,
                    "balls_per_wicket": 21.29,
                    "dot_percentage": 60.0,
                    "boundary_percentage": 4.0,
                    "balls_per_boundary": 25.0,
                },
                {
                    "player_name": "Zaheer Khan",
                    "matches": 9,
                    "innings": 9,
                    "balls_bowled": 485,
                    "delivery_rows": 492,
                    "overs": 80.83,
                    "runs_conceded": 394,
                    "wickets": 21,
                    "economy_rate": 4.88,
                    "bowling_average": 18.76,
                    "balls_per_wicket": 23.1,
                    "dot_percentage": 58.0,
                    "boundary_percentage": 7.0,
                    "balls_per_boundary": 14.29,
                },
            ]
        if metric == "wickets_taken":
            return [
                {
                    "player_name": "Lasith Malinga",
                    "matches": 203,
                    "innings": 203,
                    "balls_bowled": 4158,
                    "delivery_rows": 4210,
                    "overs": 693.0,
                    "runs_conceded": 3249,
                    "wickets": 102,
                    "economy_rate": 4.69,
                    "bowling_average": 31.85,
                    "balls_per_wicket": 40.76,
                    "dot_percentage": 62.0,
                    "boundary_percentage": 9.4,
                    "balls_per_boundary": 10.64,
                },
                {
                    "player_name": "Brett Lee",
                    "matches": 129,
                    "innings": 129,
                    "balls_bowled": 3242,
                    "delivery_rows": 3288,
                    "overs": 540.33,
                    "runs_conceded": 2328,
                    "wickets": 100,
                    "economy_rate": 4.31,
                    "bowling_average": 23.28,
                    "balls_per_wicket": 32.42,
                    "dot_percentage": 65.0,
                    "boundary_percentage": 8.8,
                    "balls_per_boundary": 11.36,
                },
            ]
        if rank_intent == "worst":
            return [
                {
                    "player_name": "Gerald Coetzee",
                    "matches": 7,
                    "innings": 7,
                    "balls_bowled": 60,
                    "delivery_rows": 64,
                    "overs": 10.0,
                    "runs_conceded": 98,
                    "wickets": 4,
                    "economy_rate": 9.8,
                    "bowling_average": 24.5,
                    "balls_per_wicket": 15.0,
                    "dot_percentage": 41.67,
                    "boundary_percentage": 18.33,
                    "balls_per_boundary": 5.45,
                },
                {
                    "player_name": "Dilruwan Perera",
                    "matches": 4,
                    "innings": 4,
                    "balls_bowled": 66,
                    "delivery_rows": 70,
                    "overs": 11.0,
                    "runs_conceded": 91,
                    "wickets": 2,
                    "economy_rate": 8.27,
                    "bowling_average": 45.5,
                    "balls_per_wicket": 33.0,
                    "dot_percentage": 42.42,
                    "boundary_percentage": 13.64,
                    "balls_per_boundary": 7.33,
                },
            ]
        return [
            {
                "player_name": "Mohammad Nabi",
                "matches": 9,
                "innings": 9,
                "balls_bowled": 75,
                "delivery_rows": 78,
                "overs": 12.5,
                "runs_conceded": 46,
                "wickets": 3,
                "economy_rate": 3.68,
                "bowling_average": 15.33,
                "balls_per_wicket": 25.0,
                "dot_percentage": 54.67,
                "boundary_percentage": 2.67,
                "balls_per_boundary": 37.5,
            },
            {
                "player_name": "Jasprit Bumrah",
                "matches": 13,
                "innings": 13,
                "balls_bowled": 222,
                "delivery_rows": 230,
                "overs": 37.0,
                "runs_conceded": 193,
                "wickets": 15,
                "economy_rate": 5.22,
                "bowling_average": 12.87,
                "balls_per_wicket": 14.8,
                "dot_percentage": 49.1,
                "boundary_percentage": 6.76,
                "balls_per_boundary": 14.8,
            },
        ]

    def get_bowling_economy_leaderboard(
        self,
        phase: str | None = None,
        years: list[int] | None = None,
        year_mode: str | None = None,
        competition: str | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_legal_balls: int = 60,
    ) -> list[dict[str, object]]:
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

    def get_fielding_catches_coverage(self, competition: str | None = None, years: list[int] | None = None) -> dict[str, object]:
        return {
            "caught_dismissals": 462,
            "matches": 48,
            "dismissed_batters": 132,
            "has_catcher_column": False,
            "available_dismissal_fields": ["dismissal", "p_out", "bat", "bowl"],
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
    ) -> list[dict[str, object]]:
        return [
            {
                "player_name": "Rashid Khan",
                "matches": 31,
                "innings": 31,
                "balls": 74,
                "runs": 42,
                "dismissals": 6,
                "average": 7.0,
                "balls_per_dismissal": 12.33,
                "strike_rate": 56.76,
                "boundary_percentage": 4.05,
                "dot_percentage": 62.16,
                "strike_rotation_percentage": 33.78,
                "false_shot_percentage": 18.92,
                "metric_value": 56.76
                if metric == "batting_strike_rate"
                else 18.92
                if metric == "false_shot_percentage"
                else 7.0,
            }
        ]

    def get_batting_strike_rate_split_leaderboard(
        self,
        split_after_balls: int = 20,
        rank_intent: str = "best",
        limit: int = 10,
        min_first_balls: int = 200,
        min_after_balls: int = 120,
    ) -> list[dict[str, object]]:
        return [
            {
                "player_name": "Michael Bracewell",
                "matches": 20,
                "innings": 20,
                "innings_past_split": 10,
                "first_balls": 305,
                "first_runs": 262,
                "after_balls": 204,
                "after_runs": 326,
                "first_strike_rate": 85.9016,
                "after_strike_rate": 159.8039,
                "metric_value": 73.9023,
            },
            {
                "player_name": "Yusuf Pathan",
                "matches": 41,
                "innings": 41,
                "innings_past_split": 13,
                "first_balls": 458,
                "first_runs": 433,
                "after_balls": 256,
                "after_runs": 377,
                "first_strike_rate": 94.5415,
                "after_strike_rate": 147.2656,
                "metric_value": 52.7241,
            },
        ]

    def get_milestone_vulnerability_leaderboard(
        self,
        post_milestone_balls: int = 12,
        rank_intent: str = "best",
        limit: int = 10,
        min_milestones: int = 5,
        min_post_balls: int = 24,
        min_baseline_balls: int = 60,
    ) -> list[dict[str, object]]:
        return [
            {
                "player_name": "Ryan Burl",
                "milestones": 6,
                "post_balls": 25,
                "post_dismissals": 5,
                "post_dots": 11,
                "post_false_shots": 9,
                "baseline_balls": 496,
                "baseline_dismissals": 10,
                "post_dismissal_percentage": 20.0,
                "baseline_dismissal_percentage": 2.0161,
                "metric_value": 17.9839,
                "post_dot_percentage": 44.0,
                "post_false_shot_percentage": 36.0,
            },
            {
                "player_name": "Robin Uthappa",
                "milestones": 6,
                "post_balls": 32,
                "post_dismissals": 5,
                "post_dots": 15,
                "post_false_shots": 10,
                "baseline_balls": 381,
                "baseline_dismissals": 17,
                "post_dismissal_percentage": 15.625,
                "baseline_dismissal_percentage": 4.4619,
                "metric_value": 11.1631,
                "post_dot_percentage": 46.875,
                "post_false_shot_percentage": 31.25,
            },
        ]

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
    ) -> list[dict[str, object]]:
        return [
            {
                "player_name": "Moeen Ali",
                "bowling_style": "OB",
                "balls": 153,
                "legal_balls": 150,
                "runs": 161,
                "dismissals": 4,
                "dot_balls": 68,
                "boundary_balls": 17,
                "false_shots": 19,
                "strike_rate": 105.23,
                "economy_rate": 6.44,
                "dot_percentage": 44.44,
                "false_shot_percentage": 12.42,
                "metric_value": 4,
            }
        ]

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
    ) -> list[dict[str, object]]:
        if batter_name != "Travis Head":
            return [
                {
                    "bowling_style": "OB",
                    "bowlers": 12,
                    "balls": 460,
                    "legal_balls": 452,
                    "runs": 608,
                    "dismissals": 15,
                    "dot_balls": 202,
                    "boundary_balls": 64,
                    "false_shots": 70,
                    "strike_rate": 132.17,
                    "economy_rate": 8.07,
                    "dot_percentage": 43.91,
                    "false_shot_percentage": 15.22,
                    "metric_value": 15,
                }
            ]
        return [
            {
                "bowling_style": "SLA",
                "bowlers": 8,
                "balls": 72,
                "legal_balls": 70,
                "runs": 104,
                "dismissals": 2,
                "dot_balls": 26,
                "boundary_balls": 12,
                "false_shots": 8,
                "strike_rate": 144.44,
                "economy_rate": 8.91,
                "dot_percentage": 36.11,
                "false_shot_percentage": 11.11,
                "metric_value": 144.44 if metric == "batting_strike_rate" else 2,
            },
            {
                "bowling_style": "OB",
                "bowlers": 6,
                "balls": 60,
                "legal_balls": 60,
                "runs": 72,
                "dismissals": 3,
                "dot_balls": 30,
                "boundary_balls": 7,
                "false_shots": 10,
                "strike_rate": 120.0,
                "economy_rate": 7.2,
                "dot_percentage": 50.0,
                "false_shot_percentage": 16.67,
                "metric_value": 120.0 if metric == "batting_strike_rate" else 3,
            }
        ]

    def get_line_length_breakdown(
        self,
        batter_name: str,
        group_by: str,
        metric: str,
        phase: str | None = None,
        rank_intent: str = "best",
        limit: int = 10,
        min_balls: int = 12,
    ) -> list[dict[str, object]]:
        return [
            {
                "bucket": "GOOD_LENGTH",
                "balls": 3692,
                "runs": 2594,
                "dismissals": 62,
                "dot_balls": 2267,
                "boundary_balls": 220,
                "false_shots": 646,
                "strike_rate": 70.26,
                "dot_percentage": 61.4,
                "false_shot_percentage": 17.5,
                "metric_value": 62,
            },
            {
                "bucket": "SHORT_OF_A_GOOD_LENGTH",
                "balls": 1806,
                "runs": 1684,
                "dismissals": 25,
                "dot_balls": 915,
                "boundary_balls": 170,
                "false_shots": 355,
                "strike_rate": 93.24,
                "dot_percentage": 50.66,
                "false_shot_percentage": 19.66,
                "metric_value": 25,
            },
        ]

    def get_player_year_trend(self, player_name: str) -> list[dict[str, object]]:
        if player_name == "Jasprit Bumrah":
            return []
        return [{"year": 2024, "runs_scored": 120, "balls_faced": 100, "control_percentage": 81.2}]

    def get_player_bowling_year_trend(self, player_name: str, phase: str | None = None) -> list[dict[str, object]]:
        if player_name == "Mitchell Starc":
            return [
                {
                    "player_name": player_name,
                    "year": 2022,
                    "matches": 7,
                    "innings": 7,
                    "balls_bowled": 108,
                    "delivery_rows": 114,
                    "overs": 18.0,
                    "runs_conceded": 117,
                    "wickets": 7,
                    "economy_rate": 6.5,
                    "bowling_average": 16.71,
                    "balls_per_wicket": 15.43,
                    "dot_balls": 42,
                    "dot_percentage": 38.89,
                    "boundary_balls": 13,
                    "boundary_percentage": 12.04,
                    "balls_per_boundary": 8.31,
                }
            ]
        return [
            {
                "player_name": player_name,
                "year": 2022,
                "matches": 8,
                "innings": 8,
                "balls_bowled": 120,
                "delivery_rows": 126,
                "overs": 20.0,
                "runs_conceded": 104,
                "wickets": 9,
                "economy_rate": 5.2,
                "bowling_average": 11.56,
                "balls_per_wicket": 13.33,
                "dot_balls": 58,
                "dot_percentage": 48.0,
                "boundary_balls": 9,
                "boundary_percentage": 7.5,
                "balls_per_boundary": 13.33,
            },
            {
                "player_name": player_name,
                "year": 2023,
                "matches": 10,
                "innings": 10,
                "balls_bowled": 180,
                "delivery_rows": 188,
                "overs": 30.0,
                "runs_conceded": 168,
                "wickets": 14,
                "economy_rate": 5.6,
                "bowling_average": 12.0,
                "balls_per_wicket": 12.86,
                "dot_balls": 81,
                "dot_percentage": 45.0,
                "boundary_balls": 14,
                "boundary_percentage": 8.0,
                "balls_per_boundary": 12.5,
            },
        ]

    def get_player_batting_position_summary(self, player_name: str, positions: list[int], phase: str | None = None) -> dict[str, object] | None:
        if positions == [1, 2]:
            return {
                "player_name": player_name,
                "positions": positions,
                "innings": 12,
                "balls_faced": 500,
                "runs_scored": 430,
                "dismissals": 10,
                "strike_rate": 86.0,
                "average": 43.0,
                "boundary_percentage": 8.0,
                "dot_percentage": 34.0,
                "control_percentage": 82.0,
                "balls_per_dismissal": 50.0,
                "runs_per_innings": 35.83,
            }
        if positions == [3]:
            return {
                "player_name": player_name,
                "positions": positions,
                "innings": 100,
                "balls_faced": 4000,
                "runs_scored": 3800,
                "dismissals": 70,
                "strike_rate": 95.0,
                "average": 54.29,
                "boundary_percentage": 10.5,
                "dot_percentage": 29.0,
                "control_percentage": 88.0,
                "balls_per_dismissal": 57.14,
                "runs_per_innings": 38.0,
            }
        return None

    def get_player_phase_summary(self, player_name: str) -> list[dict[str, object]]:
        return [
            {
                "player_name": player_name,
                "split": "Powerplay (0-10)",
                "innings": 10,
                "balls_faced": 120,
                "runs_scored": 90,
                "dismissals": 2,
                "average": 45.0,
                "strike_rate": 75.0,
                "runs_per_innings": 9.0,
                "boundary_percentage": 7.5,
                "dot_percentage": 45.0,
                "control_percentage": 80.0,
            }
        ]

    def get_player_bowling_kind_summary(self, player_name: str) -> list[dict[str, object]]:
        return [
            {
                "player_name": player_name,
                "split": "Pace",
                "innings": 10,
                "balls_faced": 80,
                "runs_scored": 88,
                "dismissals": 2,
                "average": 44.0,
                "strike_rate": 110.0,
                "runs_per_innings": 8.8,
                "boundary_percentage": 10.0,
                "dot_percentage": 35.0,
                "control_percentage": 79.0,
            }
        ]

    def get_player_bowling_style_summary(self, player_name: str) -> list[dict[str, object]]:
        return [
            {
                "player_name": player_name,
                "split": "RF",
                "style_code": "RF",
                "bowling_kind": "pace bowler",
                "innings": 10,
                "balls_faced": 90,
                "runs_scored": 85,
                "dismissals": 4,
                "average": 21.25,
                "strike_rate": 94.44,
                "runs_per_innings": 8.5,
                "boundary_percentage": 6.67,
                "dot_percentage": 50.0,
                "control_percentage": 77.0,
            },
            {
                "player_name": player_name,
                "split": "SLA",
                "style_code": "SLA",
                "bowling_kind": "spin bowler",
                "innings": 8,
                "balls_faced": 70,
                "runs_scored": 88,
                "dismissals": 1,
                "average": 88.0,
                "strike_rate": 125.71,
                "runs_per_innings": 11.0,
                "boundary_percentage": 10.0,
                "dot_percentage": 34.29,
                "control_percentage": 84.0,
            },
        ]

    def get_player_shot_breakdown(self, player_name: str, limit: int = 8, phase: str | None = None) -> list[dict[str, object]]:
        return [{"shot": "ON_DRIVE", "balls": 20, "runs": 40}]

    def get_pitch_map(self, player_name: str, bowler_name: str | None = None, phase: str | None = None) -> dict[str, object]:
        return {
            "coverage": {
                "total_balls": 100,
                "covered_balls": 88,
                "coverage_percentage": 88.0,
                "detail": "coded line/length only",
            },
            "cells": [
                {
                    "line": "OUTSIDE_OFFSTUMP",
                    "length": "GOOD_LENGTH",
                    "balls": 16,
                    "runs": 14,
                    "strike_rate": 87.5,
                    "dismissals": 1,
                    "boundary_balls": 2,
                    "dot_balls": 6,
                    "singles": 4,
                    "doubles": 1,
                    "triples": 0,
                    "fours": 2,
                    "sixes": 0,
                    "wicket_balls": 1,
                    "control_percentage": 75.0,
                }
            ],
        }

    def get_wagon_wheel(self, player_name: str, bowler_name: str | None = None, point_limit: int = 160, phase: str | None = None) -> dict[str, object]:
        return {
            "handedness": "RHB",
            "coverage": {
                "total_balls": 100,
                "covered_balls": 92,
                "coverage_percentage": 92.0,
                "detail": "wagon coordinates present",
            },
            "points": [{"x": 120.0, "y": 220.0, "outcome": "four", "runs": 4}],
            "sectors": [
                {
                    "zone_id": 3,
                    "label": "Long Off",
                    "balls": 22,
                    "runs": 34,
                    "dismissals": 1,
                    "strike_rate": 154.55,
                    "run_share_percentage": 24.0,
                    "singles": 4,
                    "doubles": 2,
                    "triples": 0,
                    "fours": 5,
                    "sixes": 1,
                    "wicket_balls": 1,
                }
            ],
        }

    def get_shot_type_profile(self, player_name: str, bowler_name: str | None = None, limit: int = 10, phase: str | None = None) -> dict[str, object]:
        return {
            "coverage": {
                "total_balls": 100,
                "covered_balls": 96,
                "coverage_percentage": 96.0,
                "detail": "shot + control recorded",
            },
            "metrics": [
                {
                    "shot": "ON_DRIVE",
                    "balls": 20,
                    "runs": 40,
                    "run_share_percentage": 32.0,
                    "control_percentage": 85.0,
                    "false_shot_percentage": 15.0,
                    "dismissal_rate": 5.0,
                    "boundary_percentage": 20.0,
                }
            ],
        }

    def get_field_zone_profile(self, player_name: str, bowler_name: str | None = None, phase: str | None = None) -> dict[str, object]:
        return {
            "handedness": "RHB",
            "coverage": {
                "total_balls": 100,
                "covered_balls": 92,
                "coverage_percentage": 92.0,
                "detail": "wagon zone coverage",
            },
            "zones": [
                {
                    "zone_id": 3,
                    "label": "Long Off",
                    "balls": 22,
                    "runs": 34,
                    "dismissals": 1,
                    "strike_rate": 154.55,
                    "run_share_percentage": 24.0,
                    "singles": 4,
                    "doubles": 2,
                    "triples": 0,
                    "fours": 5,
                    "sixes": 1,
                    "wicket_balls": 1,
                }
            ],
        }

    def get_batting_field_zone_leaderboard(
        self,
        field_zone: str,
        limit: int = 50,
        min_balls: int = 20,
    ) -> list[dict[str, object]]:
        return [
            {
                "player_name": "Kumar Sangakkara",
                "matches": 210,
                "innings": 210,
                "balls": 1982,
                "runs": 1248,
                "strike_rate": 62.97,
                "dot_percentage": 46.1,
                "boundary_percentage": 8.2,
                "false_shot_percentage": 10.4,
                "metric_value": 1248,
            },
            {
                "player_name": "Virat Kohli",
                "matches": 180,
                "innings": 180,
                "balls": 1260,
                "runs": 806,
                "strike_rate": 63.97,
                "dot_percentage": 41.8,
                "boundary_percentage": 7.9,
                "false_shot_percentage": 8.1,
                "metric_value": 806,
            },
        ][:limit]

    def get_player_split_summary(self, player_name: str, phase: str | None = None) -> dict[str, float | None]:
        return {"pace_strike_rate": 110.0, "spin_strike_rate": 128.0}

    def get_global_batting_baseline(self, phase: str | None = None) -> dict[str, float | None]:
        return {
            "strike_rate": 84.0,
            "boundary_percentage": 9.0,
            "control_percentage": 81.0,
            "dismissal_resistance": 97.0,
            "pace_strike_rate": 85.0,
            "spin_strike_rate": 82.0,
        }


def test_analytics_service_initializes_router_and_venues() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    assert service.router is not None
    assert "M Chinnaswamy Stadium" in service.available_venues


def test_strengths_response_includes_visual_payloads() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Where does Hardik Pandya score the most and on which shots?")

    assert response.status.value == "supported"
    assert response.visuals is not None
    assert response.visuals.pitch_map is not None
    assert response.visuals.wagon_wheel is not None
    assert response.visuals.shot_profile is not None
    assert response.visuals.field_zones is not None
    assert response.visuals.radar is not None
    assert any(note.title == "Pitch map coverage" for note in response.evidence_notes)


def test_shot_profile_uses_human_readable_shot_labels() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("What shot does Jos Buttler score most runs from?")

    assert response.status.value == "supported"
    assert "ON_DRIVE" not in response.summaries[0].body
    assert "on drive" in response.summaries[0].body
    assert response.tables[0].rows[0][0] == "on drive"
    assert response.charts[0].series[0]["label"] == "on drive"


def test_bowling_plan_against_batter_does_not_query_batter_as_bowler() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Build a bowling plan against David Miller.")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["David Miller"]
    assert response.interpretation.filters["plan_type"] == "bowling_to_batter"
    assert response.interpretation.filters["subject"] == "batter"
    assert response.tables[0].title == "Bowling plan against David Miller"
    assert response.tables[1].title == "Bowling style plan against David Miller"
    assert response.tables[0].rows[0][0] == "Primary option"
    assert response.tables[0].rows[0][1] == "good length, outside off stump"
    assert response.tables[1].rows[0][0] == "right-arm fast"
    table_titles = [table.title for table in response.tables]
    assert "Fetched bowling metrics" not in table_titles
    assert "Phase batting evidence" not in table_titles
    assert "Pace/spin batting evidence" not in table_titles
    assert "not the batter's own bowling record" in response.evidence_notes[0].detail


def test_bowling_plan_against_klaasen_keeps_evidence_out_of_top_level_tables() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Build a bowling plan against Heinrich Klaasen.")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Heinrich Klaasen"]
    assert response.interpretation.filters["plan_type"] == "bowling_to_batter"
    assert response.interpretation.filters["subject"] == "batter"
    assert [table.title for table in response.tables] == [
        "Bowling plan against Heinrich Klaasen",
        "Bowling style plan against Heinrich Klaasen",
    ]
    assert response.tables[1].rows[0][-1] == "Prefer"
    assert "Bowling style plan source" in [query.title for query in response.evidence_queries]


def test_length_breakdown_uses_human_readable_bucket_labels() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which length dismisses Rohit Sharma most often?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["group_by"] == "length"
    assert response.interpretation.filters["metric"] == "wickets_taken"
    assert response.tables[0].title == "Rohit Sharma length breakdown"
    assert response.tables[0].rows[0][1] == "good length"
    assert response.tables[0].rows[1][1] == "back of a length"
    assert "GOOD_LENGTH" not in response.summaries[0].body
    assert "good length leads" in response.summaries[0].body


def test_bowling_type_question_groups_by_style_not_individual_bowler() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Against which bowling type does Travis Head score fastest?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["group_by"] == "bowling_style"
    assert response.interpretation.filters["metric"] == "batting_strike_rate"
    assert response.tables[0].title == "Bowling style matchup against Travis Head"
    assert response.tables[0].columns[1] == "Bowling Style"
    assert response.tables[0].rows[0][1] == "slow left-arm orthodox"
    assert "This is grouped by bowling style, not by individual bowler." in response.summaries[0].body
    assert "Moeen Ali" not in response.summaries[0].body
    assert "ORDER BY :metric_expression_for_batting_strike_rate DESC" in response.evidence_queries[0].sql


def test_bowling_type_question_executor_overrides_missing_group_by() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())
    route = QueryRoute(
        query_class=QueryClass.venue_context_leaderboard,
        entities=("Heinrich Klaasen",),
        filters={"subject": "bowler", "skill": "bowling", "metric": "batting_strike_rate", "rank_intent": "best"},
    )

    response = service.answer_route("Against which bowling type does Heinrich Klaasen score fastest?", route)

    assert response.status.value == "supported"
    assert response.interpretation.filters["group_by"] == "bowling_style"
    assert response.interpretation.filters["subject"] == "batter"
    assert response.tables[0].title == "Bowling style matchup against Heinrich Klaasen"
    assert response.tables[0].columns[1] == "Bowling Style"
    assert "This is grouped by bowling style, not by individual bowler." in response.summaries[0].body
    assert "Moeen Ali" not in response.summaries[0].body
    assert "ORDER BY :metric_expression_for_batting_strike_rate DESC" in response.evidence_queries[0].sql


def test_bowling_type_question_normalizes_wrong_query_class_before_execution() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())
    route = QueryRoute(
        query_class=QueryClass.role_comparison,
        entities=("Heinrich Klaasen",),
        filters={"subject": "bowler", "skill": "bowling", "metric": "batting_strike_rate", "rank_intent": "best"},
    )

    response = service.answer_route("Against which bowling type does Heinrich Klaasen score fastest?", route)

    assert response.status.value == "supported"
    assert response.interpretation.query_class == "venue_context_leaderboard"
    assert response.interpretation.filters["group_by"] == "bowling_style"
    assert response.interpretation.filters["subject"] == "batter"
    assert response.tables[0].title == "Bowling style matchup against Heinrich Klaasen"
    assert "individual bowler" in response.summaries[0].body


def test_batter_after_twenty_balls_uses_strike_rate_improvement_metric() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which batter improves their strike rate the most after facing 20 balls?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["metric"] == "strike_rate_improvement_after_20"
    assert response.interpretation.filters["split_after_balls"] == 20
    assert response.tables[0].title == "Batter strike-rate change after 20 balls"
    assert "SR Change" in response.tables[0].columns
    assert "Metric" not in response.tables[0].columns
    assert response.tables[0].rows[0][1] == "Michael Bracewell"
    assert response.tables[0].rows[0][-1] == 73.9
    assert "improves most after reaching 20 balls" in response.summaries[0].body
    assert "SR Change = strike rate after ball 20 minus strike rate from balls 1-20" in response.evidence_notes[0].detail


def test_batter_milestone_question_uses_vulnerability_lift() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which batter is most vulnerable immediately after reaching a milestone?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["metric"] == "milestone_vulnerability_lift"
    assert response.interpretation.filters["context_tag"] == "after_milestone"
    assert response.interpretation.filters["post_milestone_balls"] == 12
    assert response.tables[0].title == "Batter vulnerability after milestones"
    assert "Vulnerability Lift" in response.tables[0].columns
    assert "Metric" not in response.tables[0].columns
    assert response.tables[0].rows[0][1] == "Ryan Burl"
    assert response.tables[0].rows[0][9] == 17.98
    assert "post-milestone" in response.summaries[0].body
    assert "Vulnerability Lift = post-milestone dismissal % minus normal set-batter dismissal %" in response.evidence_notes[0].detail


def test_batter_false_shot_against_spin_ranks_highest_false_shot_percentage() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which batter has the highest false-shot percentage against spin?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["metric"] == "false_shot_percentage"
    assert response.interpretation.filters["bowling_kind"] == "spin bowler"
    assert response.interpretation.filters["rank_intent"] == "best"
    assert response.tables[0].title == "Analyst batting leaderboard"
    assert response.tables[0].rows[0][13] == 18.92
    assert response.tables[0].rows[0][-1] == 18.92
    assert "ORDER BY :metric_expression_for_false_shot_percentage DESC" in response.evidence_queries[0].sql


def test_hardest_to_bowl_dot_balls_uses_lowest_dot_percentage_language() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which batter is hardest to bowl dot balls to?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["metric"] == "dot_percentage"
    assert response.interpretation.filters["rank_intent"] == "best"
    assert "has the lowest dot-ball percentage" in response.summaries[0].body
    assert "leads in the local ODI batter leaderboard for dot-ball percentage" not in response.summaries[0].body
    assert "Dot-Ball Percentage (Rank)" in response.tables[0].columns
    assert "ORDER BY :metric_expression_for_dot_percentage ASC" in response.evidence_queries[0].sql


def test_named_batter_dot_percentage_returns_single_player_metric() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("what is dot ball percentage of Virat Kohli?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["metric"] == "dot_percentage"
    assert response.interpretation.filters["subject"] == "batter"
    assert response.tables[0].title == "Single player metric"
    assert response.tables[0].rows == [["Virat Kohli", "Dot Ball Percentage", "36.00%", "all phases"]]
    assert "bowler dot balls" not in response.summaries[0].body.lower()


def test_mid_wicket_area_question_uses_batting_field_zone_leaderboard() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("which batter score must runs in mid-wicket area?")

    assert response.status.value == "supported"
    assert response.interpretation.query_class == "venue_context_leaderboard"
    assert response.interpretation.filters["subject"] == "batter"
    assert response.interpretation.filters["metric"] == "runs_scored"
    assert response.interpretation.filters["field_zone"] == "midwicket"
    assert response.tables[0].title == "Batter runs in mid-wicket area"
    assert "Batter" in response.tables[0].columns
    assert "Bowler" not in response.tables[0].columns
    assert response.tables[0].rows[0][1] == "Kumar Sangakkara"
    assert response.tables[0].rows[0][-1] == 1248
    assert "mid-wicket" in response.summaries[0].body
    assert "wagonZone" in response.evidence_notes[0].detail


def test_role_comparison_can_compare_batting_positions() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Compare Virat Kohli at number 3 vs opening in ODIs")

    assert response.status.value == "supported"
    assert response.interpretation.filters["position_groups"] == [
        {"label": "No. 3", "positions": [3]},
        {"label": "Opening", "positions": [1, 2]},
    ]
    assert response.tables[0].title == "Derived batting-position metrics"
    assert response.tables[0].rows[0][0] == "No. 3"
    assert response.tables[0].rows[1][0] == "Opening"
    assert "derived batting-order comparison" in response.summaries[0].body
    assert any(note.title == "Verification basis" for note in response.evidence_notes)


def test_player_comparison_includes_auditable_phase_and_bowling_type_splits() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Compare Virat Kohli and Steven Smith in ODIs")

    assert response.status.value == "supported"
    assert [table.title for table in response.tables] == [
        "Primary batting metrics",
        "Fetched phase split rows",
        "Fetched pace/spin split rows",
    ]
    assert [query.title for query in response.evidence_queries] == [
        "All-phase comparison source",
        "Phase split source",
        "Pace and spin split source",
    ]
    assert "Dot %" in response.tables[0].columns
    assert "COUNT(DISTINCT" in response.evidence_queries[1].sql


def test_bowling_economy_question_uses_bowler_metrics_only() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("What is Jasprit Bumrah's economy rate in death overs?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["skill"] == "bowling"
    assert response.interpretation.filters["metric"] == "economy_rate"
    assert response.tables[0].title == "Fetched bowling metrics"
    assert "Economy" in response.tables[0].columns
    assert "Strike Rate" not in response.tables[0].columns
    assert "WHERE bowl IN (:players)" in response.evidence_queries[0].sql
    assert "TRY_CAST(over AS DOUBLE) > 40.0" in response.evidence_queries[0].sql


def test_bowling_wickets_question_leads_with_wickets_only() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("wickets taken by Pat Cummins in powerplay?")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Pat Cummins"]
    assert response.interpretation.filters["phase"] == "powerplay"
    assert response.interpretation.filters["metric"] == "wickets_taken"
    assert response.summaries[0].body == "In powerplay, Pat Cummins has 70 wickets."
    assert "economy" not in response.summaries[0].body.lower()
    assert "bowler-credit" not in response.summaries[0].body.lower()
    assert response.tables[0].title == "Fetched bowling metrics"


def test_best_bowling_figures_uses_innings_figures() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("what are Tim Southee best bowling figures?")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Tim Southee"]
    assert response.interpretation.filters["metric"] == "best_bowling_figures"
    assert response.summaries[0].body == "Tim Southee's best ODI bowling figures are 7/33 against England, 2015-02-20."
    assert response.tables[0].title == "Best bowling figures"
    assert response.tables[0].rows[0][1] == "7/33"
    assert "ORDER BY wickets DESC, runs_conceded ASC" in response.evidence_queries[0].sql


def test_opponent_wise_player_performance_infers_bowling_role() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("opponent wise performance of james anderson, sort them from most successful to least successful")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["James Anderson"]
    assert response.interpretation.filters["group_by"] == "opponent"
    assert response.interpretation.filters["skill"] == "bowling"
    assert response.interpretation.filters["metric"] == "wickets_taken"
    assert response.tables[0].title == "Opponent-wise bowling performance"
    assert response.tables[0].rows[0][1] == "Australia"
    assert response.tables[0].rows[0][7] == 50
    assert "Australia" in response.summaries[0].body
    assert "GROUP BY team_bat" in response.evidence_queries[0].sql
    assert "ORDER BY wickets DESC" in response.evidence_queries[0].sql


def test_venue_wise_player_performance_infers_batting_role() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("venue wise performance of kane williamson")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Kane Williamson"]
    assert response.interpretation.filters["group_by"] == "venue"
    assert response.interpretation.filters["skill"] == "batting"
    assert response.interpretation.filters["metric"] == "runs_scored"
    assert response.tables[0].title == "Venue-wise batting performance"
    assert response.tables[0].rows[0][1] == "Seddon Park, Hamilton"
    assert response.tables[0].rows[0][4] == 640
    assert "Seddon Park, Hamilton" in response.summaries[0].body
    assert "GROUP BY ground" in response.evidence_queries[0].sql
    assert "ORDER BY runs DESC" in response.evidence_queries[0].sql


def test_bowling_year_trend_uses_bowler_rows() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Break Jasprit Bumrah down year by year as a bowler in death overs")

    assert response.status.value == "supported"
    assert response.interpretation.filters["skill"] == "bowling"
    assert response.interpretation.filters["phase"] == "death"
    assert response.tables[0].title == "Fetched bowling year trend"
    assert response.tables[0].rows[0][0] == 2022
    assert "WHERE bowl = :player" in response.evidence_queries[0].sql
    assert "TRY_CAST(over AS DOUBLE) > 40.0" in response.evidence_queries[0].sql


def test_bowling_year_trend_can_compare_two_bowlers() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Compare Jasprit Bumrah trend against Mitchell Starc as a bowler in death overs")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Jasprit Bumrah", "Mitchell Starc"]
    assert len(response.tables) == 1
    assert response.tables[0].title == "Aggregate bowling trend comparison"
    assert response.tables[0].columns == ["Metric", "Jasprit Bumrah", "Mitchell Starc"]
    assert response.tables[0].rows[1] == ["Matches", 18, 7]
    assert response.tables[0].rows[2] == ["Bowling Innings", 18, 7]
    assert response.tables[0].rows[3] == ["Legal Balls", 300, 108]
    assert response.evidence_queries[0].table.title == "Year-by-year bowling trend comparison"
    assert response.evidence_queries[0].table.columns == [
        "Year",
        "Jasprit Bumrah Matches",
        "Jasprit Bumrah Innings",
        "Jasprit Bumrah Legal Balls",
        "Jasprit Bumrah Wickets",
        "Jasprit Bumrah Economy",
        "Jasprit Bumrah Dot %",
        "Jasprit Bumrah Boundary %",
        "Mitchell Starc Matches",
        "Mitchell Starc Innings",
        "Mitchell Starc Legal Balls",
        "Mitchell Starc Wickets",
        "Mitchell Starc Economy",
        "Mitchell Starc Dot %",
        "Mitchell Starc Boundary %",
    ]
    assert response.evidence_queries[0].table.rows[0] == [2022, 8, 8, 120, 9, 5.2, 48.0, 7.5, 7, 7, 108, 7, 6.5, 38.89, 12.04]
    assert response.evidence_queries[0].table.rows[1] == [2023, 10, 10, 180, 14, 5.6, 45.0, 8.0, None, None, None, None, None, None, None]
    assert "COUNT(DISTINCT p_match) AS matches" in response.evidence_queries[0].sql
    assert "bowl AS player" in response.evidence_queries[0].sql
    assert "WHERE bowl IN (:players)" in response.evidence_queries[0].sql
    assert "GROUP BY bowl, year" in response.evidence_queries[0].sql
    assert "TRY_CAST(over AS DOUBLE) > 40.0" in response.evidence_queries[0].sql


def test_explicit_bowling_year_by_year_comparison_shows_year_table() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Compare Jasprit Bumrah and Mitchell Starc year by year as bowlers in death overs")

    assert response.status.value == "supported"
    assert [table.title for table in response.tables] == [
        "Aggregate bowling trend comparison",
        "Year-by-year bowling trend comparison",
    ]


def test_global_death_over_economy_leaderboard_since_year() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which bowler has the best death-over economy since 2022?")

    assert response.status.value == "supported"
    assert response.interpretation.query_class == "venue_context_leaderboard"
    assert response.interpretation.filters["phase"] == "death"
    assert response.interpretation.filters["year_mode"] == "after"
    assert response.interpretation.filters["rank_intent"] == "best"
    assert response.tables[0].title == "Bowling economy leaderboard"
    assert response.tables[0].rows[0][1] == "Mohammad Nabi"
    assert response.tables[0].rows[0][8] == 3.68
    assert "best death overs economy" in response.summaries[0].body
    assert "Since 2022" in response.summaries[0].body
    assert "WHERE NULLIF(TRIM(CAST(bowl AS VARCHAR)), '') IS NOT NULL" in response.evidence_queries[0].sql
    assert "TRY_CAST(over AS DOUBLE) > 40.0" in response.evidence_queries[0].sql
    assert "TRY_CAST(year AS INTEGER) >= :year" in response.evidence_queries[0].sql
    assert "ORDER BY runs_conceded / NULLIF(legal_balls / 6.0, 0) ASC" in response.evidence_queries[0].sql


def test_global_powerplay_worst_economy_leaderboard_descending() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which bowler has the worst economy in powerplay?")

    assert response.status.value == "supported"
    assert response.interpretation.query_class == "venue_context_leaderboard"
    assert response.interpretation.filters["phase"] == "powerplay"
    assert response.interpretation.filters["skill"] == "bowling"
    assert response.interpretation.filters["metric"] == "economy_rate"
    assert response.interpretation.filters["rank_intent"] == "worst"
    assert response.tables[0].title == "Bowling economy leaderboard"
    assert response.tables[0].rows[0][1] == "Gerald Coetzee"
    assert response.tables[0].rows[0][8] == 9.8
    assert "worst powerplay economy" in response.summaries[0].body
    assert "TRY_CAST(over AS DOUBLE) <= 10.0" in response.evidence_queries[0].sql
    assert "ORDER BY runs_conceded / NULLIF(legal_balls / 6.0, 0) DESC" in response.evidence_queries[0].sql


def test_global_powerplay_highest_wickets_leaderboard_descending() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which bowler has highest number of wickets in powerplay?")

    assert response.status.value == "supported"
    assert response.interpretation.query_class == "venue_context_leaderboard"
    assert response.interpretation.filters["phase"] == "powerplay"
    assert response.interpretation.filters["skill"] == "bowling"
    assert response.interpretation.filters["metric"] == "wickets_taken"
    assert response.interpretation.filters["rank_intent"] == "best"
    assert response.tables[0].title == "Bowling wickets leaderboard"
    assert response.tables[0].rows[0][1] == "Lasith Malinga"
    assert response.tables[0].rows[0][7] == 102
    assert "most powerplay wickets" in response.summaries[0].body
    assert "TRY_CAST(over AS DOUBLE) <= 10.0" in response.evidence_queries[0].sql
    assert "ORDER BY wickets DESC" in response.evidence_queries[0].sql


def test_venue_wickets_question_uses_ground_filter_before_global_leaderboard() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which player has taken the most wickets at lord's cricket ground?")

    assert response.status.value == "supported"
    assert response.interpretation.query_class == "venue_context_leaderboard"
    assert response.interpretation.filters["venue_name"] == "Lord's, London"
    assert response.interpretation.filters["metric"] == "wickets_taken"
    assert response.tables[0].title == "Venue bowling leaderboard"
    assert response.tables[0].columns[1] == "Legal Balls"
    assert response.tables[0].rows[0][0] == "Stuart Broad"
    assert response.tables[0].rows[0][3] == 15
    assert "Lord's, London" in response.summaries[0].body
    assert response.evidence_queries[0].title == "Venue bowling leaderboard source"
    assert "WHERE ground = :venue_name" in response.evidence_queries[0].sql
    assert "dismissal is credited to bowler" in response.evidence_queries[0].sql


def test_venue_wickets_question_can_exclude_english_cricketers() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Who has most wickets at lord's other than English Cricketers?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["venue_name"] == "Lord's, London"
    assert response.interpretation.filters["excluded_teams"] == ["England"]
    assert response.tables[0].rows[0][0] == "Glenn McGrath"
    assert response.tables[0].rows[0][3] == 14
    assert "excluding England" in response.summaries[0].body
    assert "team_bowl NOT IN (:excluded_teams)" in response.evidence_queries[0].sql
    assert response.evidence_queries[0].parameters == ["Lord's, London", "England", 24, 10]


def test_world_cup_wickets_leaderboard_uses_competition_filter() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Who took most wickets in cricket world cup 2011?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["competition"] == "ICC Cricket World Cup"
    assert response.interpretation.filters["years"] == [2011]
    assert response.interpretation.filters["metric"] == "wickets_taken"
    assert response.tables[0].title == "Bowling wickets leaderboard"
    assert response.tables[0].rows[0][1] == "Shahid Afridi"
    assert response.tables[0].rows[0][7] == 21
    assert response.tables[0].rows[1][1] == "Zaheer Khan"
    assert response.tables[0].rows[1][7] == 21
    assert "ICC Cricket World Cup 2011" in response.summaries[0].body
    assert "Shahid Afridi and Zaheer Khan share" in response.summaries[0].body
    assert "competition = :competition" in response.evidence_queries[0].sql
    assert "runs_conceded / NULLIF(wickets, 0) ASC" in response.evidence_queries[0].sql


def test_world_cup_catches_explains_missing_catcher_identity() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Who took most catches in 2023 world cup?")

    assert response.status.value == "insufficient_evidence"
    assert response.interpretation.filters["competition"] == "World Cup 2023"
    assert response.interpretation.filters["subject"] == "fielder"
    assert response.interpretation.filters["metric"] == "catches_taken"
    assert response.tables[0].title == "Fielding catches dataset check"
    assert response.tables[0].rows[0][0] == "In World Cup 2023"
    assert response.tables[0].rows[0][1] == 462
    assert response.tables[0].rows[0][4] == "No"
    assert "does not include a catcher/fielder column" in response.insufficiencies[0].detail
    assert "`p_out` field is the dismissed batter id" in response.insufficiencies[0].detail


def test_world_cup_final_player_of_match_uses_external_award_fact() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Who was Player of the Match in 2011 world cup final?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["external_fact"] == "player_of_match"
    assert response.interpretation.filters["stage"] == "final"
    assert response.summaries[0].body == "MS Dhoni was Player of the Match in the 2011 Cricket World Cup final."
    assert response.tables[0].title == "External match award"
    assert response.tables[0].rows[0][4] == "MS Dhoni"
    assert response.citations[0].source_type.value == "external_web"
    assert "does not include Player-of-the-Match awards" in response.evidence_notes[0].detail


def test_single_match_balls_bowled_answers_literal_metric_and_notes_batting_ambiguity() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())
    route = QueryRoute(
        query_class=QueryClass.role_comparison,
        entities=("MS Dhoni",),
        filters={
            "query_type": "single_metric",
            "answer_shape": "single_number",
            "metric": "balls_bowled",
            "subject": "bowler",
            "skill": "bowling",
            "competition": "ICC Cricket World Cup",
            "years": [2011],
            "stage": "final",
        },
        intent_plan=CricketIntentPlan(
            query_type=QueryType.single_metric,
            answer_shape=AnswerShape.single_number,
            metric=CricketMetric.balls_bowled,
            subjects=[IntentSubject(player="MS Dhoni", role=SubjectRole.bowler)],
            context=MatchContext(
                scope=ContextScope.single_match,
                competition="ICC Cricket World Cup",
                year=2011,
                years=[2011],
                stage="final",
                teams=["India", "Sri Lanka"],
            ),
        ),
    )

    response = service.answer_route("How many balls bowled by MS Dhoni in 2011 world cup final?", route)

    assert response.status.value == "supported"
    assert response.interpretation.filters["query_type"] == "single_metric"
    assert response.interpretation.filters["answer_shape"] == "single_number"
    assert response.interpretation.filters["metric"] == "balls_bowled"
    assert response.tables[0].title == "Single-match player metric"
    assert response.tables[0].rows[0][2] == "0"
    assert "bowled 0 legal balls" in response.summaries[0].body
    assert "If you meant balls faced while batting, he faced 79 balls." in response.summaries[0].body
    assert "broader summaries are not used" in response.evidence_notes[0].detail


def test_short_ball_target_batter_leaderboard_includes_average_context() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which batter should be targeted with short-ball tactics?")

    assert response.status.value == "supported"
    assert response.interpretation.filters["subject"] == "batter"
    assert response.interpretation.filters["length"] == "SHORT"
    assert response.interpretation.filters["metric"] == "batting_strike_rate"
    assert response.interpretation.filters["rank_intent"] == "worst"
    assert response.tables[0].title == "Analyst batting leaderboard"
    assert "Average" in response.tables[0].columns
    assert "Balls/Dismissal" in response.tables[0].columns
    assert response.tables[0].rows[0][7] == 7.0
    assert response.tables[0].rows[0][8] == 12.33


def test_spinner_matchup_against_batter_includes_spin_type_breakdown() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    response = service.answer_question("Which spinner should bowl to Maxwell?")

    assert response.status.value == "supported"
    assert response.interpretation.entities == ["Glenn Maxwell"]
    assert response.interpretation.filters["subject"] == "bowler"
    assert response.interpretation.filters["bowling_kind"] == "spin bowler"
    assert response.tables[0].title == "Analyst matchup bowler leaderboard"
    assert "Bowling Style" in response.tables[0].columns
    assert response.tables[0].rows[0][2] == "off spin"
    assert response.tables[1].title == "Spin type matchup against Glenn Maxwell"
    assert response.tables[1].rows[0][1] == "off spin"
    assert "GROUP BY bowl_style" in response.evidence_queries[1].sql
