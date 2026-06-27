# Grounded Failure-State Contract

Labels: `ready-for-agent`

## What to build

Introduce a clear grounded failure-state contract for database-grounded Q&A. CricAtlas should distinguish data limitations, unsupported capabilities, and planner uncertainty instead of collapsing everything into a generic unsupported or insufficient-evidence response.

The behavior should be visible through the API/chat response and tested at the semantic answer path.

## Acceptance criteria

- [ ] Data-limitation cases state that the requested fact is missing from the available ODI data.
- [ ] Unsupported-capability cases state that the current semantic/query layer cannot safely answer the request.
- [ ] Planner-uncertainty cases state that CricAtlas is not confident it understood the metric, entity, or filter.
- [ ] Fielding examples such as catches do not produce fabricated supported answers when fielding data is absent.
- [ ] Production behavior does not silently hide planner failure behind brittle fallback rules.

## Blocked by

- #1
