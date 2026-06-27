from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.app.bootstrap import get_services
from backend.app.domain.evidence_models import VisualPayload
from backend.app.services.player_resolution import resolve_player_name


router = APIRouter(prefix="/api", tags=["explore"])


class WorkbenchSearchRequest(BaseModel):
    query: str


@router.get("/players/search")
def search_players(q: str = Query(..., min_length=1), services=Depends(get_services)):
    items = services["repository"].search_players(q)
    return {"query": q, "items": items, "count": len(items)}


@router.get("/players/{player_name}")
def player_profile(player_name: str, services=Depends(get_services)):
    repo = services["repository"]
    resolved = resolve_player_name(player_name, repo.list_player_names())
    canonical_name = resolved.canonical_name or player_name
    analytics_service = services.get("analytics_service")
    if analytics_service is not None:
        visuals, coverage_notes = analytics_service._build_batter_visuals(canonical_name)
    else:
        visuals, coverage_notes = VisualPayload(), []
    return {
        "player_name": canonical_name,
        "summary": repo.get_player_batting_summary(canonical_name),
        "trend": repo.get_player_year_trend(canonical_name),
        "visuals": visuals.model_dump(),
        "coverage_notes": [note.model_dump() for note in coverage_notes],
        "suggestions": list(resolved.suggestions),
    }


@router.get("/venues/{venue_name}")
def venue_profile(venue_name: str, services=Depends(get_services)):
    return {
        "venue_name": venue_name,
        "bowling_leaderboard": services["repository"].get_venue_bowling_leaderboard(venue_name),
    }


@router.get("/compare")
def compare_players(player: list[str] = Query(default=[]), services=Depends(get_services)):
    repo = services["repository"]
    summaries = []
    for name in player[:2]:
        resolved = resolve_player_name(name, repo.list_player_names())
        summary = repo.get_player_batting_summary(resolved.canonical_name or name)
        if summary:
            summaries.append(summary)
    return {"players": summaries}


@router.post("/workbench/search")
def workbench_search(payload: WorkbenchSearchRequest, services=Depends(get_services)):
    return services["workbench_service"].search(payload.query)
