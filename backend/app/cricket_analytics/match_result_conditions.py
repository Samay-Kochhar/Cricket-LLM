"""Registered match-result condition for batting statistics (successful chases).

A *successful chase* is not a stored column. It is the conjunction of two
registered, independently accounted conditions:

- ``innings = 2`` — the existing second-innings (chasing) filter; and
- ``batting_result = "won"`` — the batting team of the delivery row equals the
  stored match winner.

``batting_result = "lost"`` means the stored winner is the *bowling* team of the
row, so an unsuccessful chase is ``innings = 2`` plus ``batting_result = "lost"``.
Language, value checks and SQL are deterministic and owned by this module; a
model may extract the same meaning but never supplies SQL.

Result policy (audited against ``data/odi_analytics.duckdb``):

- Ties, no-results and abandoned matches are stored with the placeholder winner
  ``'-'`` (122 matches). They are neither wins nor losses: excluded from both
  result values, included in unfiltered or plain "chasing" scopes.
- One match stores a winner (``ICC World XI``) that matches neither stored team
  name (``World-XI``/``Asia XI``). A missing or unmatched winner is never treated
  as a win or a loss: ``lost`` requires the winner to equal the bowling team, not
  merely differ from the batting team.
- Rain-affected matches (``rain`` recorded as 1 or 9) use the stored result as
  recorded, including revised targets; the result is not re-derived from scores.
- Only innings 1 and 2 exist in the delivery data and no super-over rows are
  stored. A chase condition always requires the literal second innings, so any
  nonstandard innings could never enter a chase scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


BattingResult = Literal["won", "lost"]
BATTING_RESULT_FILTER = "batting_result"
RESULT_CONDITION_SOURCE = "registered_result_condition_language"
BATTING_RESULT_VALUES: tuple[BattingResult, ...] = ("won", "lost")

# Stored winner placeholder for ties, no-results and abandoned matches.
NO_RESULT_WINNER = "-"

_WINNER = "NULLIF(TRIM(CAST(winner AS VARCHAR)), '')"
_BATTING_RESULT_SQL: dict[str, str] = {
    "won": f"{_WINNER} IS NOT NULL AND {_WINNER} <> '{NO_RESULT_WINNER}' "
    "AND CAST(winner AS VARCHAR) = CAST(team_bat AS VARCHAR)",
    "lost": f"{_WINNER} IS NOT NULL AND {_WINNER} <> '{NO_RESULT_WINNER}' "
    "AND CAST(winner AS VARCHAR) = CAST(team_bowl AS VARCHAR)",
}

RESULT_POLICY = (
    "Ties and no-results (stored winner '-') and a stored winner that matches "
    "neither team are neither wins nor losses and are excluded; rain-affected "
    "matches use the stored result as recorded; only the literal second innings "
    "counts as a chase (no super-over rows are stored)."
)


def is_batting_result(value: object) -> bool:
    return isinstance(value, str) and value in BATTING_RESULT_VALUES


def batting_result_clause(value: object) -> tuple[str, list[object]]:
    """Registered SQL for the condition; a malformed value never widens scope."""
    if not is_batting_result(value):
        return ("1 = 0", [])
    return (f"({_BATTING_RESULT_SQL[str(value)]})", [])


def condition_label(filters: dict[str, object]) -> str | None:
    """Short public label for the combined chase/result scope."""
    result = filters.get(BATTING_RESULT_FILTER)
    if not is_batting_result(result):
        return None
    innings = filters.get("innings")
    if innings == 2:
        return "successful chases" if result == "won" else "unsuccessful chases"
    side = "won" if result == "won" else "lost"
    if innings == 1:
        return f"batting first in matches the batting side {side}"
    return f"matches the batting side {side}"


def describe_condition(filters: dict[str, object]) -> str | None:
    """Full definition of the applied condition for evidence and summaries."""
    result = filters.get(BATTING_RESULT_FILTER)
    if not is_batting_result(result):
        return None
    innings = filters.get("innings")
    relation = (
        "the batting team equals the stored match winner"
        if result == "won"
        else "the stored match winner is the bowling team"
    )
    if innings == 2:
        kind = "successful" if result == "won" else "unsuccessful"
        return (
            f"Only {kind} chases are included: second-innings deliveries in which "
            f"{relation}."
        )
    if innings == 1:
        return f"Only first-innings deliveries in which {relation} are included."
    return f"Only deliveries in which {relation} are included (either innings)."


def summary_phrase(filters: dict[str, object]) -> str | None:
    result = filters.get(BATTING_RESULT_FILTER)
    if not is_batting_result(result):
        return None
    innings = filters.get("innings")
    if innings == 2:
        if result == "won":
            return "in successful chases (second innings won by the batting side)"
        return "in unsuccessful chases (second innings lost by the batting side)"
    side = "won" if result == "won" else "lost"
    if innings == 1:
        return f"batting first in matches the batting side {side}"
    return f"in matches the batting side {side}"


# --- language ------------------------------------------------------------------

# Modifiers that may sit between a result adjective and "chases" ("successful
# ODI chases", "successful 2019 run chases"); they are read by their own filters.
_CHASE_NOUN = (
    r"(?:(?:odi|odis|one[- ]day|run|world\s+cup|champions\s+trophy|asia\s+cup|"
    r"(?:19|20)\d{2}|home|away|international)\s+){0,3}chases?"
)
_WON_ADJ = r"(?:successful|winning|won|victorious|completed)"
_LOST_ADJ = r"(?:unsuccessful|failed|losing|lost|abortive)"
_PRONOUN_SIDE = r"(?:they|he|she|his\s+(?:team|side)|her\s+(?:team|side)|their\s+(?:team|side)|the\s+(?:team|side)|we)"
_CHASE_VERB = r"(?:chasing|batting\s+second)"

_OUTCOME_PATTERNS: tuple[tuple[str, int | None, BattingResult], ...] = (
    # Successful chases: second innings in which the batting team won.
    (rf"\b{_WON_ADJ}\s+{_CHASE_NOUN}\b", 2, "won"),
    (
        rf"\b{_CHASE_NOUN}\s+(?:(?:that|which)\s+)?(?:(?:were|was|{_PRONOUN_SIDE})\s+)?"
        r"(?:won|successful)\b",
        2,
        "won",
    ),
    (
        rf"\b{_CHASE_NOUN}\s+(?:that\s+|which\s+)?(?:ended|resulted)\s+in\s+(?:a\s+)?"
        r"(?:wins?|victor(?:y|ies))\b",
        2,
        "won",
    ),
    (r"\bsuccessfully\s+chas(?:ing|ed|es|e)\b", 2, "won"),
    (r"\bchas(?:ing|ed)\s+successfully\b", 2, "won"),
    (r"\b(?:targets?\s+)?chased\s+down\b", 2, "won"),
    (
        rf"\b(?:won|wins|win|winning|victories|victory)\s+(?:(?:while|when|by|after)\s+)?{_CHASE_VERB}\b",
        2,
        "won",
    ),
    (r"\bchasing\s+(?:wins|victories)\b", 2, "won"),
    # Unsuccessful chases: second innings in which the bowling team won.
    (rf"\b{_LOST_ADJ}\s+{_CHASE_NOUN}\b", 2, "lost"),
    (
        rf"\b{_CHASE_NOUN}\s+(?:(?:that|which)\s+)?(?:(?:were|was|{_PRONOUN_SIDE})\s+)?"
        r"(?:lost|failed|unsuccessful)\b",
        2,
        "lost",
    ),
    (
        rf"\b{_CHASE_NOUN}\s+(?:that\s+|which\s+)?(?:ended|resulted)\s+in\s+(?:a\s+)?"
        r"(?:loss|losses|defeats?)\b",
        2,
        "lost",
    ),
    (r"\bunsuccessfully\s+chas(?:ing|ed|es|e)\b", 2, "lost"),
    (r"\bfailed\s+to\s+chase(?:\s+down)?\b", 2, "lost"),
    (
        rf"\b(?:lost|losses|loss|losing|defeats?|defeated)\s+(?:(?:while|when)\s+)?{_CHASE_VERB}\b",
        2,
        "lost",
    ),
    (r"\bchasing\s+(?:losses|defeats)\b", 2, "lost"),
    # Match result without an innings condition (the batting side's result).
    (
        r"\b(?:in|during|from)\s+(?:(?:his|her|their|the|team|a|odi)\s+)?(?:odi\s+)?"
        r"(?:wins|victories|winning\s+(?:causes?|matches|games|odis|efforts?|sides?|teams?)|"
        r"won\s+(?:matches|games|odis)|matches\s+won|games\s+won)\b",
        None,
        "won",
    ),
    (
        rf"\b(?:when|where|in\s+(?:matches|games|odis)\s+(?:that\s+)?)\s*{_PRONOUN_SIDE}\s+won\b",
        None,
        "won",
    ),
    (
        r"\b(?:in|during|from)\s+(?:(?:his|her|their|the|team|a|odi)\s+)?(?:odi\s+)?"
        r"(?:losses|defeats|losing\s+(?:causes?|matches|games|odis|efforts?|sides?|teams?)|"
        r"lost\s+(?:matches|games|odis)|matches\s+lost|games\s+lost)\b",
        None,
        "lost",
    ),
    (
        rf"\b(?:when|where|in\s+(?:matches|games|odis)\s+(?:that\s+)?)\s*{_PRONOUN_SIDE}\s+lost\b",
        None,
        "lost",
    ),
)

# Result wording that asks the condition to be lifted ("all chases now").
_REMOVAL_PATTERNS: tuple[str, ...] = (
    r"\b(?:all|any|every|every\s+kind\s+of)\s+(?:(?:odi|run)\s+)?chases?\b",
    r"\b(?:regardless|irrespective)\s+of\s+(?:the\s+)?(?:match\s+)?(?:result|outcome)s?\b",
    r"\b(?:whatever|whichever)\s+the\s+(?:result|outcome)\b",
    r"\b(?:win\s+or\s+lose|won\s+or\s+lost|wins?\s+(?:or|and)\s+loss(?:es)?)\b",
    r"\b(?:any|all)\s+(?:match\s+)?outcomes?\b|\bany\s+(?:match\s+)?results?\b",
    r"\b(?:without|remove|removing|drop|dropping|ignore|ignoring)\s+(?:the\s+)?"
    r"(?:match\s+|chase\s+)?(?:result|outcome|success)\s*(?:filter|condition|restriction)?\b",
    r"\bnot\s+just\s+(?:the\s+)?(?:successful|winning|won|unsuccessful|failed|losing|lost)\b",
    r"\bincluding\s+(?:the\s+)?(?:unsuccessful|failed|losing|lost|successful|winning|won)"
    rf"(?:\s+{_CHASE_NOUN}|\s+ones)?\b",
)

_TIE_OR_NO_RESULT = re.compile(
    r"\b(?:tied|ties|tie|no[- ]results?|abandoned|washed[- ]out|drawn)\s+"
    r"(?:(?:odi\s+)?(?:matches|games|odis|chases?|contests?))\b|"
    r"\bin\s+(?:ties|tied\s+(?:matches|games|odis)|no[- ]results?)\b|"
    r"\bwhen\s+(?:the\s+)?(?:match|game)\s+(?:was\s+)?(?:tied|abandoned|washed out)\b"
)

# Residual result wording that no registered pattern read. It must fail closed
# rather than disappear (for example "in India's wins" or "matches India lost").
_RESIDUAL_RESULT = re.compile(
    r"\b(?:in|during|when|while|from|where)\s+(?:\S+\s+){0,3}?"
    r"(?:wins|victories|losses|defeats|won|lost|winning|losing|"
    r"successful|unsuccessful|failed)\b"
)
_RESIDUAL_ALLOWED = re.compile(
    # Wording that uses result words for other registered meanings.
    r"\b(?:won|win|winning|lost)\s+(?:the\s+)?toss\b|"
    r"\bmost\s+successful\b|\bsuccessful\s+(?:bowlers?|batters?|batsmen|players?)\b"
)


@dataclass(frozen=True, slots=True)
class ResultConditionMention:
    innings: int | None
    result: BattingResult | None
    span: tuple[int, int]
    kind: Literal["condition", "removal"]
    text: str


def _clean(text: str) -> str:
    return " ".join(
        text.lower().replace("’", "'").replace("–", "-").replace("—", "-").split()
    )


def result_condition_mentions(text: str) -> list[ResultConditionMention]:
    lowered = _clean(text)
    mentions: list[ResultConditionMention] = []
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < t_end and t_start < end for t_start, t_end in taken)

    for pattern in _REMOVAL_PATTERNS:
        for match in re.finditer(pattern, lowered):
            if overlaps(*match.span()):
                continue
            taken.append(match.span())
            chase = bool(re.search(r"chas", match.group(0)))
            mentions.append(
                ResultConditionMention(
                    innings=2 if chase else None,
                    result=None,
                    span=match.span(),
                    kind="removal",
                    text=match.group(0),
                )
            )
    for pattern, innings, result in _OUTCOME_PATTERNS:
        for match in re.finditer(pattern, lowered):
            if overlaps(*match.span()):
                continue
            taken.append(match.span())
            mentions.append(
                ResultConditionMention(
                    innings=innings,
                    result=result,
                    span=match.span(),
                    kind="condition",
                    text=match.group(0),
                )
            )
    return sorted(mentions, key=lambda mention: mention.span)


def requested_result_filters(text: str) -> dict[str, object]:
    """Registered filters stated by chase/result wording; {} when none or conflicting."""
    conditions = [m for m in result_condition_mentions(text) if m.kind == "condition"]
    results = {m.result for m in conditions}
    if len(results) != 1:
        return {}
    filters: dict[str, object] = {BATTING_RESULT_FILTER: next(iter(results))}
    innings = {m.innings for m in conditions if m.innings is not None}
    if len(innings) == 1:
        filters["innings"] = next(iter(innings))
    return filters


def removes_result_condition(text: str) -> bool:
    return any(m.kind == "removal" for m in result_condition_mentions(text))


def strip_result_phrases(text: str) -> str:
    """Remove chase/result wording so it is not reread as other filters."""
    lowered = _clean(text)
    mentions = result_condition_mentions(lowered)
    if not mentions:
        return lowered
    pieces: list[str] = []
    cursor = 0
    for mention in mentions:
        start, end = mention.span
        if start < cursor:
            continue
        pieces.append(lowered[cursor:start])
        pieces.append(" ")
        cursor = end
    pieces.append(lowered[cursor:])
    return " ".join("".join(pieces).split())


def result_condition_problem(text: str) -> str | None:
    """A result condition that cannot compile exactly must fail closed."""
    lowered = _clean(text)
    conditions = [m for m in result_condition_mentions(lowered) if m.kind == "condition"]
    results = {m.result for m in conditions}
    paired = re.search(
        rf"\b(?:{_WON_ADJ}|wins?)\s+(?:and|or|vs\.?|versus|compared\s+(?:to|with))\s+(?:{_LOST_ADJ}|loss(?:es)?)\b|"
        rf"\b(?:{_LOST_ADJ}|loss(?:es)?)\s+(?:and|or|vs\.?|versus|compared\s+(?:to|with))\s+(?:{_WON_ADJ}|wins?)\b",
        lowered,
    )
    if paired and any(m.kind == "removal" for m in result_condition_mentions(lowered)):
        # "win or lose" / "won or lost" lift the condition instead.
        paired = None
    if len(results) > 1 or paired:
        return (
            "Comparing successful and unsuccessful chases (or wins and losses) in one "
            "question is not supported yet. Ask for one result condition, for example "
            "most runs in successful chases or in unsuccessful chases."
        )
    if _TIE_OR_NO_RESULT.search(lowered):
        return (
            "Ties and no-results are not a registered result filter: they are stored "
            "with no winner ('-') and are excluded from both successful and "
            "unsuccessful chases. Registered result conditions are the batting side "
            "winning or losing, alone or with chasing."
        )
    if any(m.innings == 2 for m in conditions) and re.search(
        r"\b(?:batting first|first innings|innings 1|setting (?:a|the) target)\b", lowered
    ):
        return (
            "A chase is the second innings, so a chase-result condition cannot be "
            "combined with batting first. Ask about chases or about batting first."
        )
    residual = strip_result_phrases(lowered)
    residual = _RESIDUAL_ALLOWED.sub(" ", residual)
    match = _RESIDUAL_RESULT.search(residual)
    if match:
        return (
            f"The match-result condition '{match.group(0)}' could not be read as a "
            "registered result filter. Supported conditions are successful chases, "
            "unsuccessful chases, and matches the batting side won or lost."
        )
    return None


def outcome_from_language(values: list[object], evidence: str) -> BattingResult | None:
    """Read a model-extracted outcome; the values and evidence must agree."""
    readings: set[str] = set()
    for raw in [*values, evidence]:
        if not isinstance(raw, str) or not raw.strip():
            continue
        word = _clean(raw)
        if re.search(r"\b(?:unsuccessful(?:ly)?|failed|fail|lost|loss|losses|losing|lose|defeats?|defeated)\b", word):
            readings.add("lost")
        elif re.search(r"\b(?:successful(?:ly)?|success|won|wins?|winning|victor(?:y|ies|ious)|chased down)\b", word):
            readings.add("won")
        else:
            conditions = requested_result_filters(word)
            if conditions:
                readings.add(str(conditions[BATTING_RESULT_FILTER]))
    if len(readings) != 1:
        return None
    return next(iter(readings))  # type: ignore[return-value]


def innings_from_language(values: list[object], evidence: str) -> int | None:
    """Read a model-extracted innings/chase fact; values and evidence must agree."""
    readings: set[int] = set()
    for raw in [*values, evidence]:
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int) and raw in {1, 2}:
            readings.add(raw)
            continue
        if not isinstance(raw, str) or not raw.strip():
            continue
        word = _clean(raw)
        if word in {"1", "2"}:
            readings.add(int(word))
        elif re.search(r"\b(?:chas(?:e|es|ing|ed)|second(?:\s+innings)?|batting\s+second|2nd)\b", word):
            readings.add(2)
        elif re.search(r"\b(?:first(?:\s+innings)?|batting\s+first|setting|1st)\b", word):
            readings.add(1)
    if len(readings) != 1:
        return None
    return next(iter(readings))


def is_outcome_concept(concept: str) -> bool:
    lowered = _clean(concept).replace("_", " ")
    return bool(
        re.search(
            r"\b(?:outcome|result|won|win|wins|winning|success|successful|victory|"
            r"victories|loss|losses|lost|defeat)\b",
            lowered,
        )
    ) and "toss" not in lowered


def is_chase_outcome_concept(concept: str) -> bool:
    lowered = _clean(concept).replace("_", " ")
    return bool(re.search(r"\bchas", lowered)) and is_outcome_concept(lowered)


def is_innings_concept(concept: str) -> bool:
    lowered = _clean(concept).replace("_", " ")
    return bool(
        re.fullmatch(
            r"(?:batting\s+|match\s+)?(?:innings(?:\s+(?:type|number|order|kind|situation|context|status))?|"
            r"(?:run\s+)?chas(?:e|es|ing)(?:\s+(?:status|context|situation))?|batting\s+order|"
            r"batting\s+(?:first|second))",
            lowered,
        )
    )


def unsupported_role_reason() -> str:
    return (
        "Chase and match-result conditions are registered for batting statistics "
        "(the batting side's result). For bowling statistics the result must be "
        "stated from the bowling side, which is not a registered condition yet."
    )
