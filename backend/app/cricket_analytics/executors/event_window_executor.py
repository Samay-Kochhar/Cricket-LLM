from __future__ import annotations

from backend.app.cricket_analytics.schemas import CricketQueryPlan


def unsupported_reason(plan: CricketQueryPlan) -> str:
    event = f" for event '{plan.event}'" if plan.event else ""
    return f"Event-window analysis{event} was understood, but deriving those windows is not implemented yet."
