## Agent skills

### Approved UI preservation

Treat the user's approved UI as a locked reference. Do not redesign, simplify,
replace, reinterpret, or remove its layout, styling, controls, labels, metrics,
or interactions without asking the user first and receiving explicit approval.
When moving an approved feature to another surface, compare the new surface
against the approved implementation element by element and preserve it exactly.
If the reference or desired difference is unclear, stop and ask rather than
making a visual assumption.

### Issue tracker

Issues are tracked in GitHub Issues for `Samay-Kochhar/Cricket-LLM`; external PRs are not a triage surface by default. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default Matt Pocock triage label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain docs layout. See `docs/agents/domain.md`.
