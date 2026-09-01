from __future__ import annotations

import time

import backend.app.bootstrap as chat_bootstrap
import duckdb
import streamlit_app
from streamlit.testing.v1 import AppTest


def test_player_explorer_initializes_and_warm_navigates_without_chat_services(
    monkeypatch,
    tmp_path,
) -> None:
    def unexpected_chat_initialization() -> None:
        raise AssertionError("Player Explorer must not initialize chat services")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(chat_bootstrap, "get_services", unexpected_chat_initialization)
    database_path = tmp_path / "odi_analytics.duckdb"
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("CREATE SCHEMA analytics")
        connection.execute("CREATE TABLE analytics.player_lookup(player_name VARCHAR)")
        connection.execute(
            "INSERT INTO analytics.player_lookup VALUES ('Rohit Sharma'), ('Virat Kohli')"
        )
    monkeypatch.setattr(streamlit_app, "DB_PATH", database_path)
    streamlit_app.initialize_player_explorer_services.clear()

    services = streamlit_app.initialize_player_explorer_services()
    warm_started = time.perf_counter()
    warm_services = streamlit_app.initialize_player_explorer_services()
    warm_seconds = time.perf_counter() - warm_started

    assert set(services) == {"repository", "player_names"}
    assert services["player_names"] == ("Rohit Sharma", "Virat Kohli")
    assert warm_services == services
    assert warm_seconds < 0.1
    streamlit_app.initialize_player_explorer_services.clear()


def test_player_explorer_selector_uses_cached_names_without_changing_search_options() -> None:
    app = AppTest.from_string(
        """
from streamlit_player_explorer import render_player_explorer

class Repository:
    def list_player_names(self):
        raise AssertionError("Player names should come from the cached Explorer bundle")

render_player_explorer({
    "repository": Repository(),
    "player_names": ("Rohit Sharma", "Virat Kohli"),
})
"""
    ).run()

    assert not app.exception
    assert app.selectbox[0].label == "Player"
    assert app.selectbox[0].options == ["Rohit Sharma", "Virat Kohli"]
