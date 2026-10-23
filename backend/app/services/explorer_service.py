from __future__ import annotations

from typing import Any

from backend.app.domain.venues import resolve_venue
from backend.app.domain.venue_leaderboard import PHASES

from backend.app.services.player_resolution import resolve_player_name


BATTING_POLICY = "Balls faced use the recorded ballfaced flag; runs and dismissals include all recorded striker events. Dots and boundaries use balls faced. Control % uses only balls faced with recorded control; control balls show that denominator. Undefined rates remain unavailable."
BOWLING_POLICY = "Dots: legal balls with no bowler-charged runs / legal balls. Boundaries: legal balls hit for 4 or 6 / legal balls. Economy uses 6 legal balls per over. Only bowler-credit dismissals count as wickets."


def build_venue_profile(repository: object, venue_name: str, mode: str = "bowling", **filters: Any) -> dict[str, Any]:
    """Build the venue explorer payload shared by FastAPI and Streamlit."""
    from backend.app.domain.venue_leaderboard import mode_options, metric_options
    options = mode_options(mode)(**filters)
    venue = resolve_venue(venue_name)
    method = (repository.get_venue_batting_leaderboard if mode == "batting"
              else repository.get_venue_bowling_leaderboard)
    rows = method(venue_name, **options.as_dict())
    return {
        "mode": mode, "venue_id": venue.id, "venue_name": venue.display_name,
        "leaderboard": rows,
        # Preserve existing API clients while exposing one mode-independent field.
        "bowling_leaderboard": rows if mode == "bowling" else [],
        "batting_leaderboard": rows if mode == "batting" else [],
        "filters": options.as_dict(), "ranking": options.ranking,
        "metric_options": metric_options(mode), "phase_options": PHASES,
        "sample_units": options.sample_units, "venue_options": repository.list_venues(),
        "sample_policy": "Minimum applies to the filtered sample before top N. Unavailable rates are excluded from that metric ranking. " + (BATTING_POLICY if mode == "batting" else BOWLING_POLICY),
    }


def build_player_comparison(repository: object, players: list[str], mode: str = "batting",
                            metric: str | None = None, phase: str | None = None,
                            year_start: int | None = None, year_end: int | None = None,
                            venue: str | None = None) -> dict[str, Any]:
    """Both players receive exactly the same validated context, with no overall winner."""
    from backend.app.domain.venue_leaderboard import mode_options, metric_options
    cls = mode_options(mode)
    options = cls(metric=metric or ("batting_strike_rate" if mode == "batting" else "economy_rate"),
                  phase=phase, year_start=year_start, year_end=year_end)
    player_names = repository.list_player_names()
    canonical = [resolve_player_name(name, player_names).canonical_name or name for name in players[:2]]
    if len(canonical) != 2 or canonical[0] == canonical[1]:
        raise ValueError("Choose two different players to compare.")
    canonical_venue = resolve_venue(venue) if venue else None
    context = dict(phase=phase, year_start=year_start, year_end=year_end,
                   venue=canonical_venue.display_name if canonical_venue else None)
    summaries = []
    for name in canonical:
        summary = repository.get_explorer_player_summary(name, mode, **context)
        if summary is None:
            counts = (["balls_faced", "runs_scored", "dismissals", "control_balls"] if mode == "batting"
                      else ["deliveries", "runs_conceded", "wickets"])
            summary = {**{value[1]: None for value in cls.metrics.values()},
                       **{field: 0 for field in counts},
                       "player_name": name, "matches": 0, "delivery_rows": 0}
        sample = summary.get("balls_faced" if mode == "batting" else "deliveries", 0)
        summaries.append({**summary, "small_sample": sample < 24})
    totals = {"balls_faced", "runs_scored", "dismissals", "balls_bowled", "runs_conceded"}
    preference = ("Descriptive total; no preferred direction" if options.metric in totals else
                  "Lower is preferable" if options.ranking["direction"] == "asc" else "Higher is preferable")
    return {"mode": mode, "players": summaries, "filters": context,
            "ranking": {**options.ranking, "preference": preference},
            "metric_options": metric_options(mode), "phase_options": PHASES,
            "venue_options": repository.list_venues(),
            "sample_policy": "Samples below 24 balls are flagged as small; no players are excluded. Missing rates are unavailable, not zero. No overall winner is assigned. " + (BATTING_POLICY if mode == "batting" else BOWLING_POLICY)}
