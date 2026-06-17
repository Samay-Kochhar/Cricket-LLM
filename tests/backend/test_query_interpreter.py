from backend.app.domain.metric_models import QueryClass
from backend.app.domain.intent_models import AnswerShape, ContextScope, CricketMetric, QueryType, SubjectRole
from backend.app.services.query_interpreter import QueryInterpreter
from backend.app.services.query_router import QueryRouter


class FakeRepository:
    def list_player_names(self) -> list[str]:
        return [
            "Hardik Pandya",
            "Virat Kohli",
            "Jasprit Bumrah",
            "Ravichandran Ashwin",
            "Ryan ten Doeschate",
            "Tim Southee",
            "MS Dhoni",
            "Heinrich Klaasen",
        ]

    def search_players(self, query: str, limit: int = 5) -> list[str]:
        mapping = {
            "hardik pandya": ["Hardik Pandya"],
            "virat kohli": ["Virat Kohli"],
            "jasprit bumrah": ["Jasprit Bumrah"],
            "ashwin": ["Ravichandran Ashwin"],
            "ryan ten doeschate": ["Ryan ten Doeschate"],
            "tim southee": ["Tim Southee"],
            "ms dhoni": ["MS Dhoni"],
            "heinrich klaasen": ["Heinrich Klaasen"],
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
        if "compare virat kohli at number 3 vs opening" in prompt.lower():
            return (
                '{"query_class":"head_to_head_matchup","player_mentions":["Virat Kohli"],'
                '"filters":{"position_groups":[{"label":"No. 3","positions":[3]},{"label":"Opening","positions":[1,2]}]}}'
            )
        if "jasprit bumrah" in prompt.lower() and "economy" in prompt.lower():
            return (
                '{"query_class":"role_comparison","player_mentions":["Jasprit Bumrah"],'
                '"filters":{"phase":"death"}}'
            )
        if "most catches in 2023 world cup" in prompt.lower():
            return (
                '{"query_class":"venue_context_leaderboard","player_mentions":[],'
                '"filters":{"competition":"ICC Cricket World Cup","years":[2023],'
                '"subject":"fielder","skill":"fielding","metric":"catches_taken","rank_intent":"best"}}'
            )
        if "tim southee" in prompt.lower() and "bowling figure" in prompt.lower():
            return (
                '{"query_class":"venue_context_leaderboard","player_mentions":["Tim Southee"],'
                '"filters":{"subject":"bowler","skill":"bowling","metric":"best_bowling_figures","rank_intent":"best"}}'
            )
        if "balls bowled by ms dhoni" in prompt.lower():
            return (
                '{"query_type":"single_metric","answer_shape":"single_number","query_class":"role_comparison",'
                '"metric":"balls_bowled","subjects":[{"player":"MS Dhoni","role":"bowler"}],'
                '"context":{"scope":"single_match","competition":"ICC Cricket World Cup","year":2011,'
                '"years":[2011],"stage":"final","teams":["India","Sri Lanka"]},'
                '"ambiguity":{"possible_alternate_metric":"balls_faced","reason":"Dhoni was a batter/wicketkeeper in this match"},'
                '"player_mentions":["MS Dhoni"],'
                '"filters":{"subject":"bowler","skill":"bowling","metric":"balls_bowled",'
                '"competition":"ICC Cricket World Cup","years":[2011],"stage":"final"}}'
            )
        if "against which bowling type does heinrich klaasen score fastest" in prompt.lower():
            return (
                '{"query_class":"venue_context_leaderboard","player_mentions":["Heinrich Klaasen"],'
                '"filters":{"subject":"bowler","skill":"bowling","metric":"batting_strike_rate","rank_intent":"best"}}'
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


def test_query_interpreter_keeps_position_comparison_as_role_comparison() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("Compare Virat Kohli at number 3 vs opening in ODIs")

    assert interpreted.route.query_class == QueryClass.role_comparison
    assert interpreted.route.entities == ("Virat Kohli",)
    assert interpreted.route.filters["position_groups"] == [
        {"label": "No. 3", "positions": [3]},
        {"label": "Opening", "positions": [1, 2]},
    ]


def test_query_interpreter_preserves_deterministic_bowling_intent() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("What is Jasprit Bumrah's economy rate in death overs?")

    assert interpreted.used_ai is True
    assert interpreted.route.entities == ("Jasprit Bumrah",)
    assert interpreted.route.filters["phase"] == "death"
    assert interpreted.route.filters["skill"] == "bowling"
    assert interpreted.route.filters["metric"] == "economy_rate"


def test_query_interpreter_preserves_deterministic_world_cup_2023_competition() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("Who took most catches in 2023 world cup?")

    assert interpreted.used_ai is True
    assert interpreted.route.query_class == QueryClass.venue_context_leaderboard
    assert interpreted.route.filters["competition"] == "World Cup 2023"
    assert interpreted.route.filters["years"] == [2023]
    assert interpreted.route.filters["metric"] == "catches_taken"


def test_query_interpreter_keeps_named_bowling_figures_as_player_stat() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("what are tim southee best bowling figure")

    assert interpreted.used_ai is True
    assert interpreted.route.query_class == QueryClass.role_comparison
    assert interpreted.route.entities == ("Tim Southee",)
    assert interpreted.route.filters["metric"] == "best_bowling_figures"


def test_query_interpreter_preserves_single_match_balls_bowled_intent() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("How many balls bowled by MS Dhoni in 2011 world cup final?")

    assert interpreted.used_ai is True
    assert interpreted.route.query_class == QueryClass.role_comparison
    assert interpreted.route.entities == ("MS Dhoni",)
    assert interpreted.route.filters["metric"] == "balls_bowled"
    assert interpreted.route.filters["stage"] == "final"
    assert interpreted.route.intent_plan is not None
    assert interpreted.route.intent_plan.query_type == QueryType.single_metric
    assert interpreted.route.intent_plan.answer_shape == AnswerShape.single_number
    assert interpreted.route.intent_plan.metric == CricketMetric.balls_bowled
    assert interpreted.route.intent_plan.subjects[0].role == SubjectRole.bowler
    assert interpreted.route.intent_plan.context.scope == ContextScope.single_match
    assert interpreted.route.intent_plan.context.teams == ["India", "Sri Lanka"]
    assert interpreted.route.intent_plan.ambiguity is not None
    assert interpreted.route.intent_plan.ambiguity.possible_alternate_metric == CricketMetric.balls_faced


def test_query_interpreter_overrides_bad_ai_plan_for_bowling_type_grouping() -> None:
    repository = FakeRepository()
    interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=FakeGeminiClient(),
        fallback_router=QueryRouter(repository.list_player_names()),
    )

    interpreted = interpreter.interpret("Against which bowling type does Heinrich Klaasen score fastest?")

    assert interpreted.used_ai is True
    assert interpreted.route.query_class == QueryClass.venue_context_leaderboard
    assert interpreted.route.entities == ("Heinrich Klaasen",)
    assert interpreted.route.filters["group_by"] == "bowling_style"
    assert interpreted.route.filters["subject"] == "batter"
    assert interpreted.route.filters["metric"] == "batting_strike_rate"
    assert interpreted.route.filters["rank_intent"] == "best"
