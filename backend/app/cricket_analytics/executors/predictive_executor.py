from __future__ import annotations

from backend.app.cricket_analytics.schemas import CricketQueryPlan


def unsupported_reason(plan: CricketQueryPlan) -> str:
    return (
        "This requires match-level feature modelling. The question was understood, "
        "but predictive analysis is not implemented yet."
    )
