from __future__ import annotations

from typing import Any

from backend.app.services.player_resolution import resolve_player_name


def build_venue_profile(repository: object, venue_name: str) -> dict[str, Any]:
    """Build the venue explorer payload shared by FastAPI and Streamlit."""
    return {
        "venue_name": venue_name,
        "bowling_leaderboard": repository.get_venue_bowling_leaderboard(venue_name),
    }


def build_player_comparison(repository: object, players: list[str]) -> dict[str, Any]:
    """Build the two-player comparison payload shared by FastAPI and Streamlit."""
    player_names = repository.list_player_names()
    summaries: list[dict[str, Any]] = []
    for name in players[:2]:
        resolved = resolve_player_name(name, player_names)
        summary = repository.get_player_batting_summary(resolved.canonical_name or name)
        if summary:
            summaries.append(summary)
    return {"players": summaries}
