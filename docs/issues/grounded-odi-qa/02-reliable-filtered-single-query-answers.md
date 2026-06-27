# Reliable Filtered Single-Query Answers

Labels: `ready-for-agent`

## What to build

Extend the single-query Semantic V2 path so supported player, bowler, and batter stat questions work reliably with common filters and breakdowns: phase, year, venue, opposition, over range, line, length, shot type, scoring zone, bowling style, and batter/bowler hand where supported by the data.

The completed slice should let users ask natural ODI questions with filters and get a validated plan, SQL-backed evidence, and a correct concise answer.

## Acceptance criteria

- [ ] Phase, year, venue, opposition, and over-range filters normalize consistently across paraphrases.
- [ ] Line, length, shot-type, scoring-zone, and bowling-style breakdowns map to the correct groupings or filters.
- [ ] Supported cases execute through deterministic SQL builders and expose expected result columns.
- [ ] Unsupported filter/metric combinations return a clear unsupported response rather than a misleading supported answer.
- [ ] Existing golden factual and semantic trace tests continue to pass.

## Blocked by

- #1
