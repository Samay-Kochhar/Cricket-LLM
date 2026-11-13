"""Dismissal ownership and a batting-only event relation.

Synthetic events carry dismissal context, never a partner's delivery dimensions.
They must never be used as bowling deliveries or counted as balls faced.
Missing p_out is deliberately not inferred from the striker's out flag.
"""

NON_DISMISSAL_TYPES = (
    "retired hurt",
    "retired not out",
    "retired not out (hurt)",
    "not out",
)


def batter_dismissal_sql(alias: str = "", *, own: bool = True) -> str:
    p = f"{alias}." if alias else ""
    excluded = ", ".join(repr(value) for value in NON_DISMISSAL_TYPES)
    predicate = (
        f"LOWER(CAST({p}out AS VARCHAR)) = 'true' AND "
        f"NULLIF(TRIM(CAST({p}p_out AS VARCHAR)), '') IS NOT NULL AND "
        f"LOWER(TRIM(COALESCE(CAST({p}dismissal AS VARCHAR), ''))) NOT IN ({excluded})"
    )
    if own:
        predicate += f" AND {p}p_out = {p}p_bat"
    return f"({predicate})"


# A wide can dismiss its striker without adding a ball faced.
OWN_DISMISSAL = batter_dismissal_sql()
# Only context that belongs to the innings/match, rather than the partner's ball.
CONTEXT_COLUMNS = (
    "p_match",
    "inns",
    "team_bat",
    "team_bowl",
    "over",
    "ball_id",
    "date",
    "year",
    "ground",
    "country",
    "winner",
    "toss",
    "competition",
    "rain",
    "daynight",
    "gmt_offset",
    "target",
    "max_balls",
)


def batting_events_sql(columns=None) -> str:
    context = [c for c in CONTEXT_COLUMNS if columns is None or c in columns]
    # COLUMNS selects available context fields in minimal fixtures as well as production.
    context_select = "COLUMNS('^(" + "|".join(context) + ")$')"
    return f"""WITH source AS (SELECT * FROM analytics.deliveries_v1),
      names AS (SELECT p_bat, MIN(bat) AS bat FROM source GROUP BY p_bat)
      SELECT d.*, {batter_dismissal_sql('d')} AS is_batter_dismissal,
             FALSE AS synthetic_dismissal FROM source d
      UNION ALL BY NAME
      SELECT {context_select},
             d.p_out AS p_bat, n.bat AS bat, d.p_out, d.out, d.dismissal,
             '0' AS ballfaced, '0' AS batruns,
             TRUE AS is_batter_dismissal, TRUE AS synthetic_dismissal
      FROM source d LEFT JOIN names n ON n.p_bat = d.p_out
      WHERE {batter_dismissal_sql('d', own=False)}
        AND d.p_out IS DISTINCT FROM d.p_bat"""


def batting_relation_sql() -> str:
    """Self-contained relation for generated SQL, including read-only raw clients."""
    return "(" + batting_events_sql() + ")"


def batting_query_scope(plan):
    """Select batting events only for batting metrics; flag delivery-only slices."""
    from backend.app.cricket_analytics.metric_registry import get_metric

    try:
        bowling_metric = (
            get_metric(plan.metric, entity=plan.entity, filters=plan.filters).owner
            == "bowler"
        )
    except KeyError:
        bowling_metric = plan.metric in {"run_rate", "wicket_opportunity_rate"}
    batting = plan.entity != "bowler" and not bowling_metric
    ball_dimensions = {
        "bowler",
        "bowling_style",
        "bowling_style_group",
        "bowler_hand",
        "bowling_kind",
        "line",
        "length",
        "shot_type",
        "field_zone",
        "batter_hand",
        "matchup",
        "balls_faced_window",
    }
    ball_context = bool(
        ball_dimensions.intersection(plan.group_by or [])
        or ball_dimensions.intersection(plan.filters)
        or plan.split_by in ball_dimensions
        or plan.entity in ball_dimensions
    )
    return batting, ball_context
