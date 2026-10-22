"""Explicit physical-ground identities shared by selectors, interpretation and SQL.

The checked-in registry is the authority, not token/city similarity. Raw deliveries
are never rewritten. IDs must not change when a display name or sponsor changes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("’", "'").strip()).casefold()


@dataclass(frozen=True)
class Venue:
    id: str
    display_name: str
    aliases: tuple[str, ...]
    search_aliases: tuple[str, ...]


REGISTRY = json.loads((Path(__file__).parent / "data" / "odi_venues.json").read_text())
VENUES = tuple(
    Venue(row['id'], row['display_name'], tuple(row['aliases']), tuple(row['search_aliases']))
    for row in REGISTRY
)
_BY_ID = {venue.id: venue for venue in VENUES}
for _row in REGISTRY:
    for _legacy_id in _row.get('legacy_ids', []):
        if _legacy_id in _BY_ID:
            raise ValueError(f'Duplicate legacy physical-ground ID: {_legacy_id}')
        _BY_ID[_legacy_id] = _BY_ID[_row['id']]
_BY_NAME: dict[str, Venue] = {}
for _venue in VENUES:
    for _alias in _venue.aliases:
        if _key(_alias) in _BY_NAME:
            raise ValueError(f"Duplicate venue alias: {_alias}")
        _BY_NAME[_key(_alias)] = _venue
if len({venue.id for venue in VENUES}) != len(VENUES):
    raise ValueError('Duplicate physical-ground ID')


def resolve_venue(value: str) -> Venue:
    known = _BY_ID.get(value) or _BY_NAME.get(_key(value))
    if known:
        return known
    # New/unreviewed data stays separate, including identically named city grounds.
    return Venue('unreviewed-' + sha256(value.encode()).hexdigest()[:16], value, (value,), ())


def venue_display_name(value: str) -> str:
    return resolve_venue(value).display_name


def venue_options(raw_names: Iterable[str]) -> list[str]:
    return sorted({venue_display_name(name) for name in raw_names})


def venue_filter(values: Iterable[str], column: str = 'ground') -> tuple[str, list[str]]:
    """A deduplicated IN predicate scans each delivery once, even with old state.

    Column is an application-owned SQL identifier, never user input.
    """
    aliases = list(dict.fromkeys(alias for value in values for alias in resolve_venue(value).aliases))
    if not aliases:
        return 'FALSE', []
    return f"{column} IN ({', '.join('?' for _ in aliases)})", aliases


def venue_id_sql(column: str = 'ground') -> str:
    # Only checked-in constants are embedded. User filter values are parameterized.
    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
    cases = ' '.join(
        f"WHEN {literal(alias)} THEN {literal(venue.id)}"
        for venue in VENUES for alias in venue.aliases
    )
    # Match Python's conservative fallback for newly observed raw values.
    return f"CASE {column} {cases} ELSE 'unreviewed-' || SUBSTR(SHA256({column}), 1, 16) END"


def venue_display_sql(identity: str, column: str = 'ground') -> str:
    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
    cases = ' '.join(
        f"WHEN {literal(v.id)} THEN {literal(v.display_name)}"
        for v in VENUES if len(v.aliases) > 1
    )
    return f"CASE {identity} {cases} ELSE ANY_VALUE({column}) END"


def matching_venues(message: str, available: Iterable[str]) -> list[str]:
    """Recognize only explicit names/nicknames; availability is by physical ID."""
    available_ids = {resolve_venue(name).id for name in available}
    lowered = _key(message)
    matches = []
    for venue in VENUES:
        if available_ids and venue.id not in available_ids:
            continue
        aliases = (*venue.aliases, *venue.search_aliases)
        if any(re.search(r'(?<!\w)' + re.escape(_key(alias)) + r'(?!\w)', lowered) for alias in aliases):
            matches.append(venue.display_name)
    return matches
