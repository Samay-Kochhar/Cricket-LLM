from __future__ import annotations

from streamlit.testing.v1 import AppTest

from streamlit_compare_explorer import build_strike_rate_figure, load_comparison
from streamlit_venue_explorer import build_wickets_figure, load_venue_profile


class Repository:
    def list_player_names(self) -> list[str]:
        return ["Virat Kohli", "Steven Smith"]

    def list_venues(self) -> list[str]:
        return ["Melbourne Cricket Ground", "Sydney Cricket Ground"]

    def get_player_batting_summary(self, player_name: str) -> dict[str, object] | None:
        rows = {
            "Virat Kohli": {
                "player_name": "Virat Kohli",
                "runs_scored": 12000,
                "balls_faced": 13000,
                "strike_rate": 92.31,
                "boundary_percentage": 10.4,
                "control_percentage": 88.2,
            },
            "Steven Smith": {
                "player_name": "Steven Smith",
                "runs_scored": 5300,
                "balls_faced": 6200,
                "strike_rate": 85.48,
                "boundary_percentage": 8.8,
                "control_percentage": 90.1,
            },
        }
        return rows.get(player_name)

    def get_venue_bowling_leaderboard(self, venue_name: str) -> list[dict[str, object]]:
        assert venue_name == "Melbourne Cricket Ground"
        return [
            {
                "player_name": "Glenn McGrath",
                "deliveries": 720,
                "runs_conceded": 510,
                "wickets": 25,
                "economy_rate": 4.25,
            }
        ]


def test_comparison_uses_the_same_repository_summary_contract_as_the_api() -> None:
    rows = load_comparison(Repository(), ["Virat Kohli", "Steven Smith"])
    figure = build_strike_rate_figure(rows)

    assert [row["player_name"] for row in rows] == ["Virat Kohli", "Steven Smith"]
    assert list(figure.data[0].x) == [92.31, 85.48]
    assert list(figure.data[0].y) == ["Virat Kohli", "Steven Smith"]


def test_venue_profile_uses_the_same_repository_leaderboard_contract_as_the_api() -> None:
    profile = load_venue_profile(Repository(), "Melbourne Cricket Ground")
    figure = build_wickets_figure(profile["bowling_leaderboard"])

    assert profile["venue_name"] == "Melbourne Cricket Ground"
    assert profile["bowling_leaderboard"][0]["wickets"] == 25
    assert list(figure.data[0].x) == [25]
    assert list(figure.data[0].y) == ["Glenn McGrath"]


def test_compare_explorer_requires_two_players_and_renders_the_approved_columns() -> None:
    app = AppTest.from_string(
        """
from streamlit_compare_explorer import render_compare_explorer
from tests.streamlit.test_compare_venue_explorers import Repository

render_compare_explorer({"repository": Repository(), "player_names": tuple(Repository().list_player_names())})
"""
    ).run()

    assert [selectbox.label for selectbox in app.selectbox] == ["Player one", "Player two"]
    assert app.button[0].label == "Compare players"
    assert app.button[0].disabled is True

    app.selectbox[0].select("Virat Kohli").run()
    app.selectbox[1].select("Steven Smith").run()
    app.button[0].click().run()

    assert not app.exception
    assert any(markdown.value == "## Virat Kohli vs Steven Smith" for markdown in app.markdown)
    assert app.dataframe


def test_venue_explorer_selects_a_venue_and_renders_the_leaderboard() -> None:
    app = AppTest.from_string(
        """
from streamlit_venue_explorer import render_venue_explorer
from tests.streamlit.test_compare_venue_explorers import Repository

render_venue_explorer({"repository": Repository()})
"""
    ).run()

    assert app.selectbox[0].label == "Venue"
    app.selectbox[0].select("Melbourne Cricket Ground").run()
    app.button[0].click().run()

    assert not app.exception
    assert any(markdown.value == "## Melbourne Cricket Ground" for markdown in app.markdown)
    assert app.dataframe
