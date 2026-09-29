"""Batter dismissal counts by the registered dismissal-type dimension."""

from __future__ import annotations

from typing import Any

from backend.app.cricket_analytics.dismissal_types import (
    BATTER_DISMISSAL_PREDICATE,
    DISMISSAL_TYPE_EXPRESSION,
    DISMISSAL_TYPE_REGISTRY,
)
from backend.app.cricket_analytics.query_builders.aggregate_builder import (
    _clean_sql,
    _filter_clauses,
)
from backend.app.cricket_analytics.schemas import CricketQueryPlan, QueryBuildResult


DISMISSAL_TYPE_METRICS = frozenset({"dismissals", "dismissal_type_percentage"})
# Delivery context that also applies to a non-striker dismissal. Striker-only
# context (line, length, shot, field zone, batter hand) is not registered here.
DISMISSAL_TYPE_FILTERS = frozenset(
    {
        "batter",
        "bowler",
        "dismissal_type",
        "years",
        "year_mode",
        "venue",
        "venues",
        "opposition",
        "innings",
        "phase",
        "over_range",
        "competition",
        "bowling_style",
    }
)
OUTPUT_COLUMNS = [
    "batter",
    "dismissal_type",
    "dismissals",
    "total_dismissals",
    "dismissal_type_percentage",
    "matches",
]


def build_dismissal_type_query(plan: CricketQueryPlan) -> QueryBuildResult:
    """Count one batter's dismissals per stored category.

    Attribution is the dismissed batter (``p_out``), resolved from the batter's
    name through the source's own batter identifiers, so a non-striker run out
    counts for the dismissed batter and not for the striker. Requested
    categories are enumerated so a category with no dismissals returns 0. The
    share denominator is every registered dismissal in the same scope.
    """
    batter = plan.filters.get("batter")
    if not isinstance(batter, str) or plan.metric not in DISMISSAL_TYPE_METRICS:
        raise ValueError("Dismissal types require one named batter and a dismissal metric.")
    requested = plan.filters.get("dismissal_type")
    categories = (
        [str(value) for value in requested]
        if isinstance(requested, list) and requested
        else list(DISMISSAL_TYPE_REGISTRY)
    )
    unknown = [value for value in categories if value not in DISMISSAL_TYPE_REGISTRY]
    if unknown:
        raise ValueError(f"Unregistered dismissal type: {', '.join(unknown)}.")

    params: list[Any] = [batter]
    where = [BATTER_DISMISSAL_PREDICATE, "p_out IN (SELECT p_bat FROM dismissed_batter)"]
    context_filters = {
        key: value
        for key, value in plan.filters.items()
        if key not in {"batter", "dismissal_type"}
    }
    for clause, clause_params in _filter_clauses(context_filters, entity="batter"):
        where.append(clause)
        params.extend(clause_params)

    category_rows = ", ".join(f"(?, {index})" for index, _ in enumerate(categories))
    for index, category in enumerate(categories):
        params.append(category)
    explicit = isinstance(requested, list) and bool(requested)
    keep_clause = "" if explicit else "WHERE COALESCE(d.dismissals, 0) > 0"
    direction = "ASC" if plan.sort and plan.sort.direction == "asc" else "DESC"
    order_sql = (
        "ORDER BY c.position ASC"
        if explicit
        else f"ORDER BY dismissals {direction}, c.position ASC"
    )
    limit_sql = ""
    if plan.limit is not None and not explicit:
        limit_sql = "LIMIT ?"
    sql = f"""
        WITH dismissed_batter AS (
          SELECT DISTINCT p_bat FROM analytics.deliveries_v1 WHERE bat = ?
        ),
        dismissal_rows AS (
          SELECT {DISMISSAL_TYPE_EXPRESSION} AS dismissal_type, p_match
          FROM analytics.deliveries_v1
          WHERE {' AND '.join(where)}
        ),
        by_type AS (
          SELECT dismissal_type, COUNT(*) AS dismissals, COUNT(DISTINCT p_match) AS matches
          FROM dismissal_rows
          GROUP BY dismissal_type
        ),
        scope_total AS (
          SELECT COUNT(*) AS total_dismissals FROM dismissal_rows
        ),
        categories(dismissal_type, position) AS (
          VALUES {category_rows}
        )
        SELECT
          ? AS batter,
          c.dismissal_type,
          COALESCE(d.dismissals, 0) AS dismissals,
          t.total_dismissals,
          COALESCE(d.dismissals, 0) * 100.0 / NULLIF(t.total_dismissals, 0) AS dismissal_type_percentage,
          COALESCE(d.matches, 0) AS matches
        FROM categories c
        CROSS JOIN scope_total t
        LEFT JOIN by_type d ON d.dismissal_type = c.dismissal_type
        {keep_clause}
        {order_sql}
        {limit_sql}
        """
    params.append(batter)
    if limit_sql:
        params.append(plan.limit)
    return QueryBuildResult(
        sql=_clean_sql(sql),
        params=params,
        columns=list(OUTPUT_COLUMNS),
        metric_column=plan.metric,
        sample_columns=["total_dismissals"],
        description=(
            "Batter dismissals by recorded dismissal type over analytics.deliveries_v1, "
            "attributed to the dismissed batter (p_out)"
        ),
    )
