from __future__ import annotations

import json

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.evidence_models import (
    EvidenceStatus,
    InsufficientEvidenceBlock,
    QueryInterpretation,
    QueryResponse,
    SummaryBlock,
)
from backend.app.services.chat_service import ChatService
from backend.app.services.workbench_service import WorkbenchService


PLAYERS = [
    "Virat Kohli",
    "Rohit Sharma",
    "Ishant Sharma",
    "Mohit Sharma",
    "Tino Best",
    "Mitchell Starc",
    "Hardik Pandya",
    "Krunal Pandya",
]


class FakeRepository:
    def list_player_names(self) -> list[str]:
        return list(PLAYERS)

    def list_teams(self) -> list[str]:
        return ["India", "West Indies", "South Africa"]

    def get_team_available_years(self, team_name: str) -> list[int]:
        return [2023, 2022, 2021]

    def get_team_year_squad(self, team_name: str, year: int) -> list[dict[str, object]]:
        return [{"player_name": "Virat Kohli", "role_summary": "Right-hand bat | ODI batter profile"}]

    def get_player_batting_summary(self, player_name: str, phase: str | None = None) -> dict[str, object]:
        return {"runs_scored": 13848, "balls_faced": 15000}

    def get_primary_batting_hand(self, player_name: str, bowler_name: str | None = None, phase: str | None = None) -> str:
        return "RHB"

    def get_player_split_summary(self, player_name: str, phase: str | None = None) -> dict[str, float]:
        return {"pace_strike_rate": 92.0, "spin_strike_rate": 88.0}


class RecordingHandler:
    def __init__(self, response: QueryResponse | None = None) -> None:
        self.questions: list[str] = []
        self.response = response

    def __call__(self, question: str) -> QueryResponse:
        self.questions.append(question)
        if self.response is not None:
            return self.response
        return QueryResponse(
            status=EvidenceStatus.supported,
            interpretation=QueryInterpretation(
                original_question=question,
                query_class="role_comparison",
                entities=[],
            ),
            summaries=[SummaryBlock(title="Answer", body=f"Answer to {question}")],
        )


def _response(entities: list[str], **extra: object) -> QueryResponse:
    return QueryResponse(
        status=extra.pop("status", EvidenceStatus.supported),
        interpretation=QueryInterpretation(
            original_question="question",
            query_class="role_comparison",
            entities=entities,
        ),
        summaries=[SummaryBlock(title="Answer", body="Database answer.")],
        **extra,
    )


def _service(
    analytics: RecordingHandler | None = None,
    profile: RecordingHandler | None = None,
) -> tuple[WorkbenchService, RecordingHandler, RecordingHandler]:
    analytics = analytics or RecordingHandler()
    profile = profile or RecordingHandler()
    return WorkbenchService(FakeRepository(), analytics, profile), analytics, profile


def test_exact_player_lookup_keeps_the_approved_player_profile_result() -> None:
    service, analytics, profile = _service()

    payload = service.search("Virat Kohli")

    assert payload["kind"] == "player_result"
    assert payload["player_name"] == "Virat Kohli"
    assert payload["role_summary"] == "Right-hand bat | ODI batter profile | 13848 ODI runs"
    assert profile.questions == ["show me some stats of Virat Kohli"]
    assert analytics.questions == []


@pytest.mark.parametrize("query", ["kohli", "Virat", "  virat kohli  "])
def test_exact_alias_or_unique_name_word_selects_one_player(query: str) -> None:
    service, analytics, profile = _service()

    payload = service.search(query)

    assert payload["kind"] == "player_result"
    assert payload["player_name"] == "Virat Kohli"
    assert analytics.questions == []


def test_team_with_year_returns_squad_and_team_without_year_requests_year() -> None:
    service, analytics, _ = _service()

    squad = service.search("India 2019")
    squad_with_word = service.search("West Indies squad 2021")
    year_required = service.search("India")

    assert (squad["kind"], squad["team_name"], squad["year"]) == ("team_squad", "India", 2019)
    assert (squad_with_word["kind"], squad_with_word["team_name"]) == ("team_squad", "West Indies")
    assert year_required["kind"] == "team_year_required"
    assert year_required["team_name"] == "India"
    assert year_required["available_years"] == [2023, 2022, 2021]
    assert analytics.questions == []


@pytest.mark.parametrize(
    ("query", "options"),
    [
        ("Sharma", ["Ishant Sharma", "Mohit Sharma", "Rohit Sharma"]),
        ("Pandya", ["Hardik Pandya", "Krunal Pandya"]),
    ],
)
def test_ambiguous_surname_returns_targeted_player_choices(query: str, options: list[str]) -> None:
    service, analytics, profile = _service()

    payload = service.search(query)

    assert payload["kind"] == "clarification"
    assert payload["message"] == "Which player do you mean?"
    assert payload["options"] == [{"label": name, "query": name} for name in options]
    assert analytics.questions == profile.questions == []


def test_best_death_over_bowlers_is_an_analytics_ranking_not_tino_best() -> None:
    question = "Show the best death-over bowlers with at least 300 balls"
    service, analytics, profile = _service()

    payload = service.search(question)

    assert payload["kind"] == "analytics_result"
    assert "player_name" not in payload
    assert analytics.questions == [question]
    assert profile.questions == []
    assert "Tino Best" not in json.dumps(payload)


@pytest.mark.parametrize(
    "question",
    [
        "Who has the best economy in death overs?",
        "Most runs in successful chases",
        "Which bowling team has the lowest economy against India?",
        "best economy",
        "most runs",
    ],
)
def test_ordinary_metric_and_ranking_words_never_become_players(question: str) -> None:
    service, analytics, profile = _service()

    payload = service.search(question)

    assert payload["kind"] == "analytics_result"
    assert analytics.questions == [question]
    assert profile.questions == []


def test_two_player_question_is_answered_as_one_analytics_result() -> None:
    question = "Compare Virat Kohli and Rohit Sharma in death overs"
    service, analytics, _ = _service(RecordingHandler(_response(["Rohit Sharma", "Virat Kohli"])))

    payload = service.search(question)

    assert payload["kind"] == "analytics_result"
    assert payload["query"] == question
    assert payload["query_response"]["interpretation"]["entities"] == ["Rohit Sharma", "Virat Kohli"]
    assert analytics.questions == [question]


def test_single_player_analytics_keeps_the_player_card_with_shared_meaning() -> None:
    question = "death over batting strike rate of Hardik Pandya"
    service, analytics, profile = _service(RecordingHandler(_response(["Hardik Pandya"])))

    payload = service.search(question)

    assert payload["kind"] == "player_result"
    assert payload["player_name"] == "Hardik Pandya"
    assert payload["query"] == question
    assert analytics.questions == [question]
    assert profile.questions == []


def test_shared_analytics_clarification_offers_targeted_choices() -> None:
    question = "Tell me about Khan"
    response = _response(
        [],
        clarification_question="Which player do you mean?",
        clarification_options=["Rashid Khan", "Zaheer Khan"],
    )
    service, _, _ = _service(RecordingHandler(response))

    payload = service.search(question)

    assert payload["kind"] == "clarification"
    assert payload["message"] == "Which player do you mean?"
    assert payload["options"] == [
        {"label": "Rashid Khan", "query": "Tell me about Khan Use Rashid Khan."},
        {"label": "Zaheer Khan", "query": "Tell me about Khan Use Zaheer Khan."},
    ]


def test_unqualified_strike_rate_asks_the_same_metric_choice_as_chat() -> None:
    question = "Who has the highest strike rate in death overs?"
    service, analytics, _ = _service()

    payload = service.search(question)

    assert payload["kind"] == "clarification"
    assert payload["message"] == "Do you mean batting strike rate or bowling strike rate?"
    assert [option["query"] for option in payload["options"]] == [
        "Who has the highest batting strike rate in death overs?",
        "Who has the highest bowling strike rate in death overs?",
    ]
    assert analytics.questions == []


def test_unsupported_analytics_explains_the_limitation() -> None:
    response = _response(
        [],
        status=EvidenceStatus.unsupported,
        insufficiencies=[
            InsufficientEvidenceBlock(
                title="Unsupported",
                detail="Future match prediction is outside the historical ODI analytics capability.",
            )
        ],
    )
    service, _, _ = _service(RecordingHandler(response))

    payload = service.search("Who will win the next ODI?")

    assert payload["kind"] == "unsupported"
    assert payload["message"] == "Future match prediction is outside the historical ODI analytics capability."


def test_empty_query_is_rejected() -> None:
    service, analytics, profile = _service()

    assert service.search("   ")["kind"] == "empty"
    assert analytics.questions == profile.questions == []


class OfflineGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture(scope="module")
def real_services() -> tuple[WorkbenchService, ChatService]:
    repository = AnalyticsRepository(AppConfig.from_env().duckdb_path)
    semantic_service = SemanticAnalyticsService(
        repository=repository,
        gemini_client=OfflineGeminiClient(),
        app_env="development",
        allow_dev_fallback=True,
    )

    def query_handler(question: str, conversation_state=None) -> QueryResponse:
        return semantic_service.answer_question(question, conversation_state=conversation_state)

    def profile_handler(question: str) -> QueryResponse:
        raise AssertionError("natural-language analytics must not use the profile handler")

    workbench = WorkbenchService(repository, query_handler, profile_handler)
    chat = ChatService(repository=repository, query_handler=query_handler, gemini_client=OfflineGeminiClient())
    return workbench, chat


def _semantic_meaning(query_response: dict[str, object]) -> dict[str, object]:
    filters = dict(query_response["interpretation"]["filters"])
    return {
        "entities": query_response["interpretation"]["entities"],
        "filters": filters,
    }


@pytest.mark.parametrize(
    "question",
    [
        "Compare Virat Kohli and Rohit Sharma in death overs",
        "Kohli versus Starc head to head",
        "Which bowling team has the lowest economy against India?",
        "Who scored most runs in successful ODI chases?",
    ],
)
def test_workbench_and_chat_compile_the_same_semantic_meaning(
    real_services: tuple[WorkbenchService, ChatService],
    question: str,
) -> None:
    workbench, chat = real_services

    payload = workbench.search(question)
    reply = chat.reply(question, [])

    assert payload["kind"] == "analytics_result"
    assert reply.query_response is not None
    assert _semantic_meaning(payload["query_response"]) == _semantic_meaning(
        reply.query_response.model_dump()
    )


def test_real_two_player_death_question_keeps_both_players_and_death_filter(
    real_services: tuple[WorkbenchService, ChatService],
) -> None:
    workbench, _ = real_services

    filters = workbench.search("Compare Virat Kohli and Rohit Sharma in death overs")[
        "query_response"
    ]["interpretation"]["filters"]

    assert filters["semantic_operation"] == "player_compare"
    assert sorted(filters["compare_players"]) == ["Rohit Sharma", "Virat Kohli"]
    assert filters["phase"] == "death"


def test_real_head_to_head_routes_to_batter_bowler_matchup(
    real_services: tuple[WorkbenchService, ChatService],
) -> None:
    workbench, _ = real_services

    payload = workbench.search("Kohli versus Starc head to head")
    filters = payload["query_response"]["interpretation"]["filters"]

    assert payload["kind"] == "analytics_result"
    assert filters["semantic_operation"] == "matchup"
    assert (filters["batter"], filters["bowler"]) == ("Virat Kohli", "Mitchell Starc")
    assert "Virat Kohli scored 156 runs from 155 balls against Mitchell Starc" in payload["summary"]


def test_real_best_bowlers_question_never_resolves_tino_best(
    real_services: tuple[WorkbenchService, ChatService],
) -> None:
    workbench, _ = real_services

    payload = workbench.search("Show the best death-over bowlers with at least 300 balls")

    assert payload["kind"] == "analytics_result"
    assert "Tino Best" not in json.dumps(payload)
    assert payload["query_response"]["interpretation"]["filters"]["phase"] == "death"


def test_real_ambiguous_surname_lists_every_repository_match(
    real_services: tuple[WorkbenchService, ChatService],
) -> None:
    workbench, _ = real_services

    payload = workbench.search("Sharma")

    assert payload["kind"] == "clarification"
    assert [option["label"] for option in payload["options"]] == [
        "Aryansh Sharma",
        "Ishant Sharma",
        "Joginder Sharma",
        "Karn Sharma",
        "Mohit Sharma",
        "Rahul Sharma",
        "Rohit Sharma",
        "Sanchit Sharma",
    ]


def test_bootstrap_routes_workbench_analytics_through_the_chat_query_handler() -> None:
    from backend.app.bootstrap import get_services

    services = get_services()

    assert services["workbench_service"].query_handler is services["query_handler"]
    assert services["chat_service"].query_handler is services["query_handler"]
