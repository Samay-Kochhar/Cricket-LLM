from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.metric_models import QueryClass


@dataclass(frozen=True, slots=True)
class QueryClassDefinition:
    query_class: QueryClass
    label: str
    description: str
    example_questions: tuple[str, ...]


QUERY_CLASS_DEFINITIONS: dict[QueryClass, QueryClassDefinition] = {
    QueryClass.role_comparison: QueryClassDefinition(
        query_class=QueryClass.role_comparison,
        label="Role and Position Comparison",
        description="Compare ODI performance across batting positions, innings phases, or usage roles.",
        example_questions=(
            "Is Virat Kohli better at number 3 or opening in ODIs?",
            "Where is Bumrah most valuable across ODI phases?",
        ),
    ),
    QueryClass.strengths_weaknesses: QueryClassDefinition(
        query_class=QueryClass.strengths_weaknesses,
        label="Strengths and Weaknesses",
        description="Identify where a player scores, struggles, or gets dismissed.",
        example_questions=(
            "Where does Hardik Pandya score the most and on which shots?",
            "Does Shreyas Iyer still struggle against short bowling after 2023?",
        ),
    ),
    QueryClass.head_to_head_matchup: QueryClassDefinition(
        query_class=QueryClass.head_to_head_matchup,
        label="Head-to-Head Matchup",
        description="Analyze ODI batter versus bowler or player versus player matchups.",
        example_questions=(
            "Bumrah versus Steven Smith in ODIs",
            "How does a batter perform against left-arm pace?",
        ),
    ),
    QueryClass.venue_context_leaderboard: QueryClassDefinition(
        query_class=QueryClass.venue_context_leaderboard,
        label="Venue and Context Leaderboard",
        description="Rank players or teams by venue, country, competition, or innings context.",
        example_questions=(
            "Which bowler has the best ODI record at a ground?",
            "Which batter is strongest in the powerplay phase?",
        ),
    ),
    QueryClass.trend_progression: QueryClassDefinition(
        query_class=QueryClass.trend_progression,
        label="Trend and Progression",
        description="Track how ODI performance changes over time.",
        example_questions=(
            "Has Shimron Hetmyer become more destructive over time?",
            "How has a player's shot profile changed year by year?",
        ),
    ),
}
