"""Cricket participation facts, independent of question phrasing or player fame."""

from dataclasses import dataclass, field
from typing import Literal, Mapping

Role = Literal["batter", "bowler"]


@dataclass(frozen=True)
class PlayerParticipation:
    balls_faced: int = 0
    balls_bowled: int = 0
    bowling_kinds: frozenset[str] = field(default_factory=frozenset)

    def supports(self, role: Role) -> bool:
        return (self.balls_faced if role == "batter" else self.balls_bowled) > 0

    @property
    def primary_role(self) -> Role | None:
        # Occasional bowling or tail-end batting does not establish two equally
        # plausible default directions. Explicit relationships still override this.
        if self.balls_faced > 0 and self.balls_faced >= 3 * self.balls_bowled:
            return "batter"
        if self.balls_bowled > 0 and self.balls_bowled >= 3 * self.balls_faced:
            return "bowler"
        return None


class PlayerRoleResolver:
    def __init__(self, participation: Mapping[str, PlayerParticipation] | None = None):
        self.participation = dict(participation or {})

    def supports(self, player: str, role: Role) -> bool:
        fact = self.participation.get(player)
        # Absent facts never disprove explicit language, but cannot supply a role.
        return fact.supports(role) if fact is not None else True

    def primary_role(self, player: str | None) -> Role | None:
        fact = self.participation.get(player or "")
        return fact.primary_role if fact else None

    def default_pair(self, first: str, second: str) -> tuple[str, str] | None:
        possibilities = [
            (batter, bowler)
            for batter, bowler in ((first, second), (second, first))
            if self.supports(batter, "batter") and self.supports(bowler, "bowler")
        ]
        if len(possibilities) == 1:
            return possibilities[0]
        preferred = [
            pair
            for pair in possibilities
            if self.primary_role(pair[0]) == "batter"
            and self.primary_role(pair[1]) == "bowler"
        ]
        return preferred[0] if len(preferred) == 1 else None

    def shared_bowling_kind(self, players: list[str]) -> str | None:
        facts = [self.participation.get(player) for player in players]
        if any(fact is None for fact in facts):
            return None
        shared = set.intersection(*(set(fact.bowling_kinds) for fact in facts if fact))
        return next(iter(shared)) if len(shared) == 1 else None
