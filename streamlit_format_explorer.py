"""One explorer for every format: the format selector and the non-ODI views.

The sidebar keeps one Player, Compare, Matchups and Venue section. Each starts
with a Format / Gender / Competition selector. Men's ODIs (the default) render
the original approved ODI pages unchanged, over the ODI database. Every other
selection renders the matching view here over the multi-format database
(MultiFormatService), with the same headings, controls and tables wherever the
data supports them. A feature the selected data cannot support shows an
explicit "not available for this format" note instead of disappearing.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from backend.app.multiformat.service import DeliveryFilter, MultiFormatService, player_options
from streamlit_explorer_tables import render_numeric_table
from streamlit_matchup_explorer import build_matchup_pitch_html
from streamlit_player_explorer import (
    LENGTH_ORDER,
    LINE_ORDER,
    _base_layout,
    _coverage_caption,
    _display_label,
    build_phase_figure,
    build_pitch_heatmap,
    build_shot_figure,
)


ORANGE = "#F28F3B"
GREEN = "#7CE2B4"
ALL_COMPETITIONS = "All competitions"
GENDERS = {"male": "Men", "female": "Women"}
FORMAT_ORDER = (
    "ODI",
    "Test",
    "T20I",
    "T20 domestic",
    "The Hundred",
    "List A domestic",
    "First-class domestic",
    "T20 (other international)",
    "List A (other international)",
    "Multi-day (other international)",
)
FORMAT_LABELS = {
    "ODI": "ODI",
    "Test": "Test",
    "T20I": "T20I",
    "T20 domestic": "T20 leagues & domestic (IPL, BBL, …)",
    "The Hundred": "The Hundred",
    "List A domestic": "List A domestic (one-day)",
    "First-class domestic": "First-class domestic",
}
EXPLORER_VIEWS = ("Player Explorer", "Compare", "Matchups", "Venue Explorer")
NOT_AVAILABLE = "not available for this format"

# Phase definitions per format family. ODI and T20 phases come from the shared
# filter; 50-over domestic cricket uses ODI over ranges explicitly.
_T20_PHASES = {
    "All phases": {},
    "Powerplay (overs 1–6)": {"phase": "powerplay"},
    "Middle overs (7–15)": {"phase": "middle"},
    "Death overs (16–20)": {"phase": "death"},
}
_ODI_PHASES = {
    "All phases": {},
    "Powerplay (overs 1–10)": {"phase": "powerplay"},
    "Middle overs (11–40)": {"phase": "middle"},
    "Death overs (41–50)": {"phase": "death"},
}
_LIST_A_PHASES = {
    "All phases": {},
    "Powerplay (overs 1–10)": {"over_from": 1, "over_to": 10},
    "Middle overs (11–40)": {"over_from": 11, "over_to": 40},
    "Death overs (41–50)": {"over_from": 41},
}
_HUNDRED_PHASES = {
    "All phases": {},
    "Powerplay (first 25 balls)": {"phase": "powerplay"},
    "Middle (balls 26–75)": {"phase": "middle"},
    "Death (balls 76–100)": {"phase": "death"},
}
BATTING_RANKS = {
    "runs": ("Runs", "runs"),
    "strike_rate": ("Strike rate", "strike_rate"),
    "average": ("Batting average", "average"),
    "sixes": ("Sixes", "sixes"),
    "fours": ("Fours", "fours"),
}
BOWLING_RANKS = {
    "wickets": ("Wickets", "wickets"),
    "economy": ("Economy", "economy"),
    "average": ("Bowling average", "average"),
    "strike_rate": ("Bowling strike rate", "strike_rate"),
    "dot_ball_pct": ("Dot %", "dot_ball_pct"),
}


def phase_options(fmt: str) -> dict[str, dict[str, Any]] | None:
    """Phase labels and their filter fields, or None when phases do not apply."""
    if fmt == "ODI":
        return _ODI_PHASES
    if fmt == "The Hundred":
        return _HUNDRED_PHASES
    if fmt.startswith("T20"):
        return _T20_PHASES
    if fmt.startswith("List A"):
        return _LIST_A_PHASES
    return None


@dataclass(frozen=True)
class ExplorerScope:
    format: str = "ODI"
    gender: str = "male"
    competition: str | None = None

    @property
    def original_odi(self) -> bool:
        """Men's ODIs use the approved ODI explorers over the ODI database."""
        return self.format == "ODI" and self.gender == "male" and self.competition is None

    @property
    def key(self) -> str:
        return f"{self.format}|{self.gender}|{self.competition or ''}"

    @property
    def label(self) -> str:
        base = f"{GENDERS[self.gender]}'s {FORMAT_LABELS.get(self.format, self.format)}"
        return base + (f" · {self.competition}" if self.competition else "")

    def filter(self, **extra: Any) -> DeliveryFilter:
        return DeliveryFilter(format=self.format, gender=self.gender, competition=self.competition, **extra)


def default_db_path(root: Path) -> Path:
    configured = os.getenv("MULTIFORMAT_DUCKDB_PATH")
    return Path(configured) if configured else root / "data" / "cricket_all.duckdb"


# ---------------------------------------------------------------- cached reads
@st.cache_data(show_spinner=False, ttl=3600)
def _coverage(db: str) -> dict[str, Any]:
    return MultiFormatService(Path(db)).coverage()


@st.cache_data(show_spinner=False, ttl=3600)
def _competitions(db: str, fmt: str, gender: str) -> list[dict[str, Any]]:
    return MultiFormatService(Path(db)).competitions(format=fmt, gender=gender)


@st.cache_data(show_spinner=False, ttl=3600)
def _players(db: str, role: str, flt: DeliveryFilter) -> list[dict[str, Any]]:
    return player_options(MultiFormatService(Path(db)), role, flt)


@st.cache_data(show_spinner=False, ttl=3600)
def _venue_groups(db: str, flt: DeliveryFilter) -> dict[str, dict[str, Any]]:
    """Venue display name -> raw names and matches, merging verified ground aliases."""
    from backend.app.domain.venues import resolve_venue

    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {"names": [], "matches": 0})
    for row in MultiFormatService(Path(db)).venues(flt):
        venue = resolve_venue(row["venue"])
        name = row["venue"] if venue.id.startswith("unreviewed-") else venue.display_name
        groups[name]["names"].append(row["venue"])
        groups[name]["matches"] += row["matches"]
    return dict(sorted(groups.items(), key=lambda item: (-item[1]["matches"], item[0])))


# ---------------------------------------------------------------- selector
def render_scope_selector(db_path: Path) -> ExplorerScope:
    """Format, gender and competition controls shown at the top of every explorer."""
    if not db_path.exists():
        st.selectbox("Format", ["ODI"], key="explorer-format")
        st.caption("Only men's ODIs are available on this deployment: the all-formats database is not installed.")
        return ExplorerScope()
    db = str(db_path)
    formats = _coverage(db)["formats"]
    present = {row["format"] for row in formats}
    options = [f for f in FORMAT_ORDER if f in present] + sorted(present - set(FORMAT_ORDER))
    controls = st.columns([1.3, 0.8, 1.9])
    with controls[0]:
        fmt = st.selectbox("Format", options, format_func=lambda f: FORMAT_LABELS.get(f, f), key="explorer-format")
    genders = [g for g in GENDERS if any(r["format"] == fmt and r["gender"] == g for r in formats)]
    with controls[1]:
        gender = st.selectbox("Gender", genders, format_func=GENDERS.get, key=f"explorer-gender-{fmt}")
    if fmt == "ODI" and gender == "male":
        with controls[2]:
            st.caption("Men's ODIs use the full ODI database: phases, control, wagon wheels and shots.")
        return ExplorerScope()
    competitions = _competitions(db, fmt, gender)
    with controls[2]:
        competition = st.selectbox(
            "Competition",
            [ALL_COMPETITIONS, *(row["competition"] for row in competitions)],
            key=f"explorer-competition-{fmt}-{gender}",
        )
    scope = ExplorerScope(fmt, gender, None if competition == ALL_COMPETITIONS else competition)
    selected = [row for row in competitions if competition in (ALL_COMPETITIONS, row["competition"])]
    if selected:
        ll_rows = [row for row in selected if row.get("ll_deliveries")]
        ll_span = (
            f" ({min(r['ll_first_match'] for r in ll_rows):%b %Y} to {max(r['ll_last_match'] for r in ll_rows):%b %Y})"
            if ll_rows
            else ""
        )
        st.caption(
            f"{sum(r['matches'] for r in selected):,} matches · ball-by-ball "
            f"{min(r['first_match'] for r in selected):%b %Y} to {max(r['last_match'] for r in selected):%b %Y} · "
            f"line/length on {sum(r['ll_deliveries'] for r in selected):,} of "
            f"{sum(r['deliveries'] for r in selected):,} balls{ll_span}"
        )
    return scope


def render_other_format_view(view: str, db_path: Path, scope: ExplorerScope) -> None:
    service = MultiFormatService(db_path)
    renderers = {
        "Player Explorer": render_player_view,
        "Compare": render_compare_view,
        "Matchups": render_matchup_view,
        "Venue Explorer": render_venue_view,
    }
    renderers[view](service, str(db_path), scope)


# ---------------------------------------------------------------- shared pieces
def _header(kicker: str, title: str, copy: str) -> None:
    st.markdown(f"<div class='atlas-kicker'>◆ {kicker}</div>", unsafe_allow_html=True)
    st.markdown(f"<h1 class='atlas-title explorer-title'>{title}</h1>", unsafe_allow_html=True)
    st.markdown(f"<p class='atlas-copy'>{copy}</p>", unsafe_allow_html=True)


def not_available(feature: str, scope: ExplorerScope, reason: str) -> None:
    st.info(f"{feature} is {NOT_AVAILABLE} ({scope.label}). {reason}")


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value:.{digits}f}{suffix}"


def _pct(part: Any, whole: Any) -> float | None:
    return round(100 * part / whole, 2) if whole else None


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The scope pins format and gender, so stats come back as at most one row."""
    return rows[0] if rows else None


def _player_picker(db: str, label: str, role: str, flt: DeliveryFilter, key: str, placeholder: str) -> str | None:
    options = _players(db, role, flt)
    names = {row["player_id"]: f"{row['name']} · {row['matches']} matches" for row in options}
    return st.selectbox(label, options=list(names), index=None, format_func=names.get, placeholder=placeholder, key=key)


def _phase_select(scope: ExplorerScope, label: str, key: str) -> tuple[str, dict[str, Any]]:
    options = phase_options(scope.format)
    if options is None:
        st.selectbox(label, ["All phases"], key=key, disabled=True,
                     help="Phases are defined for limited-overs cricket only.")
        return "All phases", {}
    choice = st.selectbox(label, list(options), key=key)
    return choice, options[choice]


def _phase_note(scope: ExplorerScope) -> None:
    if phase_options(scope.format) is None:
        st.caption(f"Phase filter: {NOT_AVAILABLE} — phases are defined for limited-overs cricket only.")


def _limitations(service: MultiFormatService, scope: ExplorerScope) -> None:
    for row in service.limitations(DeliveryFilter(format=scope.format, gender=scope.gender)):
        st.caption(f"Limitation: {row['statement']}")


def _name(service: MultiFormatService, player_id: str) -> str:
    return (service.player(player_id) or {}).get("name", player_id)


def _year_range(start: Any, end: Any) -> dict[str, Any]:
    first = start if start is not None else end
    last = end if end is not None else start
    return {
        "year_from": int(first) if first is not None else None,
        "year_to": int(last) if last is not None else None,
    }


def build_trend_figure(rows: list[dict[str, Any]], role: str) -> go.Figure:
    field, label = ("runs", "Runs") if role == "batting" else ("wickets", "Wickets")
    figure = go.Figure(
        go.Scatter(
            x=[row["year"] for row in rows],
            y=[row[field] for row in rows],
            mode="lines+markers",
            line=dict(color=ORANGE, width=3),
            marker=dict(size=8),
            customdata=[[row.get("balls"), row.get("strike_rate")] for row in rows],
            hovertemplate=f"%{{x}}: %{{y:.0f}} {label.lower()}<br>Balls: %{{customdata[0]:.0f}}"
            "<br>Strike rate: %{customdata[1]:.1f}<extra></extra>",
        )
    )
    figure.update_layout(title=f"{label} by year", xaxis_title="Year", yaxis_title=label, showlegend=False)
    return _base_layout(figure)


def build_bar_figure(rows: list[dict[str, Any]], field: str, label: str, title: str, colour: str = ORANGE) -> go.Figure:
    figure = go.Figure(
        go.Bar(
            x=[row.get(field) for row in rows],
            y=[str(row.get("name") or "") for row in rows],
            orientation="h",
            marker_color=colour,
            hovertemplate=f"%{{y}}: %{{x}} {label}<extra></extra>",
        )
    )
    figure.update_layout(
        title=title,
        height=max(280, 60 * len(rows) + 80),
        margin=dict(l=16, r=16, t=52, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#F3EDE4",
        xaxis_title=label,
        yaxis=dict(autorange="reversed"),
    )
    return figure


def _ordered(rows: list[dict[str, Any]], key: str, order: list[str]) -> list[dict[str, Any]]:
    rank = {value: index for index, value in enumerate(order)}
    return sorted(rows, key=lambda row: (rank.get(row[key], len(order)), str(row[key])))


# ---------------------------------------------------------------- player
def _player_metrics(stats: dict[str, Any], control: dict[str, Any] | None, role: str) -> list[tuple[str, str]]:
    if role == "batting":
        return [
            ("Runs", _fmt(stats["runs"])),
            ("Balls", _fmt(stats["balls"])),
            ("Average", _fmt(stats["average"])),
            ("Strike rate", _fmt(stats["strike_rate"])),
            ("Control", _fmt((control or {}).get("control_percentage"), 2, "%")),
            ("Dot balls", _fmt(_pct(stats["dot_balls"], stats["balls"]), 2, "%")),
            ("Boundaries", _fmt(_pct(stats["fours"] + stats["sixes"], stats["balls"]), 2, "%")),
        ]
    return [
        ("Wickets", _fmt(stats["wickets"])),
        ("Balls", _fmt(stats["balls"])),
        ("Average", _fmt(stats["average"])),
        ("Economy", _fmt(stats["economy"])),
        ("Strike rate", _fmt(stats["strike_rate"])),
        ("Dot balls", _fmt(_pct(stats["dot_balls"], stats["balls"]), 2, "%")),
        ("Boundaries conceded", _fmt(_pct(stats["boundaries"], stats["balls"]), 2, "%")),
    ]


def _phase_rows(service: MultiFormatService, player_id: str, role: str, scope: ExplorerScope) -> list[dict[str, Any]]:
    rows = []
    for label, fields in (phase_options(scope.format) or {}).items():
        if not fields:
            continue
        stats = _first(service.player_stats(player_id, role, scope.filter(**fields)))
        if not stats:
            continue
        if role == "batting":
            control = service.batting_control(player_id, scope.filter(**fields))
            rows.append({
                "split": label, "balls": stats["balls"], "runs": stats["runs"],
                "dismissals": stats["dismissals"], "average": stats["average"],
                "strike_rate": stats["strike_rate"],
                "control_percentage": control["control_percentage"],
                "dot_percentage": _pct(stats["dot_balls"], stats["balls"]),
                "boundary_percentage": _pct(stats["fours"] + stats["sixes"], stats["balls"]),
            })
        else:
            rows.append({
                "split": label, "balls": stats["balls"], "runs_conceded": stats["runs_conceded"],
                "wickets": stats["wickets"], "economy": stats["economy"], "average": stats["average"],
                "strike_rate": stats["strike_rate"],
                "dot_percentage": _pct(stats["dot_balls"], stats["balls"]),
            })
    return rows


def render_player_view(service: MultiFormatService, db: str, scope: ExplorerScope) -> None:
    _header(
        "CricAtlas player explorer",
        "Know the player.<br>Inspect every zone.",
        f"Search a {escape(scope.label)} player and explore career output, phase performance, "
        "line and length scoring and recorded shot evidence.",
    )
    role = st.radio("Role", ["batting", "bowling"], format_func=str.title, horizontal=True, key="mf-player-role")
    control_left, control_right = st.columns([2, 1])
    with control_left:
        player_id = _player_picker(db, "Player", role, scope.filter(), f"mf-player-{role}-{scope.key}",
                                   "Type a player name…")
    with control_right:
        phase_label, phase_fields = _phase_select(scope, "Phase filter", f"mf-player-phase-{scope.format}")
    _phase_note(scope)
    if not player_id:
        st.info("Choose a player above. The selector supports type-to-search.")
        return
    flt = scope.filter(**phase_fields)
    name = _name(service, player_id)
    stats = _first(service.player_stats(player_id, role, flt))
    if not stats:
        st.warning(f"No {role} evidence was found for {name} in {scope.label} ({phase_label.lower()}).")
        return
    control = service.batting_control(player_id, flt) if role == "batting" else None

    st.subheader(f"{name} · {phase_label}")
    columns = [*st.columns(4), *st.columns(4)[:3]]
    for column, (label, value) in zip(columns, _player_metrics(stats, control, role), strict=True):
        column.metric(label, value)
    st.caption(
        f"{scope.label} · {stats['matches']:,} matches · ball-by-ball from "
        f"{stats['first_match']:%d %b %Y} to {stats['last_match']:%d %b %Y}."
    )
    if control is not None:
        if control["control_percentage"] is None:
            st.caption(f"Control: {NOT_AVAILABLE} — no in-control judgement is recorded for these balls.")
        elif control["recorded_balls"] < control["balls"]:
            st.caption(
                f"Control is recorded for {control['recorded_balls']:,} of {control['balls']:,} balls faced "
                "and describes only those balls."
            )

    section = st.segmented_control(
        "Analysis view",
        ["Overview", "Phase analysis", "Line & length", "Wagon wheel & shots"],
        default="Overview", label_visibility="collapsed", width="stretch", key="mf-player-section",
    ) or "Overview"

    if section == "Overview":
        trend = service.player_year_trend(player_id, role, flt)
        if trend:
            st.plotly_chart(build_trend_figure(trend, role), width="stretch", config={"displayModeBar": False})
            st.dataframe(trend, width="stretch", hide_index=True)
        else:
            st.info("No year-level trend is available for this player.")

    elif section == "Phase analysis":
        if phase_options(scope.format) is None:
            not_available("Phase analysis", scope, "Phases are defined for limited-overs cricket only.")
            return
        rows = _phase_rows(service, player_id, role, scope)
        if not rows:
            st.info("No phase split is available for this player.")
        elif role == "batting":
            st.plotly_chart(build_phase_figure(rows), width="stretch", config={"displayModeBar": False})
            if all(row["control_percentage"] is None for row in rows):
                st.caption(f"Control %: {NOT_AVAILABLE} — no in-control judgement is recorded for these balls.")
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.plotly_chart(
                build_bar_figure([{**r, "name": r["split"]} for r in rows], "economy", "Economy", "Economy by phase"),
                width="stretch", config={"displayModeBar": False},
            )
            st.dataframe(rows, width="stretch", hide_index=True)

    elif section == "Line & length":
        _render_line_length(service, player_id, role, flt, scope)

    else:
        wagon_column, shot_column = st.columns([1, 1])
        with wagon_column:
            not_available("The wagon wheel", scope, "Wagon-wheel zones are recorded only in the men's ODI data.")
        with shot_column:
            if role != "batting":
                st.info("Recorded shots describe batters. Choose the batting role to see them.")
            else:
                shots = service.shot_profile(player_id, flt)
                if shots["metrics"]:
                    st.plotly_chart(build_shot_figure(shots), width="stretch", config={"displayModeBar": False})
                    _coverage_caption("Shot-type coverage", shots)
                else:
                    not_available("Shot evidence", scope, "No shot labels are recorded for this player and selection.")


def _render_line_length(service: MultiFormatService, player_id: str, role: str, flt: DeliveryFilter, scope: ExplorerScope) -> None:
    pitch = service.pitch_cells(player_id, role, flt)
    if not pitch["cells"]:
        not_available("Line and length", scope, "No line or length is recorded for this player in this selection.")
        _limitations(service, scope)
        return
    if role == "batting":
        colour_metric = st.radio(
            "Colour cells by", ["Strike rate", "Batting average"], horizontal=True, key="mf-colour",
            help=(
                "Strike rate compares each zone with the player's weighted line/length baseline. "
                "Batting average compares runs per dismissal with the player's weighted baseline."
            ),
        )
        st.plotly_chart(
            build_pitch_heatmap(pitch, colour_metric=colour_metric),
            width="stretch",
            config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False},
        )
        st.caption(
            "Cells show strike rate (SR), batting average (Avg) and dismissals (W). Red is below the "
            "player's weighted baseline, yellow is around it and green is above it. Cells below 20 balls "
            "are light grey to avoid over-interpreting small samples."
        )
    else:
        st.markdown("#### Line × length cells (runs off the bat conceded and wickets)")
        st.dataframe(pitch["cells"], width="stretch", hide_index=True)
    _coverage_caption("Line/length coverage", pitch)
    columns = st.columns(2)
    for column, dimension, order in ((columns[0], "line", LINE_ORDER), (columns[1], "length", LENGTH_ORDER)):
        result = service.line_length(player_id, role, dimension, flt)
        with column:
            st.markdown(f"#### By {dimension}")
            if result["rows"]:
                rows = [{**row, dimension: _display_label(row[dimension])} for row in _ordered(result["rows"], dimension, order)]
                st.dataframe(rows, width="stretch", hide_index=True)
            else:
                st.caption(f"{dimension.capitalize()}: {NOT_AVAILABLE} in this selection.")
            st.caption(result["note"])
    with st.expander("All line × length cells"):
        st.dataframe(pitch["cells"], width="stretch", hide_index=True)
    _limitations(service, scope)


# ---------------------------------------------------------------- compare
def _compare_rows(service: MultiFormatService, ids: list[str], mode: str, flt: DeliveryFilter) -> list[dict[str, Any]]:
    rows = []
    for player_id in ids:
        stats = _first(service.player_stats(player_id, mode, flt))
        if not stats:
            continue
        name = _name(service, player_id)
        if mode == "batting":
            control = service.batting_control(player_id, flt)
            rows.append({
                "name": name, "Player": name, "Runs": stats["runs"], "Balls": stats["balls"],
                "Dismissals": stats["dismissals"], "Batting average": stats["average"],
                "Matches": stats["matches"], "Dot %": _pct(stats["dot_balls"], stats["balls"]),
                "Strike Rate": stats["strike_rate"],
                "Boundary %": _pct(stats["fours"] + stats["sixes"], stats["balls"]),
                "Control %": control["control_percentage"],
            })
        else:
            rows.append({
                "name": name, "Player": name, "Legal balls": stats["balls"], "Matches": stats["matches"],
                "Runs conceded": stats["runs_conceded"], "Wickets": stats["wickets"],
                "Bowling average": stats["average"], "Economy": stats["economy"],
                "Bowling strike rate": stats["strike_rate"], "Dot %": _pct(stats["dot_balls"], stats["balls"]),
                "Boundary % conceded": _pct(stats["boundaries"], stats["balls"]),
            })
    return rows


COMPARE_CHART_METRICS = {
    "batting": {"Strike Rate": "Batting strike rate", "Batting average": "Batting average", "Runs": "Runs",
                "Boundary %": "Boundary %", "Dot %": "Dot %"},
    "bowling": {"Economy": "Economy", "Bowling average": "Bowling average", "Bowling strike rate": "Bowling strike rate",
                "Wickets": "Wickets", "Dot %": "Dot %"},
}


def render_compare_view(service: MultiFormatService, db: str, scope: ExplorerScope) -> None:
    _header(
        "CricAtlas compare explorer",
        "Compare players.<br>Inspect the evidence.",
        f"Side-by-side {escape(scope.label)} batting and bowling evidence pulled from the same "
        "database-backed service used by the workbench.",
    )
    mode = st.radio("Mode", ["batting", "bowling"], format_func=str.title, horizontal=True, key="mf-compare-mode")
    columns = st.columns(2)
    with columns[0]:
        first = _player_picker(db, "Player one", mode, scope.filter(), f"mf-compare-one-{mode}-{scope.key}", "Type a player name…")
    with columns[1]:
        second = _player_picker(db, "Player two", mode, scope.filter(), f"mf-compare-two-{mode}-{scope.key}", "Type a player name…")
    venues = _venue_groups(db, scope.filter())
    metrics = COMPARE_CHART_METRICS[mode]
    with st.form("mf-compare-context", border=False):
        with st.expander("Comparison context", expanded=True):
            phase_column, venue_column, metric_column = st.columns(3)
            with phase_column:
                phase_label, phase_fields = _phase_select(scope, "Phase", f"mf-compare-phase-{scope.format}")
            with venue_column:
                venue = st.selectbox("Venue", ["", *venues], format_func=lambda v: v or "All venues",
                                     key=f"mf-compare-venue-{scope.key}")
            with metric_column:
                metric = st.selectbox("Chart metric", list(metrics), format_func=metrics.get, key=f"mf-compare-metric-{mode}")
            start_column, end_column = st.columns(2)
            with start_column:
                year_start = st.number_input("From year", min_value=1800, max_value=2200, value=None, step=1,
                                             placeholder="All years", key="mf-compare-year-start")
            with end_column:
                year_end = st.number_input("Through year", min_value=1800, max_value=2200, value=None, step=1,
                                           placeholder="All years", key="mf-compare-year-end")
            st.caption("Leave both years blank for all years. Enter one year for that year, or both for an inclusive range. "
                       "Changes apply when you press Compare players.")
            _phase_note(scope)
        submitted = st.form_submit_button(
            "Compare players", disabled=not first or not second or first == second,
            type="primary", width="stretch",
        )
    years = _year_range(year_start, year_end)
    signature = (scope.key, mode, first, second, phase_label, venue, metric, years["year_from"], years["year_to"])
    if submitted:
        venue_names = "|".join(venues[venue]["names"]) if venue else None
        flt = scope.filter(**phase_fields, venue=venue_names, **years)
        st.session_state["mf-compare-rows"] = _compare_rows(service, [first, second], mode, flt)
        st.session_state["mf-compare-request"] = signature
    rows = st.session_state.get("mf-compare-rows")
    if not isinstance(rows, list) or st.session_state.get("mf-compare-request") != signature:
        if first and second and first == second:
            st.info("Choose two different players to compare.")
        else:
            st.info("Choose two players, then press Compare players.")
        return
    st.markdown(f"## {_name(service, first)} vs {_name(service, second)}")
    if len(rows) < 2:
        st.warning(f"Both players need {mode} evidence in {scope.label} for these filters.")
        return
    year_text = f"{years['year_from']}–{years['year_to']}" if years["year_from"] else "All years"
    st.caption(f"Active filters: {mode.title()}; {scope.label}; {phase_label}; {year_text}; {venue or 'All venues'}.")
    st.caption("Descriptive comparison: sample size is shown as context, not as a ranking.")
    ball_column = "Balls" if mode == "batting" else "Legal balls"
    for row in rows:
        if (row[ball_column] or 0) < 24:
            st.warning(f"{row['Player']}: small sample (fewer than 24 balls).")
    table_rows = [{k: v for k, v in row.items() if k != "name"} for row in rows]
    rate_columns = (
        ["Batting average", "Strike Rate", "Control %", "Dot %", "Boundary %"]
        if mode == "batting"
        else ["Bowling average", "Economy", "Bowling strike rate", "Dot %", "Boundary % conceded"]
    )
    st.markdown("### Comparison Table")
    render_numeric_table(table_rows, rate_columns)
    if mode == "batting" and all(row["Control %"] is None for row in rows):
        st.caption(f"Control %: {NOT_AVAILABLE} — no in-control judgement is recorded for these balls.")
    st.markdown(f"### {metrics[metric]} comparison")
    st.plotly_chart(
        build_bar_figure(rows, metric, metrics[metric], f"{metrics[metric]} comparison"),
        width="stretch", config={"displayModeBar": False},
    )


# ---------------------------------------------------------------- matchups
def load_matchup(service: MultiFormatService, batter: str, bowler: str, flt: DeliveryFilter) -> dict[str, Any]:
    result = service.matchup(batter, bowler, flt)
    stats = _first(result["by_format"])
    names = {pid: _name(service, pid) for pid in (batter, bowler)}
    page: dict[str, Any] = {"title": f"{names[batter]} vs {names[bowler]}", "supported": bool(stats and stats["balls"])}
    if not page["supported"]:
        return page
    control = service.batting_control(batter, flt, bowler_id=bowler)
    baseline = _first(service.player_stats(batter, "batting", flt))
    runs, balls, outs = stats["runs"], stats["balls"], stats["dismissals"]
    page.update({
        "summary": (
            f"{names[batter]} scored {runs:,} runs from {balls:,} balls against {names[bowler]}, "
            f"dismissed {outs} time{'s' if outs != 1 else ''} ({stats['bowler_wickets']} credited to the bowler)."
        ),
        "metrics": {
            "Runs": runs,
            "Balls": balls,
            "Dismissals": outs,
            "Batting Avg": round(runs / outs, 2) if outs else None,
            "Batting SR": stats["strike_rate"],
            "Dot Ball %": _pct(stats["dot_balls"], balls),
            "Boundary %": _pct(stats["fours"] + stats["sixes"], balls),
            "False Shot %": control["false_shot_percentage"],
        },
        "baseline_strike_rate": baseline["strike_rate"] if baseline else None,
        "pitch": service.matchup_pitch(batter, bowler, flt),
        "dismissal_kinds": result["dismissal_kinds"],
        "row": {"Batter": names[batter], "Bowler": names[bowler], **stats},
    })
    return page


def render_matchup_view(service: MultiFormatService, db: str, scope: ExplorerScope) -> None:
    _header(
        "CricAtlas matchups",
        "Batter versus bowler.<br>Inspect every delivery.",
        f"Choose a {escape(scope.label)} batter and bowler, then narrow the question by phase, year or venue.",
    )
    player_columns = st.columns(2)
    with player_columns[0]:
        batter = _player_picker(db, "Batter", "batting", scope.filter(), f"mf-matchup-batter-{scope.key}", "Type a batter name…")
    with player_columns[1]:
        bowler = _player_picker(db, "Bowler", "bowling", scope.filter(), f"mf-matchup-bowler-{scope.key}", "Type a bowler name…")
    venues = _venue_groups(db, scope.filter())
    filter_columns = st.columns(3)
    with filter_columns[0]:
        phase_label, phase_fields = _phase_select(scope, "Phase", f"mf-matchup-phase-{scope.format}")
    with filter_columns[1]:
        year = st.number_input("Year", min_value=1971, max_value=date.today().year, value=None,
                               placeholder="All years", step=1, key="mf-matchup-year")
    with filter_columns[2]:
        venue_label = st.selectbox("Venue", ["All venues", *venues], key=f"mf-matchup-venue-{scope.key}")
    _phase_note(scope)
    request = (scope.key, batter, bowler, phase_label, int(year) if year is not None else None, venue_label)
    if st.button("Show matchup", disabled=not batter or not bowler, type="primary", width="stretch"):
        venue = None if venue_label == "All venues" else "|".join(venues[venue_label]["names"])
        flt = scope.filter(**phase_fields, venue=venue, years=(int(year),) if year is not None else ())
        st.session_state["mf-matchup-page"] = load_matchup(service, batter, bowler, flt)
        st.session_state["mf-matchup-request"] = request
    page = st.session_state.get("mf-matchup-page")
    if not isinstance(page, dict) or st.session_state.get("mf-matchup-request") != request:
        st.info("Choose both players, then press Show matchup. Each player selector supports type-to-search.")
        return
    st.markdown(f"## {page['title']}")
    if not page["supported"]:
        st.warning(
            f"No recorded {scope.label} balls were found between these players for these filters. "
            "Try another player or broaden the filters."
        )
        return
    st.markdown(page["summary"])
    metric_columns = [*st.columns(4), *st.columns(4)]
    for column, (label, value) in zip(metric_columns, page["metrics"].items(), strict=True):
        column.metric(label, "—" if value is None else f"{int(value):,}" if label in {"Runs", "Balls", "Dismissals"} else f"{float(value):.2f}")
    if page["metrics"]["False Shot %"] is None:
        st.caption(f"False Shot %: {NOT_AVAILABLE} — no in-control judgement is recorded for these balls.")

    matchup_sr, baseline_sr = page["metrics"]["Batting SR"], page["baseline_strike_rate"]
    if isinstance(matchup_sr, int | float) and isinstance(baseline_sr, int | float):
        difference = float(matchup_sr) - float(baseline_sr)
        batter_name, bowler_name = page["title"].split(" vs ", 1)
        st.markdown(
            f"""
<div style="border:1px solid rgba(239,225,207,.16);border-radius:18px;padding:18px 20px;margin:12px 0;background:rgba(9,14,18,.62)">
  <span style="color:#9eabb5;font-size:.76rem;text-transform:uppercase;letter-spacing:.12em">Compared with the batter's normal {escape(scope.label)} rate</span>
  <h3 style="margin:.45rem 0;color:#f8f6f0">{float(matchup_sr):.2f} vs {float(baseline_sr):.2f}</h3>
  <p style="margin:0;color:#9eabb5">Against {escape(bowler_name)}, {escape(batter_name)}'s strike rate is {abs(difference):.2f} points {'higher' if difference >= 0 else 'lower'} than the matching overall baseline.</p>
</div>
""",
            unsafe_allow_html=True,
        )
    balls = page["metrics"]["Balls"]
    if balls < 12:
        st.caption(f"Small sample: only {int(balls)} recorded balls, so treat these numbers as descriptive.")

    pitch = page["pitch"]
    if pitch.get("cells"):
        st.markdown("### Matchup pitch map")
        pitch_view = st.segmented_control(
            "Pitch view", ["All", "SR", "Avg", "W", "4s", "6s"], default="All",
            label_visibility="collapsed", key="mf-matchup-pitch-metric",
        )
        st.html(build_matchup_pitch_html(pitch, pitch_view=str(pitch_view or "All")))
        st.caption(
            "Cells show the observed matchup record on balls with both line and length recorded. Average is runs "
            "per dismissal; zones without a dismissal show n/a. Empty zones mean no recorded deliveries."
        )
    else:
        not_available("The matchup pitch map", scope, "No line and length is recorded for these balls.")
        _limitations(service, scope)
    if page["dismissal_kinds"]:
        st.markdown("#### How the bowler dismissed the batter")
        st.dataframe(page["dismissal_kinds"], width="stretch", hide_index=True)
    with st.expander("Full matchup row"):
        st.dataframe([page["row"]], width="stretch", hide_index=True)


# ---------------------------------------------------------------- venue
VENUE_DEFAULTS = {"sample_unit": "balls", "minimum_sample": 24, "phase": "All phases", "year_start": None, "year_end": None}


def render_venue_view(service: MultiFormatService, db: str, scope: ExplorerScope) -> None:
    _header(
        "CricAtlas venue explorer",
        "Explore a venue.<br>See who succeeds.",
        f"Ground-specific {escape(scope.label)} evidence for venue leaderboards and follow-up exploration.",
    )
    mode = st.radio("Mode", ["bowling", "batting"], format_func=str.title, horizontal=True, key="mf-venue-mode")
    ranks = BOWLING_RANKS if mode == "bowling" else BATTING_RANKS
    sample_units = {"balls": "Legal balls bowled" if mode == "bowling" else "Balls faced", "matches": "Distinct matches"}
    venues = _venue_groups(db, scope.filter())
    venue = st.selectbox(
        "Venue", list(venues), index=None, placeholder="Type a venue name…",
        format_func=lambda v: f"{v} · {venues[v]['matches']} matches", key=f"mf-venue-name-{scope.key}",
    )
    defaults = {**VENUE_DEFAULTS, "metric": next(iter(ranks))}
    active = {**defaults, **st.session_state.get(f"mf-venue-filter-{mode}", {})}
    version = st.session_state.get("mf-venue-version", 0)
    with st.form(key=f"mf-venue-controls-{version}", border=False):
        with st.expander("Filter bowlers" if mode == "bowling" else "Filter batters", expanded=False):
            sample_column, minimum_column, metric_column, phase_column = st.columns(4)
            with sample_column:
                sample_unit = st.selectbox("Filter by", list(sample_units), index=list(sample_units).index(active["sample_unit"]),
                                           format_func=sample_units.get, key=f"mf-venue-unit-{version}")
            with minimum_column:
                minimum = st.number_input("Minimum number (0 = no minimum)", min_value=0, max_value=1_000_000,
                                          value=active["minimum_sample"], step=1, key=f"mf-venue-minimum-{version}")
            with metric_column:
                metric = st.selectbox("Rank and chart by", list(ranks), index=list(ranks).index(active["metric"]),
                                      format_func=lambda key: ranks[key][0], key=f"mf-venue-metric-{mode}-{version}")
            with phase_column:
                phase_label, _ = _phase_select(scope, "Phase", f"mf-venue-phase-{scope.format}-{version}")
            start_column, end_column = st.columns(2)
            with start_column:
                year_start = st.number_input("From year", min_value=1800, max_value=2200, value=active["year_start"],
                                             step=1, placeholder="All years", key=f"mf-venue-year-start-{version}")
            with end_column:
                year_end = st.number_input("Through year", min_value=1800, max_value=2200, value=active["year_end"],
                                           step=1, placeholder="All years", key=f"mf-venue-year-end-{version}")
            st.caption("Leave both years blank for all years. Enter one year for that year, or both for an inclusive range.")
            _phase_note(scope)
            apply, reset = st.columns(2)
            apply_submitted = apply.form_submit_button("Apply filter", disabled=not venue)
            reset_submitted = reset.form_submit_button("Reset filter", disabled=not venue)
        submitted = st.form_submit_button("Explore venue", disabled=not venue, type="primary", width="stretch")
    if submitted or apply_submitted or reset_submitted:
        selected = dict(defaults) if reset_submitted else {
            "sample_unit": sample_unit, "minimum_sample": int(minimum), "metric": metric,
            "phase": phase_label, "year_start": year_start, "year_end": year_end,
        }
        st.session_state[f"mf-venue-filter-{mode}"] = selected
        st.session_state["mf-venue-request"] = (scope.key, venue)
        st.session_state["mf-venue-version"] = version + 1
        st.rerun()
    if st.session_state.get("mf-venue-request") != (scope.key, venue) or not venue:
        st.info("Choose a venue, set any filters, then press Explore venue.")
        return

    phase_fields = (phase_options(scope.format) or {}).get(active["phase"], {})
    flt = scope.filter(**phase_fields, **_year_range(active["year_start"], active["year_end"]))
    profile = service.venue_profile(
        "|".join(venues[venue]["names"]), mode, active["metric"], flt,
        min_balls=active["minimum_sample"] if active["sample_unit"] == "balls" else 0,
        min_matches=active["minimum_sample"] if active["sample_unit"] == "matches" else None,
        limit=10,
    )
    st.markdown(f"## {venue}")
    if len(venues[venue]["names"]) > 1:
        st.caption("Includes the ground's recorded names: " + "; ".join(venues[venue]["names"]) + ".")
    summary = profile["summary"]
    for column, (label, value) in zip(st.columns(5), [
        ("Matches", _fmt(summary["matches"])),
        ("Avg 1st innings", _fmt(summary["avg_first_innings_runs"], 1)),
        ("Avg 2nd innings", _fmt(summary["avg_second_innings_runs"], 1)),
        ("Run rate", _fmt(summary["run_rate"])),
        ("Runs per wicket", _fmt(summary["runs_per_wicket"])),
    ], strict=True):
        column.metric(label, value)
    unit_label = sample_units[active["sample_unit"]]
    sample_label = (
        f"at least {active['minimum_sample']} {unit_label[0].lower() + unit_label[1:]}"
        if active["minimum_sample"] else "no minimum sample"
    )
    year_text = (
        f"{_year_range(active['year_start'], active['year_end'])['year_from']}–"
        f"{_year_range(active['year_start'], active['year_end'])['year_to']}"
        if active["year_start"] or active["year_end"] else "All years"
    )
    st.caption(
        f"Filter{' (default)' if active == defaults else ''}: {sample_label}. {active['phase']}; {year_text}; "
        f"top 10 by {ranks[active['metric']][0]}. Eligibility applies after phase/year filters and before top 10."
    )
    leaders = profile["leaders"]
    if not leaders:
        st.error("No players qualify for the selected filters and metric.")
        return
    label, field = ranks[active["metric"]]
    st.markdown("### Top Wicket Takers" if active["metric"] == "wickets" else f"### {label} leaders")
    st.plotly_chart(build_bar_figure(leaders[:6], field, label, f"{label} at venue", GREEN),
                    width="stretch", config={"displayModeBar": False})
    if mode == "bowling":
        table = [{"Bowler": r["name"], "Deliveries": r["balls"], "Matches": r["matches"], "Runs": r["runs_conceded"],
                  "Wickets": r["wickets"], "Economy": r["economy"], "Bowling average": r["average"],
                  "Bowling strike rate": r["strike_rate"], "Dot %": r["dot_ball_pct"],
                  "Boundary % conceded": _pct(r["boundaries"], r["balls"])} for r in leaders]
        rate_columns = ["Bowling average", "Economy", "Bowling strike rate", "Dot %", "Boundary % conceded"]
    else:
        table = [{"Batter": r["name"], "Balls faced": r["balls"], "Matches": r["matches"], "Runs": r["runs"],
                  "Dismissals": r["dismissals"], "Batting average": r["average"], "Strike Rate": r["strike_rate"],
                  "Dot %": r["dot_ball_pct"], "Boundary %": _pct(r["fours"] + r["sixes"], r["balls"])} for r in leaders]
        rate_columns = ["Batting average", "Strike Rate", "Dot %", "Boundary %"]
    st.markdown("### Bowling Leaderboard" if mode == "bowling" else "### Batting Leaderboard")
    render_numeric_table(table, rate_columns)
    if mode == "batting":
        st.caption(f"Control %: {NOT_AVAILABLE} in venue leaderboards outside men's ODIs.")


__all__ = [
    "EXPLORER_VIEWS",
    "ExplorerScope",
    "default_db_path",
    "phase_options",
    "render_other_format_view",
    "render_scope_selector",
]
