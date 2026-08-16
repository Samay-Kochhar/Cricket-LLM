from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import streamlit as st


PAPER_COLOR = "rgba(0,0,0,0)"
TEXT_COLOR = "#F3EDE4"
ORANGE = "#F28F3B"
GREEN = "#7CE2B4"
BLUE = "#64B5F6"

LINE_ORDER = [
    "WIDE_OUTSIDE_OFFSTUMP",
    "OUTSIDE_OFFSTUMP",
    "ON_THE_STUMPS",
    "DOWN_LEG",
    "WIDE_DOWN_LEG",
]
LENGTH_ORDER = [
    "YORKER",
    "FULL",
    "GOOD_LENGTH",
    "SHORT_OF_A_GOOD_LENGTH",
    "SHORT",
]


def _display_label(value: object) -> str:
    return str(value).replace("_", " ").strip().title()


def _ordered_labels(values: set[str], preferred: list[str]) -> list[str]:
    return [value for value in preferred if value in values] + sorted(values - set(preferred))


def _base_layout(figure: go.Figure, *, height: int = 390) -> go.Figure:
    figure.update_layout(
        height=height,
        margin=dict(l=24, r=24, t=54, b=36),
        paper_bgcolor=PAPER_COLOR,
        plot_bgcolor=PAPER_COLOR,
        font_color=TEXT_COLOR,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return figure


def build_year_trend_figure(rows: list[dict[str, Any]]) -> go.Figure:
    figure = go.Figure(
        go.Scatter(
            x=[row["year"] for row in rows],
            y=[row["runs_scored"] for row in rows],
            mode="lines+markers",
            line=dict(color=ORANGE, width=3),
            marker=dict(size=8),
            customdata=[[row.get("balls_faced"), row.get("control_percentage")] for row in rows],
            hovertemplate=(
                "%{x}: %{y:.0f} runs<br>Balls: %{customdata[0]:.0f}"
                "<br>Control: %{customdata[1]:.1f}%<extra></extra>"
            ),
            name="Runs",
        )
    )
    figure.update_layout(title="Runs by year", xaxis_title="Year", yaxis_title="Runs")
    return _base_layout(figure)


def build_phase_figure(rows: list[dict[str, Any]]) -> go.Figure:
    labels = [str(row["split"]) for row in rows]
    figure = go.Figure()
    figure.add_bar(
        x=labels,
        y=[row.get("strike_rate") for row in rows],
        name="Strike rate",
        marker_color=ORANGE,
    )
    figure.add_bar(
        x=labels,
        y=[row.get("control_percentage") for row in rows],
        name="Control %",
        marker_color=GREEN,
    )
    figure.update_layout(
        title="Phase scoring and control",
        barmode="group",
        yaxis_title="Rate / percentage",
    )
    return _base_layout(figure)


def build_pitch_heatmap(pitch: dict[str, Any]) -> go.Figure:
    cells = [cell for cell in pitch.get("cells", []) if isinstance(cell, dict)]
    lines = _ordered_labels({str(cell["line"]) for cell in cells}, LINE_ORDER)
    lengths = _ordered_labels({str(cell["length"]) for cell in cells}, LENGTH_ORDER)
    cell_map = {(str(cell["length"]), str(cell["line"])): cell for cell in cells}

    z: list[list[float | None]] = []
    customdata: list[list[list[object]]] = []
    for length in lengths:
        z_row: list[float | None] = []
        custom_row: list[list[object]] = []
        for line in lines:
            cell = cell_map.get((length, line), {})
            z_row.append(float(cell["strike_rate"]) if cell.get("strike_rate") is not None else None)
            custom_row.append(
                [
                    cell.get("balls", 0),
                    cell.get("runs", 0),
                    cell.get("dismissals", 0),
                    cell.get("dot_balls", 0),
                    cell.get("control_percentage"),
                ]
            )
        z.append(z_row)
        customdata.append(custom_row)

    figure = go.Figure(
        go.Heatmap(
            x=[_display_label(line) for line in lines],
            y=[_display_label(length) for length in lengths],
            z=z,
            customdata=customdata,
            colorscale=[[0, "#17232B"], [0.5, ORANGE], [1, "#FFD166"]],
            colorbar=dict(title="Strike rate"),
            hovertemplate=(
                "%{y}, %{x}<br>Strike rate: %{z:.2f}<br>Balls: %{customdata[0]}"
                "<br>Runs: %{customdata[1]}<br>Dismissals: %{customdata[2]}"
                "<br>Dots: %{customdata[3]}<br>Control: %{customdata[4]:.1f}%<extra></extra>"
            ),
        )
    )
    figure.update_layout(title="Line × length scoring map", xaxis_title="Line", yaxis_title="Length")
    return _base_layout(figure, height=470)


def build_wagon_wheel(wagon: dict[str, Any]) -> go.Figure:
    points = [point for point in wagon.get("points", []) if isinstance(point, dict)]
    colors = {
        "dot": "#65737E",
        "single": GREEN,
        "double": BLUE,
        "triple": "#B39DDB",
        "four": ORANGE,
        "six": "#FFD166",
        "wicket": "#EF5350",
    }
    figure = go.Figure()
    for outcome in ("dot", "single", "double", "triple", "four", "six", "wicket"):
        outcome_points = [point for point in points if point.get("outcome") == outcome]
        if not outcome_points:
            continue
        figure.add_scatter(
            x=[point.get("x") for point in outcome_points],
            y=[point.get("y") for point in outcome_points],
            mode="markers",
            name=outcome.title(),
            marker=dict(
                color=colors[outcome],
                size=[7 + int(point.get("runs", 0) or 0) * 1.5 for point in outcome_points],
                opacity=0.72,
                line=dict(width=0.5, color="#091015"),
            ),
            customdata=[[point.get("runs", 0)] for point in outcome_points],
            hovertemplate=f"{outcome.title()} · %{{customdata[0]}} runs<extra></extra>",
        )
    figure.add_shape(type="circle", x0=0, y0=0, x1=300, y1=300, line=dict(color="#52616B", width=2))
    figure.add_scatter(
        x=[150],
        y=[150],
        mode="markers",
        marker=dict(symbol="diamond", size=12, color=TEXT_COLOR),
        name="Batter",
        hoverinfo="skip",
    )
    figure.update_layout(
        title=f"Wagon wheel ({wagon.get('handedness') or 'hand unknown'})",
        xaxis=dict(visible=False, range=[-8, 308], scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, range=[-8, 308]),
    )
    return _base_layout(figure, height=560)


def build_shot_figure(shot_profile: dict[str, Any]) -> go.Figure:
    rows = [row for row in shot_profile.get("metrics", []) if isinstance(row, dict)]
    rows = list(reversed(rows))
    figure = go.Figure(
        go.Bar(
            x=[row.get("runs", 0) for row in rows],
            y=[_display_label(row.get("shot", "Unknown")) for row in rows],
            orientation="h",
            marker_color=ORANGE,
            customdata=[
                [
                    row.get("balls", 0),
                    row.get("run_share_percentage"),
                    row.get("control_percentage"),
                    row.get("dismissal_rate"),
                ]
                for row in rows
            ],
            hovertemplate=(
                "%{y}: %{x} runs<br>Balls: %{customdata[0]}<br>Run share: %{customdata[1]:.1f}%"
                "<br>Control: %{customdata[2]:.1f}%<br>Dismissal rate: %{customdata[3]:.2f}%<extra></extra>"
            ),
        )
    )
    figure.update_layout(title="Recorded shot output", xaxis_title="Runs")
    return _base_layout(figure, height=max(390, 38 * len(rows) + 120))


def _coverage_caption(label: str, payload: dict[str, Any]) -> None:
    coverage = payload.get("coverage", {})
    st.caption(
        f"{label}: {coverage.get('covered_balls', 0):,} of {coverage.get('total_balls', 0):,} balls "
        f"({coverage.get('coverage_percentage', 0):.2f}%). {coverage.get('detail', '')}"
    )


def _breakdown_rows(repository: Any, player: str, group_by: str, phase: str | None) -> list[dict[str, Any]]:
    return repository.get_line_length_breakdown(
        player,
        group_by=group_by,
        metric="batting_strike_rate",
        phase=phase,
        rank_intent="best",
        limit=20,
        min_balls=12,
    )


def render_player_explorer(services: dict[str, Any]) -> None:
    repository = services["repository"]
    st.markdown("<div class='atlas-kicker'>◆ CricAtlas player explorer</div>", unsafe_allow_html=True)
    st.markdown(
        "<h1 class='atlas-title explorer-title'>Know the player.<br>Inspect every zone.</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='atlas-copy'>Search an ODI player and explore career output, phase performance, "
        "line and length scoring, wagon-wheel zones and recorded shot evidence.</p>",
        unsafe_allow_html=True,
    )

    player_names = repository.list_player_names()
    control_left, control_right = st.columns([2, 1])
    with control_left:
        player = st.selectbox(
            "Player",
            options=player_names,
            index=None,
            placeholder="Type a player name…",
        )
    with control_right:
        phase_label = st.selectbox(
            "Phase filter",
            ["All phases", "Powerplay", "Middle overs", "Death overs"],
        )

    if not player:
        st.info("Choose a player above. The selector supports type-to-search.")
        return

    phase_map = {"All phases": None, "Powerplay": "powerplay", "Middle overs": "middle", "Death overs": "death"}
    phase = phase_map[phase_label]
    summary = repository.get_player_batting_summary(player, phase=phase)
    if not summary:
        st.warning(f"No ODI batting evidence was found for {player} in {phase_label.lower()}.")
        return

    st.subheader(f"{player} · {phase_label}")
    metric_columns = st.columns(7)
    metrics = (
        ("Runs", f"{summary['runs_scored']:,}"),
        ("Balls", f"{summary['balls_faced']:,}"),
        ("Average", f"{summary['average']:.2f}" if summary.get("average") is not None else "—"),
        ("Strike rate", f"{summary['strike_rate']:.2f}" if summary.get("strike_rate") is not None else "—"),
        (
            "Control",
            f"{summary['control_percentage']:.2f}%" if summary.get("control_percentage") is not None else "—",
        ),
        ("Dot balls", f"{summary['dot_percentage']:.2f}%" if summary.get("dot_percentage") is not None else "—"),
        (
            "Boundaries",
            f"{summary['boundary_percentage']:.2f}%" if summary.get("boundary_percentage") is not None else "—",
        ),
    )
    for column, (label, value) in zip(metric_columns, metrics, strict=True):
        column.metric(label, value)

    overview_tab, phase_tab, pitch_tab, wagon_tab = st.tabs(
        ["Overview", "Phase analysis", "Line & length", "Wagon wheel & shots"]
    )

    with overview_tab:
        trend = repository.get_player_year_trend(player)
        if trend:
            st.plotly_chart(build_year_trend_figure(trend), width="stretch", config={"displayModeBar": False})
            st.dataframe(trend, width="stretch", hide_index=True)
        else:
            st.info("No year-level batting trend is available for this player.")

    with phase_tab:
        phase_rows = repository.get_player_phase_summary(player)
        if phase_rows:
            st.plotly_chart(build_phase_figure(phase_rows), width="stretch", config={"displayModeBar": False})
            st.dataframe(phase_rows, width="stretch", hide_index=True)
        else:
            st.info("No phase split is available for this player.")

    with pitch_tab:
        pitch = repository.get_pitch_map(player, phase=phase)
        if pitch.get("cells"):
            st.plotly_chart(build_pitch_heatmap(pitch), width="stretch", config={"displayModeBar": False})
            _coverage_caption("Line/length coverage", pitch)
            line_column, length_column = st.columns(2)
            with line_column:
                st.markdown("#### By line")
                st.dataframe(_breakdown_rows(repository, player, "line", phase), width="stretch", hide_index=True)
            with length_column:
                st.markdown("#### By length")
                st.dataframe(_breakdown_rows(repository, player, "length", phase), width="stretch", hide_index=True)
            with st.expander("All line × length cells"):
                st.dataframe(pitch["cells"], width="stretch", hide_index=True)
        else:
            st.info("No coded line/length evidence is available for this player and phase.")

    with wagon_tab:
        wagon = repository.get_wagon_wheel(player, point_limit=240, phase=phase)
        shots = repository.get_shot_type_profile(player, limit=12, phase=phase)
        wagon_column, shot_column = st.columns([1, 1])
        with wagon_column:
            if wagon.get("points"):
                st.plotly_chart(build_wagon_wheel(wagon), width="stretch", config={"displayModeBar": False})
                _coverage_caption("Wagon-wheel coverage", wagon)
            else:
                st.info("No wagon-wheel coordinates are available for this player and phase.")
        with shot_column:
            if shots.get("metrics"):
                st.plotly_chart(build_shot_figure(shots), width="stretch", config={"displayModeBar": False})
                _coverage_caption("Shot-type coverage", shots)
            else:
                st.info("No recorded shot labels are available for this player and phase.")
        if wagon.get("sectors"):
            st.markdown("#### Wagon sectors")
            st.dataframe(wagon["sectors"], width="stretch", hide_index=True)
