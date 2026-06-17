from __future__ import annotations

from backend.app.cricket_analytics.schemas import CricketQueryPlan


def unsupported_reason(plan: CricketQueryPlan) -> str:
    return (
        "Tactical recommendation was understood, but evidence gathering and grounded Gemini "
        "synthesis for this operation are not implemented yet."
    )
