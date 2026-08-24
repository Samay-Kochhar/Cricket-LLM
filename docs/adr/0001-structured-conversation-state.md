# Use structured conversation state for contextual follow-ups

CricAtlas carries the players, operation, metric, comparison participants, comparison metrics, and filters from the last successful answer as an optional structured `/api/chat` request and response field. Structured state is the canonical source for contextual follow-ups because it preserves resolved analytics meaning across short turns; transcript inference remains only as a compatibility fallback for older stored conversations.
