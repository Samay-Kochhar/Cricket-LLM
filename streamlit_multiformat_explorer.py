"""All-formats explorer: Tests, ODIs, T20Is, IPL and other leagues, The Hundred, domestic cricket.

Reads data/cricket_all.duckdb through MultiFormatService. The ODI explorers are
unchanged; this page adds the other formats with the same look. Every line and
length view states how many of the selected balls carry line/length and the
stored limitation for the format, because coverage differs by format and year.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from backend.app.multiformat.service import DeliveryFilter, MultiFormatService, player_options
from streamlit_player_explorer import LENGTH_ORDER, LINE_ORDER, _base_layout, _display_label, build_pitch_heatmap


ORANGE = "#F28F3B"
GREEN = "#7CE2B4"
ALL_COMPETITIONS = "All competitions"
VIEWS = ["Player", "Compare", "Matchups", "Venue"]
GENDERS = {"male": "Men", "female": "Women"}
BATTING_METRICS = {"runs": "Runs", "strike_rate": "Strike rate", "average": "Average"}
BOWLING_METRICS = {"wickets": "Wickets", "economy": "Economy", "strike_rate": "Strike rate", "average": "Average"}


def default_db_path(root: Path) -> Path:
    import os

    configured = os.getenv("MULTIFORMAT_DUCKDB_PATH")
    return Path(configured) if configured else root / "data" / "cricket_all.duckdb"


@st.cache_data(show_spinner=False, ttl=3600)
def _coverage(db: str) -> dict[str, Any]:
    return MultiFormatService(Path(db)).coverage()


@st.cache_data(show_spinner=False, ttl=3600)
def _competitions(db: str, format: str, gender: str) -> list[dict[str, Any]]:
    return MultiFormatService(Path(db)).competitions(format=format, gender=gender)


@st.cache_data(show_spinner=False, ttl=3600)
def _players(db: str, role: str, flt: DeliveryFilter) -> list[dict[str, Any]]:
    return player_options(MultiFormatService(Path(db)), role, flt)


@st.cache_data(show_spinner=False, ttl=3600)
def _venues(db: str, flt: DeliveryFilter) -> list[dict[str, Any]]:
    return MultiFormatService(Path(db)).venues(flt)


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value:.{digits}f}{suffix}"


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


def build_bar_figure(rows: list[dict[str, Any]], field: str, label: str, title: str) -> go.Figure:
    figure = go.Figure(
        go.Bar(
            x=[row.get(field) for row in rows],
            y=[str(row.get("name") or "") for row in rows],
            orientation="h",
            marker_color=GREEN,
            hovertemplate=f"%{{y}}: %{{x}} {label}<extra></extra>",
        )
    )
    figure.update_layout(title=title, xaxis_title=label, yaxis=dict(autorange="reversed"))
    return _base_layout(figure, height=max(320, 44 * len(rows) + 100))


def _ordered(rows: list[dict[str, Any]], key: str, order: list[str]) -> list[dict[str, Any]]:
    rank = {value: index for index, value in enumerate(order)}
    return sorted(rows, key=lambda row: (rank.get(row[key], len(order)), str(row[key])))


def _role_metrics(stats: dict[str, Any], role: str) -> list[tuple[str, str]]:
    if role == "batting":
        return [
            ("Matches", _fmt(stats["matches"])),
            ("Runs", _fmt(stats["runs"])),
            ("Balls", _fmt(stats["balls"])),
            ("Average", _fmt(stats["average"])),
            ("Strike rate", _fmt(stats["strike_rate"])),
            ("Dot balls", _fmt(stats["dot_ball_pct"], 1, "%")),
            ("4s / 6s", f"{stats['fours']:,} / {stats['sixes']:,}"),
        ]
    return [
        ("Matches", _fmt(stats["matches"])),
        ("Wickets", _fmt(stats["wickets"])),
        ("Balls", _fmt(stats["balls"])),
        ("Average", _fmt(stats["average"])),
        ("Economy", _fmt(stats["economy"])),
        ("Strike rate", _fmt(stats["strike_rate"])),
        ("Dot balls", _fmt(stats["dot_ball_pct"], 1, "%")),
    ]


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The filter always pins format and gender, so stats come back as at most one row."""
    return rows[0] if rows else None


def _player_picker(db: str, label: str, role: str, flt: DeliveryFilter, key: str) -> str | None:
    options = _players(db, role, flt)
    names = {row["player_id"]: f"{row['name']} · {row['matches']} matches" for row in options}
    return st.selectbox(
        label,
        options=list(names),
        index=None,
        format_func=names.get,
        placeholder="Type a player name…",
        key=key,
    )


def _limitations(service: MultiFormatService, flt: DeliveryFilter) -> None:
    for row in service.limitations(DeliveryFilter(format=flt.format, gender=flt.gender)):
        st.caption(f"Limitation: {row['statement']}")


def _render_line_length(service: MultiFormatService, player_id: str, role: str, flt: DeliveryFilter) -> None:
    pitch = service.pitch_cells(player_id, role, flt)
    if pitch["cells"] and role == "batting":
        colour_metric = st.radio("Colour cells by", ["Strike rate", "Batting average"], horizontal=True, key="mf-colour")
        st.plotly_chart(
            build_pitch_heatmap(pitch, colour_metric=colour_metric),
            width="stretch",
            config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False},
        )
        st.caption(
            "Cells show strike rate (SR), batting average (Avg) and dismissals (W) against the player's "
            "weighted baseline. Cells below 20 balls are light grey."
        )
    elif pitch["cells"]:
        st.markdown("#### Line × length cells")
        st.dataframe(pitch["cells"], width="stretch", hide_index=True)

    any_rows = False
    columns = st.columns(2)
    for column, dimension, order in ((columns[0], "line", LINE_ORDER), (columns[1], "length", LENGTH_ORDER)):
        result = service.line_length(player_id, role, dimension, flt)
        with column:
            st.markdown(f"#### By {dimension}")
            if result["rows"]:
                any_rows = True
                rows = [{**row, dimension: _display_label(row[dimension])} for row in _ordered(result["rows"], dimension, order)]
                st.dataframe(rows, width="stretch", hide_index=True)
            st.caption(result["note"])
    if not any_rows:
        st.info("No line or length is recorded for this player in this selection.")
    _limitations(service, flt)


def render_player_view(service: MultiFormatService, db: str, flt: DeliveryFilter, scope: str) -> None:
    role = st.radio("Role", ["batting", "bowling"], format_func=str.title, horizontal=True, key="mf-player-role")
    player_id = _player_picker(db, "Player", role, flt, "mf-player")
    if not player_id:
        st.info("Choose a player above. The selector supports type-to-search.")
        return
    player = service.player(player_id) or {"name": player_id}
    stats = _first(service.player_stats(player_id, role, flt))
    if not stats:
        st.warning(f"No {role} evidence for {player['name']} in {scope}.")
        return
    st.subheader(f"{player['name']} · {scope}")
    details = [player.get("batting_hand"), player.get("bowling_style_group")]
    if any(details):
        st.caption(" · ".join(str(item) for item in details if item))
    top, bottom = st.columns(4), st.columns(4)
    for column, (label, value) in zip([*top, *bottom[:3]], _role_metrics(stats, role), strict=True):
        column.metric(label, value)
    st.caption(f"Ball-by-ball from {stats['first_match']:%d %b %Y} to {stats['last_match']:%d %b %Y}.")

    section = st.segmented_control(
        "Analysis view", ["Overview", "Line & length"], default="Overview",
        label_visibility="collapsed", width="stretch", key="mf-player-section",
    ) or "Overview"
    if section == "Overview":
        trend = service.player_year_trend(player_id, role, flt)
        st.plotly_chart(build_trend_figure(trend, role), width="stretch", config={"displayModeBar": False})
        st.dataframe(trend, width="stretch", hide_index=True)
    else:
        _render_line_length(service, player_id, role, flt)


def render_compare_view(service: MultiFormatService, db: str, flt: DeliveryFilter, scope: str) -> None:
    role = st.radio("Role", ["batting", "bowling"], format_func=str.title, horizontal=True, key="mf-compare-role")
    left, right = st.columns(2)
    with left:
        first = _player_picker(db, "First player", role, flt, "mf-compare-a")
    with right:
        second = _player_picker(db, "Second player", role, flt, "mf-compare-b")
    chosen = [pid for pid in (first, second) if pid]
    if len(chosen) < 2:
        st.info("Choose two players to compare.")
        return
    rows = []
    for player_id in chosen:
        stats = _first(service.player_stats(player_id, role, flt))
        if stats:
            rows.append({"name": (service.player(player_id) or {}).get("name", player_id), **stats})
    if len(rows) < 2:
        st.warning(f"Both players need {role} evidence in {scope}.")
        return
    metrics = BATTING_METRICS if role == "batting" else BOWLING_METRICS
    metric = st.selectbox("Chart metric", list(metrics), format_func=metrics.get, key="mf-compare-metric")
    st.plotly_chart(
        build_bar_figure(rows, metric, metrics[metric], f"{metrics[metric]} comparison · {scope}"),
        width="stretch", config={"displayModeBar": False},
    )
    st.dataframe(rows, width="stretch", hide_index=True)


def render_matchup_view(service: MultiFormatService, db: str, flt: DeliveryFilter, scope: str) -> None:
    left, right = st.columns(2)
    with left:
        batter = _player_picker(db, "Batter", "batting", flt, "mf-matchup-bat")
    with right:
        bowler = _player_picker(db, "Bowler", "bowling", flt, "mf-matchup-bowl")
    if not (batter and bowler):
        st.info("Choose a batter and a bowler.")
        return
    result = service.matchup(batter, bowler, flt)
    names = {pid: (service.player(pid) or {}).get("name", pid) for pid in (batter, bowler)}
    stats = _first(result["by_format"])
    if not stats:
        st.warning(f"{names[batter]} has not faced {names[bowler]} in {scope}.")
        return
    st.subheader(f"{names[batter]} v {names[bowler]} · {scope}")
    columns = st.columns(6)
    for column, (label, value) in zip(columns, [
        ("Balls", _fmt(stats["balls"])),
        ("Runs", _fmt(stats["runs"])),
        ("Strike rate", _fmt(stats["strike_rate"])),
        ("Dismissed by bowler", _fmt(stats["bowler_wickets"])),
        ("Dot balls", _fmt(stats["dot_ball_pct"], 1, "%")),
        ("4s / 6s", f"{stats['fours']:,} / {stats['sixes']:,}"),
    ], strict=True):
        column.metric(label, value)
    st.caption(f"Meetings from {stats['first_match']:%d %b %Y} to {stats['last_match']:%d %b %Y}.")
    if result["dismissal_kinds"]:
        st.markdown("#### How the bowler dismissed the batter")
        st.dataframe(result["dismissal_kinds"], width="stretch", hide_index=True)


def render_venue_view(service: MultiFormatService, db: str, flt: DeliveryFilter, scope: str) -> None:
    venues = {row["venue"]: f"{row['venue']} · {row['matches']} matches" for row in _venues(db, flt)}
    venue = st.selectbox(
        "Venue", list(venues), index=None, format_func=venues.get,
        placeholder="Type a venue name…", key="mf-venue",
    )
    if not venue:
        st.info("Choose a venue above.")
        return
    controls = st.columns([1, 1.4, 1])
    with controls[0]:
        role = st.radio("Mode", ["bowling", "batting"], format_func=str.title, horizontal=True, key="mf-venue-role")
    metrics = BATTING_METRICS if role == "batting" else BOWLING_METRICS
    with controls[1]:
        metric = st.selectbox("Rank by", list(metrics), format_func=metrics.get, key=f"mf-venue-metric-{role}")
    with controls[2]:
        min_balls = st.number_input("Minimum balls", min_value=0, value=60, step=10, key="mf-venue-min")
    profile = service.venue_profile(venue, role, metric, flt, min_balls=int(min_balls))
    summary = profile["summary"]
    st.subheader(f"{venue} · {scope}")
    columns = st.columns(5)
    for column, (label, value) in zip(columns, [
        ("Matches", _fmt(summary["matches"])),
        ("Avg 1st innings", _fmt(summary["avg_first_innings_runs"], 1)),
        ("Avg 2nd innings", _fmt(summary["avg_second_innings_runs"], 1)),
        ("Run rate", _fmt(summary["run_rate"])),
        ("Runs per wicket", _fmt(summary["runs_per_wicket"])),
    ], strict=True):
        column.metric(label, value)
    leaders = profile["leaders"]
    if not leaders:
        st.info(f"No player reaches {int(min_balls)} balls at this venue in this selection.")
        return
    st.plotly_chart(
        build_bar_figure(leaders[:8], metric, metrics[metric], f"{metrics[metric]} at venue"),
        width="stretch", config={"displayModeBar": False},
    )
    st.dataframe(leaders, width="stretch", hide_index=True)


def render_multiformat_explorer(db_path: Path) -> None:
    st.markdown("<div class='atlas-kicker'>◆ CricAtlas all-formats explorer</div>", unsafe_allow_html=True)
    st.markdown(
        "<h1 class='atlas-title explorer-title'>Every format.<br>Every league.</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='atlas-copy'>Tests, ODIs, T20Is, the IPL, BBL, CPL, The Hundred and domestic cricket, "
        "men's and women's. Line and length appear where a source recorded them, with the coverage stated.</p>",
        unsafe_allow_html=True,
    )
    if not db_path.exists():
        st.warning(
            "The all-formats database has not been built on this machine. "
            "Build it with `python -m ingestion.app.multiformat.build`."
        )
        return
    db = str(db_path)
    service = MultiFormatService(db_path)
    formats = _coverage(db)["formats"]
    format_keys = sorted({row["format"] for row in formats}, key=lambda f: -sum(r["matches"] for r in formats if r["format"] == f))

    controls = st.columns([1.3, 0.8, 1.9])
    with controls[0]:
        fmt = st.selectbox("Format", format_keys, key="mf-format")
    genders = [g for g in GENDERS if any(r["format"] == fmt and r["gender"] == g for r in formats)]
    with controls[1]:
        gender = st.selectbox("Gender", genders, format_func=GENDERS.get, key="mf-gender")
    competitions = _competitions(db, fmt, gender)
    with controls[2]:
        competition = st.selectbox(
            "Competition",
            [ALL_COMPETITIONS, *(row["competition"] for row in competitions)],
            key=f"mf-competition-{fmt}-{gender}",
        )
    flt = DeliveryFilter(
        format=fmt, gender=gender, competition=None if competition == ALL_COMPETITIONS else competition,
    )
    scope = f"{GENDERS[gender]}'s {fmt}" + ("" if competition == ALL_COMPETITIONS else f" · {competition}")

    summary = next(r for r in formats if r["format"] == fmt and r["gender"] == gender)
    selected = [row for row in competitions if competition in (ALL_COMPETITIONS, row["competition"])]
    ll_matches = [row for row in selected if row.get("ll_deliveries")]
    ll_note = (
        f"line/length on {sum(r['ll_deliveries'] for r in selected):,} of {sum(r['deliveries'] for r in selected):,} balls"
        + (f" ({min(r['ll_first_match'] for r in ll_matches):%b %Y} to {max(r['ll_last_match'] for r in ll_matches):%b %Y})" if ll_matches else "")
    )
    st.caption(
        f"{sum(r['matches'] for r in selected):,} matches · ball-by-ball "
        f"{min(r['first_match'] for r in selected):%b %Y} to {max(r['last_match'] for r in selected):%b %Y} · {ll_note}"
        if selected else f"{summary['matches']:,} matches"
    )

    view = st.segmented_control(
        "Explorer view", VIEWS, default="Player", label_visibility="collapsed", width="stretch", key="mf-view",
    ) or "Player"
    renderers = {
        "Player": render_player_view,
        "Compare": render_compare_view,
        "Matchups": render_matchup_view,
        "Venue": render_venue_view,
    }
    renderers[view](service, db, flt, scope)
