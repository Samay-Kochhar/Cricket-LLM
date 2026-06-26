from __future__ import annotations

from typing import Any


LEGAL_BALL_PREDICATE = "COALESCE(TRY_CAST(wide AS INTEGER), 0) = 0 AND COALESCE(TRY_CAST(noball AS INTEGER), 0) = 0"

BOWLER_WICKET_TYPES = (
    "caught",
    "bowled",
    "leg before wicket",
    "stumped",
    "hit wicket",
    "caught and bowled",
)

BOWLER_WICKET_PREDICATE = (
    "LOWER(CAST(dismissal AS VARCHAR)) IN "
    "('caught', 'bowled', 'leg before wicket', 'stumped', 'hit wicket', 'caught and bowled')"
)


def phase_case_expression(over_expression: str = "TRY_CAST(over AS DOUBLE)") -> str:
    return (
        f"CASE WHEN {over_expression} <= 10 THEN 'powerplay' "
        f"WHEN {over_expression} <= 40 THEN 'middle' ELSE 'death' END"
    )


def phase_filter_clause(phase: str | None, *, prefix: str = "") -> tuple[str, list[Any]]:
    if phase == "first6":
        return f"{prefix}TRY_CAST(over AS DOUBLE) <= ?", [6.0]
    if phase == "powerplay":
        return f"{prefix}TRY_CAST(over AS DOUBLE) <= ?", [10.0]
    if phase == "middle":
        return f"{prefix}TRY_CAST(over AS DOUBLE) > ? AND TRY_CAST(over AS DOUBLE) <= ?", [10.0, 40.0]
    if phase == "death":
        return f"{prefix}TRY_CAST(over AS DOUBLE) > ?", [40.0]
    return "", []


def classify_phase(over: float | int | None) -> str | None:
    if over is None:
        return None
    value = float(over)
    if value <= 10:
        return "powerplay"
    if value <= 40:
        return "middle"
    return "death"


def is_bowler_credit_wicket(dismissal: object) -> bool:
    return isinstance(dismissal, str) and dismissal.lower() in BOWLER_WICKET_TYPES


def public_label(value: object) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, 2)
    if not isinstance(value, str):
        return value  # type: ignore[return-value]
    stripped = value.strip()
    if "_" not in stripped and "-" not in stripped and not stripped.isupper():
        return stripped
    cleaned = stripped.replace("_", " ").replace("-", " ").strip().lower()
    known = {
        "lhb": "left-hand batter",
        "rhb": "right-hand batter",
        "short of a good length": "short of a good length",
        "good length": "good length",
        "full toss": "full toss",
    }
    return known.get(cleaned, cleaned)
