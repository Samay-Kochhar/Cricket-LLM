from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.app.bootstrap import get_services
from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.main import app
from backend.app.services.chat_service import ChatService


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture()
def client() -> Iterator[TestClient]:
    config = AppConfig.from_env()
    repository = AnalyticsRepository(config.duckdb_path)
    gemini = FakeGeminiClient()
    semantic = SemanticAnalyticsService(repository=repository, gemini_client=gemini, app_env="development")
    chat_service = ChatService(repository=repository, query_handler=semantic.answer_question, gemini_client=gemini)
    app.dependency_overrides[get_services] = lambda: {
        "repository": repository,
        "query_handler": semantic.answer_question,
        "chat_service": chat_service,
    }
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "message,expected_operation",
    [
        ("what is dot ball percentage of virat kohli?", "aggregate"),
        ("Where does Hardik Pandya score the most and on which shots?", "batting_profile"),
        ("Which bowler has dismissed David Miller most often?", "matchup"),
        ("Which bowler has the biggest difference between powerplay and death-over economy?", "split_compare"),
    ],
)
def test_chat_path_answers_phase1_question_shapes(
    client: TestClient,
    message: str,
    expected_operation: str,
) -> None:
    response = client.post("/api/chat", json={"message": message, "history": []})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "analysis"
    assert payload["query_response"]["status"] == "supported"
    assert expected_operation in str(payload["query_response"]["interpretation"]["filters"].values())
    assert "ON_DRIVE" not in str(payload)


def test_chat_named_batter_scoring_by_line_keeps_batter_perspective(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "Which line does Virat Kohli score most against?", "history": []},
    )

    assert response.status_code == 200
    payload = response.json()
    result = payload["query_response"]
    filters = result["interpretation"]["filters"]

    assert payload["mode"] == "analysis"
    assert result["status"] == "supported"
    assert filters["semantic_operation"] == "aggregate"
    assert filters["semantic_metric"] == "runs_scored"
    assert filters["semantic_group_by"] == ["line"]
    assert filters["batter"] == "Virat Kohli"
    assert "Bowler" not in result["tables"][0]["columns"]


def test_chat_named_batter_dismissal_by_length_keeps_batter_filter(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "Where is David Miller dismissed most often by length?", "history": []},
    )

    assert response.status_code == 200
    payload = response.json()
    result = payload["query_response"]
    filters = result["interpretation"]["filters"]

    assert payload["mode"] == "analysis"
    assert result["status"] == "supported"
    assert filters["semantic_metric"] == "wickets_taken"
    assert filters["semantic_group_by"] == ["length"]
    assert filters["batter"] == "David Miller"
    assert "bowler" not in filters
    assert result["tables"][0]["columns"][:2] == ["Length", "Wickets Taken"]


def test_chat_named_bowler_dot_count_by_length_uses_bowler_denominator(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "How many dot balls does Bumrah bowl by length?", "history": []},
    )

    assert response.status_code == 200
    payload = response.json()
    result = payload["query_response"]
    filters = result["interpretation"]["filters"]

    assert payload["mode"] == "analysis"
    assert result["status"] == "supported"
    assert filters["semantic_metric"] == "bowler_dot_balls"
    assert filters["semantic_group_by"] == ["length"]
    assert filters["bowler"] == "Jasprit Bumrah"
    assert "batter" not in filters
    assert result["tables"][0]["columns"][:3] == [
        "Length",
        "Bowler Dot Balls",
        "Legal Balls",
    ]
    assert "1867 legal balls" in payload["message"]


def test_chat_specific_spin_subtype_is_not_broadened_by_generic_style_wording(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "What is Maxwell's batting strike rate against off spin bowling?",
            "history": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    result = payload["query_response"]

    assert payload["mode"] == "analysis"
    assert result["status"] == "supported"
    assert result["interpretation"]["filters"]["batter"] == "Glenn Maxwell"
    assert result["interpretation"]["filters"]["bowling_style"] == "off_spin"


def test_chat_false_shot_leaderboard_states_scope_and_uses_reliable_default_sample(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "Who has the worst false shot percentage against leg spinners?",
            "history": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    message = payload["message"]
    plan = payload["query_response"]["interpretation"]["filters"]

    assert payload["query_response"]["status"] == "supported"
    assert "against leg spin" in message.lower()
    assert "available odi dataset" not in message.lower()
    assert "minimum sample" not in message.lower()
    assert plan["bowling_style"] == "leg_spin"


def test_chat_most_yorkers_ranks_count_with_limit_and_phase_scope(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={
            "message": "Show the top 3 bowlers who bowled the most yorkers at the death",
            "history": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    result = payload["query_response"]
    filters = result["interpretation"]["filters"]

    assert payload["mode"] == "analysis"
    assert result["status"] == "supported"
    assert filters["semantic_metric"] == "yorker_count"
    assert filters["phase"] == "death"
    assert len(result["tables"][0]["rows"]) == 3
    assert result["tables"][0]["columns"][:2] == ["Bowler", "Yorker Count"]


def test_chat_vague_best_statistics_asks_user_to_choose_a_metric(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "Who has the best statistics?", "history": []},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "clarification"
    assert payload["query_response"] is None
    assert "metric" in payload["message"].lower()
    assert [option["label"] for option in payload["clarification_options"]] == [
        "Runs scored",
        "Batting strike rate",
        "Wickets taken",
        "Economy rate",
    ]

    clarified = client.post(
        "/api/chat",
        json={
            "message": payload["clarification_options"][0]["message"],
            "history": [
                {"role": "user", "content": "Who has the best statistics?"},
                {"role": "assistant", "content": payload["message"]},
            ],
        },
    )
    clarified_payload = clarified.json()
    assert clarified_payload["mode"] == "analysis"
    assert clarified_payload["query_response"]["status"] == "supported"
    assert (
        clarified_payload["query_response"]["interpretation"]["filters"]["semantic_metric"]
        == "runs_scored"
    )


def test_unqualified_style_filtered_strike_rate_asks_for_metric_clarification(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "What is Maxwell's strike rate against off spinners?", "history": []},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "clarification"
    assert payload["suggestions"] == []
    assert [option["label"] for option in payload["clarification_options"]] == [
        "Batting strike rate",
        "Bowling strike rate",
    ]

    clarified = client.post(
        "/api/chat",
        json={
            "message": payload["clarification_options"][0]["message"],
            "history": [
                {
                    "role": "user",
                    "content": "What is Maxwell's strike rate against off spinners?",
                },
                {"role": "assistant", "content": payload["message"]},
            ],
        },
    )

    clarified_payload = clarified.json()
    assert clarified_payload["query_response"]["status"] == "supported"
    filters = clarified_payload["query_response"]["interpretation"]["filters"]
    assert filters["batter"] == "Glenn Maxwell"
    assert filters["bowling_style"] == "off_spin"
    assert filters["semantic_metric"] == "batting_strike_rate"


def test_comparison_phase_suggestion_passes_as_an_exact_history_chain(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={"message": "Compare Bumrah and Starc in death overs", "history": []},
    )
    assert first.status_code == 200
    first_payload = first.json()
    suggestion = "Compare the same players in powerplay, middle, and death overs."
    assert suggestion in first_payload["suggestions"]

    second = client.post(
        "/api/chat",
        json={
            "message": suggestion,
            "history": [
                {"role": "user", "content": "Compare Bumrah and Starc in death overs"},
                {"role": "assistant", "content": first_payload["message"]},
            ],
            "conversation_state": first_payload["conversation_state"],
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["query_response"]["status"] == "supported"
    assert payload["query_response"]["interpretation"]["filters"]["comparison_view"] == "phase"
    assert len(payload["query_response"]["tables"][0]["rows"]) == 6


def test_comparison_follow_up_replaces_venue_and_preserves_structured_context(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "Compare Virat Kohli and Rohit Sharma by runs scored in death overs.",
            "history": [],
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["query_response"]["status"] == "supported"
    assert first_payload["conversation_state"] is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "What about at Wankhede?",
            "history": [
                {
                    "role": "user",
                    "content": "Compare Virat Kohli and Rohit Sharma by runs scored in death overs.",
                },
                {"role": "assistant", "content": first_payload["message"]},
            ],
            "conversation_state": first_payload["conversation_state"],
        },
    )

    assert second.status_code == 200
    payload = second.json()
    filters = payload["query_response"]["interpretation"]["filters"]
    assert filters["compare_players"] == ["Rohit Sharma", "Virat Kohli"]
    assert set(filters["comparison_metrics"]) == set(
        first_payload["conversation_state"]["comparison_metrics"]
    )
    assert filters["phase"] == "death"
    assert filters["venue"] == "Wankhede Stadium, Mumbai"


def test_comparison_follow_up_keeps_real_rows_when_batting_average_is_undefined(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "Compare Virat Kohli and Rohit Sharma in death overs.",
            "history": [],
        },
    )
    original_state = first.json()["conversation_state"]
    assert original_state is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "What about at Eden Gardens, Kolkata?",
            "history": [],
            "conversation_state": original_state,
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["query_response"]["status"] == "supported"
    table = payload["query_response"]["tables"][0]
    player_index = table["columns"].index("Player")
    average_index = table["columns"].index("Batting Average")
    rows_by_player = {row[player_index]: row for row in table["rows"]}
    assert rows_by_player["Virat Kohli"][average_index] == "N/A — not dismissed"
    assert "26 runs from 26 balls" in payload["message"]


def test_comparison_follow_up_replaces_time_scope_and_preserves_participants(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "Compare Virat Kohli and Rohit Sharma in death overs.",
            "history": [],
        },
    )
    first_payload = first.json()
    original_state = first_payload["conversation_state"]
    assert original_state is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "Since 2020?",
            "history": [],
            "conversation_state": original_state,
        },
    )

    assert second.status_code == 200
    filters = second.json()["query_response"]["interpretation"]["filters"]
    assert filters["compare_players"] == ["Rohit Sharma", "Virat Kohli"]
    assert set(filters["comparison_metrics"]) == set(original_state["comparison_metrics"])
    assert filters["phase"] == "death"
    assert filters["years"] == [2020]
    assert filters["year_mode"] == "after"


def test_comparison_follow_up_replaces_style_and_preserves_participants(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "Compare Virat Kohli and Rohit Sharma against spin.",
            "history": [],
        },
    )
    first_payload = first.json()
    original_state = first_payload["conversation_state"]
    assert original_state is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "Leg-spin?",
            "history": [],
            "conversation_state": original_state,
        },
    )

    assert second.status_code == 200
    filters = second.json()["query_response"]["interpretation"]["filters"]
    assert filters["compare_players"] == ["Rohit Sharma", "Virat Kohli"]
    assert set(filters["comparison_metrics"]) == set(original_state["comparison_metrics"])
    assert filters["bowling_style"] == "leg_spin"


def test_matchup_follow_up_replaces_phase_and_preserves_structured_matchup(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "How did Steve Smith perform against Jasprit Bumrah?",
            "history": [],
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["query_response"]["status"] == "supported"
    assert first_payload["conversation_state"] is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "And in death overs?",
            "history": [],
            "conversation_state": first_payload["conversation_state"],
        },
    )

    assert second.status_code == 200
    payload = second.json()
    filters = payload["query_response"]["interpretation"]["filters"]
    assert filters["batter"] == "Steven Smith"
    assert filters["bowler"] == "Jasprit Bumrah"
    assert filters["phase"] == "death"
    assert filters["semantic_operation"] == "matchup"
    assert filters["semantic_metric"] == first_payload["conversation_state"]["metric"]


def test_trend_follow_up_replaces_metric_and_window_but_preserves_player_role(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "Mitchell Starc death-over economy trend after 2018",
            "history": [],
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["query_response"]["status"] == "supported"
    assert first_payload["conversation_state"] is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "What about wickets after 2020?",
            "history": [],
            "conversation_state": first_payload["conversation_state"],
        },
    )

    assert second.status_code == 200
    payload = second.json()
    filters = payload["query_response"]["interpretation"]["filters"]
    assert filters["bowler"] == "Mitchell Starc"
    assert filters["phase"] == "death"
    assert filters["years"] == [2020]
    assert filters["year_mode"] == "after"
    assert filters["semantic_metric"] == "wickets_taken"
    assert filters["semantic_group_by"] == ["year"]


def test_ambiguous_follow_up_clarifies_without_mutating_structured_state(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "What is Virat Kohli's batting strike rate in death overs?",
            "history": [],
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    original_state = first_payload["conversation_state"]
    assert original_state is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "What about strike rate?",
            "history": [],
            "conversation_state": original_state,
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["mode"] == "clarification"
    assert payload["conversation_state"] == original_state
    assert [option["label"] for option in payload["clarification_options"]] == [
        "Batting strike rate",
        "Bowling strike rate",
    ]


def test_non_analytical_turn_does_not_break_the_next_structured_follow_up(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "What is Virat Kohli's batting strike rate in death overs?",
            "history": [],
        },
    )
    first_payload = first.json()
    original_state = first_payload["conversation_state"]
    assert original_state is not None

    unrelated = client.post(
        "/api/chat",
        json={
            "message": "Teach me how to judge spin weakness.",
            "history": [],
            "conversation_state": original_state,
        },
    )
    assert unrelated.status_code == 200
    unrelated_payload = unrelated.json()
    assert unrelated_payload["conversation_state"] == original_state

    follow_up = client.post(
        "/api/chat",
        json={
            "message": "Powerplay?",
            "history": [],
            "conversation_state": unrelated_payload["conversation_state"],
        },
    )

    assert follow_up.status_code == 200
    filters = follow_up.json()["query_response"]["interpretation"]["filters"]
    assert filters["batter"] == "Virat Kohli"
    assert filters["phase"] == "powerplay"
    assert filters["semantic_metric"] == "batting_strike_rate"


def test_ambiguous_venue_follow_up_offers_choices_without_mutating_state(
    client: TestClient,
) -> None:
    first = client.post(
        "/api/chat",
        json={
            "message": "Compare Virat Kohli and Rohit Sharma by runs scored.",
            "history": [],
        },
    )
    first_payload = first.json()
    original_state = first_payload["conversation_state"]
    assert original_state is not None

    second = client.post(
        "/api/chat",
        json={
            "message": "What about in Melbourne?",
            "history": [],
            "conversation_state": original_state,
        },
    )

    assert second.status_code == 200
    payload = second.json()
    assert payload["mode"] == "clarification"
    assert payload["conversation_state"] == original_state
    assert [option["label"] for option in payload["clarification_options"]] == [
        "Docklands Stadium, Melbourne",
        "Melbourne Cricket Ground",
    ]

    clarified = client.post(
        "/api/chat",
        json={
            "message": payload["clarification_options"][1]["message"],
            "history": [],
            "conversation_state": payload["conversation_state"],
        },
    )
    clarified_filters = clarified.json()["query_response"]["interpretation"]["filters"]
    assert clarified_filters["compare_players"] == ["Rohit Sharma", "Virat Kohli"]
    assert clarified_filters["venue"] == "Melbourne Cricket Ground"
