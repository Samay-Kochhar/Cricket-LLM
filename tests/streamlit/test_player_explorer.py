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


def test_pitch_heatmap_colours_scoring_relative_to_player_baseline() -> None:
    pitch = {
        "cells": [
            {
                "line": "OUTSIDE_OFFSTUMP",
                "length": "GOOD_LENGTH",
                "balls": 100,
                "runs": 50,
                "strike_rate": 50.0,
                "dismissals": 2,
                "dot_balls": 50,
                "control_percentage": 84.0,
            },
            {
                "line": "ON_THE_STUMPS",
                "length": "GOOD_LENGTH",
                "balls": 100,
                "runs": 150,
                "strike_rate": 150.0,
                "dismissals": 5,
                "dot_balls": 10,
                "control_percentage": 90.0,
            },
        ]
    }
    figure = build_pitch_heatmap(pitch, colour_metric="Scoring rate")

    assert list(figure.data[0].x) == ["Outside Offstump", "On The Stumps"]
    assert figure.data[0].z[0][0] == -50.0
    assert figure.data[0].z[0][1] == 50.0
    assert any(colour == "#F2C94C" for _, colour in figure.data[0].colorscale)
    assert "Avg 25.0" in figure.layout.annotations[0].text
    assert "W 2" in figure.layout.annotations[0].text
    assert "· B" not in figure.layout.annotations[0].text


def test_pitch_heatmap_colours_dismissal_chance_and_greys_small_samples() -> None:
    figure = build_pitch_heatmap(
        {
            "cells": [
                {
                    "line": "OUTSIDE_OFFSTUMP",
                    "length": "GOOD_LENGTH",
                    "balls": 100,
                    "runs": 80,
                    "strike_rate": 80.0,
                    "dismissals": 1,
                },
                {
                    "line": "ON_THE_STUMPS",
                    "length": "GOOD_LENGTH",
                    "balls": 20,
                    "runs": 30,
                    "strike_rate": 150.0,
                    "dismissals": 3,
                },
            ]
        },
        colour_metric="Dismissal chance",
        min_balls=30,
    )

    assert figure.data[0].z[0][0] == 1.0
    assert figure.data[0].z[0][1] is None
    assert "Low sample" in figure.layout.annotations[1].text
    assert "· B" not in figure.layout.annotations[1].text
    assert figure.layout.annotations[1].font.color == "#F8F6F0"
    assert figure.layout.plot_bgcolor == "#69737A"
    assert figure.data[0].colorbar.title.text == "Dismissal<br>chance (%)"


def test_pitch_heatmap_uses_cricket_length_order_without_dash_placeholders() -> None:
    lengths = [
        "FULL_TOSS",
        "YORKER",
        "FULL",
        "GOOD_LENGTH",
        "SHORT_OF_A_GOOD_LENGTH",
        "SHORT",
    ]
    figure = build_pitch_heatmap(
        {
            "cells": [
                {
                    "line": "ON_THE_STUMPS",
                    "length": length,
                    "balls": 40,
                    "runs": 40,
                    "strike_rate": 100.0,
                    "dismissals": 0,
                }
                for length in lengths
            ]
        }
    )

    assert list(figure.data[0].y) == [
        "Full Toss",
        "Yorker",
        "Full",
        "Good Length",
        "Short Of A Good Length",
        "Short",
    ]
    assert figure.layout.yaxis.autorange == "reversed"
    assert figure.layout.xaxis.showgrid is False
    assert figure.layout.yaxis.showgrid is False
    assert all("Avg n/a" in annotation.text for annotation in figure.layout.annotations)
    assert all("—" not in annotation.text for annotation in figure.layout.annotations)


def test_wagon_and_shot_figures_render_cricket_outcomes() -> None:
    wagon = build_wagon_wheel(
        {
            "handedness": "RHB",
            "sectors": [
                {
                    "zone_id": 1,
                    "label": "Deep Midwicket",
                    "balls": 40,
                    "runs": 60,
                    "dismissals": 2,
                    "run_share_percentage": 60.0,
                },
                {
                    "zone_id": 2,
                    "label": "Long On",
                    "balls": 30,
                    "runs": 40,
                    "dismissals": 1,
                    "run_share_percentage": 40.0,
                },
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

    assert wagon.data[0].type == "barpolar"
    assert list(wagon.data[0].theta) == [22.5, 67.5]
    assert "60 runs" in wagon.data[1].text[0]
    assert "60.0%" in wagon.data[1].text[0]
    assert list(shots.data[0].x) == [30]
    assert list(shots.data[0].y) == ["Cover Drive"]
