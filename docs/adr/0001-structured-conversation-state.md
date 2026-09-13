# Use structured conversation state for contextual follow-ups

CricAtlas carries the players, operation, metric, comparison participants, comparison metrics, and filters from the last successful answer as an optional structured `/api/chat` request and response field. Structured state is the canonical source for contextual follow-ups because it preserves resolved analytics meaning across short turns; transcript inference remains only as a compatibility fallback for older stored conversations.

The state schema is versioned and stores the complete `CanonicalCricketMeaning` for
the last successful answer. A contextual turn is interpreted as versioned typed
add, replace, and remove operations over that meaning. The patched meaning is then
validated and passed back through its original family compiler. Clients with older
state payloads continue to use the compatibility reconstruction path.
