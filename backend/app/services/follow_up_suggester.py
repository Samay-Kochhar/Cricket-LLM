from __future__ import annotations

from backend.app.domain.metric_models import QueryClass


FOLLOW_UPS = {
    QueryClass.role_comparison: [
        "Compare this player against peers in the same ODI role.",
        "Break the player down year by year to inspect role changes over time.",
    ],
    QueryClass.strengths_weaknesses: [
        "Compare the player's top shots against another ODI batter.",
        "Inspect whether the same weakness changes over time.",
    ],
    QueryClass.head_to_head_matchup: [
        "Compare this matchup against the batter's overall ODI baseline.",
        "Inspect the bowler against other batters from the same hand.",
    ],
    QueryClass.venue_context_leaderboard: [
        "Compare the venue results against the country-wide ODI baseline.",
        "Adjust the sample threshold and re-sort the leaderboard.",
    ],
    QueryClass.trend_progression: [
        "Split the trend before and after a specific year.",
        "Compare this trend against another ODI player.",
    ],
}


def suggest_follow_ups(query_class: QueryClass) -> list[str]:
    return FOLLOW_UPS.get(query_class, [])
