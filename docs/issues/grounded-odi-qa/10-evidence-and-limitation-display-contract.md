# Evidence And Limitation Display Contract

Labels: `ready-for-agent`

## What to build

Ensure API and UI responses display evidence, sample context, and limitation states cleanly for supported answers, data limitations, unsupported capabilities, and planner uncertainty. The user should understand what CricAtlas checked and why an answer is or is not available.

## Acceptance criteria

- [ ] Supported answers expose evidence tables, result columns, and sample context where relevant.
- [ ] Data limitation, unsupported capability, and planner uncertainty states render clearly without blank panels.
- [ ] Raw internal enum values do not appear in user-facing tables, summaries, or traces intended for display.
- [ ] Tactical workup responses can show which evidence probes were checked.
- [ ] API/chat contract tests cover the displayed status and evidence payload shape.

## Blocked by

- #6
- At least one supported query slice from the Phase 1 single-query work, such as #1 or #2.
