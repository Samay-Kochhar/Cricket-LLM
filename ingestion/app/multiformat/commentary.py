"""Recover names, runs, length, line and footwork from AUCB commentary text.

About 5,500 aucb rows (and some odata rows) have blank structured fields but
keep their commentary, which follows a fixed template:

    [FOUR!|SIX!|OUT! <Kind>.|APPEAL!] [Wide|No ball] <Bowler> to <Batter>.
    <description incl. length>, <line> <footwork> <shot>, ... for <n> run(s).

The parser is only used to fill fields that are blank. Its accuracy is
measured against rows that carry both commentary and structured values (see
tests/ingestion/test_multiformat.py and the validation report).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "FOUR! ", "APPEAL! ", "FREE HIT. ", and "OUT! <Kind>. " where the kind is a
# dismissal type, never a name (a name is always followed by " to ").
_PREFIX = re.compile(
    r"^(?:(?:FOUR|SIX|APPEAL|DROPPED|WICKET|NOT OUT)!\s*|FREE HIT\.\s*"
    r"|OUT!\s*(?:(?:Caught|Bowled|LBW|Run Out|Run out|Stumped|Caught and bowled|Hit wicket|Hit Wicket"
    r"|Obstructing the field|Handled the ball|Retired|Retired Out|Retired Hurt|Timed out)[^.]{0,20}\.\s+)?)*"
)
# A player name: up to five words, no sentence punctuation.
_NAME = r"[A-Z][^.,;:!?]{0,40}?"
_EXTRA = re.compile(r"^(Wide|No ball)\s+")
_NAMES = re.compile(rf"^(?P<bowler>{_NAME}) to (?P<batter>{_NAME})\.\s*(?P<rest>.*)$", re.S)
_RUNS = re.compile(r"\bfor (?P<n>\d+|no) runs?\b")

# Order matters: longer phrases first ("back of a length" before "length").
_LENGTHS = (
    ("full toss", "FullToss"),
    ("half volley", "HalfVolley"),
    ("back of a length", "BackOfALength"),
    ("half tracker", "HalfTracker"),
    ("bouncer", "HalfTracker"),
    ("yorker", "Yorker"),
    ("beamer", "Beamer"),
    ("length", "LengthBall"),
    ("short", "Short"),
)
_LINES = (
    ("wide outside off stump", "Wide"),
    ("wide down leg side", "WideDownLeg"),
    ("outside off stump", "OutsideOff"),
    ("off stump", "OffStump"),
    ("middle stump", "MiddleStump"),
    ("down leg side", "DownLeg"),
    ("to leg", "LegStump"),
)
_FEET = (
    ("on the front foot", "FrontFoot"),
    ("on the back foot", "BackFoot"),
    ("down the track", "DownTheTrack"),
    ("no foot movement", "NoMovement"),
    ("backing away", "BacksAway"),
    ("moves in front", "MovesInfront"),
    ("deep in crease", "DeepInCrease"),
    ("swayed away", "SwayedAway"),
    ("ducked", "Ducked"),
)


@dataclass(frozen=True, slots=True)
class ParsedCommentary:
    bowler: str | None
    batter: str | None
    is_wide: bool
    is_noball: bool
    runs: int | None  # runs credited on the ball as written ("for n runs")
    length: str | None
    line: str | None
    footwork: str | None


def _first(text: str, table: tuple[tuple[str, str], ...]) -> str | None:
    lowered = text.lower()
    best: tuple[int, str] | None = None
    for phrase, code in table:
        idx = lowered.find(phrase)
        if idx >= 0 and (best is None or idx < best[0]):
            best = (idx, code)
    return best[1] if best else None


def parse(commentary: str | None) -> ParsedCommentary | None:
    if not commentary:
        return None
    text = _PREFIX.sub("", commentary.strip(), count=1)
    extra = _EXTRA.match(text)
    if extra:
        text = text[extra.end():]
    names = _NAMES.match(text)
    if not names or len(names.group("bowler").split()) > 5 or len(names.group("batter").split()) > 5:
        return None
    rest = names.group("rest")
    segments = [s.strip() for s in rest.split(",")]
    description = segments[0] if segments else ""
    line_segment = segments[1] if len(segments) > 1 else ""
    runs_match = _RUNS.search(rest)
    runs = None
    if runs_match:
        runs = 0 if runs_match.group("n") == "no" else int(runs_match.group("n"))

    # Length is named in the description; when the delivery is described in
    # one clause ("Length ball, driving, ..."), there is no line segment.
    line = _first(line_segment, _LINES) if line_segment else None
    footwork = _first(line_segment, _FEET) if line_segment else None
    return ParsedCommentary(
        bowler=names.group("bowler").strip(),
        batter=names.group("batter").strip(),
        is_wide=bool(extra and extra.group(1) == "Wide"),
        is_noball=bool(extra and extra.group(1) == "No ball"),
        runs=runs,
        length=_first(description, _LENGTHS),
        line=line,
        footwork=footwork,
    )
