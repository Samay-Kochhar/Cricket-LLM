from __future__ import annotations

from streamlit_matchup_explorer import build_matchup_pitch_html, load_matchup_page
from streamlit.testing.v1 import AppTest


def test_load_matchup_page_uses_structured_filters_and_builds_practical_metrics() -> None:
    captured: dict[str, object] = {}

    def matchup_handler(**filters: object) -> dict[str, object]:
        captured.update(filters)
        return {
            "matchup": {
                "status": "supported",
                "summaries": [{"body": "Steven Smith scored 103 runs from 121 balls. The recorded ODI sample contains 121 balls."}],
                "tables": [
                    {
                        "columns": [
                            "Batter",
                            "Bowler",
                            "Balls",
                            "Runs",
                            "Dismissals",
                            "Batting Strike Rate",
                            "Batter Dot Ball Percentage",
                            "Boundary Percentage",
                            "False Shot Percentage",
                        ],
                        "rows": [["Steven Smith", "Jasprit Bumrah", 121, 103, 2, 85.12, 48.76, 8.26, 22.31]],
                    }
                ],
                "visuals": {
                    "pitch_map": {
                        "handedness": "RHB",
                        "coverage": {"total_balls": 121, "covered_balls": 121, "coverage_percentage": 100},
                        "cells": [{"line": "ON_THE_STUMPS", "length": "GOOD_LENGTH", "balls": 121}],
                    }
                },
            },
            "baseline": {
                "status": "supported",
                "summaries": [],
                "tables": [{"columns": ["Batter", "Batting Strike Rate"], "rows": [["Steven Smith", 93.51]]}],
                "visuals": None,
            },
        }

    page = load_matchup_page(
        {"matchup_handler": matchup_handler},
        batter="Steven Smith",
        bowler="Jasprit Bumrah",
        phase="death",
        year=2023,
        venue="Sydney Cricket Ground",
    )

    assert captured == {
        "batter": "Steven Smith",
        "bowler": "Jasprit Bumrah",
        "phase": "death",
        "year": 2023,
        "venue": "Sydney Cricket Ground",
    }
    assert page["title"] == "Steven Smith vs Jasprit Bumrah"
    assert page["summary"] == "Steven Smith scored 103 runs from 121 balls."
    assert page["metrics"] == {
        "Runs": 103,
        "Balls": 121,
        "Dismissals": 2,
        "Batting Avg": 51.5,
        "Batting SR": 85.12,
        "Dot Ball %": 48.76,
        "Boundary %": 8.26,
        "False Shot %": 22.31,
    }
    assert page["baseline_strike_rate"] == 93.51
    assert page["pitch"]["handedness"] == "RHB"


def test_matchup_pitch_html_preserves_the_approved_pitch_structure() -> None:
    html = build_matchup_pitch_html(
        {
            "handedness": "RHB",
            "cells": [
                {
                    "line": "ON_THE_STUMPS",
                    "length": "GOOD_LENGTH",
                    "balls": 30,
                    "runs": 20,
                    "strike_rate": 66.67,
                    "dismissals": 1,
                    "fours": 2,
                    "sixes": 0,
                    "wicket_balls": 1,
                },
                {
                    "line": "WIDE_DOWN_LEG",
                    "length": "GOOD_LENGTH",
                    "balls": 1,
                    "runs": 0,
                    "strike_rate": 0,
                    "dismissals": 1,
                },
            ],
        },
        pitch_view="Avg",
    )

    assert "--pitch-line-columns:0.5fr 0.5fr 0.6fr 1fr" in html
    assert html.index("Wide outside off") < html.index("Outside off") < html.index("On the stumps")
    assert html.index("On the stumps") < html.index("Down leg")
    assert html.count('class="atlas-pitch-cell empty"') == 23
    assert html.count('class="atlas-pitch-stumps"') == 1
    assert "20.0" in html and "AVG" in html
    assert "No deliveries" in html
    assert "WIDE_DOWN_LEG" not in html
    assert "1-3" not in html
    assert html.index("Full toss") < html.index('class="atlas-pitch-stumps"') < html.index("Yorker")

    left_handed_html = build_matchup_pitch_html({"handedness": "LHB", "cells": []})
    assert "--pitch-line-columns:1fr 0.6fr 0.5fr 0.5fr" in left_handed_html
    assert left_handed_html.index("Down leg") < left_handed_html.index("On the stumps")
    assert left_handed_html.index("On the stumps") < left_handed_html.index("Outside off")
    assert left_handed_html.index("Outside off") < left_handed_html.index("Wide outside off")

    outcome_pitch = {
        "cells": [{
            "line": "ON_THE_STUMPS", "length": "GOOD_LENGTH", "balls": 30,
            "runs": 20, "strike_rate": 66.67, "dismissals": 1,
            "fours": 2, "sixes": 1, "wicket_balls": 1,
        }],
    }
    for view, colour in {
        "W": "239, 83, 80",
        "4s": "242, 143, 59",
        "6s": "255, 209, 102",
    }.items():
        outcome_html = build_matchup_pitch_html(outcome_pitch, pitch_view=view)
        assert f"rgba({colour}, 0.700)" in outcome_html
        assert "66.7</strong><span>SR" in outcome_html
        assert "4 2" in outcome_html and "6 1" in outcome_html and "W 1" in outcome_html


def test_load_matchup_page_supports_a_cached_service_bundle_from_before_matchups() -> None:
    class CachedSemanticService:
        def answer_matchup_page(self, **filters: object) -> dict[str, object]:
            return {
                "matchup": {
                    "status": "insufficient_evidence",
                    "summaries": [],
                    "tables": [],
                    "visuals": None,
                },
                "baseline": {
                    "status": "supported",
                    "summaries": [],
                    "tables": [],
                    "visuals": None,
                },
            }

    page = load_matchup_page(
        {"semantic_service": CachedSemanticService()},
        batter="Shikhar Dhawan",
        bowler="Mitchell Starc",
    )

    assert page["supported"] is False
    assert page["title"] == "Shikhar Dhawan vs Mitchell Starc"


def test_matchup_explorer_offers_searchable_players_and_renders_answer_metrics() -> None:
    app = AppTest.from_string(
        """
from streamlit_matchup_explorer import render_matchup_explorer

class Repository:
    def list_player_names(self):
        return ["Steven Smith", "Jasprit Bumrah"]

    def list_venues(self):
        return ["Sydney Cricket Ground"]

def matchup_handler(**filters):
    return {
        "matchup": {
            "status": "supported",
            "summaries": [{"body": "Steven Smith scored 103 runs from 121 balls."}],
            "tables": [{
                "columns": ["Batter", "Bowler", "Balls", "Runs", "Dismissals", "Batting Strike Rate"],
                "rows": [["Steven Smith", "Jasprit Bumrah", 121, 103, 2, 85.12]],
            }],
            "visuals": {
                "pitch_map": {
                    "handedness": "RHB",
                    "cells": [{
                        "line": "ON_THE_STUMPS", "length": "GOOD_LENGTH", "balls": 121,
                        "runs": 103, "strike_rate": 85.12, "dismissals": 2,
                        "fours": 8, "sixes": 1, "wicket_balls": 2,
                    }],
                },
            },
        },
        "baseline": {
            "status": "supported",
            "summaries": [],
            "tables": [{"columns": ["Batter", "Batting Strike Rate"], "rows": [["Steven Smith", 93.51]]}],
            "visuals": None,
        },
    }

render_matchup_explorer({"repository": Repository(), "matchup_handler": matchup_handler})
"""
    ).run()

    assert [selectbox.label for selectbox in app.selectbox[:2]] == ["Batter", "Bowler"]
    assert app.button[0].label == "Show matchup"
    assert app.button[0].disabled is True
    app.selectbox[0].select("Steven Smith").run()
    app.selectbox[1].select("Jasprit Bumrah").run()
    assert not app.metric
    assert app.button[0].disabled is False
    app.button[0].click().run()

    assert not app.exception
    assert any(markdown.value == "## Steven Smith vs Jasprit Bumrah" for markdown in app.markdown)
    assert [(metric.label, metric.value) for metric in app.metric[:5]] == [
        ("Runs", "103"),
        ("Balls", "121"),
        ("Dismissals", "2"),
        ("Batting Avg", "51.50"),
        ("Batting SR", "85.12"),
    ]
    rendered_pitch = app.get("html")
    assert len(rendered_pitch) == 1
    assert app.segmented_control[0].options == ["All", "SR", "Avg", "W", "4s", "6s"]
    assert any(
        "Compared with the batter's normal ODI rate" in markdown.value
        and "85.12 vs 93.51" in markdown.value
        for markdown in app.markdown
    )


def test_matchup_explorer_keeps_search_controls_available_after_query_error() -> None:
    app = AppTest.from_string(
        """
from streamlit_matchup_explorer import render_matchup_explorer

class Repository:
    def list_player_names(self):
        return ["Shikhar Dhawan", "Mitchell Starc", "Virat Kohli"]

    def list_venues(self):
        return []

def matchup_handler(**filters):
    raise KeyError("matchup_handler")

render_matchup_explorer({"repository": Repository(), "matchup_handler": matchup_handler})
"""
    ).run()

    app.selectbox[0].select("Shikhar Dhawan").run()
    app.selectbox[1].select("Mitchell Starc").run()
    app.button[0].click().run()

    assert not app.exception
    assert [selectbox.label for selectbox in app.selectbox[:2]] == ["Batter", "Bowler"]
    assert app.button[0].label == "Show matchup"
    assert any("could not be loaded" in error.value for error in app.error)

    app.selectbox[0].select("Virat Kohli").run()
    assert not app.error
    assert app.button[0].disabled is False
