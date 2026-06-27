from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    single_metric = "single_metric"
    leaderboard = "leaderboard"
    comparison = "comparison"
    trend = "trend"
    match_fact = "match_fact"
    tactical_plan = "tactical_plan"
    strengths_weaknesses = "strengths_weaknesses"
    conversation = "conversation"


class AnswerShape(str, Enum):
    single_number = "single_number"
    short_fact = "short_fact"
    leaderboard = "leaderboard"
    comparison_table = "comparison_table"
    trend_chart = "trend_chart"
    scouting_report = "scouting_report"
    tactical_plan = "tactical_plan"
    insufficient_data = "insufficient_data"


class ContextScope(str, Enum):
    career = "career"
    season = "season"
    competition = "competition"
    single_match = "single_match"
    phase = "phase"
    venue = "venue"
    matchup = "matchup"


class SubjectRole(str, Enum):
    batter = "batter"
    bowler = "bowler"
    fielder = "fielder"
    player = "player"
    team = "team"


class CricketMetric(str, Enum):
    balls_bowled = "balls_bowled"
    overs_bowled = "overs_bowled"
    balls_faced = "balls_faced"
    runs_scored = "runs_scored"
    runs_conceded = "runs_conceded"
    wickets_taken = "wickets_taken"
    economy_rate = "economy_rate"
    best_bowling_figures = "best_bowling_figures"
    balls_per_wicket = "balls_per_wicket"
    balls_per_boundary = "balls_per_boundary"
    dot_balls = "dot_balls"
    bowler_dot_balls = "bowler_dot_balls"
    dot_percentage = "dot_percentage"
    bowler_dot_percentage = "bowler_dot_percentage"
    boundaries = "boundaries"
    boundaries_conceded = "boundaries_conceded"
    boundaries_per_over = "boundaries_per_over"
    catches_taken = "catches_taken"
    dismissals = "dismissals"
    batting_strike_rate = "batting_strike_rate"
    strike_rate_improvement_after_20 = "strike_rate_improvement_after_20"
    milestone_vulnerability_lift = "milestone_vulnerability_lift"
    batting_average = "batting_average"
    boundary_percentage = "boundary_percentage"
    strike_rotation_percentage = "strike_rotation_percentage"
    false_shot_percentage = "false_shot_percentage"
    yorker_count = "yorker_count"
    yorker_percentage = "yorker_percentage"
    yorker_success_rate = "yorker_success_rate"
    false_shots_per_over = "false_shots_per_over"
    boundaries_per_100_balls = "boundaries_per_100_balls"
    extras_rate = "extras_rate"
    player_of_match = "player_of_match"


class IntentSubject(BaseModel):
    player: str | None = None
    team: str | None = None
    role: SubjectRole = SubjectRole.player


class MatchContext(BaseModel):
    scope: ContextScope = ContextScope.career
    competition: str | None = None
    year: int | None = None
    years: list[int] = Field(default_factory=list)
    year_mode: str | None = None
    stage: str | None = None
    teams: list[str] = Field(default_factory=list)
    venue_name: str | None = None
    phase: str | None = None
    match_id: str | None = None
    group_by: str | None = None
    length: str | None = None
    line: str | None = None
    bowling_kind: str | None = None
    bowling_style_group: str | None = None
    bat_hand: str | None = None
    over_range: list[int] = Field(default_factory=list)


class IntentAmbiguity(BaseModel):
    possible_alternate_metric: CricketMetric | None = None
    reason: str | None = None


class CricketIntentPlan(BaseModel):
    query_type: QueryType = QueryType.comparison
    answer_shape: AnswerShape = AnswerShape.comparison_table
    metric: CricketMetric | None = None
    subjects: list[IntentSubject] = Field(default_factory=list)
    context: MatchContext = Field(default_factory=MatchContext)
    rank_intent: str | None = None
    ambiguity: IntentAmbiguity | None = None
    unsupported_reason: str | None = None

    def primary_player(self) -> str | None:
        for subject in self.subjects:
            if subject.player:
                return subject.player
        return None

    def primary_role(self) -> SubjectRole | None:
        return self.subjects[0].role if self.subjects else None
