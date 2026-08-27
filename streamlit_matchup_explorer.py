from __future__ import annotations

from datetime import date
from html import escape
import logging
import re
from typing import Any

import streamlit as st


LOGGER = logging.getLogger("cricatlas.streamlit.matchups")

MATCHUP_PITCH_LINES = (
    "WIDE_OUTSIDE_OFFSTUMP",
    "OUTSIDE_OFFSTUMP",
    "ON_THE_STUMPS",
    "DOWN_LEG",
)
MATCHUP_PITCH_LENGTHS = (
    "FULL_TOSS",
    "YORKER",
    "FULL",
    "GOOD_LENGTH",
    "SHORT_OF_A_GOOD_LENGTH",
    "SHORT",
)
MATCHUP_PITCH_LABELS = {
    "WIDE_OUTSIDE_OFFSTUMP": "Wide outside off",
    "OUTSIDE_OFFSTUMP": "Outside off",
    "ON_THE_STUMPS": "On the stumps",
    "DOWN_LEG": "Down leg",
    "FULL_TOSS": "Full toss",
    "YORKER": "Yorker",
    "FULL": "Full",
    "GOOD_LENGTH": "Good length",
    "SHORT_OF_A_GOOD_LENGTH": "Back of a length",
    "SHORT": "Short",
}


def build_matchup_pitch_html(
    pitch: dict[str, Any],
    *,
    pitch_view: str = "All",
) -> str:
    """Render the approved matchup pitch structure used by the web explorer."""
    handedness = str(pitch.get("handedness") or "").upper()
    lines = list(MATCHUP_PITCH_LINES)
    column_weights = "0.5fr 0.5fr 0.6fr 1fr"
    if handedness == "LHB":
        lines.reverse()
        column_weights = "1fr 0.6fr 0.5fr 0.5fr"

    cells = [
        cell
        for cell in pitch.get("cells", [])
        if isinstance(cell, dict)
        and str(cell.get("line")) in MATCHUP_PITCH_LINES
        and str(cell.get("length")) in MATCHUP_PITCH_LENGTHS
    ]
    cell_map = {(str(cell["length"]), str(cell["line"])): cell for cell in cells}

    def primary_value(cell: dict[str, Any]) -> float | None:
        if pitch_view == "Avg":
            dismissals = int(cell.get("dismissals", 0) or 0)
            return float(cell.get("runs", 0) or 0) / dismissals if dismissals else None
        value = cell.get("strike_rate")
        return float(value) if isinstance(value, int | float) else None

    def colour_value(cell: dict[str, Any]) -> float:
        if pitch_view == "W":
            return float(cell.get("wicket_balls", cell.get("dismissals", 0)) or 0)
        if pitch_view == "4s":
            return float(cell.get("fours", 0) or 0)
        if pitch_view == "6s":
            return float(cell.get("sixes", 0) or 0)
        return primary_value(cell) or 0.0

    max_value = max((colour_value(cell) for cell in cells), default=1.0) or 1.0
    value_label = "AVG" if pitch_view == "Avg" else "SR"
    line_headers = "".join(
        f'<span class="atlas-pitch-axis-label">{escape(MATCHUP_PITCH_LABELS[line])}</span>'
        for line in lines
    )
    rows: list[str] = []
    for length in MATCHUP_PITCH_LENGTHS:
        rendered_cells: list[str] = []
        for line in lines:
            cell = cell_map.get((length, line))
            if cell is None:
                rendered_cells.append(
                    '<div class="atlas-pitch-cell empty"><span>No deliveries</span></div>'
                )
                continue
            value = primary_value(cell)
            ratio = max(0.0, min(1.0, colour_value(cell) / max_value))
            alpha = 0.18 + ratio * 0.52
            rgb = {
                "Avg": "103, 163, 255",
                "W": "239, 83, 80",
                "4s": "242, 143, 59",
                "6s": "255, 209, 102",
            }.get(pitch_view, "124, 226, 180")
            value_text = f"{value:.1f}" if value is not None else "—"
            fours = int(cell.get("fours", 0) or 0)
            sixes = int(cell.get("sixes", 0) or 0)
            wickets = int(cell.get("wicket_balls", cell.get("dismissals", 0)) or 0)
            title = escape(f"{MATCHUP_PITCH_LABELS[length]} / {MATCHUP_PITCH_LABELS[line]}")
            rendered_cells.append(
                f'<div class="atlas-pitch-cell" data-line="{line}" title="{title}" '
                f'style="background-color:rgba({rgb}, {alpha:.3f})">'
                f"<strong>{value_text}</strong><span>{value_label}</span>"
                '<div class="atlas-pitch-cell-stats">'
                f'<span class="atlas-mini-chip four">4 {fours}</span>'
                f'<span class="atlas-mini-chip six">6 {sixes}</span>'
                f'<span class="atlas-mini-chip wicket">W {wickets}</span>'
                "</div></div>"
            )
        stumps = (
            '<div class="atlas-pitch-stumps" aria-hidden="true"><span></span><span></span><span></span></div>'
            if length == "FULL_TOSS"
            else ""
        )
        rows.append(
            '<div class="atlas-pitch-grid-row">'
            f'<div class="atlas-pitch-length-label">{escape(MATCHUP_PITCH_LABELS[length])}</div>'
            f"{''.join(rendered_cells)}{stumps}</div>"
        )

    return f"""
<style>
.atlas-approved-pitch {{ --pitch-line-columns:{column_weights}; display:flex; flex-direction:column; gap:14px; width:min(100%,900px); margin:4px auto 12px; }}
.atlas-pitch-line-headers, .atlas-pitch-grid-row {{ display:grid; grid-template-columns:130px var(--pitch-line-columns); column-gap:0; }}
.atlas-pitch-line-headers {{ align-items:end; }}
.atlas-pitch-axis-label, .atlas-pitch-length-label {{ color:#9eabb5; font-size:.76rem; text-transform:uppercase; letter-spacing:.12em; }}
.atlas-pitch-axis-label {{ padding-inline:4px; text-align:center; }}
.atlas-pitch-board {{ position:relative; border-radius:28px; border:1px solid rgba(239,225,207,.16); background:radial-gradient(circle at top center,rgba(242,143,59,.08),transparent 24%),linear-gradient(180deg,rgba(239,225,207,.1),rgba(239,225,207,.04)),rgba(9,14,18,.76); padding:26px 18px 18px; overflow:hidden; }}
.atlas-pitch-board::before {{ content:""; position:absolute; inset:16px 19px 16px 149px; border-radius:22px; background:linear-gradient(180deg,rgba(234,215,191,.88),rgba(217,192,161,.76)); box-shadow:inset 0 0 0 1px rgba(111,79,44,.22); pointer-events:none; }}
.atlas-pitch-grid {{ position:relative; display:grid; gap:10px; z-index:1; }}
.atlas-pitch-grid-row {{ position:relative; }}
.atlas-pitch-length-label {{ display:flex; align-items:center; }}
.atlas-pitch-cell {{ min-height:98px; border-radius:10px; border:1px solid rgba(255,255,255,.08); padding:10px; display:flex; flex-direction:column; gap:8px; justify-content:space-between; color:#101418; box-shadow:inset 0 1px 0 rgba(255,255,255,.04); }}
.atlas-pitch-cell.empty {{ justify-content:center; align-items:center; background:rgba(255,255,255,.05); color:rgba(11,16,20,.56); }}
.atlas-pitch-cell.empty span {{ font-size:.68rem; letter-spacing:.08em; }}
.atlas-pitch-cell strong {{ font-size:1.2rem; }}
.atlas-pitch-cell > span {{ color:rgba(11,16,20,.72); font-size:.72rem; letter-spacing:.14em; }}
.atlas-pitch-cell-stats {{ display:flex; flex-wrap:wrap; gap:6px; }}
.atlas-mini-chip {{ display:inline-flex; align-items:center; justify-content:center; min-height:24px; padding:0 8px; border-radius:999px; background:rgba(11,16,20,.68); color:#f8f6f0; font-size:.74rem; }}
.atlas-mini-chip.four {{ background:rgba(242,143,59,.86); color:#101418; }}
.atlas-mini-chip.six {{ background:rgba(255,209,102,.9); color:#101418; }}
.atlas-mini-chip.wicket {{ background:rgba(239,83,80,.88); }}
.atlas-pitch-stumps {{ position:absolute; left:calc(50% + 65px); bottom:-22px; transform:translateX(-50%); display:flex; gap:4px; z-index:2; }}
.atlas-pitch-stumps span {{ width:6px; height:34px; border-radius:999px; background:rgba(11,16,20,.78); }}
.atlas-pitch-legend {{ display:flex; gap:12px; flex-wrap:wrap; color:#9eabb5; font-size:.84rem; }}
@media (max-width:700px) {{ .atlas-pitch-line-headers, .atlas-pitch-grid-row {{ grid-template-columns:78px var(--pitch-line-columns); }} .atlas-pitch-board::before {{ left:97px; }} .atlas-pitch-stumps {{ left:calc(50% + 39px); }} .atlas-pitch-cell {{ min-height:82px; padding:7px; }} .atlas-pitch-axis-label, .atlas-pitch-length-label {{ font-size:.62rem; }} }}
</style>
<div class="atlas-approved-pitch" style="--pitch-line-columns:{column_weights}">
  <div class="atlas-pitch-line-headers"><span></span>{line_headers}</div>
  <div class="atlas-pitch-board"><div class="atlas-pitch-grid">{''.join(rows)}</div></div>
  <div class="atlas-pitch-legend"><span>Orange: fours</span><span>Yellow: sixes</span><span>Red: wickets</span></div>
</div>
"""


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
        resolved_batter, resolved_bowler = page["title"].split(" vs ", 1)
        st.markdown(
            f"""
<div style="border:1px solid rgba(239,225,207,.16);border-radius:18px;padding:18px 20px;margin:12px 0;background:rgba(9,14,18,.62)">
  <span style="color:#9eabb5;font-size:.76rem;text-transform:uppercase;letter-spacing:.12em">Compared with the batter's normal ODI rate</span>
  <h3 style="margin:.45rem 0;color:#f8f6f0">{float(matchup_strike_rate):.2f} vs {float(baseline_strike_rate):.2f}</h3>
  <p style="margin:0;color:#9eabb5">Against {escape(resolved_bowler)}, {escape(resolved_batter)}'s strike rate is {abs(difference):.2f} points {direction} than the matching overall baseline.</p>
</div>
""",
            unsafe_allow_html=True,
        )

    balls = page["metrics"].get("Balls")
    if isinstance(balls, int | float) and balls < 12:
        st.caption(f"Small sample: only {int(balls)} recorded balls, so treat these numbers as descriptive.")

    pitch = page["pitch"]
    if isinstance(pitch, dict) and pitch.get("cells"):
        st.markdown("### Matchup pitch map")
        pitch_view = st.segmented_control(
            "Pitch view",
            ["All", "SR", "Avg", "W", "4s", "6s"],
            default="All",
            label_visibility="collapsed",
            key="matchup-pitch-metric",
        )
        st.html(build_matchup_pitch_html(pitch, pitch_view=str(pitch_view or "All")))
        st.caption(
            "Cells show the observed matchup record. Average is runs per dismissal; zones without a dismissal "
            "show n/a. Empty zones mean no recorded deliveries."
        )
    else:
        st.info("No line-and-length pitch map is available for this matchup and these filters.")

    with st.expander("Full matchup row"):
        st.dataframe([page["row"]], width="stretch", hide_index=True)
