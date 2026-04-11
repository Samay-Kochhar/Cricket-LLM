from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches


ALIASES = {
    "steve smith": "Steven Smith",
    "virat kohli": "Virat Kohli",
    "hardik pandya": "Hardik Pandya",
    "jasprit bumrah": "Jasprit Bumrah",
    "shreyas iyer": "Shreyas Iyer",
    "shimron hetmyer": "Shimron Hetmyer",
    "rovman powell": "Rovman Powell",
}


def normalize_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum() or ch.isspace()).strip()


@dataclass(frozen=True, slots=True)
class PlayerResolutionResult:
    canonical_name: str | None
    suggestions: tuple[str, ...]


def resolve_player_name(name: str, available_names: list[str]) -> PlayerResolutionResult:
    available_map = {normalize_name(player): player for player in available_names}
    normalized = normalize_name(name)

    if normalized in available_map:
        return PlayerResolutionResult(canonical_name=available_map[normalized], suggestions=())

    if normalized in ALIASES:
        alias_target = ALIASES[normalized]
        alias_normalized = normalize_name(alias_target)
        if alias_normalized in available_map:
            return PlayerResolutionResult(canonical_name=available_map[alias_normalized], suggestions=())
        return PlayerResolutionResult(canonical_name=alias_target, suggestions=())

    suggestions = get_close_matches(name, available_names, n=5, cutoff=0.6)
    return PlayerResolutionResult(canonical_name=None, suggestions=tuple(suggestions))
