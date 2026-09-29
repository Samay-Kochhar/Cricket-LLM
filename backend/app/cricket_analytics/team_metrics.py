"""Registered team metrics with explicit batting-team and bowling-team roles.

A team question names a *grouped team subject* and, optionally, an opposition.
Roles are explicit so a team request can never become a player ranking or
filter the wrong side:

- ``bowling_team``: the team whose bowlers delivered the ball (``team_bowl``).
- ``batting_team``: the team batting on that ball (``team_bat``).

Registered team metrics (metric -> grouped team role):

- ``economy_rate`` grouped by ``bowling_team``: bowler-attributed runs
  (``bowlruns``) per six legal balls. ``bowlruns`` includes wides and no-ball
  runs charged to the bowler and excludes byes and leg-byes; legal balls exclude
  wides and no-balls. This is the same convention as player economy. It is not
  the opposition's innings run rate (total runs including byes and leg-byes),
  which is a different team metric and is not registered.

Language, role assignment, thresholds and SQL are deterministic. Gemini is not
consulted for these questions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.plan_normalizer import (
    requested_limit_from_wording,
    requested_minimum_sample,
    requested_sort_direction,
)
from backend.app.cricket_analytics.schemas import (
    CricketQueryPlan,
    MinimumSampleSpec,
    SortSpec,
)

TEAM_METRIC_SOURCE = "registered_team_metric_language"

# Grouped team role -> the player role whose deliveries it aggregates.
TEAM_ROLE_OWNERS = {"bowling_team": "bowler", "batting_team": "batter"}
# Registered team metric -> grouped team role.
REGISTERED_TEAM_METRICS = {"economy_rate": "bowling_team"}
# Filters that compose with a registered team metric (besides the team roles).
TEAM_METRIC_FILTERS = frozenset(
    {
        "batting_team",
        "bowling_team",
        "years",
        "year_mode",
        "phase",
        "over_range",
        "venue",
        "venues",
        "competition",
        "innings",
        "match_lighting",
    }
)

TEAM_ECONOMY_DEFINITION = (
    "Team economy groups deliveries by the bowling team: bowler-attributed runs "
    "(bowlruns, which include wides and no-ball runs and exclude byes and leg-byes) "
    "per six legal balls (wides and no-balls excluded), the same convention as "
    "player economy. It is not the opposition's innings run rate, which also counts "
    "byes and leg-byes and is not a registered team metric."
)

_BOWLING_SIDE = re.compile(
    r"\b(?:bowling|fielding)\s+(?:teams?|sides?|units?|attacks?|line-?ups?|nations?)\b"
)
_BATTING_SIDE = re.compile(r"\bbatting\s+(?:teams?|sides?|units?|line-?ups?|orders?|nations?)\b")
_GENERIC_TEAM = re.compile(
    r"\b(?:teams?|sides?|nations?|countries|national\s+sides?|international\s+sides?)\b"
)
_RANKING = re.compile(
    r"\b(?:which|what|rank(?:ed|ing|s)?|top|bottom|best|worst|lowest|highest|"
    r"most|least|fewest|leaders?|leaderboard)\b"
)
_TEAM_RATE_WORDS = re.compile(
    r"\b(?:innings\s+run\s+rate|run\s+rate\s+conceded|"
    r"conceded\s+run\s+rate|total\s+runs?\s+conceded\s+per\s+over)\b"
)


@dataclass(frozen=True, slots=True)
class TeamMetricIssue:
    concept: str
    requested: object
    outcome: str  # "clarification" | "unsupported"
    reason: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TeamMetricMeaning:
    metric: str | None
    team_role: str | None
    filters: dict[str, object]
    direction: str
    limit: int
    minimum_legal_balls: int
    sample_explicit: bool
    evidence: dict[str, str] = field(default_factory=dict)
    issues: tuple[TeamMetricIssue, ...] = ()

    def canonical(self) -> dict[str, object]:
        return {
            "family": "team_ranking",
            "metric": self.metric,
            "grouped_team_role": self.team_role,
            "filters": dict(self.filters),
            "sort_direction": self.direction,
            "limit": self.limit,
            "minimum_sample": {"legal_balls": self.minimum_legal_balls},
            "minimum_sample_explicit": self.sample_explicit,
        }

    def outcome(self) -> tuple[str, str, list[str]] | None:
        if not self.issues:
            return None
        unsupported = [issue for issue in self.issues if issue.outcome == "unsupported"]
        if unsupported:
            return (
                "unsupported",
                " ".join(dict.fromkeys(issue.reason for issue in unsupported)),
                [],
            )
        options = [option for issue in self.issues for option in issue.options]
        return (
            "clarification",
            " ".join(dict.fromkeys(issue.reason for issue in self.issues)),
            list(dict.fromkeys(options)),
        )

    def compile(self) -> CricketQueryPlan:
        if self.metric is None or self.team_role is None:
            raise ValueError("A team metric meaning needs a registered metric and team role.")
        return CricketQueryPlan(
            operation="aggregate",
            entity="team",
            metric=self.metric,
            group_by=[self.team_role],
            filters=dict(self.filters),
            sort=SortSpec(by=self.metric, direction=self.direction),  # type: ignore[arg-type]
            limit=self.limit,
            minimum_sample=MinimumSampleSpec(legal_balls=self.minimum_legal_balls),
            minimum_sample_explicit=self.sample_explicit,
            question_subject="team_ranking",
            explanation_intent="registered team metric",
            confidence=1.0,
        )

    def completeness(self, question: str) -> dict[str, object]:
        facts: list[dict[str, object]] = []

        def add(fact_type: str, concept: str, requested: object, target: str) -> None:
            facts.append(
                {
                    "fact_type": fact_type,
                    "concept": concept,
                    "requested": requested,
                    "evidence": self.evidence.get(concept, question),
                    "disposition": "compiled",
                    "canonical_target": target,
                    "reason": None,
                }
            )

        if self.metric:
            add("metric", "metric", self.metric, f"metric.{self.metric}")
        if self.team_role:
            add("entity", "grouped_team", self.team_role, f"group_by.{self.team_role}")
        for key, value in self.filters.items():
            add("filter", key, value, f"filter.{key}")
        add("ordering", "sort_direction", self.direction, "sort.direction")
        add("limit", "limit", self.limit, "limit")
        facts.append(
            {
                "fact_type": "sample_threshold",
                "concept": "minimum_sample",
                "requested": {"legal_balls": self.minimum_legal_balls},
                "evidence": self.evidence.get("minimum_sample", question),
                "disposition": "compiled" if self.sample_explicit else "default_applied",
                "canonical_target": "minimum_sample.legal_balls",
                "reason": None if self.sample_explicit else "Documented rate-ranking default.",
            }
        )
        for issue in self.issues:
            facts.append(
                {
                    "fact_type": "filter" if issue.concept not in {"metric", "grouped_team"} else issue.concept,
                    "concept": issue.concept,
                    "requested": issue.requested,
                    "evidence": question,
                    "disposition": (
                        "clarification_required" if issue.outcome == "clarification" else "unsupported"
                    ),
                    "canonical_target": None,
                    "reason": issue.reason,
                }
            )
        blocking = bool(self.issues)
        return {"complete": not blocking, "allows_execution": not blocking, "facts": facts}


def names_team_role(text: str) -> bool:
    """Explicit bowling-side or batting-side wording ("bowling side", "batting team")."""
    lowered = _clean(text)
    return bool(_BOWLING_SIDE.search(lowered) or _BATTING_SIDE.search(lowered))


def is_team_subject_question(text: str) -> bool:
    """A question whose grouped subject is a team rather than a player."""
    lowered = _clean(text)
    return bool(
        _BOWLING_SIDE.search(lowered)
        or _BATTING_SIDE.search(lowered)
        or _GENERIC_TEAM.search(lowered)
    )


def extract_team_metric_meaning(
    question: str,
    resolver: object,
    available_teams: Sequence[str],
) -> TeamMetricMeaning | None:
    """Deterministic team-metric meaning, or None when this is not a team ranking."""
    from backend.app.cricket_analytics.canonical_meaning import (
        _extract_players,
        _metric_and_role,
        _team_filters,
    )

    lowered = _clean(question)
    if not is_team_subject_question(lowered) or not _RANKING.search(lowered):
        return None
    if _extract_players(question, getattr(resolver, "available_players", ())):
        return None

    issues: list[TeamMetricIssue] = []
    evidence: dict[str, str] = {}

    # Team names are roles, never player names; strip them before reading the metric.
    metric_text = lowered
    for team in available_teams:
        metric_text = re.sub(rf"(?<!\w){re.escape(team.lower())}(?!\w)", " ", metric_text)
    if _TEAM_RATE_WORDS.search(lowered):
        metric: str | None = None
        issues.append(
            TeamMetricIssue(
                concept="metric",
                requested=_TEAM_RATE_WORDS.search(lowered).group(0),  # type: ignore[union-attr]
                outcome="unsupported",
                reason=(
                    "Opposition innings run rate (total runs, including byes and leg-byes, "
                    "per over) is a different team metric and is not registered. Registered "
                    "team metric: bowling-team economy (bowler-attributed runs per six legal balls)."
                ),
            )
        )
    elif re.search(r"\brun[- ]rates?\b", metric_text):
        # A team's scoring rate is its own concept, never the runs total.
        metric = "run_rate"
    else:
        metric, _role = _metric_and_role(metric_text, None, None)
        if metric is None and re.search(r"\beconom(?:y|ical)\b", metric_text):
            metric = "economy_rate"
    if metric is not None and metric not in REGISTERED_TEAM_METRICS:
        issues.append(
            TeamMetricIssue(
                concept="metric",
                requested=metric,
                outcome="unsupported",
                reason=(
                    f"Team {metric.replace('_', ' ')} is not a registered team metric yet. "
                    "Registered team metric: bowling-team economy."
                ),
            )
        )
    elif metric is None and not issues:
        issues.append(
            TeamMetricIssue(
                concept="metric",
                requested=None,
                outcome="unsupported",
                reason=(
                    "Team analysis needs a registered team metric. Registered team metric: "
                    "bowling-team economy."
                ),
            )
        )

    team_role = REGISTERED_TEAM_METRICS.get(metric or "")
    if team_role == "bowling_team" and _BATTING_SIDE.search(lowered) and not _BOWLING_SIDE.search(lowered):
        issues.append(
            TeamMetricIssue(
                concept="grouped_team",
                requested="batting_team",
                outcome="clarification",
                reason=(
                    "Economy is conceded by the bowling side. Should this rank bowling "
                    "teams, or did you mean a batting-team metric?"
                ),
                options=("Rank bowling teams by economy",),
            )
        )

    filters: dict[str, object] = {}
    teams = _team_filters(question, available_teams)
    extra_teams = _additional_team_mentions(question, available_teams, teams)
    if extra_teams:
        issues.append(
            TeamMetricIssue(
                concept="team",
                requested=extra_teams,
                outcome="unsupported",
                reason=(
                    "More than one opposition or grouped team was named; a team ranking "
                    "supports one batting opposition and one bowling-team filter."
                ),
            )
        )
    if team_role == "bowling_team":
        if "opposition" in teams:
            filters["batting_team"] = teams["opposition"]
            evidence["batting_team"] = str(teams["opposition"])
        if "player_team" in teams:
            filters["bowling_team"] = teams["player_team"]
            evidence["bowling_team"] = str(teams["player_team"])
        if filters.get("batting_team") and filters.get("batting_team") == filters.get("bowling_team"):
            issues.append(
                TeamMetricIssue(
                    concept="team",
                    requested=filters["batting_team"],
                    outcome="unsupported",
                    reason="A team cannot bowl against itself.",
                )
            )

    explicit = resolver._explicit_filters(question, lowered)  # type: ignore[attr-defined]
    for key, value in explicit.items():
        if key in {"opposition", "player_team"}:
            continue
        if key in TEAM_METRIC_FILTERS:
            filters[key] = value
        else:
            issues.append(
                TeamMetricIssue(
                    concept=key,
                    requested=value,
                    outcome="unsupported",
                    reason=f"Filtering a team ranking by {key.replace('_', ' ')} is not registered yet.",
                )
            )

    # Unregistered metrics never execute; thresholds are read on the registered one.
    sample_metric = metric if metric in REGISTERED_TEAM_METRICS else "economy_rate"
    explicit_sample = requested_minimum_sample(lowered, sample_metric)
    if explicit_sample is not None and explicit_sample.legal_balls is None:
        if explicit_sample.innings is not None:
            issues.append(
                TeamMetricIssue(
                    concept="minimum_sample",
                    requested={"innings": explicit_sample.innings},
                    outcome="unsupported",
                    reason="Team economy qualifications are expressed in legal balls.",
                )
            )
        explicit_sample = MinimumSampleSpec(legal_balls=explicit_sample.balls)
    default_minimum = get_metric(sample_metric, entity="bowler").minimum_sample.legal_balls or 60
    minimum = (
        int(explicit_sample.legal_balls)
        if explicit_sample is not None and explicit_sample.legal_balls is not None
        else default_minimum
    )

    direction = requested_sort_direction(lowered, sample_metric, "bowler") or (
        get_metric(sample_metric, entity="bowler").default_sort
    )
    limit = requested_limit_from_wording(lowered) or 10
    return TeamMetricMeaning(
        metric=metric if metric in REGISTERED_TEAM_METRICS else None,
        team_role=team_role,
        filters=filters,
        direction=direction,
        limit=int(limit),
        minimum_legal_balls=minimum,
        sample_explicit=explicit_sample is not None,
        evidence=evidence,
        issues=tuple(issues),
    )


def team_metric_ownership_ok(plan: CricketQueryPlan) -> bool:
    """A team plan may use a player-owned metric only through its registered role."""
    return (
        plan.entity == "team"
        and plan.group_by == [REGISTERED_TEAM_METRICS.get(plan.metric)]
    )


def team_metric_plan_errors(plan: CricketQueryPlan) -> list[str]:
    if plan.entity != "team" or plan.question_subject != "team_ranking":
        return []
    errors: list[str] = []
    if not team_metric_ownership_ok(plan):
        errors.append(
            f"Team metric '{plan.metric}' must be grouped by its registered team role."
        )
    if "opposition" in plan.filters or "player_team" in plan.filters:
        errors.append("Team plans must use explicit batting_team or bowling_team filters.")
    unknown = set(plan.filters) - TEAM_METRIC_FILTERS
    if unknown:
        errors.append(f"Unregistered team-ranking filters: {sorted(unknown)}.")
    if plan.minimum_sample is None or plan.minimum_sample.legal_balls is None:
        errors.append("Team economy rankings need a legal-ball qualification.")
    return errors


def _additional_team_mentions(
    question: str, available_teams: Sequence[str], resolved: dict[str, object]
) -> list[str]:
    lowered = _clean(question)
    named = [
        team
        for team in available_teams
        if re.search(rf"(?<!\w){re.escape(team.lower())}(?!\w)", lowered)
    ]
    # A shorter team name contained in a longer one ("India" in "West Indies" is
    # not, but "Ireland" in "Northern Ireland" style names are) is not extra.
    named = [
        team
        for team in named
        if not any(team != other and team.lower() in other.lower() for other in named)
    ]
    return [team for team in named if team not in resolved.values()]


def _clean(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split())
