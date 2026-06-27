# Database-Backed Match Facts

Labels: `ready-for-agent`

## What to build

Support simple factual questions when the answer can be grounded in ODI database match metadata or ball-by-ball data. Questions about known matches, tournaments, finals, teams, innings, totals, or available awards/facts should answer only when the required fact exists in the database.

## Acceptance criteria

- [ ] Supported match-fact questions normalize to a factual lookup or equivalent safe semantic plan.
- [ ] The answer is grounded in database metadata or ball-by-ball evidence, not external knowledge.
- [ ] Missing match facts return data limitation or unsupported capability as appropriate.
- [ ] Existing unsupported external-fact tests continue to reject facts not present in the dataset.
- [ ] The response exposes enough evidence context for the user to see what database fact was used.

## Blocked by

- #6
