"""Context-filtered explorer aggregates, shared by comparison and venue rankings."""
from backend.app.cricket_analytics.cricket_definitions import (
    BOWLER_WICKET_PREDICATE, LEGAL_BALL_PREDICATE, phase_filter_clause,
)
from backend.app.domain.venues import venue_filter
from backend.app.domain.venue_leaderboard import mode_options


def query_stats(repository, mode, *, phase=None, year_start=None, year_end=None,
                venue=None, player=None, ranking=None):
    """Filter delivery rows first; aggregate once, then apply sample eligibility/top N."""
    mode_options(mode)(phase=phase, year_start=year_start, year_end=year_end)
    clauses, params = ["1=1"], []
    phase_sql, phase_params = phase_filter_clause(phase, prefix=" AND ")
    clauses[0] += phase_sql
    params.extend(phase_params)
    if year_start is not None:
        clauses.append("TRY_CAST(year AS INTEGER) BETWEEN ? AND ?")
        params.extend([year_start, year_end])
    if venue:
        sql, values = venue_filter([venue])
        clauses.append(sql)
        params.extend(values)
    name = "bat" if mode == "batting" else "bowl"
    if player:
        clauses.append(f"{name} = ?")
        params.append(player)
    if mode == "batting":
        faced = "TRY_CAST(ballfaced AS INTEGER) = 1"
        counts = f"""
            SUM(CASE WHEN {faced} THEN 1 ELSE 0 END) AS balls_faced,
            COALESCE(SUM(TRY_CAST(batruns AS INTEGER)), 0) AS runs_scored,
            SUM(CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN 1 ELSE 0 END) AS dismissals,
            SUM(CASE WHEN {faced} AND TRY_CAST(batruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
            SUM(CASE WHEN {faced} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls,
            COUNT(CASE WHEN {faced} THEN TRY_CAST(control AS DOUBLE) END) AS control_balls,
            AVG(CASE WHEN {faced} THEN TRY_CAST(control AS DOUBLE) END) * 100 AS control_percentage
        """
        rates = """runs_scored / NULLIF(dismissals, 0) AS average,
            runs_scored * 100.0 / NULLIF(balls_faced, 0) AS strike_rate,
            dot_balls * 100.0 / NULLIF(balls_faced, 0) AS dot_percentage,
            boundary_balls * 100.0 / NULLIF(balls_faced, 0) AS boundary_percentage"""
    else:
        counts = f"""
            SUM(CASE WHEN {LEGAL_BALL_PREDICATE} THEN 1 ELSE 0 END) AS deliveries,
            COALESCE(SUM(TRY_CAST(bowlruns AS INTEGER)), 0) AS runs_conceded,
            SUM(CASE WHEN {BOWLER_WICKET_PREDICATE} THEN 1 ELSE 0 END) AS wickets,
            SUM(CASE WHEN {LEGAL_BALL_PREDICATE} AND TRY_CAST(bowlruns AS INTEGER) = 0 THEN 1 ELSE 0 END) AS dot_balls,
            SUM(CASE WHEN {LEGAL_BALL_PREDICATE} AND TRY_CAST(batruns AS INTEGER) IN (4, 6) THEN 1 ELSE 0 END) AS boundary_balls
        """
        rates = """runs_conceded / NULLIF(wickets, 0) AS bowling_average,
            deliveries / NULLIF(wickets, 0) AS bowling_strike_rate,
            runs_conceded * 6.0 / NULLIF(deliveries, 0) AS economy_rate,
            dot_balls * 100.0 / NULLIF(deliveries, 0) AS dot_percentage,
            boundary_balls * 100.0 / NULLIF(deliveries, 0) AS boundary_percentage"""
    tail = "ORDER BY player_name"
    if ranking:
        field, direction = ranking.ranking["field"], ranking.ranking["direction"]
        unit = "deliveries" if ranking.sample_unit == "legal_balls" else ranking.sample_unit
        tail = f"WHERE {unit} >= ? AND {field} IS NOT NULL ORDER BY {field} {direction}, player_name ASC LIMIT ?"
        params.extend([ranking.minimum_sample, ranking.limit])
    sql = f"""WITH counts AS (
        SELECT {name} AS player_name, COUNT(DISTINCT p_match) AS matches,
            COUNT(*) AS delivery_rows, {counts}
        FROM analytics.deliveries_v1 WHERE {' AND '.join(clauses)} GROUP BY {name}
    ), rates AS (SELECT *, {rates} FROM counts) SELECT * FROM rates {tail}"""
    # Retain column names at the database boundary; no positional parallel schema.
    from backend.app.db.connection import get_connection
    with get_connection(repository.db_path) as conn:
        result = conn.execute(sql, params)
        fields = [col[0] for col in result.description]
        return [dict(zip(fields, row)) for row in result.fetchall()]
