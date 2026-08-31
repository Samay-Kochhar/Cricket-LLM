from __future__ import annotations

from backend.app.cricket_analytics.cricket_definitions import public_label
from backend.app.cricket_analytics.executors.player_compare_executor import PlayerCompareResult
from backend.app.cricket_analytics.metric_registry import get_metric


BATTER_PRIORITY = (
    "runs_scored",
    "batting_strike_rate",
    "batting_average",
    "batter_dot_ball_percentage",
    "boundary_percentage",
)
BOWLER_PRIORITY = (
    "wickets_taken",
    "wickets_per_over",
    "economy_rate",
    "bowling_strike_rate",
    "bowler_dot_ball_percentage",
)


def build_player_comparison_insight(compare: PlayerCompareResult) -> str:
    if len(compare.players) < 2:
        return "No clear numerical difference was available for a useful summary."
    if compare.view == "phase":
        return _phase_insight(compare)
    if compare.view == "opposition":
        return _opposition_insight(compare)
    return _overall_insight(compare)


def _phase_insight(compare: PlayerCompareResult) -> str:
    metric = _focus_metric(compare)
    if metric is None:
        return "No clear phase difference was available for a useful summary."
    first_player, second_player = compare.players[:2]
    rows = {
        (str(row.get("player")), str(row.get("phase"))): row
        for row in compare.rows
        if row.get("player") and row.get("phase")
    }
    comparisons: list[tuple[str, str | None, dict[str, object], dict[str, object]]] = []
    for phase in ("powerplay", "middle", "death"):
        first_row = rows.get((first_player, phase))
        second_row = rows.get((second_player, phase))
        if first_row is None or second_row is None:
            continue
        leader = _leader(
            first_row.get(metric),
            second_row.get(metric),
            metric,
            first_player,
            second_player,
        )
        if leader is not False:
            comparisons.append((phase, leader, first_row, second_row))
    if not comparisons:
        return "No clear phase difference was available for a useful summary."

    leaders = [leader for _, leader, _, _ in comparisons]
    if len(comparisons) == 3 and leaders[0] is not None and len(set(leaders)) == 1:
        winner = str(leaders[0])
        other = second_player if winner == first_player else first_player
        lead = f"{winner} {_comparison_verb(metric)} {other} in all three phases."
    else:
        parts = []
        for player in (first_player, second_player):
            phases = [phase for phase, leader, _, _ in comparisons if leader == player]
            if phases:
                parts.append(f"{player} led in {_join_phases(phases)}")
        tied = [phase for phase, leader, _, _ in comparisons if leader is None]
        if tied:
            parts.append(f"they were level in {_join_phases(tied)}")
        lead = "; ".join(parts) + "."

    phase, _, first_row, second_row = max(
        comparisons,
        key=lambda item: abs(float(item[2][metric]) - float(item[3][metric])),
    )
    detail = (
        f"The largest {_gap_name(metric)} gap was {_phase_preposition(phase)}: "
        f"{_number(first_row[metric])} vs {_number(second_row[metric])}"
    )
    sample_column = compare.sample_columns[0] if compare.sample_columns else None
    if sample_column and first_row.get(sample_column) is not None and second_row.get(sample_column) is not None:
        sample_unit = "balls" if "ball" in sample_column else sample_column.replace("_", " ")
        detail += (
            f", from {_number(first_row[sample_column])} and "
            f"{_number(second_row[sample_column])} {sample_unit}, respectively"
        )
    return f"{lead} {detail}."


def _opposition_insight(compare: PlayerCompareResult) -> str:
    metric = _focus_metric(compare)
    if metric is None:
        return "No clear opposition difference was available for a useful summary."
    first_player, second_player = compare.players[:2]
    first_rows = {
        str(row.get("opposition")): row
        for row in compare.rows
        if row.get("player") == first_player and row.get("opposition")
    }
    second_rows = {
        str(row.get("opposition")): row
        for row in compare.rows
        if row.get("player") == second_player and row.get("opposition")
    }
    candidates = []
    for opposition in first_rows.keys() & second_rows.keys():
        first_value = first_rows[opposition].get(metric)
        second_value = second_rows[opposition].get(metric)
        if _is_number(first_value) and _is_number(second_value):
            candidates.append(
                (abs(float(first_value) - float(second_value)), opposition, first_value, second_value)
            )
    if not candidates:
        return "No clear opposition difference was available for a useful summary."
    _, opposition, first_value, second_value = max(candidates, key=lambda item: item[0])
    clause = _metric_clause(
        {metric: first_value},
        {metric: second_value},
        metric,
        first_player,
        second_player,
    )
    return f"Against {opposition}, {clause}."


def _overall_insight(compare: PlayerCompareResult) -> str:
    first_player, second_player = compare.players[:2]
    first_row = next((row for row in compare.rows if row.get("player") == first_player), {})
    second_row = next((row for row in compare.rows if row.get("player") == second_player), {})

    paired_metrics = (
        ("runs_scored", "batting_strike_rate"),
        ("wickets_taken", "economy_rate"),
    )
    for first_metric, second_metric in paired_metrics:
        if first_metric in compare.metrics and second_metric in compare.metrics:
            first_clause = _metric_clause(
                first_row, second_row, first_metric, first_player, second_player
            )
            second_clause = _metric_clause(
                first_row, second_row, second_metric, first_player, second_player
            )
            if first_clause and second_clause:
                return f"{first_clause}, while {second_clause}."

    for metric in _ordered_metrics(compare):
        clause = _metric_clause(first_row, second_row, metric, first_player, second_player)
        if clause:
            return clause + "."
    return "No clear numerical difference was available for a useful summary."


def _metric_clause(
    first_row: dict[str, object],
    second_row: dict[str, object],
    metric: str,
    first_player: str,
    second_player: str,
) -> str | None:
    first_value = first_row.get(metric)
    second_value = second_row.get(metric)
    if not _is_number(first_value) or not _is_number(second_value):
        return None
    leader = _leader(first_value, second_value, metric, first_player, second_player)
    if leader is None:
        return f"The players were level on {_metric_label(metric)} at {_number(first_value)}"
    other = second_player if leader == first_player else first_player
    leader_value = first_value if leader == first_player else second_value
    other_value = second_value if leader == first_player else first_value
    return (
        f"{leader} {_single_metric_verb(metric)} {other}: "
        f"{_number(leader_value)} vs {_number(other_value)}"
    )


def _focus_metric(compare: PlayerCompareResult) -> str | None:
    batter = any("balls_faced" in row for row in compare.rows)
    priority = (
        ("batting_strike_rate", "runs_scored", "batting_average")
        if batter
        else ("economy_rate", "wickets_taken", "wickets_per_over", "bowling_strike_rate")
    )
    return next((metric for metric in priority if metric in compare.metrics), None) or (
        compare.metrics[0] if compare.metrics else None
    )


def _ordered_metrics(compare: PlayerCompareResult) -> list[str]:
    priority = BATTER_PRIORITY if any("balls_faced" in row for row in compare.rows) else BOWLER_PRIORITY
    return [metric for metric in priority if metric in compare.metrics] + [
        metric for metric in compare.metrics if metric not in priority
    ]


def _leader(
    first_value: object,
    second_value: object,
    metric: str,
    first_player: str,
    second_player: str,
) -> str | None | bool:
    if not _is_number(first_value) or not _is_number(second_value):
        return False
    if float(first_value) == float(second_value):
        return None
    first_leads = float(first_value) > float(second_value)
    if get_metric(metric).higher_is_better is False:
        first_leads = not first_leads
    return first_player if first_leads else second_player


def _comparison_verb(metric: str) -> str:
    return {
        "batting_strike_rate": "scored faster than",
        "economy_rate": "was more economical than",
        "runs_scored": "scored more runs than",
        "wickets_taken": "took more wickets than",
        "batter_dot_ball_percentage": "had a lower dot-ball percentage than",
        "boundary_percentage": "hit boundaries more often than",
        "bowler_dot_ball_percentage": "bowled dots more often than",
    }.get(metric, f"led {_metric_label(metric)} against")


def _single_metric_verb(metric: str) -> str:
    return {
        "runs_scored": "scored more runs than",
        "batting_strike_rate": "scored faster than",
        "batting_average": "had a higher batting average than",
        "wickets_taken": "took more wickets than",
        "wickets_per_over": "took wickets more frequently than",
        "economy_rate": "was more economical than",
        "bowling_strike_rate": "took wickets more frequently than",
        "batter_dot_ball_percentage": "had a lower dot-ball percentage than",
        "boundary_percentage": "hit boundaries more often than",
        "bowler_dot_ball_percentage": "bowled dots more often than",
        "false_shot_percentage": "played fewer false shots than",
        "control_percentage": "played in control more often than",
    }.get(metric, f"led {_metric_label(metric)} against")


def _gap_name(metric: str) -> str:
    return {
        "batting_strike_rate": "strike-rate",
        "economy_rate": "economy-rate",
        "wickets_per_over": "wicket-rate",
    }.get(metric, _metric_label(metric).lower())


def _metric_label(metric: str) -> str:
    return get_metric(metric).label


def _phase_preposition(phase: str) -> str:
    return {
        "powerplay": "in the powerplay",
        "middle": "in the middle overs",
        "death": "at the death",
    }.get(phase, f"in {phase}")


def _join_phases(phases: list[str]) -> str:
    if phases == ["middle", "death"]:
        return "the middle and death overs"
    labels = {
        "powerplay": "the powerplay",
        "middle": "the middle overs",
        "death": "the death overs",
    }
    rendered = [labels.get(phase, phase) for phase in phases]
    if len(rendered) == 1:
        return rendered[0]
    return ", ".join(rendered[:-1]) + f" and {rendered[-1]}"


def _number(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(public_label(value))


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
