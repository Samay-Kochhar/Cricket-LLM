from __future__ import annotations

import logging
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from streamlit_explorer_tables import render_numeric_table

from backend.app.services.explorer_service import build_player_comparison
from backend.app.domain.venue_leaderboard import mode_options


LOGGER = logging.getLogger("cricatlas.streamlit.compare")

# Presentation only: preserve the shared phase IDs and recorded-over predicates.
COMPARE_PHASES = {
    "": "All overs",
    "powerplay": "ODI powerplay (overs 1–10)",
    "middle": "Middle overs (11–40)",
    "death": "Death overs (after 40)",
}


def load_comparison(repository: object, players: list[str], **filters) -> list[dict[str, Any]]:
    """Load the same two-player summaries exposed by GET /api/compare."""
    return build_player_comparison(repository, players, **filters)["players"]


def build_strike_rate_figure(players: list[dict[str, Any]], metric: str = "batting_strike_rate", mode: str = "batting") -> go.Figure:
    label, field, _ = mode_options(mode).metrics[metric]
    figure = go.Figure(
        go.Bar(
            x=[player.get(field) for player in players],
            y=[str(player.get("player_name") or "") for player in players],
            orientation="h",
            marker_color="#F28F3B",
            hovertemplate="%{y}: %{x:.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        title=f"{label} comparison",
        height=max(280, 76 * len(players)),
        margin=dict(l=16, r=16, t=52, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#F3EDE4",
        xaxis_title=label,
        yaxis=dict(autorange="reversed"),
    )
    return figure


def render_compare_explorer(services: dict[str, Any]) -> None:
    repository = services["repository"]
    if st.session_state.get("compare-phase") == "first6":
        st.session_state["compare-phase"] = ""
    player_names = list(services.get("player_names") or repository.list_player_names())

    st.markdown("<div class='atlas-kicker'>◆ CricAtlas compare explorer</div>", unsafe_allow_html=True)
    st.markdown(
        "<h1 class='atlas-title explorer-title'>Compare ODI players.<br>Inspect the evidence.</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='atlas-copy'>Side-by-side ODI batting and bowling evidence pulled from the same database-backed service used by the workbench.</p>",
        unsafe_allow_html=True,
    )

    mode = st.radio("Mode", ["batting", "bowling"], format_func=str.title, horizontal=True, key="compare-mode")
    metrics = mode_options(mode).metrics
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

    # Submit context edits together. Outside a form, blurring a year input can
    # trigger a separate rerun just as the user clicks Compare.
    with st.form("compare-context", border=False):
        with st.expander("Comparison context", expanded=True):
            phase_column, venue_column, metric_column = st.columns(3)
            with phase_column:
                phase = st.selectbox(
                    "Phase", list(COMPARE_PHASES), format_func=COMPARE_PHASES.get,
                    key="compare-phase",
                )
            with venue_column:
                venue = st.selectbox("Venue", [""] + repository.list_venues(), format_func=lambda v: v or "All venues", key="compare-venue")
            with metric_column:
                metric = st.selectbox("Chart metric", list(metrics),
                                      index=list(metrics).index("batting_strike_rate" if mode == "batting" else "economy_rate"),
                                      format_func=lambda key: metrics[key][0], key=f"compare-metric-{mode}")
            start_column, end_column = st.columns(2)
            with start_column:
                year_start = st.number_input("From year", min_value=1800, max_value=2200, value=None, step=1, placeholder="All years", key="compare-year-start")
            with end_column:
                year_end = st.number_input("Through year", min_value=1800, max_value=2200, value=None, step=1, placeholder="All years", key="compare-year-end")
            st.caption("Leave both years blank for all years. Enter one year for that year, or both for an inclusive range. "
                       "Changes apply when you press Compare players.")
        submitted = st.form_submit_button(
            "Compare players",
            disabled=not first or not second or first == second,
            type="primary",
            use_container_width=True,
        )
    start = year_start if year_start is not None else year_end
    end = year_end if year_end is not None else year_start
    context = dict(mode=mode, metric=metric, phase=phase or None, venue=venue or None,
                   year_start=int(start) if start is not None else None,
                   year_end=int(end) if end is not None else None)
    request = [first, second] if first and second else []
    signature = (request, context)
    if submitted:
        try:
            with st.spinner("Loading ODI comparison evidence…"):
                profile = build_player_comparison(repository, request, **context)
                st.session_state["compare-profile"] = profile
                st.session_state["compare-players"] = profile["players"]
                st.session_state["compare-request"] = signature
                st.session_state.pop("compare-error", None)
        except ValueError as exc:
            st.session_state.pop("compare-players", None)
            st.session_state["compare-error"] = str(exc)
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
    if not isinstance(players, list) or applied_request != signature:
        if first and second and first == second:
            st.info("Choose two different players to compare.")
        elif not error:
            st.info("Choose two players, then press Compare players.")
        return

    st.markdown(f"## {first} vs {second}")
    if not players:
        st.warning("No ODI batting summaries are available for this pair.")
        return

    profile = st.session_state["compare-profile"]
    filters = profile["filters"]
    st.caption(f"Active filters: {mode.title()}; {COMPARE_PHASES[filters['phase'] or '']}; "
               f"{str(filters['year_start']) + '–' + str(filters['year_end']) if filters['year_start'] else 'All years'}; "
               f"{filters['venue'] or 'All venues'}. {profile['ranking']['preference']}.")
    st.caption(profile["sample_policy"])
    for player in players:
        if player["small_sample"]:
            st.warning(f"{player['player_name']}: small sample (fewer than 24 balls).")
    table_rows = [
        {
            "Player": player.get("player_name"),
            "Runs": player.get("runs_scored"),
            "Balls": player.get("balls_faced"),
            "Dismissals": player.get("dismissals"),
            "Batting average": player.get("average"),
            "Matches": player.get("matches"),
            "Control balls": player.get("control_balls"),
            "Dot %": player.get("dot_percentage"),
            "Strike Rate": player.get("strike_rate"),
            "Boundary %": player.get("boundary_percentage"),
            "Control %": player.get("control_percentage"),
        }
        for player in players
    ]
    if mode == "bowling":
        table_rows = [{"Player": player["player_name"], "Legal balls": player.get("deliveries", 0),
                       "Matches": player.get("matches", 0), "Runs conceded": player.get("runs_conceded"),
                       "Wickets": player.get("wickets"),
                       "Bowling average": player.get("bowling_average"),
                       "Economy": player.get("economy_rate"),
                       "Bowling strike rate": player.get("bowling_strike_rate"),
                       "Dot %": player.get("dot_percentage"),
                       "Boundary % conceded": player.get("boundary_percentage")} for player in players]
    st.markdown("### Comparison Table")
    rate_columns = (
        ["Batting average", "Strike Rate", "Control %", "Dot %", "Boundary %"]
        if mode == "batting"
        else ["Bowling average", "Economy", "Bowling strike rate", "Dot %", "Boundary % conceded"]
    )
    render_numeric_table(table_rows, rate_columns)
    st.markdown(f"### {profile['ranking']['label']}")
    st.plotly_chart(build_strike_rate_figure(players, metric, mode), use_container_width=True, config={"displayModeBar": False})
