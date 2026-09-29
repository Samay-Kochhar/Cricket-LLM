import pytest

from backend.app.cricket_analytics.plan_normalizer import requested_sort_direction


@pytest.mark.parametrize(
    "question",
    [
        "top seven batters by strike rate versus spin, 100 balls minimum.",
        "rank batters by batting strike rate, minimum sample 120.",
        "top 5 batters by batting strike rate minimum 60 balls",
        "top 5 batters by batting strike rate, at least 60 balls",
        "top 5 batters by batting strike rate, minimum of 60",
        "top 5 batters by batting strike rate, 60-ball minimum",
    ],
)
def test_sample_threshold_wording_does_not_set_sort_direction(question):
    assert requested_sort_direction(question, "batting_strike_rate", "batter") != "asc"


def test_explicit_direction_words_still_apply():
    assert requested_sort_direction("lowest economy, minimum 90 legal balls", "economy", "bowler") == "asc"
    assert requested_sort_direction("who hit the minimum sixes", "six_count", "batter") == "asc"
    assert requested_sort_direction("maximum sixes, minimum 100 balls", "six_count", "batter") == "desc"
