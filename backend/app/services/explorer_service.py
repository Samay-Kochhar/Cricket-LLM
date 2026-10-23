from __future__ import annotations

from typing import Any

from backend.app.domain.venues import resolve_venue
from backend.app.domain.venue_leaderboard import METRICS, PHASES, SAMPLE_UNITS, VenueBowlingOptions

from backend.app.services.player_resolution import resolve_player_name


def build_venue_profile(repository: object, venue_name: str, **filters: Any) -> dict[str, Any]:
    """Build the venue explorer payload shared by FastAPI and Streamlit."""
    options = VenueBowlingOptions(**filters)
    venue = resolve_venue(venue_name)
    return {
        "venue_id": venue.id,
        "venue_name": venue.display_name,
        "bowling_leaderboard": repository.get_venue_bowling_leaderboard(venue_name, **options.as_dict()),
        "filters": options.as_dict(),
        "ranking": options.ranking,
        "metric_options": [{"metric": key, "label": value[0], "field": value[1], "direction": value[2]} for key, value in METRICS.items()],
        "phase_options": PHASES,
        "sample_units": SAMPLE_UNITS,
        "venue_options": repository.list_venues(),
        "sample_policy": "Minimum applies to the filtered sample before top N. Unavailable rates are excluded from that metric ranking. Dots: legal balls with no bowler-charged runs / legal balls. Boundaries: legal balls hit for 4 or 6 / legal balls. Economy uses 6 legal balls per over.",
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
