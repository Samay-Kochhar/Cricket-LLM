"""Registered batter dismissal-type dimension.

Dismissal type is a categorical dimension over the stored ``dismissal`` field.
Counts use dismissed-batter attribution: a delivery row counts for a batter when
the source marks it as a dismissal (``out``) and its ``p_out`` identifier is that
batter. That includes a non-striker who is run out and excludes a striker whose
partner was run out. It is independent of bowler-credit wicket attribution,
which keeps using ``BOWLER_WICKET_PREDICATE``.

Stored categories are literal. The source has no separate caught-and-bowled
category and no fielder or catcher field, so "caught" means only the stored
``caught`` category, and caught-and-bowled, caught-behind or fielder-specific
catches are data limitations rather than silently merged categories.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DismissalTypeDefinition:
    stored: str
    label: str
    pattern: str
    bowler_credit: bool


DISMISSAL_TYPE_REGISTRY: dict[str, DismissalTypeDefinition] = {
    definition.stored: definition
    for definition in (
        DismissalTypeDefinition("caught", "Caught", r"caught(?: out)?", True),
        DismissalTypeDefinition("bowled", "Bowled", r"bowled", True),
        DismissalTypeDefinition(
            "leg before wicket",
            "Leg before wicket",
            r"lbw|l\.b\.w\.?|leg[- ]before(?:[- ](?:the[- ])?wicket)?",
            True,
        ),
        DismissalTypeDefinition("run out", "Run out", r"run[- ]?outs?", False),
        DismissalTypeDefinition("stumped", "Stumped", r"stumped", True),
        DismissalTypeDefinition("hit wicket", "Hit wicket", r"hit[- ]wicket", True),
        DismissalTypeDefinition(
            "obstructing the field",
            "Obstructing the field",
            r"obstruct(?:ing|ed|ion of)? the field",
            False,
        ),
        DismissalTypeDefinition(
            "handled the ball",
            "Handled the ball",
            r"handl(?:ed|ing) the ball",
            False,
        ),
    )
}

# Values stored with ``out = True`` that are not dismissals of the batter.
NON_DISMISSAL_OUT_VALUES = ("retired not out (hurt)", "not out")

DISMISSAL_TYPE_SQL_LIST = ", ".join(
    f"'{stored}'" for stored in DISMISSAL_TYPE_REGISTRY
)
DISMISSAL_TYPE_EXPRESSION = "LOWER(TRIM(CAST(dismissal AS VARCHAR)))"
BATTER_DISMISSAL_PREDICATE = (
    "LOWER(CAST(out AS VARCHAR)) = 'true' AND "
    f"{DISMISSAL_TYPE_EXPRESSION} IN ({DISMISSAL_TYPE_SQL_LIST})"
)

# Detail the source does not record. Asking for it is a data limitation.
_UNRECORDED_DETAILS: tuple[tuple[str, str], ...] = (
    (
        r"\bcaught (?:and|&|n) bowled\b|\bc ?& ?b\b",
        "caught and bowled",
    ),
    (
        r"\bcaught (?:behind|at\b|in the (?:deep|slips?|ring|outfield)|"
        r"by (?:the |a )?(?:keeper|wicket[- ]?keeper|fielder|slip))",
        "caught by a particular fielder or position",
    ),
    (r"\btimed out\b", "timed out"),
    (r"\bretired\b", "retired"),
)
_UNRECORDED_REASON = {
    "caught and bowled": (
        "The ODI delivery data stores caught-and-bowled dismissals inside the "
        "literal 'caught' category and does not record the catcher, so they "
        "cannot be separated. For the separate caught and bowled dismissal types, "
        "ask for caught versus bowled."
    ),
    "caught by a particular fielder or position": (
        "The ODI delivery data records the 'caught' dismissal type but not the "
        "catcher or fielding position."
    ),
    "timed out": "The ODI delivery data has no recorded 'timed out' dismissals.",
    "retired": (
        "Retirements are recorded as 'retired not out (hurt)', which is not a "
        "dismissal, so they are excluded from batter dismissal types."
    ),
}

_AXIS = re.compile(
    r"\b(?:(?:dismissal|out) (?:types?|modes?|methods?|kinds?|categor(?:y|ies)|breakdown)"
    r"|(?:types?|modes?|methods?|kinds?|ways?|forms?|categor(?:y|ies)) of "
    r"(?:dismissals?|getting out|being dismissed)"
    r"|how (?!often\b|many\b|much\b|long\b|quickly\b|soon\b)(?:(?:has|have|had|does|did|is|was|were) )?(?:[\w']+ ){0,3}"
    r"(?:been |got |gotten |get |gets |getting |usually |mostly |typically |commonly )*"
    r"(?:dismissed|out)\b(?! of)"
    r"|ways? (?:[\w']+ ){0,3}(?:got|gets|get|getting|gotten|was|is|been|being) (?:out|dismissed)\b"
    r"|(?:most|least) (?:common|frequent|usual) (?:way|mode|method|type|form)s?"
    r"(?: of (?:dismissal|getting out))?)"
)
_DISMISSAL_WORD = re.compile(r"\bdismiss(?:al|als|ed|es|ing)?\b")
_PASSIVE = re.compile(
    r"\b(?:got|get|gets|getting|gotten|been|was|were|is|being|be)\b"
    r"(?:\s+[\w']+){0,3}?\s+(?:caught|bowled|stumped|run[- ]out|lbw|leg[- ]before|hit[- ]wicket|out)\b"
)
_COMPARING = re.compile(
    r"\b(?:compare|compared|comparing|comparison|versus|vs|both|each|separately|respectively)\b"
)
_FREQUENCY = re.compile(
    r"\b(?:how (?:often|many times)|number of times|times|counts?|tally|totals?)\b"
)
_SHARE = re.compile(
    r"\b(?:percent(?:age)?s?|share|proportion|fraction|what part|how much of)\b|%"
)
# Fielding or bowler-credit perspectives that are not a dismissed batter.
_FIELDING = re.compile(
    r"\b(?:catches|catcher|catching|fielders?|fielding|effect(?:ed|s|ing)?|"
    r"affect(?:ed|s)?|execut(?:e|ed|es|ing)|involved|involvement|completed|"
    r"direct hits?|throws?)\b"
)
_SINGLE_MATCH = re.compile(
    r"\b(?:finals?|semi[- ]?finals?|quarter[- ]?finals?|eliminator|(?:that|this|last|latest|opening) (?:match|game))\b"
)
_OTHER_METRICS = re.compile(
    r"\b(?:runs(?! chases?)|run rate|strike rate|average|economy|wickets?|boundar(?:y|ies)|"
    r"sixes|fours|dot balls?|false shots?|yorkers?|balls faced|scor(?:e|ed|es|ing))\b"
)


@dataclass(frozen=True, slots=True)
class DismissalTypeRequest:
    categories: tuple[str, ...]
    breakdown: bool
    share: bool
    unrecorded: tuple[str, ...]
    other_metric: bool
    fielding_perspective: bool
    ratio: bool
    single_match: bool

    @property
    def unrecorded_reason(self) -> str | None:
        if not self.unrecorded:
            return None
        return " ".join(_UNRECORDED_REASON[item] for item in self.unrecorded)


def _normalized(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").replace("–", "-").split())


def _category_mentions(text: str) -> list[tuple[int, str]]:
    mentions: list[tuple[int, str]] = []
    for stored, definition in DISMISSAL_TYPE_REGISTRY.items():
        for match in re.finditer(rf"(?<![\w-])(?:{definition.pattern})(?![\w-])", text):
            mentions.append((match.start(), stored))
    return mentions


def requested_dismissal_types(question: str) -> DismissalTypeRequest | None:
    """Detect a batter dismissal-type request from explicit wording.

    Category words only count when the wording is about a dismissal: a
    dismissal word, passive "was/got ... caught" wording, frequency wording,
    or two or more categories. "Overs bowled" and similar bowling wording
    therefore never become a dismissal category.
    """
    text = _normalized(question)
    unrecorded: list[str] = []
    stripped = text
    comparing = bool(_COMPARING.search(text))
    for pattern, label in _UNRECORDED_DETAILS:
        if label == "caught and bowled" and comparing:
            # "Compare how often X was caught and bowled" lists the two
            # literal categories; the answer shows each one separately.
            continue
        if re.search(pattern, stripped):
            unrecorded.append(label)
            stripped = re.sub(pattern, " ", stripped)
    mentions = _category_mentions(stripped)
    categories = tuple(
        dict.fromkeys(stored for _, stored in sorted(mentions))
    )
    breakdown = bool(_AXIS.search(text))
    context = bool(
        _DISMISSAL_WORD.search(text)
        or _PASSIVE.search(text)
        or len(categories) + len(unrecorded) >= 2
        or (
            (unrecorded or any(category != "bowled" for category in categories))
            and _FREQUENCY.search(text)
        )
    )
    if not (breakdown or ((categories or unrecorded) and context)):
        return None
    without_categories = stripped
    for stored, definition in DISMISSAL_TYPE_REGISTRY.items():
        without_categories = re.sub(
            rf"(?<![\w-])(?:{definition.pattern})(?![\w-])", " ", without_categories
        )
    return DismissalTypeRequest(
        categories=categories,
        breakdown=breakdown,
        share=bool(_SHARE.search(text)),
        unrecorded=tuple(dict.fromkeys(unrecorded)),
        other_metric=bool(_OTHER_METRICS.search(without_categories)),
        fielding_perspective=bool(_FIELDING.search(text)),
        ratio=bool(re.search(r"\bratios?\b|\brelative to\b|\bper (?:caught|bowled)\b", text)),
        single_match=bool(_SINGLE_MATCH.search(text)),
    )


def canonical_dismissal_type(value: object) -> str | None:
    """Map one extracted category value to its stored category, or None."""
    text = _normalized(str(value)).replace("_", " ").strip(" .")
    if not text:
        return None
    for pattern, _ in _UNRECORDED_DETAILS:
        if re.search(pattern, text):
            return None
    for stored, definition in DISMISSAL_TYPE_REGISTRY.items():
        if re.fullmatch(rf"(?:{definition.pattern})", text):
            return stored
    return None


def is_dismissal_type_concept(concept: str) -> bool:
    text = _normalized(concept).replace("_", " ")
    if re.search(r"\b(?:batters?|batsm[ae]n|bowlers?|players?|dismissor|by)\b", text):
        # "dismissed batter" and "dismissed by" are relationships, not categories.
        return False
    return bool(
        re.search(r"\bdismiss", text)
        or re.search(r"\b(?:how out|mode of (?:dismissal|getting out)|out type|wicket type)\b", text)
    )


def is_dismissal_share_concept(concept: str) -> bool:
    text = _normalized(concept).replace("_", " ")
    return bool(_DISMISSAL_WORD.search(text) and _SHARE.search(text))


def dismissal_type_label(stored: object) -> str:
    definition = DISMISSAL_TYPE_REGISTRY.get(str(stored))
    return definition.label if definition else str(stored)


def dismissal_type_mentions(question: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Literal categories and unrecorded details named anywhere in the text.

    Used for contextual follow-ups whose previous answer already established
    the dismissal-type meaning ("What about stumped?").
    """
    text = _normalized(question)
    comparing = bool(_COMPARING.search(text))
    unrecorded: list[str] = []
    for pattern, label in _UNRECORDED_DETAILS:
        if label == "caught and bowled" and comparing:
            continue
        if re.search(pattern, text):
            unrecorded.append(label)
            text = re.sub(pattern, " ", text)
    categories = tuple(dict.fromkeys(stored for _, stored in sorted(_category_mentions(text))))
    return categories, tuple(unrecorded)


def unrecorded_reason(unrecorded: tuple[str, ...]) -> str:
    return " ".join(_UNRECORDED_REASON[item] for item in unrecorded)


def without_dismissal_categories(question: str) -> str:
    text = _normalized(question)
    for pattern, _ in _UNRECORDED_DETAILS:
        text = re.sub(pattern, " ", text)
    for definition in DISMISSAL_TYPE_REGISTRY.values():
        text = re.sub(rf"(?<![\w-])(?:{definition.pattern})(?![\w-])", " ", text)
    return " ".join(text.split())


def requests_all_dismissal_types(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:all|every|each|any|other) (?:the )?(?:dismissal |out )?"
            r"(?:types?|modes?|methods?|kinds?|categor(?:y|ies))\b|\ball (?:his |her |their )?dismissals\b",
            _normalized(question),
        )
    )


def requests_dismissal_share(question: str) -> bool:
    return bool(_SHARE.search(_normalized(question)))


def requests_dismissal_counts(question: str) -> bool:
    return bool(
        re.search(r"\b(?:counts?|how many|number of|totals?|raw numbers?)\b", _normalized(question))
    )
