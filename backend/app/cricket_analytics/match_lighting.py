"""Registered match-lighting dimension (the stored ``daynight`` category).

The delivery data records one lighting category per match in ``daynight``:

- ``day match``
- ``day/night match``
- ``night match``

The value is a *match* category. A ``day/night match`` is not evidence that
every delivery was bowled at night; only that the match was scheduled across
day and night. Stored labels are used literally and are never merged or
reassigned.

Language rules (deterministic; a model may extract the same meaning but never
supplies values or SQL):

- "day/night", "day-night", "d/n" -> ``day/night match``.
- "pure night", "night-only", "only night", "fully at night" -> ``night match``.
- Casual "night" (for example "day versus night matches") -> ``day/night match``,
  because ODIs described as night games are recorded as day/night matches. The
  answer discloses this reading. When the same question also names day/night
  explicitly, casual "night" instead means the separate ``night match``
  category, so the two never collapse.
- "day", "daytime" (never "one-day") -> ``day match``.
- Other lighting wording ("floodlit", "under lights", "evening", "twilight")
  is not a recorded category and fails closed with the categories named.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MATCH_LIGHTING = "match_lighting"
LIGHTING_COLUMN = "daynight"
LIGHTING_SOURCE = "registered_match_lighting_language"

DAY_MATCH = "day match"
DAY_NIGHT_MATCH = "day/night match"
NIGHT_MATCH = "night match"
LIGHTING_VALUES: tuple[str, ...] = (DAY_MATCH, DAY_NIGHT_MATCH, NIGHT_MATCH)

PUBLIC_LABELS = {
    DAY_MATCH: "day match",
    DAY_NIGHT_MATCH: "day/night match",
    NIGHT_MATCH: "night match",
}

DAY_NIGHT_DISCLOSURE = (
    "'day/night match' is the recorded match category: the match was scheduled "
    "across day and night. It is not evidence that every delivery was bowled at night."
)
CASUAL_NIGHT_DISCLOSURE = (
    "Casual 'night' wording was read as the recorded 'day/night match' category. "
    "Pure 'night match' is a separate recorded category; ask for pure night matches "
    "to use it."
)

LightingKind = Literal["day", "day_night", "pure_night", "casual_night", "unrecorded"]

_MATCH_NOUN = r"(?:matches|match|games|game|odis|odi|fixtures|fixture|contests|cricket|conditions)"
_PATTERNS: tuple[tuple[LightingKind, str], ...] = (
    ("day_night", r"\bday\s*(?:[/-]\s*)?night\b(?=\s*" + _MATCH_NOUN + r")|\bday\s*[/-]\s*night\b|\bd/n\b"),
    (
        "pure_night",
        r"\b(?:pure(?:ly)?|fully|entirely|only|strictly|genuine|true)[\s-]+(?:at[\s-]+)?night(?:time)?\b"
        r"|\bnight[\s-]+only\b|\bnight\s+matches\s+only\b",
    ),
    (
        "unrecorded",
        r"\b(?:floodlit|under\s+(?:the\s+)?(?:lights|floodlights)|twilight|evening|afternoon|dusk)\b",
    ),
    ("casual_night", r"(?<![/-])\bnight(?:time)?\b"),
    ("day", r"(?<!one[- ])(?<!one)\bday(?:time)?\b(?!\s*[/-]\s*night)"),
)
_ANCHOR = re.compile(
    r"\b(?:day|night|daytime|nighttime|day\s*[/-]\s*night|floodlit|twilight|evening|afternoon|dusk)"
    r"(?:\s*[/-]\s*night)?\s+" + _MATCH_NOUN + r"\b"
    r"|\bday\s*[/-]\s*night\b|\bd/n\b|\bdaytime\b|\bnight\s*time\b|\bnighttime\b"
    r"|\bat\s+night\b|\bduring\s+the\s+day\b|\bunder\s+(?:the\s+)?(?:lights|floodlights)\b"
    r"|\b(?:match\s+)?lighting\b|\bnight[\s-]+only\b"
)


@dataclass(frozen=True, slots=True)
class LightingMention:
    kind: LightingKind
    span: tuple[int, int]
    text: str


def _clean(text: str) -> str:
    return " ".join(
        text.lower().replace("’", "'").replace("–", "-").replace("—", "-").split()
    )


def lighting_mentions(text: str) -> list[LightingMention]:
    """Lighting words, in question order, when the question is about match lighting."""
    lowered = _clean(text)
    if not _ANCHOR.search(lowered):
        return []
    mentions: list[LightingMention] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in _PATTERNS:
        for match in re.finditer(pattern, lowered):
            start, end = match.span()
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue
            taken.append((start, end))
            mentions.append(LightingMention(kind=kind, span=(start, end), text=match.group(0)))
    return sorted(mentions, key=lambda mention: mention.span)


def requested_lighting_values(text: str) -> list[str]:
    """Registered stored categories in question order (duplicates removed)."""
    mentions = lighting_mentions(text)
    explicit_day_night = any(m.kind == "day_night" for m in mentions)
    values: list[str] = []
    for mention in mentions:
        if mention.kind == "day":
            value = DAY_MATCH
        elif mention.kind == "day_night":
            value = DAY_NIGHT_MATCH
        elif mention.kind == "pure_night":
            value = NIGHT_MATCH
        elif mention.kind == "casual_night":
            value = NIGHT_MATCH if explicit_day_night else DAY_NIGHT_MATCH
        else:
            continue
        if value not in values:
            values.append(value)
    return values


def casual_night_used(text: str) -> bool:
    mentions = lighting_mentions(text)
    return any(m.kind == "casual_night" for m in mentions) and not any(
        m.kind == "day_night" for m in mentions
    )


def lighting_problem(text: str) -> str | None:
    """Lighting wording that cannot compile to recorded categories."""
    mentions = lighting_mentions(text)
    unrecorded = [m.text for m in mentions if m.kind == "unrecorded"]
    if unrecorded:
        return (
            f"Match lighting '{unrecorded[0]}' is not a recorded category. The database "
            "records each match only as 'day match', 'day/night match' or 'night match'."
        )
    if len(requested_lighting_values(text)) > 2:
        return (
            "Comparing more than two match-lighting categories in one question is not "
            "supported yet. Choose two of 'day match', 'day/night match' and 'night match'."
        )
    return None


def strip_lighting_phrases(text: str) -> str:
    """Remove lighting words so "day"/"night" are not reread as other meanings."""
    lowered = _clean(text)
    pieces: list[str] = []
    cursor = 0
    for mention in lighting_mentions(lowered):
        start, end = mention.span
        if start < cursor:
            continue
        pieces.append(lowered[cursor:start])
        pieces.append(" ")
        cursor = end
    pieces.append(lowered[cursor:])
    return " ".join("".join(pieces).split())


def is_lighting_value(value: object) -> bool:
    return isinstance(value, str) and value in LIGHTING_VALUES


def lighting_clause(value: object) -> tuple[str, list[object]]:
    """Registered filter SQL; a malformed value never widens scope."""
    if not is_lighting_value(value):
        return ("1 = 0", [])
    return (f"CAST({LIGHTING_COLUMN} AS VARCHAR) = ?", [value])


def split_case_expression() -> str:
    """Split bucket expression over the literal stored categories only."""
    whens = " ".join(
        f"WHEN CAST({LIGHTING_COLUMN} AS VARCHAR) = '{value}' THEN '{value}'"
        for value in LIGHTING_VALUES
    )
    return f"CASE {whens} ELSE NULL END"


def is_lighting_concept(concept: str) -> bool:
    lowered = _clean(concept).replace("_", " ")
    return bool(
        re.search(r"\b(?:day ?/? ?night|lighting|day|night|floodlit|lights)\b", lowered)
        and not re.search(r"\b(?:one day|toss|innings)\b", lowered)
    )


def lighting_values_from_language(values: list[object], evidence: str) -> list[str]:
    """Read model-extracted lighting values against the question wording."""
    stated = requested_lighting_values(evidence) if evidence else []
    if stated:
        return stated
    readings: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        word = _clean(raw)
        reading = requested_lighting_values(f"{word} matches")
        for value in reading:
            if value not in readings:
                readings.append(value)
    return readings
