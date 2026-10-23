from __future__ import annotations

import logging
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from backend.app.services.explorer_service import build_venue_profile
from backend.app.domain.venue_leaderboard import METRICS, PHASES, SAMPLE_UNITS, VenueBowlingOptions


LOGGER = logging.getLogger("cricatlas.streamlit.venue")
DEFAULT_FILTER = VenueBowlingOptions().as_dict()

def load_venue_profile(repository: object, venue_name: str, **filters: Any) -> dict[str, Any]:
    """Load the same venue payload exposed by GET /api/venues/{venue_name}."""
    return build_venue_profile(repository, venue_name, **filters)


def build_wickets_figure(rows: list[dict[str, Any]], metric: str = "wickets_taken") -> go.Figure:
    label, field, _ = METRICS[metric]
    leaders = rows[:6]
    figure = go.Figure(
        go.Bar(
            x=[row.get(field) for row in leaders],
            y=[str(row.get("player_name") or "") for row in leaders],
            orientation="h",
            marker_color="#7CE2B4",
            hovertemplate=f"%{{y}}: %{{x}} {label}<extra></extra>",
        )
    )
    figure.update_layout(
        title=f"{label} at venue",
        height=max(320, 52 * len(leaders)),
        margin=dict(l=16, r=16, t=52, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#F3EDE4",
        xaxis_title=label,
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
                st.session_state["venue-filter"] = dict(DEFAULT_FILTER)
                st.session_state["venue-filter-version"] = st.session_state.get("venue-filter-version", 0) + 1
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

    if "venue-filter" not in st.session_state or "ranking" not in profile:
        # An open session may still hold the previous sorting controls' result.
        profile = load_venue_profile(repository, venue, **{**DEFAULT_FILTER, **st.session_state.get("venue-filter", {})})
        st.session_state["venue-profile"] = profile
        st.session_state["venue-filter"] = profile["filters"]

    st.markdown(f"## {profile['venue_name']}")
    active_filter = {**DEFAULT_FILTER, **st.session_state["venue-filter"]}
    st.markdown("### Filter bowlers")
    version = st.session_state.get("venue-filter-version", 0)
    with st.form(key=f"venue-filter-controls-{version}"):
        sample_unit = st.selectbox(
            "Filter by", list(SAMPLE_UNITS), key=f"venue-sample-unit-{version}",
            index=list(SAMPLE_UNITS).index(active_filter["sample_unit"]),
            format_func=SAMPLE_UNITS.get,
        )
        minimum_sample = st.number_input(
            "Minimum number (0 = no minimum)", key=f"venue-minimum-{version}",
            min_value=0, max_value=1_000_000, value=active_filter["minimum_sample"], step=1,
        )
        metric = st.selectbox("Rank and chart by", list(METRICS), key=f"venue-metric-{version}",
                              index=list(METRICS).index(active_filter["metric"]),
                              format_func=lambda key: METRICS[key][0])
        phase = st.selectbox("Phase", list(PHASES), key=f"venue-phase-{version}",
                             index=list(PHASES).index(active_filter["phase"] or ""),
                             format_func=PHASES.get)
        years_enabled = st.checkbox("Filter by year or inclusive year range", value=active_filter["year_start"] is not None, key=f"venue-years-enabled-{version}")
        year_start = st.number_input("From year", key=f"venue-year-start-{version}", min_value=1800, max_value=2200,
                                     value=active_filter["year_start"] or 2023, step=1)
        year_end = st.number_input("Through year", key=f"venue-year-end-{version}", min_value=1800, max_value=2200,
                                   value=active_filter["year_end"] or 2023, step=1)
        apply, reset = st.columns(2)
        apply_submitted = apply.form_submit_button("Apply filter")
        reset_submitted = reset.form_submit_button("Reset filter")

    if apply_submitted or reset_submitted:
        selected = (
            dict(DEFAULT_FILTER)
            if reset_submitted
            else {
                "sample_unit": sample_unit,
                "minimum_sample": int(minimum_sample),
                "metric": metric, "phase": phase or None,
                "year_start": int(year_start) if years_enabled else None,
                "year_end": int(year_end) if years_enabled else None,
                "limit": 10,
            }
        )
        try:
            updated = load_venue_profile(repository, venue, **selected)
            if not updated["bowling_leaderboard"]:
                st.error("No bowlers qualify for the selected filters and metric.")
                return
            st.session_state["venue-profile"] = updated
            st.session_state["venue-filter"] = selected
            if reset_submitted:
                st.session_state["venue-filter-version"] = st.session_state.get("venue-filter-version", 0) + 1
                st.rerun()
            profile = updated
            active_filter = selected
        except ValueError as exc:
            st.error(str(exc))
            return
        except Exception:
            LOGGER.exception("CricAtlas could not update the venue filter")
            st.error("The venue filter could not be updated.")
            return

    unit_label = SAMPLE_UNITS[active_filter["sample_unit"]]
    sample_label = (
        f"at least {active_filter['minimum_sample']} {unit_label[0].lower() + unit_label[1:]}"
        if active_filter["minimum_sample"]
        else "no minimum sample"
    )
    st.caption(
        f"Filter{' (default)' if active_filter == DEFAULT_FILTER else ''}: {sample_label}. "
        f"{PHASES[active_filter['phase'] or '']}; "
        f"{str(active_filter['year_start']) + '–' + str(active_filter['year_end']) if active_filter['year_start'] else 'All years'}; "
        f"top 10 by {profile['ranking']['label']} ({profile['ranking']['direction']}). "
        "Eligibility applies after phase/year filters and before top 10."
    )
    st.caption(profile["sample_policy"])
    leaderboard = profile["bowling_leaderboard"]
    if not leaderboard:
        st.warning("No venue leaderboard data is available.")
        return

    table_rows = [
        {
            "Bowler": row.get("player_name"),
            "Deliveries": row.get("deliveries"),
            "Delivery rows": row.get("delivery_rows"),
            "Matches": row.get("matches"),
            "Runs": row.get("runs_conceded"),
            "Wickets": row.get("wickets"),
            "Economy": _format_economy(row.get("economy_rate")),
            "Bowling average": _format_economy(row.get("bowling_average")),
            "Bowling strike rate": _format_economy(row.get("bowling_strike_rate")),
            "Dot %": _format_economy(row.get("dot_percentage")),
            "Boundary % conceded": _format_economy(row.get("boundary_percentage")),
        }
        for row in leaderboard
    ]
    st.markdown("### Top Wicket Takers" if active_filter["metric"] == "wickets_taken" else f"### {profile['ranking']['label']} leaders")
    st.plotly_chart(
        build_wickets_figure(leaderboard, active_filter["metric"]),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    st.markdown("### Bowling Leaderboard")
    st.dataframe(table_rows, use_container_width=True, hide_index=True)
