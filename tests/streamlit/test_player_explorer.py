from __future__ import annotations

from streamlit_player_explorer import (
    build_phase_figure,
    build_pitch_heatmap,
    build_shot_figure,
    build_wagon_wheel,
    build_year_trend_figure,
    load_player_section,
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
    assert phase.layout.title.x == 0.01
    assert phase.layout.legend.y < 0
    assert phase.layout.margin.b >= 70


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
    figure = build_pitch_heatmap(pitch, colour_metric="Strike rate")

    meta = figure.layout.meta
    good_length = meta["lengths"].index("Good Length")
    outside_off = meta["lines"].index("Outside Offstump")
    on_stumps = meta["lines"].index("On The Stumps")
    assert meta["colour_values"][good_length][outside_off] == -50.0
    assert meta["colour_values"][good_length][on_stumps] == 50.0
    assert any("Avg 25.0" in annotation.text for annotation in figure.layout.annotations)
    assert any("W 2" in annotation.text for annotation in figure.layout.annotations)
    assert all("· B" not in annotation.text for annotation in figure.layout.annotations)


def test_pitch_heatmap_colours_batting_average_and_greys_small_samples() -> None:
    figure = build_pitch_heatmap(
        {
            "cells": [
                {
                    "line": "OUTSIDE_OFFSTUMP",
                    "length": "GOOD_LENGTH",
                    "balls": 100,
                    "runs": 80,
                    "strike_rate": 80.0,
                    "dismissals": 2,
                },
                {
                    "line": "ON_THE_STUMPS",
                    "length": "GOOD_LENGTH",
                    "balls": 100,
                    "runs": 120,
                    "strike_rate": 120.0,
                    "dismissals": 4,
                },
                {
                    "line": "DOWN_LEG",
                    "length": "GOOD_LENGTH",
                    "balls": 19,
                    "runs": 30,
                    "strike_rate": 157.9,
                    "dismissals": 3,
                },
            ]
        },
        colour_metric="Batting average",
    )

    meta = figure.layout.meta
    good_length = meta["lengths"].index("Good Length")
    outside_off = meta["lines"].index("Outside Offstump")
    on_stumps = meta["lines"].index("On The Stumps")
    down_leg = meta["lines"].index("Down Leg")
    assert round(meta["colour_values"][good_length][outside_off], 2) == 6.67
    assert round(meta["colour_values"][good_length][on_stumps], 2) == -3.33
    assert meta["colour_values"][good_length][down_leg] is None
    assert any("Low sample" in annotation.text for annotation in figure.layout.annotations)
    assert all("· B" not in annotation.text for annotation in figure.layout.annotations)
    assert meta["low_sample_fill"] == "#D8DCDE"
    assert figure.layout.plot_bgcolor == "#24452F"
    assert figure.data[-1].marker.colorbar.title.text == "Avg vs<br>baseline"
    assert "baseline Avg 33.3" in figure.layout.title.text


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

    assert figure.layout.meta["lengths"] == [
        "Full Toss",
        "Yorker",
        "Full",
        "Good Length",
        "Short Of A Good Length",
        "Short",
    ]
    assert figure.layout.xaxis.visible is False
    assert figure.layout.yaxis.visible is False
    cell_annotations = [
        annotation for annotation in figure.layout.annotations if annotation.name == "pitch-cell-value"
    ]
    data_annotations = [annotation for annotation in cell_annotations if "No data" not in annotation.text]
    assert all("Avg n/a" in annotation.text for annotation in data_annotations)
    assert all("—" not in annotation.text for annotation in figure.layout.annotations)
    shape_names = {shape.name for shape in figure.layout.shapes}
    assert {"crease-bowler", "bails-bowler"} <= shape_names
    assert len({name for name in shape_names if name and name.startswith("stump-")}) == 3
    first_cell = figure.data[0]
    assert first_cell.fill == "toself"
    assert (first_cell.x[1] - first_cell.x[0]) < (first_cell.x[2] - first_cell.x[3])


def test_player_overview_does_not_eagerly_load_other_analysis_sections() -> None:
    class RecordingRepository:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get_player_year_trend(self, player: str) -> list[dict[str, object]]:
            self.calls.append("year")
            return [{"year": 2024}]

        def __getattr__(self, name: str) -> object:
            if name.startswith("get_"):
                def unexpected(*args: object, **kwargs: object) -> object:
                    self.calls.append(name)
                    return {}

                return unexpected
            raise AttributeError(name)

    repository = RecordingRepository()

    payload = load_player_section(repository, "Virat Kohli", None, "Overview")

    assert payload == {"trend": [{"year": 2024}]}
    assert repository.calls == ["year"]


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
    assert wagon.layout.dragmode is False
    assert wagon.layout.polar.angularaxis.rotation == 0
    side_labels = {annotation.text: annotation.x for annotation in wagon.layout.annotations}
    assert side_labels["OFF SIDE"] < 0.5
    assert side_labels["LEG SIDE"] > 0.5
    assert list(shots.data[0].x) == [30]
    assert list(shots.data[0].y) == ["Cover Drive"]


def test_wagon_side_labels_follow_left_handed_batter_orientation() -> None:
    wagon = build_wagon_wheel({"handedness": "LHB", "sectors": []})

    side_labels = {annotation.text: annotation.x for annotation in wagon.layout.annotations}
    assert side_labels["LEG SIDE"] < 0.5
    assert side_labels["OFF SIDE"] > 0.5
