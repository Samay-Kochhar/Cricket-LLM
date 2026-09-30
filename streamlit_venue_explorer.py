from __future__ import annotations

import logging
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from backend.app.services.explorer_service import build_venue_profile


LOGGER = logging.getLogger("cricatlas.streamlit.venue")


def load_venue_profile(repository: object, venue_name: str) -> dict[str, Any]:
    """Load the same venue payload exposed by GET /api/venues/{venue_name}."""
    return build_venue_profile(repository, venue_name)


def build_wickets_figure(rows: list[dict[str, Any]]) -> go.Figure:
    leaders = rows[:6]
    figure = go.Figure(
        go.Bar(
            x=[int(row.get("wickets") or 0) for row in leaders],
            y=[str(row.get("player_name") or "") for row in leaders],
            orientation="h",
            marker_color="#7CE2B4",
            hovertemplate="%{y}: %{x} wickets<extra></extra>",
        )
    )
    figure.update_layout(
        title="Wickets at venue",
        height=max(320, 52 * len(leaders)),
        margin=dict(l=16, r=16, t=52, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#F3EDE4",
        xaxis_title="Wickets",
        yaxis=dict(autorange="reversed"),
    )
    return figure


def _format_economy(value: object) -> str:
    return "—" if value is None else f"{float(value):.2f}"


def render_venue_explorer(services: dict[str, Any]) -> None:
    repository = services["repository"]
    venues = repository.list_venues()

    st.markdown("<div class='atlas-kicker'>◆ CricAtlas venue explorer</div>", unsafe_allow_html=True)
    st.markdown(
        "<h1 class='atlas-title explorer-title'>Explore an ODI venue.<br>See who succeeds.</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='atlas-copy'>Ground-specific ODI bowling evidence for venue leaderboard questions and follow-up exploration.</p>",
        unsafe_allow_html=True,
    )

    venue = st.selectbox(
        "Venue",
        options=venues,
        index=None,
        placeholder="Type a venue name…",
        key="venue-explorer-name",
    )
    submitted = st.button(
        "Explore venue",
        disabled=not venue,
        type="primary",
        use_container_width=True,
    )
    if submitted:
        try:
            with st.spinner("Loading ground-specific ODI evidence…"):
                st.session_state["venue-profile"] = load_venue_profile(repository, venue)
                st.session_state["venue-request"] = venue
                st.session_state.pop("venue-error", None)
        except Exception:
            LOGGER.exception("CricAtlas could not load the selected venue")
            st.session_state.pop("venue-profile", None)
            st.session_state.pop("venue-request", None)
            st.session_state["venue-error"] = "This venue could not be loaded."

    error = st.session_state.get("venue-error")
    if error:
        st.error(str(error))
    profile = st.session_state.get("venue-profile")
    applied_request = st.session_state.get("venue-request")
    if not isinstance(profile, dict) or applied_request != venue:
        if not error:
            st.info("Choose a venue, then press Explore venue.")
        return

    st.markdown(f"## {profile['venue_name']}")
    leaderboard = profile["bowling_leaderboard"]
    if not leaderboard:
        st.warning("No venue leaderboard data is available.")
        return

    table_rows = [
        {
            "Bowler": row.get("player_name"),
            "Deliveries": row.get("deliveries"),
            "Runs": row.get("runs_conceded"),
            "Wickets": row.get("wickets"),
            "Economy": _format_economy(row.get("economy_rate")),
        }
        for row in leaderboard
    ]
    st.markdown("### Bowling Leaderboard")
    st.dataframe(table_rows, width="stretch", hide_index=True)
    st.markdown("### Top Wicket Takers")
    st.plotly_chart(build_wickets_figure(leaderboard), width="stretch", config={"displayModeBar": False})
