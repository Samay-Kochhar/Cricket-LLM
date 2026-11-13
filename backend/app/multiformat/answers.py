"""Validated plan execution and presentation through the existing evidence UI."""

from __future__ import annotations

import re
from dataclasses import replace

from backend.app.domain.evidence_models import (
    EvidenceNote,
    EvidenceStatus,
    QueryInterpretation,
    QueryResponse,
    TableBlock,
)
from backend.app.multiformat import execution
from backend.app.multiformat.plans import ScopePlan
from backend.app.multiformat.understanding import delivery_filter

AFGHAN_NOTE = "Afghanistan player data is limited: men’s internationals are incomplete, with T20I coverage starting in 2019. Recorded totals may understate careers."


def safe_text(text):
    # Source provenance is intentionally omitted from answers.
    text = re.sub(r"(?i)cricsheet|aucb|espn", "the recorded data", str(text))
    return text


def table(title, rows):
    if not rows:
        return None
    cols = list(rows[0])

    def value(v):
        if v is None or isinstance(v, (str, int, float)):
            return v
        return str(v)

    return TableBlock(
        title=title, columns=cols, rows=[[value(r.get(k)) for k in cols] for r in rows]
    )


def answer_plan(chat, question, plan):
    service = chat.service
    errors = list(plan.unsupported)
    if not plan.scopes and plan.intent != "coverage":
        errors.append("missing competition or format scope")
    if plan.intent == "ranking" and not plan.metrics:
        errors.append("missing ranking metric")
    players = []
    changes = []
    for name in plan.players:
        candidates = chat.planner.names.choose(name, plan.scopes)
        if len(candidates) != 1:
            errors.append(
                "ambiguous player "
                + name
                + " ("
                + ", ".join(c["name"] for c in candidates[:6])
                + ")"
                if candidates
                else "unresolved player " + name
            )
        else:
            players.append(candidates[0])
            if candidates[0]["name"].lower() != name.lower():
                changes.append(f"{name} → {candidates[0]['name']}")
    if plan.intent in {"stats", "comparison", "matchup"} and not players:
        errors.append("player identification")
    if plan.intent == "matchup" and len(players) != 2:
        errors.append("two distinct players for the matchup")
    if plan.intent == "comparison" and len(players) < 2 and len(plan.scopes) < 2:
        errors.append("comparison targets")
    if len({p["player_id"] for p in players}) != len(players):
        errors.append("distinct player targets")
    if plan.intent == "partnership" and len(players) > 2:
        errors.append("partnerships involving more than two named players")
    supported = (
        {"balls", "runs", "average", "strike_rate", "dot_ball_pct", "fours", "sixes"}
        if plan.role == "batting"
        else {"balls", "wickets", "average", "strike_rate", "economy", "dot_ball_pct"}
    )
    if plan.intent not in {"coverage", "partnership", "venue", "matchup"}:
        errors += [
            f"{plan.role} metric {m}" for m in plan.metrics if m not in supported
        ]
    with service._connect() as c:
        columns = {r[0] for r in c.execute("DESCRIBE analytics.deliveries").fetchall()}
        valid_formats = {
            r[0]
            for r in c.execute(
                "SELECT DISTINCT format FROM analytics.deliveries"
            ).fetchall()
        }
        for scope in plan.scopes:
            requested = (
                [scope.competition] if scope.competition else []
            ) + scope.competitions
            for competition in requested:
                if not c.execute(
                    "SELECT count(*) FROM analytics.coverage WHERE competition ILIKE ?",
                    [competition],
                ).fetchone()[0]:
                    errors.append("unresolved competition " + competition)
    for scope in plan.scopes:
        if scope.format and scope.format not in valid_formats:
            errors.append("format " + scope.format)
        errors += ["format " + f for f in scope.formats if f not in valid_formats]
        if plan.phase and scope.format in {"Test", "First-class domestic"}:
            errors.append("phase in first-class cricket")
    if plan.bowler_styles:
        allowed = {
            "LF",
            "LFM",
            "LM",
            "LMF",
            "RF",
            "RFM",
            "RM",
            "RMF",
            "LB",
            "LBG",
            "OB",
            "SLA",
            "LWS",
        }
        errors += ["bowler style " + s for s in plan.bowler_styles if s not in allowed]
    if plan.bowler_kind and plan.bowler_kind not in {"pace bowler", "spin bowler"}:
        errors.append("bowler kind " + plan.bowler_kind)
    if plan.bowler_arm and plan.bowler_arm.lower() not in {"left", "right"}:
        errors.append("bowler arm " + plan.bowler_arm)
    if plan.over_from and plan.over_to and plan.over_from > plan.over_to:
        errors.append("reversed over range")
    if plan.phase and "over_no" not in columns:
        errors.append("phase data")
    if (plan.over_from or plan.over_to) and "over_no" not in columns:
        errors.append("over data")
    if plan.bowler_styles and "bowler_style_code" not in columns:
        errors.append("bowler style data")
    if plan.venue and "venue" not in columns:
        errors.append("venue data")
    if plan.intent == "partnership" and "non_striker_id" not in columns:
        errors.append("partnership data")
    # Supported: one named player's own line or length categories ranked by
    # one metric. Leaderboards across line/length groups are not.
    own_categories = len(players) == 1 and len(plan.dimensions) == 1
    filtered_dimensions = all(
        (d == "length" and plan.lengths) or (d == "line" and plan.lines)
        for d in plan.dimensions
    )
    if plan.intent == "ranking" and (
        len(plan.metrics) > 1
        or (plan.dimensions and not own_categories and not filtered_dimensions)
    ):
        errors.append("ranking across multiple metrics or line/length groups")
    if plan.intent in {"partnership", "venue", "matchup"} and (
        plan.dimensions or plan.bowler_styles
    ):
        errors.append("line/length or bowling-type breakdown for " + plan.intent)
    scopes = plan.scopes or [ScopePlan(label="all formats")]
    filters = [delivery_filter(plan, s) for s in scopes]
    label = ", ".join(
        (
            ("women’s " + s.label)
            if s.gender == "female"
            and "women" not in s.label.lower()
            and s.label not in {"WPL", "WBBL", "the WPL", "the WBBL"}
            else s.label
        )
        for s in scopes
    )
    details = [", ".join(p["name"] for p in players), plan.role, label]
    if plan.years:
        details.append(", ".join(map(str, plan.years)))
    if plan.year_from or plan.year_to:
        details.append(f'{plan.year_from or "start"}–{plan.year_to or "latest"}')
    if plan.phase:
        details.append(plan.phase)
    if plan.over_from:
        details.append(f"overs {plan.over_from}–{plan.over_to}")
    if plan.bowler_styles:
        details.append("vs " + "/".join(plan.bowler_styles))
    if plan.bowler_arm or plan.bowler_kind:
        details.append(
            "vs " + " ".join(x for x in [plan.bowler_arm, plan.bowler_kind] if x)
        )
    if plan.venue:
        details.append(plan.venue)
    if plan.opponent:
        details.append("against " + plan.opponent)
    if plan.lengths or plan.lines:
        details.append(", ".join(plan.lengths + plan.lines))
    headline = "Showing: " + " · ".join(x for x in details if x)
    tables = []
    notes = [
        EvidenceNote(
            title="Definitions",
            detail="Batting average = runs / dismissals, excluding retired hurt/not out. Career totals include own non-striker dismissals; per-ball matchup, bowling-type and line/length views count only dismissals on the striker’s deliveries, including wides. Batting balls exclude wides. Bowling wickets exclude run-outs; economy is runs conceded per six legal balls, including in The Hundred. Matches count recorded batting/bowling appearances, including a non-striker dismissal without a ball faced. Bowling dot-ball percentage counts legal deliveries with zero team runs; byes and leg-byes are not dots. Player totals include super-over deliveries. Descriptive rates show the observed sample; minimum-ball thresholds apply to rankings. Rates use the recorded sample only.",
        )
    ]
    if not errors and (plan.bowler_styles or plan.bowler_arm or plan.bowler_kind):
        from backend.app.multiformat.service import _rows

        for scope, flt in zip(scopes, filters):
            base = replace(flt, bowler_styles=(), bowler_arm=None, bowler_kind=None)
            where, params = base.sql()
            if players:
                where += (
                    " AND d.batter_id = ?"
                    if plan.role == "batting"
                    else " AND d.bowler_id = ?"
                )
                params.append(players[0]["player_id"])
            field = (
                "bowler_style_code"
                if plan.bowler_styles
                else ("bowler_arm" if plan.bowler_arm else "bowler_kind")
            )
            with service._connect() as conn:
                cov = _rows(
                    conn,
                    f"SELECT count(*) AS total,count(d.{field}) AS known FROM analytics.deliveries d WHERE {where}",
                    params,
                )[0]
            pct = 100 * cov["known"] / cov["total"] if cov["total"] else 0
            notes.append(
                EvidenceNote(
                    title="Bowling-type coverage — " + scope.label,
                    detail=f"The requested bowling classification is recorded for {cov['known']:,} of {cov['total']:,} deliveries in this context ({pct:.1f}%). Unclassified deliveries cannot be assigned to the requested type.",
                )
            )
    if changes:
        notes.append(EvidenceNote(title="Resolved names", detail="; ".join(changes)))
    if errors:
        summary = (
            "I can't answer the " + "; ".join(dict.fromkeys(errors)) + " part yet."
        )
    else:
        summary = ""
        for scope, flt in zip(scopes, filters):
            if plan.intent == "coverage":
                rows = execution.coverage(service, flt)
                t = table("Coverage by competition and year", rows)
                if t:
                    tables.append(t)
                for dim in plan.dimensions:
                    total = sum(r["deliveries"] for r in rows)
                    covered = sum(r["with_" + dim] for r in rows)
                    starts = [r["first_" + dim] for r in rows if r["first_" + dim]]
                    sentence = f"{dim.title()} is recorded for {covered:,} of {total:,} deliveries"
                    if total:
                        sentence += f" ({100 * covered / total:.1f}%)"
                    sentence += (
                        f", starting {min(starts)}."
                        if starts
                        else "; none is recorded in this scope."
                    )
                    summary += (" " if summary else "") + sentence
            elif plan.intent == "partnership":
                rows, missing = execution.partnerships(
                    service,
                    flt,
                    [p["player_id"] for p in players],
                    plan.partnership_min_runs,
                    plan.limit,
                )
                t = table("Partnerships — " + scope.label, rows)
                if t:
                    tables.append(t)
                if missing["missing"]:
                    notes.append(
                        EvidenceNote(
                            title="Partnership coverage",
                            detail=f"{missing['missing']} of {missing['total']} deliveries lack the non-striker identity and cannot be included.",
                        )
                    )
            elif plan.intent == "matchup":
                # In "Bowler dismissed Batter", reading order is bowler first.
                batter, bowler = (
                    (players[1], players[0]) if plan.role == "bowling" else players
                )
                result = service.matchup(batter["player_id"], bowler["player_id"], flt)
                t = table(
                    batter["name"] + " vs " + bowler["name"] + " — " + scope.label,
                    result["by_format"],
                )
                if t:
                    tables.append(t)
                else:
                    summary = (
                        "No recorded deliveries between these players in this scope."
                    )
            elif plan.intent == "venue":
                t = table(
                    "Venue scoring — " + scope.label,
                    execution.venue_summary(service, flt),
                )
                if t:
                    tables.append(t)
            elif plan.intent == "ranking" and not (players and plan.dimensions):
                rows = execution.aggregate(
                    service,
                    flt,
                    plan.role,
                    ranking=True,
                    min_balls=plan.min_balls,
                    metric=plan.metrics[0],
                    limit=plan.limit,
                    descending=plan.descending,
                )
                t = table(
                    "Ranking by "
                    + plan.metrics[0].replace("_", " ")
                    + " — "
                    + scope.label,
                    rows,
                )
                if t:
                    tables.append(t)
                else:
                    summary = f"No {plan.role} rankings meet this sample."
                notes.append(
                    EvidenceNote(
                        title="Minimum sample",
                        detail=f"Minimum {plan.min_balls} balls; ranked by {plan.metrics[0]}.",
                    )
                )
                for dim in plan.dimensions:
                    cov = execution.coverage(
                        service, replace(flt, lengths=(), lines=())
                    )
                    total = sum(r["deliveries"] for r in cov)
                    known = sum(r["with_" + dim] for r in cov)
                    pct = 100 * known / total if total else 0
                    notes.append(
                        EvidenceNote(
                            title=dim.title() + " coverage",
                            detail=f"{dim.title()} is recorded for {known:,} of {total:,} deliveries ({pct:.1f}%). This ranking uses only recorded categories matching the displayed filters.",
                        )
                    )
            else:
                for player in players:
                    for dim in plan.dimensions or [None]:
                        rows = execution.aggregate(
                            service, flt, plan.role, player["player_id"], dimension=dim
                        )
                        has_observations = bool(rows)
                        if dim and plan.intent == "ranking":
                            rows = [
                                r
                                for r in rows
                                if r["balls"] >= plan.min_balls
                                and r.get(plan.metrics[0]) is not None
                            ]
                            notes.append(
                                EvidenceNote(
                                    title="Category ranking eligibility",
                                    detail=f"Only categories with at least {plan.min_balls} balls enter this ranking. Coverage and distribution denominators include all annotated deliveries.",
                                )
                            )
                            if not rows and has_observations:
                                summary += f" No {dim} category reaches the {plan.min_balls}-ball minimum."
                        t = table(
                            player["name"]
                            + " — "
                            + scope.label
                            + (" by " + dim if dim else ""),
                            rows,
                        )
                        if t:
                            tables.append(t)
                        elif not dim:
                            summary += f" No recorded {plan.role} deliveries for {player['name']} in {scope.label}."
                        if dim:
                            # Coverage denominator precedes requested line/length
                            # filters; otherwise missing values would disappear.
                            base = replace(flt, lengths=(), lines=())
                            result = service.line_length(
                                player["player_id"], plan.role, dim, base
                            )
                            notes.append(
                                EvidenceNote(
                                    title=dim.title() + " coverage",
                                    detail=safe_text(result["note"])
                                    + " Rows show balls faced/legal balls; delivery_rows includes extras; distribution percentages use annotated deliveries.",
                                )
                            )
                            if not has_observations:
                                cov = execution.coverage(
                                    service,
                                    replace(
                                        base, years=(), year_from=None, year_to=None
                                    ),
                                )
                                spans = [
                                    r["first_" + dim].year
                                    for r in cov
                                    if r["with_" + dim] and r["first_" + dim]
                                ]
                                summary = f"No {dim} data in this selected sample." + (
                                    f" Recorded {dim} coverage for this competition starts in {min(spans)}."
                                    if spans
                                    else ""
                                )
                                for limitation in result["limitations"]:
                                    statement = safe_text(limitation["statement"])
                                    detail = re.search(
                                        r"[^.]*\b(?:line|length)\b[^.]*\.?",
                                        statement,
                                        re.I,
                                    )
                                    detail = detail[0].strip() if detail else statement
                                    if detail not in summary:
                                        summary += " " + detail
                                    notes.append(
                                        EvidenceNote(
                                            title="Stored annotation limitation",
                                            detail=statement,
                                        )
                                    )
        if (
            plan.intent in {"ranking", "comparison"}
            and players
            and plan.dimensions
            and plan.metrics
        ):
            # "Which length does X score fastest against": rank the player's
            # own categories, honouring the minimum sample.
            metric = plan.metrics[0]
            lower = (plan.descending is False) or (
                plan.descending is None
                and plan.role == "bowling"
                and metric in {"economy", "average", "strike_rate"}
            )
            for t in tables:
                if metric not in t.columns or "balls" not in t.columns:
                    continue
                key = t.columns[0]
                eligible = [
                    r
                    for r in t.rows
                    if isinstance(r[t.columns.index(metric)], (int, float))
                    and (r[t.columns.index("balls")] or 0) >= plan.min_balls
                ]
                if eligible:
                    best = (min if lower else max)(
                        eligible, key=lambda r: r[t.columns.index(metric)]
                    )
                    where = t.title.replace(" by " + key, "")
                    category = (
                        str(best[0])
                        .replace("_", " ")
                        .lower()
                        .replace("offstump", "off stump")
                        .capitalize()
                    )
                    summary += (
                        f" {'Lowest' if lower else 'Highest'} {metric.replace('_', ' ')} by {key} ({where}): "
                        f"{category}, {best[t.columns.index(metric)]} from {best[t.columns.index('balls')]} balls "
                        f"(minimum {plan.min_balls} balls)."
                    )
                else:
                    summary += (
                        f" No {key} category reaches the {plan.min_balls}-ball minimum."
                    )
        if plan.intent == "comparison" and plan.metrics and not plan.dimensions:
            metric = plan.metrics[0]
            observed = []
            for t in tables:
                if metric in t.columns:
                    for row in t.rows:
                        val = row[t.columns.index(metric)]
                        if isinstance(val, (int, float)):
                            observed.append((val, t.title))
            if len(observed) > 1:
                lower = plan.role == "bowling" and metric in {
                    "economy",
                    "average",
                    "strike_rate",
                }
                extreme = (min if lower else max)(v for v, _ in observed)
                targets = ", ".join(title for v, title in observed if v == extreme)
                summary += f" {'Lowest' if lower else 'Highest'} recorded {metric.replace('_',' ')}: {targets} ({extreme})."
        if not tables and not summary:
            summary = "No recorded deliveries match these filters."
    # The general note always ends the collapsed evidence. Named Afghanistan
    # players also receive a prominent limitation directly in the answer.
    afghan = False
    if players and {"batting_team", "bowling_team"} <= columns:
        with service._connect() as c:
            for player in players:
                afghan = afghan or bool(
                    c.execute(
                        "SELECT count(*) FROM analytics.deliveries WHERE (batter_id=? AND batting_team='Afghanistan' OR bowler_id=? AND bowling_team='Afghanistan') AND format IN ('ODI','Test','T20I')",
                        [player["player_id"]] * 2,
                    ).fetchone()[0]
                )
    if afghan:
        summary += " Data for Afghanistan players is limited (international records are incomplete; T20Is start in 2019)."
    notes.append(EvidenceNote(title="Afghanistan coverage", detail=AFGHAN_NOTE))
    status = (
        EvidenceStatus.unsupported
        if errors
        else (
            EvidenceStatus.supported if tables else EvidenceStatus.insufficient_evidence
        )
    )
    response = QueryResponse(
        status=status,
        failure_state="unsupported_capability" if errors else None,
        interpretation=QueryInterpretation(
            original_question=question,
            query_class="multiformat",
            entities=[p["name"] for p in players],
            filters=plan.model_dump(),
        ),
        tables=tables,
        evidence_notes=notes,
    )
    # Plain API consumers receive the same tables and limitations as the UI.
    text = headline + ("\n" + summary.strip() if summary.strip() else "")
    for t in tables:
        text += (
            "\n\n"
            + t.title
            + "\n| "
            + " | ".join(t.columns)
            + " |\n| "
            + " | ".join("---" for _ in t.columns)
            + " |"
        )
        for row in t.rows:
            text += (
                "\n| " + " | ".join("-" if v is None else str(v) for v in row) + " |"
            )
    text += "\n\nEvidence & limitations\n" + "\n".join(
        n.title + ": " + n.detail for n in notes
    )
    return text, response, changes
