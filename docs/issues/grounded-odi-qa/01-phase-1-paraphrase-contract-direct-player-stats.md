# Phase 1 Paraphrase Contract For Direct Player Stats

Labels: `ready-for-agent`

## What to build

Build the first Phase 1 paraphrase contract for direct player statistics. Different user phrasings for the same player batting or bowling stat should normalize to the same Semantic V2 plan, execute through approved SQL evidence, and return a supported answer with clean user-facing labels.

This slice should cover a narrow but complete path: chat/query input, LLM/fallback semantic planning behavior as applicable, plan validation, SQL evidence, result validation, and response output.

## Acceptance criteria

- [ ] Multiple paraphrases of the same direct player stat produce the same normalized operation, entity, metric, grouping, filters, and status.
- [ ] Common short names and nicknames such as Kohli, Bumrah, and Hardik resolve to canonical ODI player names.
- [ ] Supported cases execute SQL against the ODI analytics table and expose expected result columns.
- [ ] User-facing summaries/tables do not leak raw internal enum values.
- [ ] Tests assert normalized plan and SQL evidence first, with only light prose checks.

## Blocked by

None - can start immediately.
