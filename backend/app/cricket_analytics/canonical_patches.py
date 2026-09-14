"""Typed contextual updates over the last successful canonical cricket meaning."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from backend.app.cricket_analytics.canonical_meaning import CanonicalCricketMeaning
from backend.app.cricket_analytics.metric_registry import get_metric
from backend.app.cricket_analytics.plan_normalizer import requested_limit_from_wording
from backend.app.cricket_analytics.schemas import MinimumSampleSpec

if TYPE_CHECKING:
    from backend.app.cricket_analytics.canonical_meaning import CanonicalMeaningResolver


PatchAction = Literal["add", "replace", "remove"]
PatchTarget = Literal[
    "filter.phase",
    "filter.venue",
    "filter.venues",
    "filter.years",
    "filter.year_mode",
    "filter.opposition",
    "filter.bowling_style",
    "filter.batter_hand",
    "filter.comparison_view",
    "metric",
    "limit",
    "minimum_sample",
]

PATCHABLE_FILTERS = {
    "phase",
    "venue",
    "venues",
    "years",
    "year_mode",
    "opposition",
    "bowling_style",
    "batter_hand",
    "comparison_view",
}


class VersionedCanonicalMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    meaning: CanonicalCricketMeaning


class MeaningPatchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: PatchAction
    target: PatchTarget
    value: object | None = None


class CanonicalMeaningPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    operations: list[MeaningPatchOperation] = Field(min_length=1)


class MeaningPatchResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "clarification", "not_applicable"]
    patch: CanonicalMeaningPatch | None = None
    meaning: CanonicalCricketMeaning | None = None
    clarification: str | None = None
    clarification_options: list[str] = Field(default_factory=list)


def canonical_meaning_from_state(
    state: Mapping[str, object] | BaseModel | None,
) -> CanonicalCricketMeaning | None:
    if state is None:
        return None
    raw_state = (
        state.model_dump(mode="python") if isinstance(state, BaseModel) else state
    )
    raw = raw_state.get("canonical_meaning")
    if raw is None:
        return None
    try:
        return VersionedCanonicalMeaning.model_validate(raw).meaning
    except (TypeError, ValueError):
        return None


def interpret_meaning_patch(
    resolver: CanonicalMeaningResolver,
    question: str,
    previous: CanonicalCricketMeaning,
) -> MeaningPatchResolution:
    """Resolve only facts expressed by a contextual turn."""
    from backend.app.cricket_analytics.canonical_meaning import (
        _explicit_sample,
        _extract_players,
        _metric_and_role,
        _normalized_text,
    )

    text = _normalized_text(question)
    metric_text = re.sub(r"\bsr\b", "strike rate", text)
    named_players = _extract_players(question, resolver.available_players)
    if named_players:
        return MeaningPatchResolution(status="not_applicable")

    explicit_filters = resolver._explicit_filters(question, text)
    if all(phase in text for phase in ("powerplay", "middle", "death")):
        explicit_filters.pop("phase", None)
        if previous.family == "comparison":
            explicit_filters["comparison_view"] = "phase"
    unsupported_filters = set(explicit_filters) - PATCHABLE_FILTERS
    if unsupported_filters:
        label = sorted(unsupported_filters)[0].replace("_", " ")
        return MeaningPatchResolution(
            status="clarification",
            clarification=f"Changing {label} needs a complete standalone question.",
        )
    contextual_strike_rate = bool(
        re.search(r"\b(?:strike rate|sr)\b", metric_text)
        and "batting strike rate" not in metric_text
        and "bowling strike rate" not in metric_text
    )
    if contextual_strike_rate:
        explicit_metric = (
            "batting_strike_rate"
            if previous.role == "batter"
            else "bowling_strike_rate"
        )
        metric_role = previous.role
    else:
        explicit_metric, metric_role = _metric_and_role(
            metric_text, None, previous.role
        )
    sample = _explicit_sample(text, explicit_metric or previous.metric)
    limit = requested_limit_from_wording(text)
    removals = _requested_removals(text)

    changes_present = bool(
        explicit_filters or explicit_metric or sample or limit or removals
    )
    if not changes_present or not _looks_contextual(text):
        return MeaningPatchResolution(status="not_applicable")

    if explicit_metric and metric_role not in {previous.role, None}:
        return MeaningPatchResolution(
            status="clarification",
            clarification=(
                f"The previous analysis treats the subject as a {previous.role}. "
                f"Should the role also change for {explicit_metric.replace('_', ' ')}?"
            ),
        )

    operations: list[MeaningPatchOperation] = []
    for key in removals:
        if key == "minimum_sample":
            operations.append(
                MeaningPatchOperation(action="remove", target="minimum_sample")
            )
        elif key == "limit":
            operations.append(MeaningPatchOperation(action="remove", target="limit"))
        elif key == "venue" and "venues" in previous.filters:
            operations.append(
                MeaningPatchOperation(action="remove", target="filter.venues")
            )
        elif key in previous.filters:
            operations.append(
                MeaningPatchOperation(
                    action="remove", target=cast(PatchTarget, f"filter.{key}")
                )
            )
            if key == "years" and "year_mode" in previous.filters:
                operations.append(
                    MeaningPatchOperation(action="remove", target="filter.year_mode")
                )

    for key, value in explicit_filters.items():
        target = cast(PatchTarget, f"filter.{key}")
        action: PatchAction = "replace" if key in previous.filters else "add"
        operations.append(
            MeaningPatchOperation(action=action, target=target, value=value)
        )
    if "years" in explicit_filters and "year_mode" not in explicit_filters:
        if "year_mode" in previous.filters:
            operations.append(
                MeaningPatchOperation(action="remove", target="filter.year_mode")
            )
    if "venue" in explicit_filters and "venues" in previous.filters:
        operations.append(
            MeaningPatchOperation(action="remove", target="filter.venues")
        )
    if "venues" in explicit_filters and "venue" in previous.filters:
        operations.append(MeaningPatchOperation(action="remove", target="filter.venue"))
    if "phase" in explicit_filters and "comparison_view" in previous.filters:
        operations.append(
            MeaningPatchOperation(action="remove", target="filter.comparison_view")
        )
    if "comparison_view" in explicit_filters and "phase" in previous.filters:
        operations.append(MeaningPatchOperation(action="remove", target="filter.phase"))

    if explicit_metric and explicit_metric != previous.metric:
        operations.append(
            MeaningPatchOperation(
                action="replace", target="metric", value=explicit_metric
            )
        )
    if sample:
        operations.append(
            MeaningPatchOperation(
                action="replace" if previous.minimum_sample else "add",
                target="minimum_sample",
                value=sample.model_dump(mode="json", exclude_none=True),
            )
        )
    if limit:
        operations.append(
            MeaningPatchOperation(
                action="replace" if previous.limit is not None else "add",
                target="limit",
                value=limit,
            )
        )

    operations = _deduplicate_operations(operations)
    if not operations:
        return MeaningPatchResolution(status="not_applicable")
    patch = CanonicalMeaningPatch(operations=operations)
    return apply_meaning_patch(previous, patch)


def apply_meaning_patch(
    previous: CanonicalCricketMeaning,
    patch: CanonicalMeaningPatch,
) -> MeaningPatchResolution:
    meaning = previous.model_copy(deep=True)
    filters = dict(meaning.filters)
    for operation in patch.operations:
        target = operation.target
        if target.startswith("filter."):
            key = target.removeprefix("filter.")
            split_filter = {
                "phase": "phase",
                "batter_hand": "batter_hand",
                "bowling_style": "bowling_style_group",
            }.get(key)
            if meaning.family == "split" and meaning.split_by == split_filter:
                return MeaningPatchResolution(
                    status="clarification",
                    patch=patch,
                    clarification=(
                        f"{key.replace('_', ' ').title()} is the comparison axis. "
                        "Which split value should be changed?"
                    ),
                )
            if operation.action == "remove":
                filters.pop(key, None)
            else:
                filters[key] = operation.value
            continue
        if target == "metric":
            metric = str(operation.value)
            rule = get_metric(metric, entity=meaning.role, filters=filters)
            if rule.owner not in {meaning.role, "batter_or_bowler"}:
                return MeaningPatchResolution(
                    status="clarification",
                    patch=patch,
                    clarification=f"Choose a statistic for the existing {meaning.role} role.",
                )
            meaning.metric = metric
            meaning.sort_direction = cast(Literal["asc", "desc"], rule.default_sort)
            if meaning.family == "comparison":
                meaning.comparison_metrics = [metric]
                filters["comparison_metrics"] = [metric]
        elif target == "limit":
            meaning.limit = (
                None
                if operation.action == "remove"
                else int(cast(int, operation.value))
            )
        elif target == "minimum_sample":
            meaning.minimum_sample = (
                None
                if operation.action == "remove"
                else MinimumSampleSpec.model_validate(operation.value)
            )
            meaning.minimum_sample_explicit = operation.action != "remove"
    meaning.filters = filters
    return MeaningPatchResolution(status="resolved", patch=patch, meaning=meaning)


def _looks_contextual(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:and|also|now|only|just|instead|switch|change|replace|restrict|limit|"
            r"what about|how about|that|this|it|them|those|same|without|remove|drop|"
            r"regardless|any|all|overall|career)\b",
            text,
        )
        or len(text.split()) <= 6
    )


def _requested_removals(text: str) -> list[str]:
    removals: list[str] = []
    patterns = {
        "phase": r"\b(?:all|any) (?:innings )?phases?\b|\b(?:overall|remove|drop|without) (?:the )?phase\b",
        "venue": r"\b(?:any|all) venues?\b|\b(?:regardless of|remove|drop|without) (?:the )?venue\b",
        "years": r"\b(?:all years|career(?: totals?)?)\b|\b(?:remove|drop|without) (?:the )?year(?: filter)?\b",
        "opposition": r"\b(?:any|all) (?:opposition|opponents?|teams?)\b|\b(?:remove|drop|without) (?:the )?opposition\b",
        "bowling_style": r"\b(?:all|any) bowling styles?\b|\b(?:regardless of|remove|drop|without) (?:the )?(?:bowling )?style\b",
        "batter_hand": r"\b(?:both|any) hands?\b|\b(?:regardless of|remove|drop|without) (?:the )?handedness\b",
        "minimum_sample": r"\b(?:no|remove|drop|without) (?:the )?(?:minimum|sample threshold|sample floor)\b",
        "limit": r"\b(?:no|remove|drop|without) (?:the )?limit\b|\ball results\b",
    }
    for key, pattern in patterns.items():
        if re.search(pattern, text):
            removals.append(key)
    return removals


def _deduplicate_operations(
    operations: list[MeaningPatchOperation],
) -> list[MeaningPatchOperation]:
    latest: dict[str, MeaningPatchOperation] = {}
    for operation in operations:
        latest[operation.target] = operation
    return list(latest.values())
