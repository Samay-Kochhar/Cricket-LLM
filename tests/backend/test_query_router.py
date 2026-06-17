from backend.app.domain.metric_models import QueryClass
from backend.app.services.query_router import QueryRouter


def test_query_router_detects_matchup_and_entities() -> None:
    router = QueryRouter(["Steven Smith", "Jasprit Bumrah", "Virat Kohli"])

    route = router.route("Steven Smith vs Jasprit Bumrah in ODIs")

    assert route.query_class == QueryClass.head_to_head_matchup
    assert route.entities == ("Steven Smith", "Jasprit Bumrah")


def test_query_router_detects_trend_question() -> None:
    router = QueryRouter(["Shimron Hetmyer"])

    route = router.route("Has Shimron Hetmyer become more destructive after 2020?")

    assert route.query_class == QueryClass.trend_progression
    assert route.filters["years"] == [2020]
    assert route.filters["year_mode"] == "after"


def test_query_router_extracts_batting_position_groups() -> None:
    router = QueryRouter(["Virat Kohli"])

    route = router.route("Compare Virat Kohli at number 3 vs opening in ODIs")

    assert route.query_class == QueryClass.role_comparison
    assert route.entities == ("Virat Kohli",)
    assert route.filters["position_groups"] == [
        {"label": "No. 3", "positions": [3]},
        {"label": "Opening", "positions": [1, 2]},
    ]


def test_query_router_marks_bowling_economy_intent() -> None:
    router = QueryRouter(["Jasprit Bumrah"])

    route = router.route("What is Jasprit Bumrah's economy rate in death overs?")

    assert route.query_class == QueryClass.role_comparison
    assert route.entities == ("Jasprit Bumrah",)
    assert route.filters["phase"] == "death"
    assert route.filters["skill"] == "bowling"
    assert route.filters["metric"] == "economy_rate"


def test_query_router_preserves_balls_bowled_metric() -> None:
    router = QueryRouter(["MS Dhoni"])

    route = router.route("How many balls bowled by MS Dhoni in 2011 world cup final?")

    assert route.query_class == QueryClass.role_comparison
    assert route.entities == ("MS Dhoni",)
    assert route.filters["years"] == [2011]
    assert route.filters["competition"] == "ICC Cricket World Cup"
    assert route.filters["stage"] == "final"
    assert route.filters["subject"] == "bowler"
    assert route.filters["skill"] == "bowling"
    assert route.filters["metric"] == "balls_bowled"


def test_query_router_preserves_balls_faced_metric() -> None:
    router = QueryRouter(["MS Dhoni"])

    route = router.route("How many balls faced by MS Dhoni in 2011 world cup final?")

    assert route.entities == ("MS Dhoni",)
    assert route.filters["subject"] == "batter"
    assert route.filters["skill"] == "batting"
    assert route.filters["metric"] == "balls_faced"


def test_query_router_detects_named_best_bowling_figures() -> None:
    router = QueryRouter(["Tim Southee"])

    route = router.route("what are Tim Southee best bowling figures?")

    assert route.query_class == QueryClass.role_comparison
    assert route.entities == ("Tim Southee",)
    assert route.filters["subject"] == "bowler"
    assert route.filters["skill"] == "bowling"
    assert route.filters["metric"] == "best_bowling_figures"


def test_query_router_detects_opponent_wise_split() -> None:
    router = QueryRouter(["James Anderson"])

    route = router.route("opponent wise performance of James Anderson, sort them from most successful to least successful")

    assert route.query_class == QueryClass.role_comparison
    assert route.entities == ("James Anderson",)
    assert route.filters["group_by"] == "opponent"
    assert route.filters["rank_intent"] == "best"


def test_query_router_detects_venue_wise_player_split() -> None:
    router = QueryRouter(["Kane Williamson"])

    route = router.route("venue wise performance of Kane Williamson")

    assert route.query_class == QueryClass.role_comparison
    assert route.entities == ("Kane Williamson",)
    assert route.filters["group_by"] == "venue"


def test_query_router_groups_bowling_type_questions_by_style() -> None:
    router = QueryRouter(["Travis Head"])

    route = router.route("Against which bowling type does Travis Head score fastest?")

    assert route.query_class == QueryClass.venue_context_leaderboard
    assert route.entities == ("Travis Head",)
    assert route.filters["group_by"] == "bowling_style"
    assert route.filters["subject"] == "batter"
    assert route.filters["metric"] == "batting_strike_rate"


def test_query_router_treats_mid_wicket_as_batting_field_zone() -> None:
    router = QueryRouter(["Virat Kohli"])

    route = router.route("which batter score must runs in mid-wicket area?")

    assert route.query_class == QueryClass.venue_context_leaderboard
    assert route.entities == ()
    assert route.filters["subject"] == "batter"
    assert route.filters["skill"] == "batting"
    assert route.filters["metric"] == "runs_scored"
    assert route.filters["field_zone"] == "midwicket"
    assert route.filters["rank_intent"] == "best"


def test_query_router_detects_year_by_year_trend_question() -> None:
    router = QueryRouter(["Jasprit Bumrah"])

    route = router.route("Break Jasprit Bumrah down year by year as a bowler")

    assert route.query_class == QueryClass.trend_progression
    assert route.entities == ("Jasprit Bumrah",)
    assert route.filters["skill"] == "bowling"


def test_query_router_detects_global_bowling_economy_leaderboard() -> None:
    router = QueryRouter(["Jasprit Bumrah"])

    route = router.route("Which bowler has the best death-over economy since 2022?")

    assert route.query_class == QueryClass.venue_context_leaderboard
    assert route.entities == ()
    assert route.filters["phase"] == "death"
    assert route.filters["skill"] == "bowling"
    assert route.filters["metric"] == "economy_rate"
    assert route.filters["years"] == [2022]
    assert route.filters["year_mode"] == "after"
    assert route.filters["rank_intent"] == "best"


def test_query_router_detects_worst_bowling_economy_leaderboard() -> None:
    router = QueryRouter(["Jasprit Bumrah"])

    route = router.route("Which bowler has the worst economy in powerplay?")

    assert route.query_class == QueryClass.venue_context_leaderboard
    assert route.entities == ()
    assert route.filters["phase"] == "powerplay"
    assert route.filters["skill"] == "bowling"
    assert route.filters["metric"] == "economy_rate"
    assert route.filters["rank_intent"] == "worst"


def test_query_router_treats_highest_wickets_as_best_rank_intent() -> None:
    router = QueryRouter(["Jasprit Bumrah"])

    route = router.route("Which bowler has highest number of wickets in powerplay?")

    assert route.query_class == QueryClass.venue_context_leaderboard
    assert route.entities == ()
    assert route.filters["phase"] == "powerplay"
    assert route.filters["skill"] == "bowling"
    assert route.filters["metric"] == "wickets_taken"
    assert route.filters["rank_intent"] == "best"


def test_query_router_resolves_matchup_aliases_in_question_order() -> None:
    router = QueryRouter(["David Miller", "Rashid Khan", "Jasprit Bumrah", "David Warner"])

    route = router.route("How many runs has Miller scored against Rashid Khan?")

    assert route.query_class == QueryClass.head_to_head_matchup
    assert route.entities == ("David Miller", "Rashid Khan")
    assert route.filters["metric"] == "runs_scored"


def test_query_router_detects_delivery_and_target_batter_leaderboards() -> None:
    router = QueryRouter(["David Miller"])

    yorkers = router.route("Which bowler bowls the most yorkers?")
    short_balls = router.route("Which batter should be targeted with short-ball tactics?")
    short_ball_average = router.route("Which batter has the lowest average against short balls?")

    assert yorkers.query_class == QueryClass.venue_context_leaderboard
    assert yorkers.filters["subject"] == "bowler"
    assert yorkers.filters["length"] == "YORKER"
    assert yorkers.filters["metric"] == "yorker_count"
    assert short_balls.query_class == QueryClass.venue_context_leaderboard
    assert short_balls.filters["subject"] == "batter"
    assert short_balls.filters["length"] == "SHORT"
    assert short_balls.filters["metric"] == "batting_strike_rate"
    assert short_balls.filters["rank_intent"] == "worst"
    assert short_ball_average.filters["subject"] == "batter"
    assert short_ball_average.filters["length"] == "SHORT"
    assert short_ball_average.filters["metric"] == "batting_average"
    assert short_ball_average.filters["rank_intent"] == "worst"


def test_query_router_detects_world_cup_competition_filter() -> None:
    router = QueryRouter([])

    route = router.route("Who took most wickets in cricket world cup 2011?")
    catches = router.route("Who took most catches in 2023 world cup?")

    assert route.query_class == QueryClass.venue_context_leaderboard
    assert route.filters["competition"] == "ICC Cricket World Cup"
    assert route.filters["years"] == [2011]
    assert route.filters["metric"] == "wickets_taken"
    assert route.filters["rank_intent"] == "best"
    assert catches.query_class == QueryClass.venue_context_leaderboard
    assert catches.filters["competition"] == "World Cup 2023"
    assert catches.filters["years"] == [2023]
    assert catches.filters["subject"] == "fielder"
    assert catches.filters["skill"] == "fielding"
    assert catches.filters["metric"] == "catches_taken"
    assert catches.filters["rank_intent"] == "best"


def test_query_router_detects_world_cup_final_player_of_match_fact() -> None:
    router = QueryRouter([])

    route = router.route("Who was Player of the Match in 2011 world cup final?")

    assert route.query_class == QueryClass.venue_context_leaderboard
    assert route.filters["competition"] == "ICC Cricket World Cup"
    assert route.filters["years"] == [2011]
    assert route.filters["external_fact"] == "player_of_match"
    assert route.filters["stage"] == "final"
