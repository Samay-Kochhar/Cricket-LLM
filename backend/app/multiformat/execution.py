"""Execute a validated reading. All result values are calculated by DuckDB."""

from dataclasses import replace

from backend.app.multiformat.service import (
    _rows,
    _role_parts,
    _BALL_BATTING_AGG,
    _batting_rates,
)


def coverage(service, flt):
    where, params = flt.sql()
    dims = (
        "d.format,d.gender,d.competition,d.year"
        if flt.competition or flt.competitions
        else "d.format,d.gender"
    )
    with service._connect() as c:
        return _rows(
            c,
            f"""SELECT {dims},
            count(DISTINCT match_id) AS matches, min(match_date) AS first_match, max(match_date) AS last_match,
            count(*) AS deliveries, count(d.line) AS with_line, count(d.length) AS with_length,
            min(d.match_date) FILTER (d.line IS NOT NULL) AS first_line,
            min(d.match_date) FILTER (d.length IS NOT NULL) AS first_length,
            round(100.0*count(d.line)/count(*),1) AS line_pct,
            round(100.0*count(d.length)/count(*),1) AS length_pct
            FROM analytics.deliveries d WHERE {where} GROUP BY ALL ORDER BY {dims}""",
            params,
        )


def aggregate(
    service,
    flt,
    role,
    player_id=None,
    dimension=None,
    ranking=False,
    min_balls=0,
    metric="runs",
    limit=10,
    descending=None,
):
    where, params = flt.sql()
    # Career and scope totals include own non-striker dismissals. Per-ball
    # line/length and opponent-bowler statistics concern balls actually faced.
    per_ball = bool(
        dimension in {"line", "length"}
        or flt.bowler_styles
        or flt.bowler_arm
        or flt.bowler_kind
        or flt.lengths
        or flt.lines
    )
    source, key, agg, rates = _role_parts(role)
    if role == "batting" and per_ball:
        source, key, agg = "analytics.deliveries d", "batter_id", _BALL_BATTING_AGG
    groups = []
    if ranking:
        groups = [f"d.{key} AS player_id", "p.name"]
    elif dimension:
        if dimension not in {"line", "length", "venue", "format"}:
            raise ValueError("Invalid dimension")
        groups = [f"d.{dimension}"]
    else:
        groups = ["d.format", "d.gender"]
    if player_id:
        where += f" AND d.{key} = ?"
        params.append(player_id)
    if dimension in {"line", "length"}:
        where += f" AND d.{dimension} IS NOT NULL"
    join = f" JOIN analytics.players p ON p.player_id=d.{key}" if ranking else ""
    delivery_count = (
        "count(*) FILTER (d.faced)"
        if role == "batting" and not per_ball
        else "count(*)"
    )
    with service._connect() as c:
        rows = _rows(
            c,
            f"SELECT {', '.join(groups)}, min(d.match_date) AS first_match,max(d.match_date) AS last_match, {delivery_count} AS delivery_rows, {agg} FROM {source}{join} WHERE {where} GROUP BY ALL",
            params,
        )
    rows = [rates(r) for r in rows]
    if dimension in {"line", "length"}:
        total = sum(r["delivery_rows"] for r in rows)
        for r in rows:
            r["delivery_pct"] = (
                round(100 * r["delivery_rows"] / total, 2) if total else None
            )
    if ranking:
        rows = [
            r for r in rows if r["balls"] >= min_balls and r.get(metric) is not None
        ]
        desc = (
            descending
            if descending is not None
            else not (
                metric in {"average", "strike_rate", "economy"} and role == "bowling"
            )
        )
        rows.sort(
            key=lambda r: ((-r[metric] if desc else r[metric]), r.get("name", ""))
        )
        rows = rows[:limit]
    else:
        rows.sort(key=lambda r: -r["balls"])
    return rows


def partnerships(service, flt, player_ids=(), min_runs=None, limit=10):
    where, params = flt.sql()
    filter_params = list(params)
    # Segment on a change in unordered batting pair before applying named-pair
    # filters. This preserves separate stands after retirement or replacement.
    pairfilter = "TRUE"
    if len(player_ids) == 2:
        pairfilter = "a=? AND b=?"
        params += sorted(player_ids)
    elif len(player_ids) == 1:
        pairfilter = "(a=? OR b=?)"
        params += [player_ids[0], player_ids[0]]
    with service._connect() as c:
        missing = _rows(
            c,
            f"SELECT count(*) FILTER (d.non_striker_id IS NULL) AS missing,count(*) AS total FROM analytics.deliveries d WHERE {where}",
            filter_params,
        )[0]
        rows = _rows(
            c,
            f"""WITH pairs AS (
          SELECT d.*,
            CASE WHEN non_striker_id IS NOT NULL THEN least(batter_id,non_striker_id) END AS a,
            CASE WHEN non_striker_id IS NOT NULL THEN greatest(batter_id,non_striker_id) END AS b
          FROM analytics.deliveries d WHERE {where}
        ), changes AS (
          SELECT *,CASE WHEN lag(a||':'||b) OVER w = a||':'||b THEN 0 ELSE 1 END AS changed
          FROM pairs WINDOW w AS (PARTITION BY match_id,innings_no ORDER BY innings_delivery_seq)
        ), numbered AS (
          SELECT *,sum(changed) OVER (PARTITION BY match_id,innings_no ORDER BY innings_delivery_seq) AS stand
          FROM changes
        ), stands AS (
          SELECT a,b,match_id,innings_no,stand,sum(runs_total) AS runs,count(*) FILTER (is_legal) AS balls
          FROM numbered WHERE a IS NOT NULL AND b IS NOT NULL AND {pairfilter} GROUP BY ALL
        ) SELECT pa.name AS batter_1,pb.name AS batter_2,count(*) AS stands,
          sum(runs) AS partnership_runs,max(runs) AS best_stand,
          count(*) FILTER (runs>=50) AS fifty_plus_stands,count(*) FILTER (runs>=100) AS hundred_plus_stands,
          count(*) FILTER (runs>=?) AS qualifying_stands
          FROM stands JOIN analytics.players pa ON pa.player_id=a JOIN analytics.players pb ON pb.player_id=b
          GROUP BY ALL ORDER BY partnership_runs DESC,batter_1,batter_2 LIMIT ?""",
            [*params, min_runs or 0, limit],
        )
    return rows, missing


def venue_summary(service, flt):
    from backend.app.domain.venues import venue_id_sql, venue_display_sql

    where, params = flt.sql()
    identity = venue_id_sql("d.venue")
    with service._connect() as c:
        return _rows(
            c,
            f"""WITH innings AS (
          SELECT {identity} AS venue_id,any_value(d.venue) AS venue,d.match_id,d.innings_no,sum(d.runs_total) AS runs,
            count(*) FILTER (d.is_legal) AS balls
          FROM analytics.deliveries d WHERE {where} AND NOT coalesce(d.is_super_over,FALSE) GROUP BY ALL
        ) SELECT {venue_display_sql('venue_id','venue')} AS venue,count(DISTINCT match_id) AS matches,
          round(avg(runs) FILTER (innings_no=1),2) AS avg_first_innings_runs,
          round(avg(runs) FILTER (innings_no=2),2) AS avg_second_innings_runs,
          round(6.0*sum(runs)/nullif(sum(balls),0),2) AS run_rate
          FROM innings GROUP BY venue_id ORDER BY avg_first_innings_runs DESC NULLS LAST,venue""",
            params,
        )
