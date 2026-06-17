from __future__ import annotations

from pathlib import Path

import yaml

from backend.app.domain.intent_models import AnswerShape, ContextScope, CricketMetric, QueryType, SubjectRole
from backend.app.services.query_router import QueryRouter


SUITE_PATH = Path(__file__).resolve().parents[1] / "evals" / "intent_question_suite.yaml"


def test_intent_question_suite_has_broad_valid_schema_coverage() -> None:
    suite = yaml.safe_load(SUITE_PATH.read_text())

    assert isinstance(suite, list)
    assert len(suite) >= 50
    assert len({item["id"] for item in suite}) == len(suite)

    query_types = set()
    answer_shapes = set()
    for item in suite:
        assert item["question"].strip()
        query_types.add(QueryType(item["expected_query_type"]))
        answer_shapes.add(AnswerShape(item["expected_answer_shape"]))
        ContextScope(item["expected_scope"])
        SubjectRole(item["expected_role"])
        if item.get("expected_metric"):
            CricketMetric(item["expected_metric"])

    assert {
        QueryType.single_metric,
        QueryType.leaderboard,
        QueryType.comparison,
        QueryType.trend,
        QueryType.match_fact,
        QueryType.tactical_plan,
        QueryType.strengths_weaknesses,
        QueryType.conversation,
    }.issubset(query_types)
    assert {
        AnswerShape.single_number,
        AnswerShape.leaderboard,
        AnswerShape.comparison_table,
        AnswerShape.trend_chart,
        AnswerShape.short_fact,
        AnswerShape.tactical_plan,
        AnswerShape.scouting_report,
        AnswerShape.insufficient_data,
    }.issubset(answer_shapes)


def test_deterministic_router_covers_literal_single_metric_questions_from_suite() -> None:
    router = QueryRouter(["MS Dhoni", "Jasprit Bumrah"])

    balls_bowled = router.route("How many balls bowled by MS Dhoni in 2011 world cup final?")
    assert balls_bowled.filters["metric"] == "balls_bowled"
    assert balls_bowled.filters["stage"] == "final"
    assert balls_bowled.filters["competition"] == "ICC Cricket World Cup"

    balls_faced = router.route("How many balls did MS Dhoni face in the 2011 World Cup final?")
    assert balls_faced.filters["metric"] == "balls_faced"
    assert balls_faced.filters["subject"] == "batter"

    overs_bowled = router.route("How many overs has Jasprit Bumrah bowled at the death?")
    assert overs_bowled.filters["metric"] == "overs_bowled"
    assert overs_bowled.filters["phase"] == "death"
    assert overs_bowled.filters["subject"] == "bowler"


def test_user_question_suite_matches_planner_metric_and_subject_expectations() -> None:
    suite = yaml.safe_load(SUITE_PATH.read_text())
    router = QueryRouter(
        [
            "AB de Villiers",
            "David Miller",
            "David Warner",
            "Glenn Maxwell",
            "Hardik Pandya",
            "Heinrich Klaasen",
            "Jasprit Bumrah",
            "Jos Buttler",
            "Kane Williamson",
            "Lasith Malinga",
            "Mitchell Starc",
            "MS Dhoni",
            "Pat Cummins",
            "Ravichandran Ashwin",
            "Rohit Sharma",
            "Shimron Hetmyer",
            "Steven Smith",
            "Tim Southee",
            "Travis Head",
            "Virat Kohli",
        ]
    )

    failures = []
    for item in suite:
        if not str(item["id"]).startswith("user-"):
            continue
        route = router.route(item["question"])
        expected_metric = item.get("expected_metric")
        expected_role = item.get("expected_role")
        if expected_metric and route.filters.get("metric") != expected_metric:
            failures.append(f"{item['id']}: metric {route.filters.get('metric')} != {expected_metric}")
        if expected_role and route.filters.get("subject") != expected_role:
            failures.append(f"{item['id']}: subject {route.filters.get('subject')} != {expected_role}")

    assert failures == []
