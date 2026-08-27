from __future__ import annotations

from datetime import date
import logging
import re
from typing import Any

import streamlit as st

from streamlit_player_explorer import build_pitch_heatmap


LOGGER = logging.getLogger("cricatlas.streamlit.matchups")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"Expected a mapping or model, received {type(value).__name__}")


def _first_table_row(response: dict[str, Any]) -> dict[str, Any]:
    tables = response.get("tables") or []
    if not tables:
        return {}
    table = tables[0]
    rows = table.get("rows") or []
    if not rows:
        return {}
    return dict(zip(table.get("columns") or [], rows[0], strict=False))


def _summary_text(body: str) -> str:
    body = re.sub(r" The recorded ODI sample contains [^.]+\.$", "", body)
    return re.sub(r" This is a low sample of [^.]+\.$", "", body)


def load_matchup_page(
    services: dict[str, Any],
    *,
    batter: str,
    bowler: str,
    phase: str = "all",
    year: int | None = None,
    venue: str | None = None,
) -> dict[str, Any]:
    handler = services.get("matchup_handler")
    if not callable(handler):
        handler = getattr(services.get("semantic_service"), "answer_matchup_page", None)
    if not callable(handler):
        raise RuntimeError("The matchup service is unavailable in the current service bundle.")
    result = handler(
        batter=batter,
        bowler=bowler,
        phase=phase,
        year=year,
        venue=venue,
    )
    matchup = _as_dict(result["matchup"])
    baseline = _as_dict(result["baseline"])
    row = _first_table_row(matchup)
    baseline_row = _first_table_row(baseline)
    resolved_batter = str(row.get("Batter") or batter)
    resolved_bowler = str(row.get("Bowler") or bowler)
    runs = row.get("Runs")
    balls = row.get("Balls", row.get("Balls Faced"))
    dismissals = row.get("Dismissals")
    batting_average = (
        float(runs) / float(dismissals)
        if isinstance(runs, int | float) and isinstance(dismissals, int | float) and dismissals > 0
        else None
    )
    visuals = matchup.get("visuals") or {}
    summaries = matchup.get("summaries") or []
    return {
        "supported": matchup.get("status") == "supported" and bool(row),
        "title": f"{resolved_batter} vs {resolved_bowler}",
        "summary": _summary_text(str(summaries[0].get("body") or "")) if summaries else "",
        "metrics": {
            "Runs": runs,
            "Balls": balls,
            "Dismissals": dismissals,
            "Batting Avg": batting_average,
            "Batting SR": row.get("Batting Strike Rate"),
            "Dot Ball %": row.get("Batter Dot Ball Percentage"),
            "Boundary %": row.get("Boundary Percentage"),
            "False Shot %": row.get("False Shot Percentage"),
        },
        "baseline_strike_rate": baseline_row.get("Batting Strike Rate"),
        "pitch": visuals.get("pitch_map"),
        "row": row,
    }


def _metric_value(label: str, value: Any) -> str:
    if value is None:
        return "—"
    if label in {"Runs", "Balls", "Dismissals"}:
        return f"{int(value):,}"
    return f"{float(value):.2f}"


def render_matchup_explorer(services: dict[str, Any]) -> None:
    repository = services["repository"]
    st.markdown("<div class='atlas-kicker'>◆ CricAtlas matchups</div>", unsafe_allow_html=True)
    st.markdown(
        "<h1 class='atlas-title explorer-title'>Batter versus bowler.<br>Inspect every delivery.</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='atlas-copy'>Choose an ODI batter and bowler, then narrow the question by phase, year or venue.</p>",
        unsafe_allow_html=True,
    )

    player_names = repository.list_player_names()
    player_columns = st.columns(2)
    with player_columns[0]:
        batter = st.selectbox(
            "Batter",
            options=player_names,
            index=None,
            placeholder="Type a batter name…",
            key="matchup-batter",
        )
    with player_columns[1]:
        bowler = st.selectbox(
            "Bowler",
            options=player_names,
            index=None,
            placeholder="Type a bowler name…",
            key="matchup-bowler",
        )

    filter_columns = st.columns(3)
    with filter_columns[0]:
        phase_label = st.selectbox(
            "Phase",
            ["All overs", "Powerplay", "Middle overs", "Death overs"],
            key="matchup-phase",
        )
    with filter_columns[1]:
        year = st.number_input(
            "Year",
            min_value=1971,
            max_value=date.today().year,
            value=None,
            placeholder="All years",
            step=1,
            key="matchup-year",
        )
    with filter_columns[2]:
        venues = repository.list_venues()
        venue_label = st.selectbox(
            "Venue",
            ["All venues", *venues],
            key="matchup-venue",
        )

    phase = {
        "All overs": "all",
        "Powerplay": "powerplay",
        "Middle overs": "middle",
        "Death overs": "death",
    }[phase_label]
    venue = None if venue_label == "All venues" else venue_label
    request = {
        "batter": batter,
        "bowler": bowler,
        "phase": phase,
        "year": int(year) if year is not None else None,
        "venue": venue,
    }
    submitted = st.button(
        "Show matchup",
        disabled=not batter or not bowler,
        type="primary",
        width="stretch",
    )
    if submitted:
        try:
            with st.spinner("Checking the ODI ball-by-ball evidence…"):
                st.session_state["matchup-page"] = load_matchup_page(services, **request)
                st.session_state["matchup-request"] = request
                st.session_state.pop("matchup-error", None)
                st.session_state.pop("matchup-error-request", None)
        except Exception:
            LOGGER.exception("CricAtlas could not load the selected matchup")
            st.session_state.pop("matchup-page", None)
            st.session_state.pop("matchup-request", None)
            st.session_state["matchup-error"] = (
                "This matchup could not be loaded. Change either player or broaden the filters, then try again."
            )
            st.session_state["matchup-error-request"] = request

    error = st.session_state.get("matchup-error")
    error_request = st.session_state.get("matchup-error-request")
    if error and error_request == request:
        st.error(str(error))
    page = st.session_state.get("matchup-page")
    applied_request = st.session_state.get("matchup-request")
    if not isinstance(page, dict) or applied_request != request:
        if not error or error_request != request:
            st.info(
                "Choose both players, then press Show matchup. Each player selector supports type-to-search."
            )
        return

    st.markdown(f"## {page['title']}")
    if not page["supported"]:
        st.warning(
            f"No recorded ODI balls were found between {batter} and {bowler} for these filters. "
            "Try another player or broaden the filters."
        )
        return

    if page["summary"]:
        st.markdown(page["summary"])

    metric_items = list(page["metrics"].items())
    metric_columns = [*st.columns(4), *st.columns(4)]
    for column, (label, value) in zip(metric_columns, metric_items, strict=True):
        column.metric(label, _metric_value(label, value))

    matchup_strike_rate = page["metrics"].get("Batting SR")
    baseline_strike_rate = page["baseline_strike_rate"]
    if isinstance(matchup_strike_rate, int | float) and isinstance(baseline_strike_rate, int | float):
        difference = float(matchup_strike_rate) - float(baseline_strike_rate)
        direction = "higher" if difference >= 0 else "lower"
        st.info(
            f"Against {page['title'].split(' vs ', 1)[1]}, the batter's SR is "
            f"{abs(difference):.2f} points {direction} than their matching ODI baseline "
            f"({float(matchup_strike_rate):.2f} vs {float(baseline_strike_rate):.2f})."
        )

    balls = page["metrics"].get("Balls")
    if isinstance(balls, int | float) and balls < 12:
        st.caption(f"Small sample: only {int(balls)} recorded balls, so treat these numbers as descriptive.")

    pitch = page["pitch"]
    if isinstance(pitch, dict) and pitch.get("cells"):
        st.markdown("### Matchup pitch map")
        colour_metric = st.radio(
            "Colour cells by",
            ["Strike rate", "Batting average"],
            horizontal=True,
            key="matchup-pitch-metric",
        )
        st.plotly_chart(
            build_pitch_heatmap(pitch, colour_metric=colour_metric, min_balls=1),
            width="stretch",
            config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False},
        )
        st.caption(
            "Cells show the observed matchup record. Average is runs per dismissal; zones without a dismissal "
            "show n/a. Empty zones mean no recorded deliveries."
        )
    else:
        st.info("No line-and-length pitch map is available for this matchup and these filters.")

    with st.expander("Full matchup row"):
        st.dataframe([page["row"]], width="stretch", hide_index=True)
