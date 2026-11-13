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

### Plain-English explanations

The user wants reports, Markdown files and chat explanations in simple, plain
English. Explain the result first, then how it works, with concrete cricket
examples where useful. Be concise without skipping the explanation needed to
understand it. Define technical terms immediately or avoid them. Explain what
every test score counts, distinguish new questions from questions used for
fixes, and say which reader or Gemini model each result describes. Separate
missing software from missing data. Do not assume the user understands words
such as validator, plan, guardrail, adjudication or regression.


### Required plain-language rule for this user

Apply this to chat replies, progress updates, reports and issue descriptions.
The user has explicitly said that unexplained technical language wastes their
time and must not be used.

- Start with what is wrong, why it happened, and the concrete solution.
- Use ordinary words and short, connected explanations. Explain an unavoidable
  technical term immediately; do not assume the user knows it.
- Say "the website's computer does not have the cricket records file yet",
  rather than "the all-format database is not installed/provisioned".
- Say "when the rules cannot answer, Gemini searches the records and calculates
  the answer", rather than "AI investigation keeps control after handoff".
- Say "check the old and new records with the same questions before keeping one",
  rather than "establish parity before retiring the legacy dependency".
- Do not use terms such as handoff, parity, regression, guardrail, validator,
  oracle, payload, schema or deployment as unexplained labels in user-facing text.
- Explain the reason for each proposed step and whether it has actually been
  completed. Do not use local timing measurements to claim the website is fast.
- Do not replace a clear explanation with a large technical report or visual.
  Keep implementation details in a separately explained section only when an
  agent needs exact file paths or field names to carry out the work.
