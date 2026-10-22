from __future__ import annotations

from backend.app.domain.venues import matching_venues, resolve_venue


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
    matches = matching_venues(message, available_venues)
    if matches:
        return matches
    lowered = message.lower()
    available_ids = {resolve_venue(name).id for name in available_venues}
    for alias, canonical in VENUE_ALIASES.items():
        if alias in lowered and (not available_ids or resolve_venue(canonical).id in available_ids):
            return [canonical]
    return []


def same_venue_family(venues: list[str]) -> bool:
    return len({resolve_venue(venue).id for venue in venues}) == 1
