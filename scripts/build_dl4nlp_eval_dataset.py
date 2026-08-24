from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from backend.app.bootstrap import get_services
from backend.app.cricket_analytics.executors import matchup_executor, player_compare_executor, split_compare_executor
from backend.app.cricket_analytics.ontology import METRICS
from backend.app.cricket_analytics.plan_normalizer import normalize_plan
from backend.app.cricket_analytics.plan_validator import validate_plan
from backend.app.cricket_analytics.query_builders.aggregate_builder import build_aggregate_query
from backend.app.cricket_analytics.schemas import CricketQueryPlan, SortSpec


DEFAULT_OUTPUT = Path("tests/evals/dl4nlp_cricket_query_100.yaml")


@dataclass(frozen=True, slots=True)
class Candidate:
    case_id: str
    category: str
    question: str
    plan: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the DL4NLP cricket query-generation evaluation set.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output YAML path.")
    parser.add_argument("--limit", type=int, default=100, help="Number of non-empty cases to write.")
    args = parser.parse_args()

    services = get_services()
    repository = services["repository"]

    selected: list[dict[str, Any]] = []
    skipped: list[str] = []
    for candidate in candidates():
        try:
            case = materialize_case(candidate, repository)
        except Exception as exc:  # pragma: no cover - script-level guard.
            skipped.append(f"{candidate.case_id}: {exc}")
            continue
        if case["answer_key"]["row_count"] <= 0:
            skipped.append(f"{candidate.case_id}: empty answer")
            continue
        selected.append(case)
        if len(selected) == args.limit:
            break

    if len(selected) < args.limit:
        raise SystemExit(f"Only built {len(selected)} non-empty cases. Skipped: {skipped[:10]}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(selected, sort_keys=False, allow_unicode=False, width=110),
        encoding="utf-8",
    )
    print(f"Wrote {len(selected)} cases to {output_path}")
    if skipped:
        print(f"Skipped {len(skipped)} candidate cases while building a non-empty gold set.")
    return 0


def materialize_case(candidate: Candidate, repository: Any) -> dict[str, Any]:
    plan = normalize_plan(CricketQueryPlan.model_validate(candidate.plan))
    validation = validate_plan(plan, candidate.question)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    answer_key = answer_key_for_plan(plan, repository)
    plan_dict = plan.model_dump(mode="json", exclude_none=True)
    case: dict[str, Any] = {
        "id": candidate.case_id,
        "category": candidate.category,
        "question": candidate.question,
        "expected_operation": plan.operation,
        "expected_entity": plan.entity,
        "expected_metric": plan.metric,
        "expected_group_by": list(plan.group_by),
        "expected_filters": dict(plan.filters),
        "expected_sort": plan.sort.model_dump(mode="json") if plan.sort else None,
        "expected_limit": plan.limit,
        "expected_plan": plan_dict,
        "answer_key": answer_key,
        "answer_check_fields": answer_check_fields(plan, answer_key["columns"]),
    }
    if plan.minimum_sample:
        case["expected_minimum_sample"] = plan.minimum_sample.model_dump(mode="json", exclude_none=True)
    return case


def answer_key_for_plan(plan: CricketQueryPlan, repository: Any) -> dict[str, Any]:
    if plan.operation == "aggregate":
        build = build_aggregate_query(plan)
        rows = [dict(zip(build.columns, row)) for row in repository._fetchall(build.sql, build.params)]
        return answer_key("aggregate_builder", build.columns, rows)

    if plan.operation == "player_compare":
        result = player_compare_executor.execute_player_compare(plan, repository)
        return answer_key("player_compare_executor", result.columns, result.rows)

    if plan.operation == "matchup":
        build = matchup_executor.build_matchup_query(plan)
        rows = [dict(zip(build.query.columns, row)) for row in repository._fetchall(build.query.sql, build.query.params)]
        return answer_key("matchup_executor", build.query.columns, rows)

    if plan.operation == "split_compare":
        build = split_compare_executor.build_split_compare_query(plan)
        rows = [dict(zip(build.query.columns, row)) for row in repository._fetchall(build.query.sql, build.query.params)]
        return answer_key("split_compare_executor", build.query.columns, rows)

    raise ValueError(f"Unsupported gold-answer operation: {plan.operation}")


def answer_check_fields(plan: CricketQueryPlan, columns: list[str]) -> list[str]:
    if plan.operation == "player_compare":
        metrics = plan.filters.get("comparison_metrics")
        fields = ["player", *(str(metric) for metric in metrics if isinstance(metric, str))] if isinstance(metrics, list) else ["player", plan.metric]
        return [field for field in fields if field in columns]

    if plan.operation == "matchup":
        metric_field = {
            "runs_scored": "runs",
            "balls_faced": "balls",
            "wickets_taken": "wickets",
            "batting_strike_rate": "strike_rate",
            "batter_dot_ball_percentage": "dot_percentage",
            "bowler_dot_ball_percentage": "bowler_dot_percentage",
            "boundary_percentage": "boundary_percentage",
            "false_shot_percentage": "false_shot_percentage",
            "dismissals": "dismissals",
        }.get(plan.metric, "rank_value")
        fields = [*plan.group_by, "batter", "bowler", metric_field]
        return list(dict.fromkeys(field for field in fields if field in columns))

    if plan.operation == "split_compare":
        fields = [plan.entity, "difference", "rank_value"]
        return [field for field in fields if field in columns]

    fields = [*plan.group_by, plan.metric]
    return list(dict.fromkeys(field for field in fields if field in columns))


def answer_key(executor: str, columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    clean_rows = [clean_row(row) for row in rows]
    return {
        "source": "expected_plan_executed_on_local_duckdb",
        "executor": executor,
        "status": "supported" if clean_rows else "empty_result",
        "columns": columns,
        "row_count": len(clean_rows),
        "top_rows": clean_rows[:5],
        "expected_top_row": dict(clean_rows[0]) if clean_rows else None,
    }


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: clean_value(value) for key, value in row.items()}


def clean_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return str(value)


def aggregate(
    case_id: str,
    category: str,
    question: str,
    *,
    entity: str,
    metric: str,
    group_by: list[str],
    filters: dict[str, Any] | None = None,
    limit: int = 10,
    sort_direction: str | None = None,
) -> Candidate:
    metric_def = METRICS[metric]
    return Candidate(
        case_id,
        category,
        question,
        {
            "operation": "aggregate",
            "entity": entity,
            "metric": metric,
            "group_by": group_by,
            "filters": filters or {},
            "sort": {"by": metric, "direction": sort_direction or metric_def.default_sort},
            "limit": limit,
        },
    )


def compare(
    case_id: str,
    category: str,
    question: str,
    *,
    entity: str,
    players: list[str],
    metrics: list[str],
    filters: dict[str, Any] | None = None,
) -> Candidate:
    all_filters = dict(filters or {})
    all_filters["compare_players"] = players
    all_filters["comparison_metrics"] = metrics
    primary_metric = metrics[0]
    return Candidate(
        case_id,
        category,
        question,
        {
            "operation": "player_compare",
            "entity": entity,
            "metric": primary_metric,
            "group_by": [entity],
            "filters": all_filters,
            "sort": {"by": primary_metric, "direction": METRICS[primary_metric].default_sort},
            "limit": 10,
        },
    )


def matchup(
    case_id: str,
    category: str,
    question: str,
    *,
    entity: str,
    metric: str,
    group_by: list[str],
    filters: dict[str, Any],
    limit: int = 10,
) -> Candidate:
    return Candidate(
        case_id,
        category,
        question,
        {
            "operation": "matchup",
            "entity": entity,
            "metric": metric,
            "group_by": group_by,
            "filters": filters,
            "sort": {"by": metric, "direction": METRICS.get(metric, METRICS["batting_strike_rate"]).default_sort},
            "limit": limit,
        },
    )


def candidates() -> list[Candidate]:
    cases: list[Candidate] = []
    batters = [
        "Virat Kohli",
        "Rohit Sharma",
        "Babar Azam",
        "Jos Buttler",
        "Heinrich Klaasen",
        "David Warner",
        "Steven Smith",
        "Glenn Maxwell",
        "David Miller",
        "AB de Villiers",
    ]
    bowlers = [
        "Jasprit Bumrah",
        "Mitchell Starc",
        "Lasith Malinga",
        "Rashid Khan",
        "Tim Southee",
        "Trent Boult",
        "Kagiso Rabada",
        "Shaheen Shah Afridi",
        "Ravichandran Ashwin",
        "Shakib Al Hasan",
    ]

    for index, batter in enumerate(batters, start=1):
        cases.append(aggregate(f"direct-batter-runs-{index:02d}", "direct_batter_stat", f"How many ODI runs has {batter} scored?", entity="batter", metric="runs_scored", group_by=["batter"], filters={"batter": batter}, limit=1))
        cases.append(aggregate(f"direct-batter-sr-{index:02d}", "direct_batter_stat", f"What is {batter}'s ODI batting strike rate?", entity="batter", metric="batting_strike_rate", group_by=["batter"], filters={"batter": batter}, limit=1))

    for index, bowler in enumerate(bowlers, start=1):
        cases.append(aggregate(f"direct-bowler-wickets-{index:02d}", "direct_bowler_stat", f"How many ODI wickets has {bowler} taken?", entity="bowler", metric="wickets_taken", group_by=["bowler"], filters={"bowler": bowler}, limit=1))
        cases.append(aggregate(f"direct-bowler-economy-{index:02d}", "direct_bowler_stat", f"What is {bowler}'s ODI economy rate?", entity="bowler", metric="economy_rate", group_by=["bowler"], filters={"bowler": bowler}, limit=1))

    leaderboard_cases = [
        ("leader-batter-runs", "Which batter has scored the most ODI runs?", "batter", "runs_scored", ["batter"], {}, None),
        ("leader-batter-sr", "Which batter has the highest ODI batting strike rate?", "batter", "batting_strike_rate", ["batter"], {}, None),
        ("leader-batter-boundary", "Which batter has the highest boundary percentage?", "batter", "boundary_percentage", ["batter"], {}, None),
        ("leader-batter-dot", "Which batter has the lowest dot-ball percentage?", "batter", "batter_dot_ball_percentage", ["batter"], {}, "asc"),
        ("leader-bowler-wickets", "Which bowler has taken the most ODI wickets?", "bowler", "wickets_taken", ["bowler"], {}, None),
        ("leader-bowler-economy", "Which bowler has the lowest ODI economy rate?", "bowler", "economy_rate", ["bowler"], {}, None),
        ("leader-bowler-yorkers", "Which bowler bowls the highest percentage of yorkers?", "bowler", "yorker_percentage", ["bowler"], {}, None),
        ("leader-bowler-dots", "Which bowler has the highest dot-ball percentage?", "bowler", "bowler_dot_ball_percentage", ["bowler"], {}, None),
        ("leader-death-economy", "Which bowler has the best economy rate in death overs?", "bowler", "economy_rate", ["bowler"], {"phase": "death"}, None),
        ("leader-powerplay-wickets", "Which bowler has taken the most wickets in the powerplay?", "bowler", "wickets_taken", ["bowler"], {"phase": "powerplay"}, None),
        ("leader-since-2022-death-economy", "Which bowler has the best death-over economy since 2022?", "bowler", "economy_rate", ["bowler"], {"phase": "death", "years": [2022], "year_mode": "after"}, None),
        ("leader-2023-runs", "Which batter scored the most ODI runs in 2023?", "batter", "runs_scored", ["batter"], {"years": [2023]}, None),
        ("leader-venue-lords-wickets", "Who has taken the most wickets at Lord's?", "bowler", "wickets_taken", ["bowler"], {"venue": "Lord's, London"}, None),
        ("leader-venue-mcg-runs", "Which batter has scored the most runs at the Melbourne Cricket Ground?", "batter", "runs_scored", ["batter"], {"venue": "Melbourne Cricket Ground"}, None),
        ("leader-spin-sr", "Which batter scores fastest against spin?", "batter", "batting_strike_rate", ["batter"], {"bowling_style": "spin"}, None),
        ("leader-pace-runs", "Which batter has scored the most runs against pace?", "batter", "runs_scored", ["batter"], {"bowling_style": "pace"}, None),
        ("leader-left-arm-pace-wickets", "Which left-arm pace bowler has the most wickets?", "bowler", "wickets_taken", ["bowler"], {"bowling_style": "left_arm_pace"}, None),
        ("leader-yorker-count", "Which bowler has bowled the most yorkers?", "bowler", "yorker_count", ["bowler"], {}, None),
        ("leader-venue-boundary", "Which venue has the highest boundary percentage?", "venue", "boundary_percentage", ["venue"], {}, None),
        ("leader-venue-runs", "Which venue has the most recorded ODI runs?", "venue", "runs_scored", ["venue"], {}, None),
    ]
    for case_id, question, entity, metric, group_by, filters, direction in leaderboard_cases:
        cases.append(aggregate(case_id, "leaderboard", question, entity=entity, metric=metric, group_by=group_by, filters=filters, sort_direction=direction))

    grouped_specs = [
        ("style-sr", "Against which bowling style does {player} score fastest?", "batting_strike_rate", "bowling_style"),
        ("style-runs", "Against which bowling style has {player} scored the most runs?", "runs_scored", "bowling_style"),
        ("length-sr", "Against which length does {player} have the highest strike rate?", "batting_strike_rate", "length"),
        ("length-dismissals", "Which length dismisses {player} most often?", "dismissals", "length"),
    ]
    for player_index, batter in enumerate(["Virat Kohli", "Rohit Sharma", "Jos Buttler", "Heinrich Klaasen", "David Miller"], start=1):
        for spec_index, (prefix, question, metric, group_by) in enumerate(grouped_specs, start=1):
            cases.append(aggregate(f"{prefix}-{player_index:02d}-{spec_index:02d}", "batter_breakdown", question.format(player=batter), entity="batter", metric=metric, group_by=[group_by], filters={"batter": batter}))

    bowler_grouped_specs = [
        ("bowler-phase-economy", "In which phase is {player}'s economy rate lowest?", "economy_rate", "phase"),
        ("bowler-length-wickets", "Which length has produced the most wickets for {player}?", "wickets_taken", "length"),
    ]
    for player_index, bowler in enumerate(["Jasprit Bumrah", "Mitchell Starc", "Lasith Malinga", "Rashid Khan", "Tim Southee"], start=1):
        for spec_index, (prefix, question, metric, group_by) in enumerate(bowler_grouped_specs, start=1):
            cases.append(aggregate(f"{prefix}-{player_index:02d}-{spec_index:02d}", "bowler_breakdown", question.format(player=bowler), entity="bowler", metric=metric, group_by=[group_by], filters={"bowler": bowler}))

    cases.extend(
        [
            compare("compare-kohli-smith", "player_comparison", "Compare Virat Kohli and Steven Smith as ODI batters.", entity="batter", players=["Virat Kohli", "Steven Smith"], metrics=["runs_scored", "batting_strike_rate", "batting_average", "boundary_percentage"]),
            compare("compare-rohit-warner", "player_comparison", "Compare Rohit Sharma and David Warner as ODI batters.", entity="batter", players=["Rohit Sharma", "David Warner"], metrics=["runs_scored", "batting_strike_rate", "boundary_percentage"]),
            compare("compare-buttler-klaasen", "player_comparison", "Compare Jos Buttler and Heinrich Klaasen against spin.", entity="batter", players=["Jos Buttler", "Heinrich Klaasen"], metrics=["batting_strike_rate", "runs_scored", "boundary_percentage"], filters={"bowling_style": "spin"}),
            compare("compare-bumrah-starc", "player_comparison", "Compare Jasprit Bumrah and Mitchell Starc as ODI bowlers.", entity="bowler", players=["Jasprit Bumrah", "Mitchell Starc"], metrics=["wickets_taken", "economy_rate", "bowling_strike_rate", "bowler_dot_ball_percentage"]),
            compare("compare-bumrah-starc-death", "player_comparison", "Compare Jasprit Bumrah and Mitchell Starc in death overs.", entity="bowler", players=["Jasprit Bumrah", "Mitchell Starc"], metrics=["economy_rate", "wickets_taken", "bowler_dot_ball_percentage"], filters={"phase": "death"}),
            compare("compare-malinga-boult", "player_comparison", "Compare Lasith Malinga and Trent Boult as ODI bowlers.", entity="bowler", players=["Lasith Malinga", "Trent Boult"], metrics=["wickets_taken", "economy_rate", "yorker_percentage"]),
            matchup("matchup-smith-bumrah", "matchup", "How has Steven Smith done against Jasprit Bumrah in ODIs?", entity="matchup", metric="batting_strike_rate", group_by=[], filters={"batter": "Steven Smith", "bowler": "Jasprit Bumrah"}, limit=1),
            matchup("matchup-maxwell-ashwin", "matchup", "How has Glenn Maxwell performed against Ravichandran Ashwin?", entity="matchup", metric="runs_scored", group_by=[], filters={"batter": "Glenn Maxwell", "bowler": "Ravichandran Ashwin"}, limit=1),
            matchup("matchup-warner-dismissers", "matchup", "Which bowler has dismissed David Warner the most?", entity="bowler", metric="wickets_taken", group_by=["bowler"], filters={"batter": "David Warner"}),
            matchup("matchup-klaasen-dot-bowlers", "matchup", "Which bowler has the highest dot-ball percentage against Heinrich Klaasen?", entity="bowler", metric="bowler_dot_ball_percentage", group_by=["bowler"], filters={"batter": "Heinrich Klaasen"}),
            matchup("matchup-bumrah-batters", "matchup", "Against which batters has Jasprit Bumrah taken the most wickets?", entity="batter", metric="wickets_taken", group_by=["batter"], filters={"bowler": "Jasprit Bumrah"}),
            matchup("matchup-spin-maxwell", "matchup", "Which spin bowling style is most effective against Glenn Maxwell by dot-ball percentage?", entity="bowling_style", metric="bowler_dot_ball_percentage", group_by=["bowling_style"], filters={"batter": "Glenn Maxwell", "bowling_style": "spin"}),
            matchup("matchup-kohli-boundary-bowlers", "matchup", "Which bowler has conceded the highest boundary percentage against Virat Kohli?", entity="bowler", metric="boundary_percentage", group_by=["bowler"], filters={"batter": "Virat Kohli"}),
            matchup("matchup-miller-false-shot", "matchup", "Which bowler induces the highest false-shot percentage against David Miller?", entity="bowler", metric="false_shot_percentage", group_by=["bowler"], filters={"batter": "David Miller"}),
        ]
    )

    return cases


if __name__ == "__main__":
    raise SystemExit(main())
