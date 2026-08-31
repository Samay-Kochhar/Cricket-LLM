from __future__ import annotations

import re


VENUE_ALIASES = {
    "wankhede": "Wankhede Stadium, Mumbai",
    "lord's": "Lord's, London",
    "lord’s": "Lord's, London",
    "lords": "Lord's, London",
    "mcg": "Melbourne Cricket Ground",
    "melbourne cricket ground": "Melbourne Cricket Ground",
    "the oval": "Kennington Oval, London",
    "kennington oval": "Kennington Oval, London",
}


def venue_alias_matches(message: str, available_venues: list[str] | tuple[str, ...]) -> list[str]:
    lowered = message.lower()
    available = set(available_venues)
    for alias, canonical in VENUE_ALIASES.items():
        if alias in lowered and (not available or canonical in available):
            return [canonical]
    return []


def same_venue_family(venues: list[str]) -> bool:
    family_names = {
        re.sub(r"[^a-z0-9]+", " ", venue.split(",", 1)[0].lower()).strip()
        for venue in venues
    }
    return len(family_names) == 1
