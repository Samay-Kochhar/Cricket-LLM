from backend.app.domain.metric_models import QueryClass
from backend.app.services.query_router import QueryRouter


def test_query_router_detects_matchup_and_entities() -> None:
    router = QueryRouter(["Steven Smith", "Jasprit Bumrah", "Virat Kohli"])

    route = router.route("Bumrah vs Steven Smith in ODIs")

    assert route.query_class == QueryClass.head_to_head_matchup
    assert "Steven Smith" in route.entities


def test_query_router_detects_trend_question() -> None:
    router = QueryRouter(["Shimron Hetmyer"])

    route = router.route("Has Shimron Hetmyer become more destructive after 2020?")

    assert route.query_class == QueryClass.trend_progression
    assert route.filters["years"] == [2020]
    assert route.filters["year_mode"] == "after"
