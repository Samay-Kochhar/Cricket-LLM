from backend.app.domain.metric_models import QueryClass
from backend.app.services.query_interpreter import QueryInterpreter
from backend.app.services.query_router import QueryRouter


class FakeRepository:
    def list_player_names(self) -> list[str]:
        return ["Hardik Pandya", "Virat Kohli", "Ravichandran Ashwin", "Ryan ten Doeschate"]

    def search_players(self, query: str, limit: int = 5) -> list[str]:
        mapping = {
            "hardik pandya": ["Hardik Pandya"],
            "virat kohli": ["Virat Kohli"],
            "ashwin": ["Ravichandran Ashwin"],
            "ryan ten doeschate": ["Ryan ten Doeschate"],
        }
        return mapping.get(query.lower(), [])


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return True

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        if "death over strike rate of hardik pandya" in prompt.lower():
            return (
                '{"query_class":"role_comparison","player_mentions":["hardik pandya"],'
                '"filters":{"phase":"death"}}'
            )
        if "where does hardik pandya score the most and on which shots" in prompt.lower():
            return (
                '{"query_class":"strengths_weaknesses","player_mentions":["Hardik Pandya"],'
                '"filters":{}}'
            )
        return None


def test_query_interpreter_uses_ai_to_extract_entities_and_filters() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("death over strike rate of hardik pandya")

    assert interpreted.used_ai is True
    assert interpreted.route.query_class == QueryClass.role_comparison
    assert interpreted.route.entities == ("Hardik Pandya",)
    assert interpreted.route.filters["phase"] == "death"


def test_query_interpreter_does_not_extract_filler_words_as_players() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("Where does Hardik Pandya score the most and on which shots?")

    assert interpreted.route.query_class == QueryClass.strengths_weaknesses
    assert interpreted.route.entities == ("Hardik Pandya",)
