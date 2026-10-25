from __future__ import annotations

import logging
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from streamlit_explorer_tables import render_numeric_table

from backend.app.services.explorer_service import build_venue_profile
from backend.app.domain.venue_leaderboard import METRICS, PHASES as ALL_PHASES, SAMPLE_UNITS, VenueBowlingOptions, mode_options


LOGGER = logging.getLogger("cricatlas.streamlit.venue")
DEFAULT_FILTER = VenueBowlingOptions().as_dict()
PHASES = {key: label for key, label in ALL_PHASES.items() if key != "first6"}

def load_venue_profile(repository: object, venue_name: str, **filters: Any) -> dict[str, Any]:
    """Load the same venue payload exposed by GET /api/venues/{venue_name}."""
    return build_venue_profile(repository, venue_name, **filters)


def build_wickets_figure(rows: list[dict[str, Any]], metric: str = "wickets_taken", mode: str = "bowling") -> go.Figure:
    label, field, _ = mode_options(mode).metrics[metric]
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

    mode = st.radio("Mode", ["bowling", "batting"], format_func=str.title, horizontal=True, key="venue-mode")
    defaults = mode_options(mode)().as_dict()
    metrics = mode_options(mode).metrics
    sample_units = mode_options(mode).sample_units

    venue = st.selectbox(
        "Venue",
        options=venues,
        index=None,
        placeholder="Type a venue name…",
        key="venue-explorer-name",
    )
    profile = st.session_state.get("venue-profile")
    applied_request = st.session_state.get("venue-request")
    if isinstance(profile, dict) and profile.get("filters", {}).get("phase") == "first6":
        st.session_state.pop("venue-profile", None)
        st.session_state.pop("venue-filter", None)
        st.session_state["venue-filter-version"] = st.session_state.get("venue-filter-version", 0) + 1
        profile = None

    if isinstance(profile, dict) and applied_request == venue:
        if profile.get("mode", "bowling") != mode:
            selected = {**defaults, **{key: profile["filters"][key] for key in ("phase", "year_start", "year_end", "minimum_sample", "limit")}}
            if profile["filters"]["sample_unit"] == "matches":
                selected["sample_unit"] = "matches"
            profile = load_venue_profile(repository, venue, mode=mode, **selected)
            st.session_state["venue-profile"] = profile
            st.session_state["venue-filter"] = selected
            st.session_state["venue-request"] = venue
            st.session_state["venue-filter-version"] = st.session_state.get("venue-filter-version", 0) + 1

        if "venue-filter" not in st.session_state or "ranking" not in profile:
            # An open session may still hold the previous sorting controls' result.
            profile = load_venue_profile(repository, venue, mode=mode, **{**defaults, **st.session_state.get("venue-filter", {})})
            st.session_state["venue-profile"] = profile
            st.session_state["venue-filter"] = profile["filters"]
    active_filter = {**defaults, **st.session_state.get("venue-filter", {})}
    if active_filter["metric"] not in metrics:
        active_filter["metric"] = defaults["metric"]
    if active_filter["sample_unit"] not in sample_units:
        active_filter["sample_unit"] = defaults["sample_unit"]
    version = st.session_state.get("venue-filter-version", 0)
    for endpoint in ("start", "end"):
        st.session_state.setdefault(f"venue-year-{endpoint}-{version}", active_filter[f"year_{endpoint}"])
    with st.form(key=f"venue-filter-controls-{version}", border=False):
        with st.expander("Filter bowlers" if mode == "bowling" else "Filter batters", expanded=False):
            sample_column, minimum_column, metric_column, phase_column = st.columns(4)
            with sample_column:
                sample_unit = st.selectbox(
                    "Filter by", list(sample_units), key=f"venue-sample-unit-{version}",
                    index=list(sample_units).index(active_filter["sample_unit"]),
                    format_func=sample_units.get,
                )
            with minimum_column:
                minimum_sample = st.number_input(
                    "Minimum number (0 = no minimum)", key=f"venue-minimum-{version}",
                    min_value=0, max_value=1_000_000, value=active_filter["minimum_sample"], step=1,
                )
            with metric_column:
                metric = st.selectbox("Rank and chart by", list(metrics), key=f"venue-metric-{version}",
                                      index=list(metrics).index(active_filter["metric"]),
                                      format_func=lambda key: metrics[key][0])
            with phase_column:
                phase = st.selectbox("Phase", list(PHASES), key=f"venue-phase-{version}",
                                     index=list(PHASES).index(active_filter["phase"] or ""),
                                     format_func=PHASES.get)
            start_column, end_column = st.columns(2)
            with start_column:
                year_start = st.number_input("From year", key=f"venue-year-start-{version}", min_value=1800, max_value=2200,
                                             value=None, step=1, placeholder="All years")
            with end_column:
                year_end = st.number_input("Through year", key=f"venue-year-end-{version}", min_value=1800, max_value=2200,
                                           value=None, step=1, placeholder="All years")
            st.caption("Leave both years blank for all years. Enter one year for that year, or both for an inclusive range.")
            apply, reset = st.columns(2)
            apply_submitted = apply.form_submit_button("Apply filter", disabled=not venue)
            reset_submitted = reset.form_submit_button("Reset filter", disabled=not venue)

        submitted = st.form_submit_button(
            "Explore venue", disabled=not venue, type="primary", use_container_width=True,
        )

    start = year_start if year_start is not None else year_end
    end = year_end if year_end is not None else year_start
    if submitted or apply_submitted or reset_submitted:
        selected = (
            dict(defaults)
            if reset_submitted
            else {
                "sample_unit": sample_unit,
                "minimum_sample": int(minimum_sample),
                "metric": metric, "phase": phase or None,
                "year_start": int(start) if start is not None else None,
                "year_end": int(end) if end is not None else None,
                "limit": 10,
            }
        )
        try:
            updated = load_venue_profile(repository, venue, mode=mode, **selected)
            st.session_state["venue-profile"] = updated
            st.session_state["venue-filter"] = selected
            st.session_state["venue-request"] = venue
            st.session_state["venue-filter-version"] = st.session_state.get("venue-filter-version", 0) + 1
        except ValueError as exc:
            st.error(str(exc))
            return
        except Exception:
            LOGGER.exception("CricAtlas could not update the venue filter")
            st.error("The venue filter could not be updated.")
            return
        # Render every successful submission with its applied defaults. Leaving
        # the previous form mounted changes widget defaults on the next submit
        # and can restore stale year/minimum values instead of the user's edits.
        st.rerun()

    if not isinstance(profile, dict) or applied_request != venue:
        st.info("Choose a venue, set any filters, then press Explore venue.")
        return

    st.markdown(f"## {profile['venue_name']}")
    unit_label = sample_units[active_filter["sample_unit"]]
    sample_label = (
        f"at least {active_filter['minimum_sample']} {unit_label[0].lower() + unit_label[1:]}"
        if active_filter["minimum_sample"]
        else "no minimum sample"
    )
    st.caption(
        f"Filter{' (default)' if active_filter == defaults else ''}: {sample_label}. "
        f"{PHASES[active_filter['phase'] or '']}; "
        f"{str(active_filter['year_start']) + '–' + str(active_filter['year_end']) if active_filter['year_start'] else 'All years'}; "
        f"top 10 by {profile['ranking']['label']} ({profile['ranking']['direction']}). "
        "Eligibility applies after phase/year filters and before top 10."
    )
    st.caption(profile["sample_policy"])
    leaderboard = profile["leaderboard"]
    if not leaderboard:
        st.error("No players qualify for the selected filters and metric.")
        return

    table_rows = [
        {
            "Bowler": row.get("player_name"),
            "Deliveries": row.get("deliveries"),
            "Delivery rows": row.get("delivery_rows"),
            "Matches": row.get("matches"),
            "Runs": row.get("runs_conceded"),
            "Wickets": row.get("wickets"),
            "Economy": row.get("economy_rate"),
            "Bowling average": row.get("bowling_average"),
            "Bowling strike rate": row.get("bowling_strike_rate"),
            "Dot %": row.get("dot_percentage"),
            "Boundary % conceded": row.get("boundary_percentage"),
        }
        for row in leaderboard
    ]
    if mode == "batting":
        table_rows = [{"Batter": row["player_name"], "Balls faced": row["balls_faced"],
                       "Matches": row["matches"], "Runs": row["runs_scored"], "Dismissals": row["dismissals"],
                       "Batting average": row["average"], "Strike Rate": row["strike_rate"],
                       "Control %": row["control_percentage"], "Control balls": row["control_balls"],
                       "Dot %": row["dot_percentage"], "Boundary %": row["boundary_percentage"]}
                      for row in leaderboard]
    st.markdown("### Top Wicket Takers" if active_filter["metric"] == "wickets_taken" else f"### {profile['ranking']['label']} leaders")
    st.plotly_chart(
        build_wickets_figure(leaderboard, active_filter["metric"], mode),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    st.markdown("### Bowling Leaderboard" if mode == "bowling" else "### Batting Leaderboard")
    rate_columns = (
        ["Batting average", "Strike Rate", "Control %", "Dot %", "Boundary %"]
        if mode == "batting"
        else ["Bowling average", "Economy", "Bowling strike rate", "Dot %", "Boundary % conceded"]
    )
    render_numeric_table(table_rows, rate_columns)
