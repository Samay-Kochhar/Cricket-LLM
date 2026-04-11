# Golden Query Expectations

The golden-query set is not trying to prove that CricAtlas answers every cricket question. It is trying to pin down trust behavior for the current ODI-only scope.

## Expected Rules

- Supported ODI queries must return a structured payload with the expected evidence blocks.
- Unsupported or missing-entity cases must return `insufficient_evidence`, not invented analysis.
- Venue questions should resolve an explicit venue name into the interpretation filters when possible.
- Matchup questions must identify two ODI entities and return direct database-backed evidence.
- Trend questions must preserve the trend chart/table structure after time filtering.

## What These Evals Catch

- Query-class regression in the router
- Missing citations on supported responses
- Accidental fallback from structured evidence to plain text only
- Hallucination-prone unsupported cases
- Broken venue/player deep-link behavior caused by missing interpretation entities or filters
