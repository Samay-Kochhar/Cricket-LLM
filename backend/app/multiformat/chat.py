"""One reading, one validator and database execution for multi-format questions.

Unscoped and plain ODI requests retain the existing ODI route. Deterministic
and optional model readers produce the same UnderstandingPlan contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from backend.app.multiformat.service import DeliveryFilter, MultiFormatService

# Order matters: specific competitions before generic formats.
_SCOPES: tuple[tuple[re.Pattern[str], str, DeliveryFilter], ...] = (
    (
        re.compile(r"\bIPL\b|indian premier league", re.I),
        "the IPL",
        DeliveryFilter(competition="Indian Premier League"),
    ),
    (
        re.compile(r"\bWPL\b|women'?s premier league", re.I),
        "the WPL",
        DeliveryFilter(competition="Women's Premier League"),
    ),
    (
        re.compile(r"\bWBBL\b|women'?s big bash", re.I),
        "the WBBL",
        DeliveryFilter(competition="Women's Big Bash League"),
    ),
    (
        re.compile(r"\bBBL\b|big bash", re.I),
        "the BBL",
        DeliveryFilter(competition="Big Bash League"),
    ),
    (
        re.compile(r"\bCPL\b|caribbean premier league", re.I),
        "the CPL",
        DeliveryFilter(competition="Caribbean Premier League"),
    ),
    (
        re.compile(r"\bPSL\b|pakistan super league", re.I),
        "the PSL",
        DeliveryFilter(competition="Pakistan Super League"),
    ),
    (re.compile(r"\bSA20\b", re.I), "SA20", DeliveryFilter(competition="SA20")),
    (
        re.compile(r"\bILT20\b|international league t20", re.I),
        "the ILT20",
        DeliveryFilter(competition="International League T20"),
    ),
    (
        re.compile(r"\bMLC\b|major league cricket", re.I),
        "Major League Cricket",
        DeliveryFilter(competition="Major League Cricket"),
    ),
    (
        re.compile(r"\bT20 Blast\b|\bVitality Blast\b", re.I),
        "the T20 Blast",
        DeliveryFilter(competition="%Blast%"),
    ),
    (
        re.compile(r"\bthe hundred\b", re.I),
        "The Hundred",
        DeliveryFilter(format="The Hundred"),
    ),
    (
        re.compile(r"\bT20 ?Is?\b|\bT20 internationals?\b|\bT20 world cup\b", re.I),
        "T20Is",
        DeliveryFilter(format="T20I"),
    ),
    (
        re.compile(r"\bT20s?\b|\btwenty20\b", re.I),
        "T20 cricket",
        DeliveryFilter(formats=("T20I", "T20 domestic")),
    ),
    (
        re.compile(r"\bTests?\b|\btest (?:cricket|matches|match|career)\b"),
        "Tests",
        DeliveryFilter(format="Test"),
    ),
    (
        re.compile(
            r"\bfirst[- ]class\b|\bcounty championship\b|\bsheffield shield\b", re.I
        ),
        "first-class cricket",
        DeliveryFilter(format="First-class domestic"),
    ),
)
_ODI = re.compile(r"\bODIs?\b|\bone[- ]day international", re.I)
_WOMEN = re.compile(r"\bwomen'?s?\b|\bwomen\b", re.I)
_YEAR = re.compile(r"\b(?:in |during )?((?:19|20)\d{2})\b")
_SINCE = re.compile(r"\b(?:since|from|after) ((?:19|20)\d{2})\b", re.I)


@dataclass(frozen=True, slots=True)
class Scope:
    label: str
    flt: DeliveryFilter
    gender_stated: bool = (
        False  # "women's", WPL/WBBL; otherwise men's unless a named player says otherwise
    )


def detect_scope(message: str) -> Scope | None:
    """The non-ODI scope a question names, or None (ODI questions keep their path)."""
    if _ODI.search(message):
        return None
    for pattern, label, flt in _SCOPES:
        if pattern.search(message):
            gender = (
                "female"
                if _WOMEN.search(message) or label in {"the WPL", "the WBBL"}
                else "male"
            )
            flt = replace(flt, gender=gender)
            since = _SINCE.search(message)
            year = _YEAR.search(message)
            if since:
                flt = replace(flt, year_from=int(since.group(1)))
                label = f"{label} since {since.group(1)}"
            elif year:
                flt = replace(
                    flt, year_from=int(year.group(1)), year_to=int(year.group(1))
                )
                label = f"{label} in {year.group(1)}"
            if (
                gender == "female"
                and "women" not in label.lower()
                and label not in {"the WPL", "the WBBL"}
            ):
                label = f"women's {label}"
            return Scope(label=label, flt=flt, gender_stated=gender == "female")
    return None


@dataclass(slots=True)
class MultiFormatAnswer:
    message: str
    suggestions: list[str]
    clarification: list[str] | None = None
    query_response: Any = None
    plan: dict[str, Any] | None = None
    validation_changes: list[str] | None = None
    reading_note: str | None = None


class MultiFormatChat:
    def __init__(self, service: MultiFormatService, planner=None) -> None:
        from backend.app.multiformat.understanding import DeterministicPlanner

        self.service = service
        self.planner = DeterministicPlanner(service)
        self.reader = planner or self.planner

    def answer(self, message: str) -> MultiFormatAnswer | None:
        from backend.app.multiformat.answers import answer_plan
        from backend.app.multiformat.plans import UnderstandingPlan

        raw = self.reader.read(message)
        if raw is None:
            return None
        plan = UnderstandingPlan.model_validate(raw)
        text, response, changes = answer_plan(self, message, plan)
        reading_note = (
            self.reader.diagnostic(message)
            if hasattr(self.reader, "diagnostic")
            else None
        )
        if reading_note:
            from backend.app.domain.evidence_models import EvidenceNote

            response.evidence_notes.insert(
                max(len(response.evidence_notes) - 1, 0),
                EvidenceNote(title="Question reader", detail=reading_note),
            )
            headline, separator, rest = text.partition("\n")
            text = headline + "\n" + reading_note + separator + rest
        return MultiFormatAnswer(
            text,
            [],
            query_response=response,
            plan=plan.model_dump(),
            validation_changes=changes,
            reading_note=reading_note,
        )
