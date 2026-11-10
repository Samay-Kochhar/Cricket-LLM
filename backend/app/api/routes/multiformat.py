"""Read-only API over the multi-format database: /api/v2/data/...

Independent of the ODI chat stack: it has its own database path
(MULTIFORMAT_DUCKDB_PATH, default data/cricket_all.duckdb) and does not change
any existing endpoint.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.multiformat.service import DeliveryFilter, MultiFormatService

router = APIRouter(prefix="/api/v2/data", tags=["multi-format data"])


@lru_cache
def get_multiformat_service() -> MultiFormatService:
    root = Path(__file__).resolve().parents[4]
    configured = os.getenv("MULTIFORMAT_DUCKDB_PATH")
    return MultiFormatService(Path(configured) if configured else root / "data" / "cricket_all.duckdb")


def _filter(
    format: str | None = None,
    gender: str | None = Query(None, pattern="^(male|female)$"),
    competition: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> DeliveryFilter:
    return DeliveryFilter(format=format, gender=gender, competition=competition, year_from=year_from, year_to=year_to)


def _guard(call):
    try:
        return call()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/coverage")
def coverage(service: MultiFormatService = Depends(get_multiformat_service)):
    """Formats, date ranges, line/length availability and the limitation statements."""
    return _guard(service.coverage)


@router.get("/competitions")
def competitions(
    format: str | None = None,
    gender: str | None = Query(None, pattern="^(male|female)$"),
    service: MultiFormatService = Depends(get_multiformat_service),
):
    return {"items": _guard(lambda: service.competitions(format=format, gender=gender))}


@router.get("/players/search")
def search_players(q: str = Query(..., min_length=2), service: MultiFormatService = Depends(get_multiformat_service)):
    items = _guard(lambda: service.search_players(q))
    return {"query": q, "items": items, "count": len(items)}


def _player_or_404(service: MultiFormatService, player_id: str):
    player = _guard(lambda: service.player(player_id))
    if player is None:
        raise HTTPException(status_code=404, detail=f"Unknown player id {player_id!r}; use /players/search")
    return player


@router.get("/players/{player_id}/stats")
def player_stats(
    player_id: str,
    role: str = Query("batting", pattern="^(batting|bowling)$"),
    flt: DeliveryFilter = Depends(_filter),
    service: MultiFormatService = Depends(get_multiformat_service),
):
    player = _player_or_404(service, player_id)
    return {"player": player, "role": role, "by_format": service.player_stats(player_id, role, flt)}


@router.get("/players/{player_id}/line-length")
def player_line_length(
    player_id: str,
    role: str = Query("batting", pattern="^(batting|bowling)$"),
    dimension: str = Query("length", pattern="^(length|line)$"),
    flt: DeliveryFilter = Depends(_filter),
    service: MultiFormatService = Depends(get_multiformat_service),
):
    player = _player_or_404(service, player_id)
    return {"player": player, **service.line_length(player_id, role, dimension, flt)}
