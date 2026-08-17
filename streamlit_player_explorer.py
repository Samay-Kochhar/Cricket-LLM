from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import streamlit as st


PAPER_COLOR = "rgba(0,0,0,0)"
TEXT_COLOR = "#F3EDE4"
ORANGE = "#F28F3B"
GREEN = "#7CE2B4"

LINE_ORDER = [
    "WIDE_OUTSIDE_OFFSTUMP",
    "OUTSIDE_OFFSTUMP",
    "ON_THE_STUMPS",
    "DOWN_LEG",
    "WIDE_DOWN_LEG",
]
LENGTH_ORDER = [
    "FULL_TOSS",
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
        margin=dict(l=24, r=24, t=72, b=44),
        paper_bgcolor=PAPER_COLOR,
        plot_bgcolor=PAPER_COLOR,
        font_color=TEXT_COLOR,
        title=dict(x=0.01, xanchor="left", y=0.98, yanchor="top"),
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
    figure.update_layout(title="Runs by year", xaxis_title="Year", yaxis_title="Runs", showlegend=False)
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
    figure = _base_layout(figure)
    figure.update_layout(
        margin=dict(l=24, r=24, t=72, b=82),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="left", x=0),
    )
    return figure


def build_pitch_heatmap(
    pitch: dict[str, Any],
    *,
    colour_metric: str = "Strike rate",
    min_balls: int = 20,
) -> go.Figure:
    cells = [cell for cell in pitch.get("cells", []) if isinstance(cell, dict)]
    lines = _ordered_labels({str(cell["line"]) for cell in cells}, LINE_ORDER)
    lengths = _ordered_labels({str(cell["length"]) for cell in cells}, LENGTH_ORDER)
    cell_map = {(str(cell["length"]), str(cell["line"])): cell for cell in cells}

    reliable_cells = [cell for cell in cells if int(cell.get("balls", 0) or 0) >= min_balls]
    reliable_balls = sum(int(cell.get("balls", 0) or 0) for cell in reliable_cells)
    reliable_runs = sum(int(cell.get("runs", 0) or 0) for cell in reliable_cells)
    reliable_dismissals = sum(int(cell.get("dismissals", 0) or 0) for cell in reliable_cells)
    baseline_strike_rate = (reliable_runs / reliable_balls * 100.0) if reliable_balls else 0.0
    baseline_average = (reliable_runs / reliable_dismissals) if reliable_dismissals else None

    z: list[list[float | None]] = []
    customdata: list[list[list[object]]] = []
    annotations: list[dict[str, Any]] = []
    annotation_values: list[float | None] = []
    reliable_values: list[float] = []
    for length in lengths:
        z_row: list[float | None] = []
        custom_row: list[list[object]] = []
        for line in lines:
            cell = cell_map.get((length, line), {})
            balls = int(cell.get("balls", 0) or 0)
            runs = int(cell.get("runs", 0) or 0)
            dismissals = int(cell.get("dismissals", 0) or 0)
            strike_rate = float(cell["strike_rate"]) if cell.get("strike_rate") is not None else None
            average = (runs / dismissals) if dismissals else None
            is_reliable = balls >= min_balls
            if colour_metric == "Batting average":
                colour_value = (
                    average - baseline_average
                    if is_reliable and average is not None and baseline_average is not None
                    else None
                )
            elif is_reliable and strike_rate is not None:
                colour_value = strike_rate - baseline_strike_rate
            else:
                colour_value = None
            z_row.append(colour_value)
            if colour_value is not None:
                reliable_values.append(float(colour_value))
            custom_row.append(
                [
                    balls,
                    runs,
                    dismissals,
                    cell.get("dot_balls", 0),
                    cell.get("control_percentage"),
                    strike_rate,
                    average,
                ]
            )
            average_label = f"{average:.1f}" if average is not None else "n/a"
            if not cell:
                annotation_text = "<b>No data</b>"
            elif balls < min_balls:
                annotation_text = (
                    f"<b>SR {strike_rate:.1f}</b><br>Avg {average_label}"
                    f"<br>W {dismissals}<br><i>Low sample</i>"
                )
            else:
                annotation_text = f"<b>SR {strike_rate:.1f}</b><br>Avg {average_label}<br>W {dismissals}"
            annotations.append(
                {
                    "x": _display_label(line),
                    "y": _display_label(length),
                    "text": annotation_text,
                    "showarrow": False,
                }
            )
            annotation_values.append(colour_value)
        z.append(z_row)
        customdata.append(custom_row)

    colour_extent = max((abs(value) for value in reliable_values), default=10.0)
    neutral_band = 5.0 if colour_metric == "Batting average" else 7.5
    yellow_band = min(0.24, neutral_band / (2 * colour_extent)) if colour_extent else 0.24
    colorscale = [
        [0, "#B83232"],
        [0.5 - yellow_band, "#D9534F"],
        [0.5, "#F2C94C"],
        [0.5 + yellow_band, "#3FAE6A"],
        [1, "#1F7A46"],
    ]
    zmin = -colour_extent
    zmax = colour_extent
    if colour_metric == "Batting average":
        colorbar_title = "Avg vs<br>baseline"
        baseline_label = f"{baseline_average:.1f}" if baseline_average is not None else "n/a"
        chart_title = f"Line × length average · baseline Avg {baseline_label}"
    else:
        colorbar_title = "SR vs<br>baseline"
        chart_title = f"Line × length strike rate · baseline SR {baseline_strike_rate:.1f}"

    for annotation, value in zip(annotations, annotation_values, strict=True):
        if value is None:
            text_colour = "#263238"
        else:
            text_colour = "#1D292E" if abs(value) <= (zmax * 0.22) else "#F8F6F0"
        annotation["font"] = {"size": 11, "color": text_colour}

    figure = go.Figure(
        go.Heatmap(
            x=[_display_label(line) for line in lines],
            y=[_display_label(length) for length in lengths],
            z=z,
            customdata=customdata,
            colorscale=colorscale,
            zmin=zmin,
            zmax=zmax,
            xgap=4,
            ygap=4,
            colorbar=dict(title=colorbar_title),
            hovertemplate=(
                "%{y}, %{x}<br>Strike rate: %{customdata[5]:.2f}<br>Average: %{customdata[6]:.2f}"
                "<br>Dismissals: %{customdata[2]}<br>Balls: %{customdata[0]}"
                "<br>Runs: %{customdata[1]}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        title=chart_title,
        yaxis_title="Length",
        annotations=annotations,
        shapes=_pitch_shapes(),
    )
    figure = _base_layout(figure, height=max(660, 92 * len(lengths) + 210))
    figure.update_layout(margin=dict(l=32, r=28, t=118, b=82), plot_bgcolor="#C8CDD0")
    figure.update_xaxes(showgrid=False, zeroline=False, side="top")
    figure.update_yaxes(autorange="reversed", showgrid=False, zeroline=False)
    return figure


def _pitch_shapes() -> list[dict[str, Any]]:
    line = dict(color="#E9D9A6", width=2)
    shapes: list[dict[str, Any]] = [
        dict(
            type="rect",
            name="pitch-border",
            xref="paper",
            yref="paper",
            x0=-0.015,
            x1=1.015,
            y0=-0.015,
            y1=1.015,
            line=dict(color="#CBB77C", width=3),
        ),
        dict(
            type="line",
            name="crease-batter",
            xref="paper",
            yref="paper",
            x0=0,
            x1=1,
            y0=-0.015,
            y1=-0.015,
            line=line,
        ),
    ]
    for index, x in enumerate((0.475, 0.5, 0.525), start=1):
        shapes.append(
            dict(
                type="line",
                name=f"stump-batter-{index}",
                xref="paper",
                yref="paper",
                x0=x,
                x1=x,
                y0=-0.07,
                y1=-0.015,
                line=dict(color="#F1D68A", width=4),
            )
        )
    shapes.append(
        dict(
            type="line",
            name="bails-batter",
            xref="paper",
            yref="paper",
            x0=0.468,
            x1=0.532,
            y0=-0.07,
            y1=-0.07,
            line=dict(color="#F1D68A", width=3),
        )
    )
    return shapes


def build_wagon_wheel(wagon: dict[str, Any]) -> go.Figure:
    sectors = sorted(
        [sector for sector in wagon.get("sectors", []) if isinstance(sector, dict)],
        key=lambda sector: int(sector.get("zone_id", 0)),
    )
    theta = [(int(sector.get("zone_id", 1)) - 1) * 45 + 22.5 for sector in sectors]
    shares = [float(sector.get("run_share_percentage", 0) or 0) for sector in sectors]
    max_share = max(shares, default=1.0)

    def sector_colour(share: float) -> str:
        strength = min(max(share / max_share, 0.0), 1.0)
        red = round(68 - 35 * strength)
        green = round(145 + 55 * strength)
        blue = round(86 - 25 * strength)
        return f"rgb({red},{green},{blue})"

    figure = go.Figure()
    figure.add_barpolar(
        r=[100] * len(sectors),
        theta=theta,
        width=[45] * len(sectors),
        marker=dict(
            color=[sector_colour(share) for share in shares],
            line=dict(color="rgba(241,244,222,.72)", width=1.5),
        ),
        customdata=[
            [
                sector.get("label"),
                sector.get("runs", 0),
                sector.get("run_share_percentage", 0),
                sector.get("balls", 0),
                sector.get("strike_rate"),
                sector.get("dismissals", 0),
            ]
            for sector in sectors
        ],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>%{customdata[1]} runs · %{customdata[2]:.2f}% share"
            "<br>Balls: %{customdata[3]}<br>Strike rate: %{customdata[4]:.2f}"
            "<br>Dismissals: %{customdata[5]}<extra></extra>"
        ),
        name="Scoring sectors",
    )
    figure.add_scatterpolar(
        r=[65] * len(sectors),
        theta=theta,
        mode="text",
        text=[
            f"<b>{int(sector.get('runs', 0) or 0):,} runs</b>"
            f"<br>{float(sector.get('run_share_percentage', 0) or 0):.1f}%"
            for sector in sectors
        ],
        textfont=dict(color="#F7F8E8", size=11),
        hoverinfo="skip",
        showlegend=False,
    )
    handedness = str(wagon.get("handedness") or "hand unknown").upper()
    left_side, right_side = ("LEG SIDE", "OFF SIDE") if handedness == "LHB" else ("OFF SIDE", "LEG SIDE")
    figure.update_layout(
        title=f"Wagon-wheel scoring sectors · {wagon.get('handedness') or 'hand unknown'}",
        showlegend=False,
        dragmode=False,
        polar=dict(
            bgcolor="#2A6A3A",
            radialaxis=dict(visible=False, range=[0, 100]),
            angularaxis=dict(visible=False, direction="clockwise", rotation=0),
        ),
        annotations=[
            dict(
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                text="🏏",
                showarrow=False,
                font=dict(size=24),
                bgcolor="#D8BD72",
                bordercolor="#F5E1A4",
                borderwidth=2,
                borderpad=8,
            ),
            dict(
                x=-0.06,
                y=0.5,
                xref="paper",
                yref="paper",
                text=left_side,
                textangle=-90,
                showarrow=False,
                font=dict(size=11, color="#B7E6C4"),
            ),
            dict(
                x=1.06,
                y=0.5,
                xref="paper",
                yref="paper",
                text=right_side,
                textangle=90,
                showarrow=False,
                font=dict(size=11, color="#B7E6C4"),
            ),
        ],
    )
    figure = _base_layout(figure, height=560)
    figure.update_layout(margin=dict(l=64, r=64, t=76, b=42))
    return figure


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
    top_metric_columns = st.columns(4)
    bottom_metric_columns = st.columns(4)
    metric_columns = [*top_metric_columns, *bottom_metric_columns[:3]]
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
            colour_metric = st.radio(
                "Colour cells by",
                ["Strike rate", "Batting average"],
                horizontal=True,
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
                "are light grey to avoid over-interpreting small samples. In average mode, zones without a "
                "dismissal are also grey because batting average is not yet defined; ball counts remain on hover."
            )
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
        wagon = repository.get_wagon_wheel(player, point_limit=0, phase=phase)
        shots = repository.get_shot_type_profile(player, limit=12, phase=phase)
        wagon_column, shot_column = st.columns([1, 1])
        with wagon_column:
            if wagon.get("sectors"):
                st.plotly_chart(
                    build_wagon_wheel(wagon),
                    width="stretch",
                    config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False},
                )
                st.caption(
                    "Each field sector shows runs and its share of wagon-covered runs. Hover for the zone name, "
                    "balls, strike rate and dismissals."
                )
                _coverage_caption("Wagon-wheel coverage", wagon)
            else:
                st.info("No wagon-wheel sector data is available for this player and phase.")
        with shot_column:
            if shots.get("metrics"):
                st.plotly_chart(build_shot_figure(shots), width="stretch", config={"displayModeBar": False})
                _coverage_caption("Shot-type coverage", shots)
            else:
                st.info("No recorded shot labels are available for this player and phase.")
        if wagon.get("sectors"):
            st.markdown("#### Wagon sectors")
            st.dataframe(wagon["sectors"], width="stretch", hide_index=True)
