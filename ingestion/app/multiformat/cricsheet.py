"""Parse the Cricsheet JSON archive into match, player and delivery tables.

Cricsheet is the scoring backbone of the multi-format build: it is the most
complete and most accurate ball-by-ball record we have (see
docs/data-sources.md). It carries no line, length or shot data.
"""

from __future__ import annotations

import json
import zipfile
from datetime import date
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

# Dismissal kinds credited to the bowler. Run outs, retirements, obstructing the
# field, handled the ball and timed out are team dismissals only.
BOWLER_WICKET_KINDS = frozenset(
    {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
)
# Kinds that do not end a batter's innings as a dismissal.
NON_DISMISSAL_KINDS = frozenset({"retired hurt", "retired not out"})

MATCH_SCHEMA = pa.schema(
    [
        ("match_id", pa.string()),
        ("match_type", pa.string()),
        ("gender", pa.string()),
        ("team_type", pa.string()),
        ("format", pa.string()),
        ("competition", pa.string()),
        ("event_match_number", pa.string()),
        ("event_stage", pa.string()),
        ("season", pa.string()),
        ("start_date", pa.date32()),
        ("end_date", pa.date32()),
        ("venue", pa.string()),
        ("city", pa.string()),
        ("team1", pa.string()),
        ("team2", pa.string()),
        ("toss_winner", pa.string()),
        ("toss_decision", pa.string()),
        ("winner", pa.string()),
        ("win_by_runs", pa.int32()),
        ("win_by_wickets", pa.int32()),
        ("win_by_innings", pa.bool_()),
        ("result", pa.string()),
        ("method", pa.string()),
        ("eliminator", pa.string()),
        ("balls_per_over", pa.int8()),
        ("scheduled_overs", pa.int16()),
        ("player_of_match", pa.string()),
        ("data_version", pa.string()),
        ("revision", pa.int16()),
    ]
)

PLAYER_SCHEMA = pa.schema(
    [
        ("match_id", pa.string()),
        ("team", pa.string()),
        ("player_name", pa.string()),
        ("player_id", pa.string()),
    ]
)

DELIVERY_SCHEMA = pa.schema(
    [
        ("match_id", pa.string()),
        ("innings_no", pa.int8()),
        ("is_super_over", pa.bool_()),
        ("batting_team", pa.string()),
        ("bowling_team", pa.string()),
        ("over_no", pa.int16()),
        ("delivery_in_over", pa.int16()),
        ("legal_ball_in_over", pa.int16()),
        ("innings_delivery_seq", pa.int32()),
        ("is_legal", pa.bool_()),
        ("batter", pa.string()),
        ("batter_id", pa.string()),
        ("non_striker", pa.string()),
        ("non_striker_id", pa.string()),
        ("bowler", pa.string()),
        ("bowler_id", pa.string()),
        ("runs_batter", pa.int16()),
        ("runs_extras", pa.int16()),
        ("runs_total", pa.int16()),
        ("non_boundary", pa.bool_()),
        ("wides", pa.int16()),
        ("noballs", pa.int16()),
        ("byes", pa.int16()),
        ("legbyes", pa.int16()),
        ("penalty", pa.int16()),
        ("wicket_count", pa.int8()),
        ("wicket_kind", pa.string()),
        ("player_out", pa.string()),
        ("player_out_id", pa.string()),
        ("fielders", pa.string()),
        ("is_bowler_wicket", pa.bool_()),
        ("wicket2_kind", pa.string()),
        ("player_out2", pa.string()),
        ("player_out2_id", pa.string()),
        ("review_by", pa.string()),
        ("review_decision", pa.string()),
        ("target_runs", pa.int16()),
        ("target_overs", pa.float32()),
        ("declared", pa.bool_()),
    ]
)


def classify_format(match_type: str, team_type: str | None, balls_per_over: int | None, competition: str) -> str:
    """Map Cricsheet's match_type/team_type onto CricAtlas format labels."""
    international = team_type == "international"
    if match_type == "Test":
        return "Test"
    if match_type == "ODI":
        return "ODI"
    if match_type == "T20" and international:
        return "T20I"
    if match_type == "IT20":
        return "T20 (other international)"
    if match_type == "ODM":
        return "List A (other international)" if international else "List A domestic"
    if match_type == "MDM":
        return "Multi-day (other international)" if international else "First-class domestic"
    if match_type == "T20":
        if balls_per_over == 5 or "hundred" in competition.lower():
            return "The Hundred"
        return "T20 domestic"
    return match_type


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def parse_match(match_id: str, payload: dict[str, Any]) -> tuple[dict, list[dict], list[dict]]:
    info = payload["info"]
    registry = (info.get("registry") or {}).get("people") or {}
    event = info.get("event") or {}
    competition = event.get("name") or ""
    outcome = info.get("outcome") or {}
    by = outcome.get("by") or {}
    teams = list(info.get("teams") or []) + [None, None]
    dates = sorted(date.fromisoformat(str(d)) for d in info.get("dates") or [])
    toss = info.get("toss") or {}
    meta = payload.get("meta") or {}

    match = {
        "match_id": match_id,
        "match_type": info.get("match_type"),
        "gender": info.get("gender"),
        "team_type": info.get("team_type"),
        "format": classify_format(
            info.get("match_type", ""), info.get("team_type"), info.get("balls_per_over"), competition
        ),
        "competition": competition or None,
        "event_match_number": None if event.get("match_number") is None else str(event.get("match_number")),
        "event_stage": _str_or_none(event.get("stage") or event.get("group")),
        "season": None if info.get("season") is None else str(info.get("season")),
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
        "venue": _str_or_none(info.get("venue")),
        "city": _str_or_none(info.get("city")),
        "team1": teams[0],
        "team2": teams[1],
        "toss_winner": _str_or_none(toss.get("winner")),
        "toss_decision": toss.get("decision"),
        "winner": _str_or_none(outcome.get("winner")),
        "win_by_runs": _int_or_none(by.get("runs")),
        "win_by_wickets": _int_or_none(by.get("wickets")),
        "win_by_innings": bool(by.get("innings")),
        "result": _str_or_none(outcome.get("result")),
        "method": _str_or_none(outcome.get("method")),
        "eliminator": _str_or_none(outcome.get("eliminator")),
        "balls_per_over": info.get("balls_per_over"),
        "scheduled_overs": _int_or_none(info.get("overs")),
        "player_of_match": "; ".join(info.get("player_of_match") or []) or None,
        "data_version": _str_or_none(meta.get("data_version")),
        "revision": _int_or_none(meta.get("revision")),
    }

    players = [
        {"match_id": match_id, "team": team, "player_name": name, "player_id": registry.get(name)}
        for team, names in (info.get("players") or {}).items()
        for name in names
    ]

    deliveries: list[dict] = []
    team_names = [t for t in teams if t]
    for innings_index, innings in enumerate(payload.get("innings") or [], start=1):
        batting_team = innings.get("team")
        bowling_team = next((t for t in team_names if t != batting_team), None)
        target = innings.get("target") or {}
        seq = 0
        for over in innings.get("overs") or []:
            over_no = int(over["over"])
            legal = 0
            for position, delivery in enumerate(over.get("deliveries") or [], start=1):
                seq += 1
                extras = delivery.get("extras") or {}
                runs = delivery.get("runs") or {}
                is_legal = "wides" not in extras and "noballs" not in extras
                if is_legal:
                    legal += 1
                wickets = delivery.get("wickets") or []
                first = wickets[0] if wickets else {}
                second = wickets[1] if len(wickets) > 1 else {}
                first_out = first.get("player_out") or first.get("playeer_out")
                review = delivery.get("review") or {}
                deliveries.append(
                    {
                        "match_id": match_id,
                        "innings_no": innings_index,
                        "is_super_over": bool(innings.get("super_over")),
                        "batting_team": batting_team,
                        "bowling_team": bowling_team,
                        "over_no": over_no,
                        "delivery_in_over": position,
                        "legal_ball_in_over": legal,
                        "innings_delivery_seq": seq,
                        "is_legal": is_legal,
                        "batter": delivery.get("batter"),
                        "batter_id": registry.get(delivery.get("batter")),
                        "non_striker": delivery.get("non_striker"),
                        "non_striker_id": registry.get(delivery.get("non_striker")),
                        "bowler": delivery.get("bowler"),
                        "bowler_id": registry.get(delivery.get("bowler")),
                        "runs_batter": runs.get("batter", 0),
                        "runs_extras": runs.get("extras", 0),
                        "runs_total": runs.get("total", 0),
                        "non_boundary": bool(runs.get("non_boundary")),
                        "wides": extras.get("wides"),
                        "noballs": extras.get("noballs"),
                        "byes": extras.get("byes"),
                        "legbyes": extras.get("legbyes"),
                        "penalty": extras.get("penalty"),
                        "wicket_count": len(wickets),
                        "wicket_kind": first.get("kind"),
                        "player_out": first_out,
                        "player_out_id": registry.get(first_out) if first_out else None,
                        "fielders": "; ".join(
                            f.get("name", "") + (" (sub)" if f.get("substitute") else "")
                            for f in first.get("fielders") or []
                        )
                        or None,
                        "is_bowler_wicket": first.get("kind") in BOWLER_WICKET_KINDS
                        or second.get("kind") in BOWLER_WICKET_KINDS,
                        "wicket2_kind": second.get("kind"),
                        "player_out2": second.get("player_out"),
                        "player_out2_id": registry.get(second.get("player_out")) if second else None,
                        "review_by": review.get("by"),
                        "review_decision": review.get("decision"),
                        "target_runs": _int_or_none(target.get("runs")),
                        "target_overs": target.get("overs"),
                        "declared": bool(innings.get("declared")),
                    }
                )
    return match, players, deliveries


def iter_archive(zip_path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".json"):
                continue
            yield Path(name).stem, json.loads(archive.read(name))


class _ParquetSink:
    def __init__(self, path: Path, schema: pa.Schema, batch_rows: int = 250_000) -> None:
        self.path = path
        self.schema = schema
        self.batch_rows = batch_rows
        self.rows: list[dict] = []
        self.writer = pq.ParquetWriter(str(path), schema, compression="zstd")
        self.count = 0

    def extend(self, rows: list[dict]) -> None:
        self.rows.extend(rows)
        if len(self.rows) >= self.batch_rows:
            self.flush()

    def flush(self) -> None:
        if self.rows:
            self.writer.write_table(pa.Table.from_pylist(self.rows, schema=self.schema))
            self.count += len(self.rows)
            self.rows = []

    def close(self) -> int:
        self.flush()
        self.writer.close()
        return self.count


def convert_archive(zip_path: Path, out_dir: Path) -> dict[str, int]:
    """Write matches/players/deliveries Parquet files from the Cricsheet zip."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sinks = {
        "matches": _ParquetSink(out_dir / "cs_matches.parquet", MATCH_SCHEMA, 20_000),
        "players": _ParquetSink(out_dir / "cs_players.parquet", PLAYER_SCHEMA),
        "deliveries": _ParquetSink(out_dir / "cs_deliveries.parquet", DELIVERY_SCHEMA),
    }
    for match_id, payload in iter_archive(zip_path):
        match, players, deliveries = parse_match(match_id, payload)
        sinks["matches"].extend([match])
        sinks["players"].extend(players)
        sinks["deliveries"].extend(deliveries)
    return {name: sink.close() for name, sink in sinks.items()}
