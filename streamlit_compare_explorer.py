from __future__ import annotations

import logging
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from backend.app.services.explorer_service import build_player_comparison


LOGGER = logging.getLogger("cricatlas.streamlit.compare")


def load_comparison(repository: object, players: list[str]) -> list[dict[str, Any]]:
    """Load the same two-player summaries exposed by GET /api/compare."""
    return build_player_comparison(repository, players)["players"]


def build_strike_rate_figure(players: list[dict[str, Any]]) -> go.Figure:
    figure = go.Figure(
        go.Bar(
            x=[float(player.get("strike_rate") or 0) for player in players],
            y=[str(player.get("player_name") or "") for player in players],
            orientation="h",
            marker_color="#F28F3B",
            hovertemplate="%{y}: %{x:.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        title="Strike rate comparison",
        height=max(280, 76 * len(players)),
        margin=dict(l=16, r=16, t=52, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#F3EDE4",
        xaxis_title="Strike rate",
        yaxis=dict(autorange="reversed"),
    )
    return figure


def _format_number(value: object, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def render_compare_explorer(services: dict[str, Any]) -> None:
    repository = services["repository"]
    player_names = list(services.get("player_names") or repository.list_player_names())

    st.markdown("<div class='atlas-kicker'>◆ CricAtlas compare explorer</div>", unsafe_allow_html=True)
    st.markdown(
        "<h1 class='atlas-title explorer-title'>Compare ODI players.<br>Inspect the evidence.</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='atlas-copy'>Side-by-side ODI batting evidence pulled from the same database-backed service used by the workbench.</p>",
        unsafe_allow_html=True,
    )

    columns = st.columns(2)
    with columns[0]:
        first = st.selectbox(
            "Player one",
            options=player_names,
            index=None,
            placeholder="Type a player name…",
            key="compare-player-one",
        )
    with columns[1]:
        second = st.selectbox(
            "Player two",
            options=player_names,
            index=None,
            placeholder="Type a player name…",
            key="compare-player-two",
        )

    request = [first, second] if first and second else []
    submitted = st.button(
        "Compare players",
        disabled=not first or not second or first == second,
        type="primary",
        use_container_width=True,
    )
    if submitted:
        try:
            with st.spinner("Loading ODI comparison evidence…"):
                st.session_state["compare-players"] = load_comparison(repository, request)
                st.session_state["compare-request"] = request
                st.session_state.pop("compare-error", None)
        except Exception:
            LOGGER.exception("CricAtlas could not load the selected comparison")
            st.session_state.pop("compare-players", None)
            st.session_state.pop("compare-request", None)
            st.session_state["compare-error"] = "This player comparison could not be loaded."

    error = st.session_state.get("compare-error")
    if error:
        st.error(str(error))
    players = st.session_state.get("compare-players")
    applied_request = st.session_state.get("compare-request")
    if not isinstance(players, list) or applied_request != request:
        if first and second and first == second:
            st.info("Choose two different players to compare.")
        elif not error:
            st.info("Choose two players, then press Compare players.")
        return

    st.markdown(f"## {first} vs {second}")
    if not players:
        st.warning("No ODI batting summaries are available for this pair.")
        return

    table_rows = [
        {
            "Player": player.get("player_name"),
            "Runs": player.get("runs_scored"),
            "Balls": player.get("balls_faced"),
            "Strike Rate": _format_number(player.get("strike_rate")),
            "Boundary %": _format_number(player.get("boundary_percentage")),
            "Control %": _format_number(player.get("control_percentage")),
        }
        for player in players
    ]
    st.markdown("### Comparison Table")
    st.dataframe(table_rows, width="stretch", hide_index=True)
    st.markdown("### Strike Rate")
    st.plotly_chart(build_strike_rate_figure(players), width="stretch", config={"displayModeBar": False})
