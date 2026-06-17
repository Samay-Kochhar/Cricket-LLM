from __future__ import annotations

from backend.app.cricket_analytics.schemas import CricketQueryPlan


def unsupported_reason(plan: CricketQueryPlan) -> str:
    return (
        f"Distribution analysis for metric '{plan.metric}' was understood, "
        "but concentration/entropy execution is not implemented yet."
    )
