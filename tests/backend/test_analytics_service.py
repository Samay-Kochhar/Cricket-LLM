from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.metric_catalog import MetricCatalog


class StubRepository:
    def list_player_names(self) -> list[str]:
        return ["Virat Kohli", "Steven Smith", "Hardik Pandya"]

    def list_venues(self) -> list[str]:
        return ["M Chinnaswamy Stadium"]

    def get_player_batting_summary(self, player_name: str, phase: str | None = None) -> dict[str, object] | None:
        return {
            "player_name": player_name,
            "balls_faced": 100,
            "runs_scored": 120,
            "dismissals": 4,
            "strike_rate": 120.0,
            "boundary_percentage": 14.0,
            "control_percentage": 78.0,
        }

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
