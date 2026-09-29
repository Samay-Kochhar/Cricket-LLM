"""Registered numeric match-state filters (typed predicates over delivery state).

Only fields registered here may compile into a database predicate. A predicate is
a registered field, a comparison operator and a numeric value (or an inclusive
bound pair); it is never an arbitrary SQL expression. Language parsing is
deterministic: the model may extract the same meaning, but the numbers, operators,
database column and null policy are owned by this module.

Required run rate audit (``data/odi_analytics.duckdb``): ``inns_rrr`` is only
recorded for second-innings deliveries and equals
``ROUND(inns_runs_rem * 6 / inns_balls_rem, 2)`` where both remaining values are
the state *after* the recorded delivery (624,753 of 625,076 second-innings rows
match exactly; the remaining 323 rows have no balls remaining and store 0). A
delivery with no balls remaining has no defined required rate, so it is treated
as unavailable rather than as zero, exactly like first-innings rows.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal


NumericOperator = Literal["gt", "gte", "lt", "lte", "between"]
MATCH_STATE_SOURCE = "registered_match_state_language"

OPERATOR_SQL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
OPERATOR_SYMBOLS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
OPERATOR_WORDS = {"gt": "above", "gte": "at least", "lt": "below", "lte": "at most"}


@dataclass(frozen=True, slots=True)
class MatchStateField:
    field_id: str
    label: str
    column: str
    value_sql: str
    availability_sql: str
    alias_pattern: str
    minimum: float
    maximum: float
    timing: str
    null_policy: str


REQUIRED_RUN_RATE = MatchStateField(
    field_id="required_run_rate",
    label="required run rate",
    column="inns_rrr",
    value_sql="TRY_CAST(inns_rrr AS DOUBLE)",
    availability_sql=(
        "TRY_CAST(inns_rrr AS DOUBLE) IS NOT NULL "
        "AND TRY_CAST(inns_balls_rem AS DOUBLE) > 0"
    ),
    alias_pattern=(
        r"required\s+(?:run[- ]?|scoring\s+)?rate|required\s+rr\b|\brrr\b|"
        r"\breq(?:'?d|\.)?\s+(?:run[- ]?)?rate|asking\s+(?:run[- ]?)?rate|"
        r"run[- ]rate\s+required"
    ),
    minimum=0.0,
    maximum=100.0,
    timing=(
        "recorded after each delivery: runs still needed x 6 / legal balls "
        "remaining, both after the ball"
    ),
    null_policy=(
        "recorded only for second-innings deliveries with balls remaining; "
        "first-innings deliveries and deliveries with no balls remaining are "
        "excluded, never treated as zero"
    ),
)

MATCH_STATE_FIELDS: dict[str, MatchStateField] = {
    REQUIRED_RUN_RATE.field_id: REQUIRED_RUN_RATE,
}


# Stored numeric state that is not (yet) a registered filter. Mentioned with a
# numeric comparison, these fail closed with the concept retained verbatim.
_UNREGISTERED_CONCEPTS: tuple[tuple[str, str], ...] = (
    ("current run rate", r"(?:current|scoring)\s+run[- ]?rate|\bcrr\b"),
    ("run rate", r"(?<!required )(?<!asking )(?<!req )\brun[- ]?rate"),
    ("target", r"\btargets?\b"),
    (
        "runs needed",
        r"\bruns?\s+(?:needed|required|remaining|left|to\s+(?:win|get))",
    ),
    ("balls remaining", r"\b(?:balls?|deliveries|overs)\s+(?:remaining|left)"),
    (
        "wickets in hand",
        r"\bwickets?\s+(?:in\s+hand|down|lost|fallen|remaining|left)",
    ),
    ("win probability", r"\bwin(?:ning)?\s+(?:probability|chances?|prob)\b"),
    ("predicted score", r"\b(?:predicted|projected)\s+(?:score|total)"),
    ("team score", r"\b(?:team|innings)\s+(?:score|total)"),
)

_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "eighteen": 18,
    "twenty": 20,
}
_WORD_ALTERNATION = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_NUM = rf"(\d{{1,4}}(?:\.\d+)?(?!\d)(?!\.\d)|\.\d+(?!\d)|(?:{_WORD_ALTERNATION})\b)"
# "8 an over", "8 runs per over", "8 rpo" all restate the rate unit.
_RATE_UNIT = r"(?:\s*(?:runs?\s+)?(?:an|a|per)\s+over\b|\s*rpo\b|\s*runs?\s+an?\s+over\b)?"
# A number followed by a sample/count unit belongs to another construct.
_OTHER_UNIT = (
    r"(?!\s*(?:legal\s+)?(?:balls?|deliver|innings|overs?\b|matches|games|"
    r"wickets?|runs?\b(?!\s+(?:an|a|per)\s+over)|%|percent|years?))"
)
_LINK = (
    r"(?:\s+(?:was|is|were|are|stood|stands|sat|sits|went|goes|got|gets|"
    r"has\s+been|had\s+been|have\s+been|been|of|at(?!\s+(?:least|most)\b)|climbed|climbing|rose|rising|"
    r"being|remained|remains|stays?|stayed|the))*"
)
_GTE_PREFIX = (
    r"at\s+least|no\s+less\s+than|not\s+less\s+than|a\s+minimum\s+of|"
    r"minimum\s+of|>=|≥|greater\s+than\s+or\s+equal\s+to|"
    r"(?:more|higher)\s+than\s+or\s+equal\s+to|upwards\s+of"
)
_LTE_PREFIX = (
    r"at\s+most|no\s+more\s+than|not\s+more\s+than|a\s+maximum\s+of|"
    r"maximum\s+of|up\s+to|<=|≤|less\s+than\s+or\s+equal\s+to|"
    r"(?:lower)\s+than\s+or\s+equal\s+to"
)
_GT_PREFIX = (
    r"above|over|greater\s+than|more\s+than|higher\s+than|exceeding|exceeded|"
    r"exceeds|in\s+excess\s+of|north\s+of|beyond|>"
)
_LT_PREFIX = r"below|under|less\s+than|fewer\s+than|lower\s+than|beneath|south\s+of|<"
_ANY_PREFIX = f"{_GTE_PREFIX}|{_LTE_PREFIX}|{_GT_PREFIX}|{_LT_PREFIX}|between|from"
_REMOVAL = (
    r"(?:without|remove|removing|drop|dropping|ignore|ignoring|regardless\s+of|"
    r"irrespective\s+of|no|any|all|clear|lift)\s+(?:the\s+|that\s+|a\s+)?"
)
_REMOVAL_SUFFIX = r"(?:\s+(?:filter|condition|threshold|restriction|limit|cut-?off)s?)?"


class NumericPredicate:
    """A typed comparison: registered field + operator + numeric value(s)."""

    __slots__ = ("operator", "value", "lower", "upper")

    def __init__(
        self,
        operator: NumericOperator,
        value: int | float | None = None,
        *,
        lower: int | float | None = None,
        upper: int | float | None = None,
    ) -> None:
        self.operator = operator
        self.value = value
        self.lower = lower
        self.upper = upper

    def as_filter(self) -> dict[str, object]:
        if self.operator == "between":
            return {"operator": "between", "lower": self.lower, "upper": self.upper}
        return {"operator": self.operator, "value": self.value}

    def values(self) -> list[int | float]:
        if self.operator == "between":
            return [v for v in (self.lower, self.upper) if v is not None]
        return [self.value] if self.value is not None else []

    def describe(self, field: MatchStateField, *, symbols: bool = False) -> str:
        if self.operator == "between":
            return (
                f"{field.label} between {_fmt(self.lower)} and {_fmt(self.upper)} "
                "(inclusive)"
            )
        if symbols:
            return f"{field.label} {OPERATOR_SYMBOLS[self.operator]} {_fmt(self.value)}"
        return f"{field.label} {OPERATOR_WORDS[self.operator]} {_fmt(self.value)}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NumericPredicate) and self.as_filter() == other.as_filter()

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.as_filter().items())))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"NumericPredicate({self.as_filter()!r})"


@dataclass(frozen=True, slots=True)
class MatchStateMention:
    """One match-state concept found in language, resolved or not."""

    concept: str
    field: MatchStateField | None
    predicate: NumericPredicate | None
    span: tuple[int, int]
    kind: Literal["predicate", "removal", "unresolved", "unregistered"]
    problem: str | None = None


def number_value(raw: object) -> int | float | None:
    """Parse one numeric value exactly; integral values stay integers."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if not math.isfinite(raw):
            return None
        return int(raw) if raw.is_integer() else raw
    if not isinstance(raw, str):
        return None
    text = raw.strip().lower()
    if text in _NUMBER_WORDS:
        return _NUMBER_WORDS[text]
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return None
    if not decimal.is_finite():
        return None
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def predicate_from_filter(value: object, field: MatchStateField) -> NumericPredicate | None:
    """Validate a compiled plan filter value; malformed shapes never compile."""
    if not isinstance(value, dict):
        return None
    operator = value.get("operator")
    if operator == "between":
        if set(value) != {"operator", "lower", "upper"}:
            return None
        lower = _strict_number(value.get("lower"))
        upper = _strict_number(value.get("upper"))
        if lower is None or upper is None or not lower < upper:
            return None
        if not (field.minimum <= lower and upper <= field.maximum):
            return None
        return NumericPredicate("between", lower=lower, upper=upper)
    if operator not in OPERATOR_SQL or set(value) != {"operator", "value"}:
        return None
    number = _strict_number(value.get("value"))
    if number is None or not field.minimum <= number <= field.maximum:
        return None
    return NumericPredicate(operator, number)  # type: ignore[arg-type]


def predicate_sql(field: MatchStateField, predicate: NumericPredicate) -> tuple[str, list[float]]:
    """Parameterized SQL from the registered column; values are bound, never inlined."""
    availability = f"({field.availability_sql})"
    if predicate.operator == "between":
        return (
            f"{availability} AND {field.value_sql} BETWEEN ? AND ?",
            [float(predicate.lower), float(predicate.upper)],  # type: ignore[arg-type]
        )
    return (
        f"{availability} AND {field.value_sql} {OPERATOR_SQL[predicate.operator]} ?",
        [float(predicate.value)],  # type: ignore[arg-type]
    )


def match_state_filter_clauses(filters: dict[str, object]) -> list[tuple[str, list[float]]]:
    clauses: list[tuple[str, list[float]]] = []
    for key, value in filters.items():
        field = MATCH_STATE_FIELDS.get(key)
        if field is None:
            continue
        predicate = predicate_from_filter(value, field)
        if predicate is None:
            # Validation rejects malformed predicates; never widen the scope.
            clauses.append(("1 = 0", []))
            continue
        clauses.append(predicate_sql(field, predicate))
    return clauses


def match_state_filters_in(filters: dict[str, object]) -> list[tuple[MatchStateField, NumericPredicate]]:
    found: list[tuple[MatchStateField, NumericPredicate]] = []
    for key, value in filters.items():
        field = MATCH_STATE_FIELDS.get(key)
        if field is None:
            continue
        predicate = predicate_from_filter(value, field)
        if predicate is not None:
            found.append((field, predicate))
    return found


def describe_filter(key: str, value: object) -> str | None:
    field = MATCH_STATE_FIELDS.get(key)
    if field is None:
        return None
    predicate = predicate_from_filter(value, field)
    return predicate.describe(field) if predicate else None


# --- language ------------------------------------------------------------------


def match_state_mentions(text: str) -> list[MatchStateMention]:
    """Find every registered or stored numeric match-state concept in language."""
    lowered = _clean(text)
    mentions: list[MatchStateMention] = []
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < t_end and t_start < end for t_start, t_end in taken)

    for field in MATCH_STATE_FIELDS.values():
        alias = rf"(?:{field.alias_pattern})"
        for match in re.finditer(rf"\b{_REMOVAL}{alias}{_REMOVAL_SUFFIX}", lowered):
            if _is_removal_context(lowered, match):
                mentions.append(
                    MatchStateMention(
                        concept=_alias_text(match.group(0), alias),
                        field=field,
                        predicate=None,
                        span=match.span(),
                        kind="removal",
                    )
                )
                taken.append(match.span())
        for match in re.finditer(alias, lowered):
            if overlaps(*match.span()):
                continue
            mentions.append(_field_mention(lowered, field, match, taken))

    for concept, pattern in _UNREGISTERED_CONCEPTS:
        for match in re.finditer(pattern, lowered):
            if overlaps(*match.span()):
                continue
            comparison = _comparison_after(lowered, match.end()) or _comparison_before(
                lowered, match.start()
            )
            if comparison is None:
                continue
            span = (min(match.start(), comparison[1][0]), max(match.end(), comparison[1][1]))
            taken.append(span)
            mentions.append(
                MatchStateMention(
                    concept=concept,
                    field=None,
                    predicate=None,
                    span=span,
                    kind="unregistered",
                    problem=unregistered_reason(concept),
                )
            )
    chase = re.search(
        rf"\bchas(?:e|es|ing)\s+(?:down\s+)?(?:(?:a\s+)?targets?\s+(?:of\s+)?)?"
        rf"(?:(?:{_ANY_PREFIX})\s+{_NUM}|{_NUM}\s*\+)",
        lowered,
    )
    if chase and not overlaps(*chase.span()):
        mentions.append(
            MatchStateMention(
                concept="target",
                field=None,
                predicate=None,
                span=chase.span(),
                kind="unregistered",
                problem=unregistered_reason("target"),
            )
        )
    return sorted(mentions, key=lambda mention: mention.span)


def registered_predicates(text: str) -> dict[str, dict[str, object]]:
    """Resolved registered predicates keyed by plan filter name."""
    predicates: dict[str, dict[str, object]] = {}
    for mention in match_state_mentions(text):
        if mention.kind == "predicate" and mention.field and mention.predicate:
            key = mention.field.field_id
            value = mention.predicate.as_filter()
            if key in predicates and predicates[key] != value:
                # Two different thresholds for one field are not one predicate.
                return {}
            predicates[key] = value
    return predicates


def conflicting_predicates(text: str) -> bool:
    seen: dict[str, dict[str, object]] = {}
    for mention in match_state_mentions(text):
        if mention.kind == "predicate" and mention.field and mention.predicate:
            key = mention.field.field_id
            value = mention.predicate.as_filter()
            if key in seen and seen[key] != value:
                return True
            seen[key] = value
    return False


def removed_fields(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            mention.field.field_id
            for mention in match_state_mentions(text)
            if mention.kind == "removal" and mention.field is not None
        )
    )


def unresolved_mention(text: str) -> MatchStateMention | None:
    """The first concept that must fail closed instead of compiling silently."""
    if conflicting_predicates(text):
        mention = next(
            m for m in match_state_mentions(text) if m.kind == "predicate"
        )
        return MatchStateMention(
            concept=mention.concept,
            field=mention.field,
            predicate=None,
            span=mention.span,
            kind="unresolved",
            problem=(
                f"The question states more than one {mention.field.label if mention.field else mention.concept} "
                "threshold. Ask for one threshold or an inclusive range such as between 6 and 8."
            ),
        )
    for mention in match_state_mentions(text):
        if mention.kind in {"unresolved", "unregistered"}:
            return mention
    return None


def strip_match_state_phrases(text: str) -> str:
    """Remove predicate/removal wording so numbers are not reread as samples etc."""
    lowered = _clean(text)
    mentions = match_state_mentions(lowered)
    if not mentions:
        # Leave unrelated wording byte-for-byte unchanged (apart from case).
        return text.lower()
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


def bare_predicate_match(text: str) -> tuple[NumericPredicate, str] | None:
    """A follow-up threshold with no field ("What about above 10?").

    Returns the predicate and the text with that threshold removed. "over" is
    not accepted without a field because it also introduces over numbers.
    """
    lowered = _clean(text)
    if match_state_mentions(lowered):
        return None
    prefixes = f"{_GTE_PREFIX}|{_LTE_PREFIX}|{_GT_PREFIX.replace('over|', '')}|{_LT_PREFIX}|between"
    found: list[tuple[NumericPredicate, tuple[int, int]]] = []
    for match in re.finditer(rf"(?:(?<=\s)|^)(?:{prefixes})", lowered):
        parsed = _parse_comparison(lowered, match.start())
        if parsed is None or parsed[0] is None:
            continue
        found.append((parsed[0], parsed[1]))
    if len(found) != 1:
        return None
    predicate, (start, end) = found[0]
    return predicate, " ".join((lowered[:start] + " " + lowered[end:]).split())


def bare_predicate(text: str) -> NumericPredicate | None:
    match = bare_predicate_match(text)
    return match[0] if match else None


def predicate_from_language_values(
    operator: str | None,
    values: list[object],
    evidence: str,
    field: MatchStateField,
) -> NumericPredicate | None:
    """Interpret a model-extracted filter; every reading must agree exactly."""
    readings: list[NumericPredicate] = []
    numbers = [number_value(value) for value in values]
    if operator is not None and values and all(n is not None for n in numbers):
        if operator == "between" and len(numbers) == 2:
            lower, upper = sorted(numbers)  # type: ignore[type-var]
            readings.append(NumericPredicate("between", lower=lower, upper=upper))
        elif operator in OPERATOR_SQL and len(numbers) == 1:
            readings.append(NumericPredicate(operator, numbers[0]))  # type: ignore[arg-type]
        else:
            return None
    elif operator is not None and operator not in {*OPERATOR_SQL, "between"}:
        return None
    string_values = [value for value in values if isinstance(value, str) and number_value(value) is None]
    if string_values:
        parsed = _parse_standalone(" ".join(string_values))
        if parsed is None:
            return None
        readings.append(parsed)
    evidence_mentions = [
        mention
        for mention in match_state_mentions(evidence)
        if mention.field is field and mention.kind == "predicate"
    ]
    if evidence_mentions:
        readings.extend(m.predicate for m in evidence_mentions if m.predicate)
    else:
        # The evidence excerpt must agree with any structured reading.
        parsed = _parse_standalone(evidence)
        if parsed is not None:
            readings.append(parsed)
    if not readings or any(reading != readings[0] for reading in readings):
        return None
    predicate = readings[0]
    return predicate_from_filter(predicate.as_filter(), field)


def field_for_concept(concept: str) -> MatchStateField | None:
    lowered = _clean(concept).replace("_", " ")
    for field in MATCH_STATE_FIELDS.values():
        if re.fullmatch(rf"(?:the\s+)?(?:{field.alias_pattern})(?:\s+threshold)?", lowered):
            return field
        if lowered in {field.field_id.replace("_", " "), field.label}:
            return field
    return None


def unregistered_concept(concept: str) -> str | None:
    lowered = _clean(concept).replace("_", " ")
    if field_for_concept(lowered) is not None:
        return None
    for name, pattern in _UNREGISTERED_CONCEPTS:
        if re.fullmatch(rf"(?:the\s+)?(?:{pattern})\w*", lowered) or lowered == name:
            return name
    if lowered in {"chase target", "target score", "run chase target"}:
        return "target"
    return None


def is_numeric_condition(operator: str | None, values: list[object], evidence: str = "") -> bool:
    """Whether an extracted filter compares a quantity (not a category)."""
    if operator in {*OPERATOR_SQL, "between"}:
        return True
    if any(number_value(value) is not None for value in values):
        return True
    text = " ".join(str(value) for value in values if isinstance(value, str))
    return _parse_standalone(text) is not None or _parse_standalone(evidence) is not None


def unregistered_reason(concept: str) -> str:
    return (
        f"Filtering by {concept} is not a registered match-state filter. "
        "Only required run rate thresholds are supported (for example above 8, "
        "at least 8, below 6 or between 6 and 8)."
    )


def availability_note(field: MatchStateField) -> str:
    return (
        f"The {field.label} filter uses the stored {field.column} value, "
        f"{field.timing}. It is {field.null_policy}."
    )


# --- internals -----------------------------------------------------------------


def _clean(text: str) -> str:
    return " ".join(
        text.lower().replace("’", "'").replace("–", "-").replace("—", "-").split()
    )


def _alias_text(text: str, alias: str) -> str:
    match = re.search(alias, text)
    return match.group(0) if match else text


def _is_removal_context(text: str, match: re.Match[str]) -> bool:
    # "all required rates"/"any required rate" etc. must not be followed by a
    # threshold, which would make it an ordinary predicate ("any rrr above 8").
    return _comparison_after(text, match.end()) is None


def _field_mention(
    text: str,
    field: MatchStateField,
    match: re.Match[str],
    taken: list[tuple[int, int]],
) -> MatchStateMention:
    concept = match.group(0)
    after = _comparison_after(text, match.end())
    before = None if after else _comparison_before(text, match.start())
    comparison = after or before
    if comparison is None:
        taken.append(match.span())
        return MatchStateMention(
            concept=concept,
            field=field,
            predicate=None,
            span=match.span(),
            kind="unresolved",
            problem=(
                f"Which {field.label} threshold do you mean? {field.label.capitalize()} "
                "is supported as a threshold filter, for example above 8, at least 8, "
                "below 6 or between 6 and 8."
            ),
        )
    predicate, (start, end) = comparison
    span = (min(match.start(), start), max(match.end(), end))
    taken.append(span)
    if predicate is None:
        return MatchStateMention(
            concept=concept,
            field=field,
            predicate=None,
            span=span,
            kind="unresolved",
            problem=(
                f"Which {field.label} comparison do you mean: above, at least, below, "
                "at most, or an inclusive range such as between 6 and 8?"
            ),
        )
    validated = predicate_from_filter(predicate.as_filter(), field)
    if validated is None:
        return MatchStateMention(
            concept=concept,
            field=field,
            predicate=None,
            span=span,
            kind="unresolved",
            problem=(
                f"The {field.label} threshold must be between {_fmt(field.minimum)} and "
                f"{_fmt(field.maximum)}, with a range's lower bound below its upper bound."
            ),
        )
    trailing = text[span[1]:]
    if re.match(
        rf"^\s*,?\s*(?:and|or|but|vs\.?|versus|compared\s+(?:to|with)|than|while)\b"
        rf".{{0,24}}?\b(?:{_ANY_PREFIX})\s*{_NUM}{_OTHER_UNIT}",
        trailing,
    ):
        return MatchStateMention(
            concept=concept,
            field=field,
            predicate=None,
            span=span,
            kind="unresolved",
            problem=(
                f"Only one {field.label} condition can be applied: a single threshold "
                "or an inclusive range such as between 6 and 8. Comparing required-rate "
                "bands is not supported yet."
            ),
        )
    return MatchStateMention(
        concept=concept,
        field=field,
        predicate=validated,
        span=span,
        kind="predicate",
    )


def _comparison_after(
    text: str, position: int
) -> tuple[NumericPredicate | None, tuple[int, int]] | None:
    link = re.match(_LINK, text[position:])
    start = position + (link.end() if link else 0)
    start += len(text[start:]) - len(text[start:].lstrip())
    return _parse_comparison(text, start, allow_bare=True)


def _comparison_before(
    text: str, position: int
) -> tuple[NumericPredicate | None, tuple[int, int]] | None:
    window_start = max(0, position - 40)
    window = text[window_start:position]
    patterns: tuple[tuple[str, NumericOperator | None], ...] = (
        (rf"{_NUM}\s*\+\s*(?:an?\s+over\s+)?$", "gte"),
        (rf"(?:{_GTE_PREFIX})\s+(?:an?\s+)?{_NUM}{_RATE_UNIT}\s+$", "gte"),
        (rf"(?:{_LTE_PREFIX})\s+(?:an?\s+)?{_NUM}{_RATE_UNIT}\s+$", "lte"),
        (rf"(?:{_GT_PREFIX})\s+(?:an?\s+)?{_NUM}{_RATE_UNIT}\s+$", "gt"),
        (rf"(?:{_LT_PREFIX})\s+(?:an?\s+)?{_NUM}{_RATE_UNIT}\s+$", "lt"),
    )
    for pattern, operator in patterns:
        match = re.search(pattern, window)
        if match:
            number = number_value(match.group(1))
            if number is None:
                return None
            return (
                NumericPredicate(operator, number),  # type: ignore[arg-type]
                (window_start + match.start(), position),
            )
    return None


def _parse_comparison(
    text: str, start: int, *, allow_bare: bool = False
) -> tuple[NumericPredicate | None, tuple[int, int]] | None:
    rest = text[start:]
    tail = _RATE_UNIT + _OTHER_UNIT
    ranges = (
        rf"between\s+{_NUM}{_RATE_UNIT}\s*(?:and|to|-|&)\s*{_NUM}{tail}",
        rf"from\s+{_NUM}{_RATE_UNIT}\s*(?:to|-|until|through)\s*{_NUM}{tail}",
        rf"(?:in\s+the\s+)?{_NUM}\s*(?:-|to)\s*{_NUM}{tail}(?:\s+range)?",
    )
    for pattern in ranges:
        match = re.match(pattern, rest)
        if match:
            lower = number_value(match.group(1))
            upper = number_value(match.group(2))
            if lower is None or upper is None:
                return None
            return (
                NumericPredicate("between", lower=lower, upper=upper),
                (start, start + match.end()),
            )
    postfix = (
        (rf"{_NUM}{_RATE_UNIT}\s*(?:\+|or\s+(?:more|higher|above|greater|over|plus))", "gte"),
        (rf"{_NUM}{_RATE_UNIT}\s*(?:or\s+(?:less|lower|below|under|fewer))", "lte"),
    )
    for pattern, operator in postfix:
        match = re.match(pattern, rest)
        if match:
            number = number_value(match.group(1))
            if number is None:
                return None
            return NumericPredicate(operator, number), (start, start + match.end())  # type: ignore[arg-type]
    prefixed: tuple[tuple[str, NumericOperator], ...] = (
        (_GTE_PREFIX, "gte"),
        (_LTE_PREFIX, "lte"),
        (_GT_PREFIX, "gt"),
        (_LT_PREFIX, "lt"),
    )
    for prefix, operator in prefixed:
        match = re.match(rf"(?:{prefix})\s*(?:an?\s+)?{_NUM}{tail}", rest)
        if match:
            number = number_value(match.group(1))
            if number is None:
                return None
            return NumericPredicate(operator, number), (start, start + match.end())
    equality = re.match(rf"(?:exactly|equal\s+to|=|precisely)\s*{_NUM}{tail}", rest)
    if equality:
        return None, (start, start + equality.end())
    if allow_bare:
        bare = re.match(rf"{_NUM}{tail}", rest)
        if bare:
            # "required rate of 8" names a value without saying how to compare.
            return None, (start, start + bare.end())
    return None


def _parse_standalone(text: str) -> NumericPredicate | None:
    lowered = _clean(text)
    for index in range(len(lowered)):
        if index and lowered[index - 1].isalnum():
            continue
        parsed = _parse_comparison(lowered, index)
        if parsed is not None:
            return parsed[0]
    return None


def _strict_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _fmt(value: int | float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
