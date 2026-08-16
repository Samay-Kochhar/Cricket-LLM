from __future__ import annotations

from streamlit_player_explorer import (
    build_phase_figure,
    build_pitch_heatmap,
    build_shot_figure,
    build_wagon_wheel,
    build_year_trend_figure,
)


def test_year_and_phase_figures_preserve_profile_metrics() -> None:
    trend = build_year_trend_figure(
        [{"year": 2023, "runs_scored": 100, "balls_faced": 90, "control_percentage": 88.0}]
    )
    phase = build_phase_figure(
        [{"split": "Powerplay", "strike_rate": 75.0, "control_percentage": 91.0}]
    )

    assert list(trend.data[0].x) == [2023]
    assert list(trend.data[0].y) == [100]
    assert list(phase.data[0].y) == [75.0]
    assert list(phase.data[1].y) == [91.0]


def test_pitch_heatmap_maps_line_length_cells_and_evidence() -> None:
    figure = build_pitch_heatmap(
        {
            "cells": [
                {
                    "line": "OUTSIDE_OFFSTUMP",
                    "length": "GOOD_LENGTH",
                    "balls": 50,
                    "runs": 45,
                    "strike_rate": 90.0,
                    "dismissals": 2,
                    "dot_balls": 20,
                    "control_percentage": 84.0,
                }
            ]
        }
    )

    assert list(figure.data[0].x) == ["Outside Offstump"]
    assert list(figure.data[0].y) == ["Good Length"]
    assert figure.data[0].z[0][0] == 90.0
    assert figure.data[0].customdata[0][0][0] == 50


def test_wagon_and_shot_figures_render_cricket_outcomes() -> None:
    wagon = build_wagon_wheel(
        {
            "handedness": "RHB",
            "points": [
                {"x": 250, "y": 150, "runs": 4, "outcome": "four"},
                {"x": 100, "y": 220, "runs": 1, "outcome": "single"},
            ],
        }
    )
    shots = build_shot_figure(
        {
            "metrics": [
                {
                    "shot": "COVER_DRIVE",
                    "balls": 20,
                    "runs": 30,
                    "run_share_percentage": 15.0,
                    "control_percentage": 90.0,
                    "dismissal_rate": 1.2,
                }
            ]
        }
    )

    assert {trace.name for trace in wagon.data} >= {"Four", "Single", "Batter"}
    assert list(shots.data[0].x) == [30]
    assert list(shots.data[0].y) == ["Cover Drive"]
