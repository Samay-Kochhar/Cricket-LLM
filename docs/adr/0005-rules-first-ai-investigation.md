# Rules first, AI investigation when the rules cannot account for a question

Decision date: 2026-11-13. Branch: `feature/ai-fallback` (not merged).

Familiar questions get fast database answers; unfamiliar questions get a more
capable AI investigation; unresolved questions become specific cases to improve.

**Database rules answer only when every part of the question is accounted for.**
After the deterministic reader builds its plan, `self_check.rules_hand_off`
checks each question word: it must be a player the reader found (including a
close misspelling next to a found name), a competition, format, venue or team
the plan uses, a number the plan uses, a word the reader actually interprets,
or a meaning-neutral word. A leftover word ("opening", "successful", "ducks",
"fourth innings") means the rules would answer a simpler question, so they hand
the question off instead. An explicit refusal ("I can't answer the X part")
hands off too. The rules' own plans and numbers are unchanged; the evidence
section now states the path ("Database rules", "AI investigation" or "Not
answered").

**The AI investigation receives the whole question and real tools.** A Gemini
model (default `gemini-3.1-pro-preview`, high thinking) calls `run_sql` against
a private, read-only DuckDB instance that attaches the multi-format database
and the ODI database (`odi`). Guardrails are enforced in code: one SELECT/WITH
statement, no write/DDL/ATTACH/COPY/PRAGMA/SET, no file functions, no
source-identifying columns, external access disabled and settings locked,
200-row results (larger results are refused so the model aggregates), a
20-second query limit, at most 10 queries and 14 model turns. The knowledge
pack is built from the database (tables, coverage, stored limitation
statements, competition names) plus CricAtlas's fixed definitions.

**Numbers are checked, not trusted.** Tables are copied directly from query
results by query number. Every number in the interpretation line, answer,
definitions and limitations must appear in a successful query result (allowing display
rounding and fractions shown as percentages). A question number or SQL literal alone
is insufficient. Table titles are checked too; malformed submissions and client
exceptions become saved cases.
A failing answer is sent back; after three failures the question is not
answered. Source brands are scrubbed from model text.

**Unresolved questions become saved cases.** When no checked answer exists
(model refuses, fails the number check, hits limits, or no AI is configured),
the reply says plainly that it could not answer and why, and the question,
reason and what was tried are appended to the local, gitignored
`data/unanswered_questions.jsonl` (`UNANSWERED_BACKLOG_PATH` overrides).

**Configuration.** The AI investigation is off unless
`MULTIFORMAT_INVESTIGATION_MODEL` names a model; tests force it off. Every model
response is cached by request hash under `data/investigation_cache`, so a
repeated question is not paid twice and evaluations replay offline
(`MULTIFORMAT_INVESTIGATION_OFFLINE=true`). ODI-chat refusals are handed to the
same investigation when it is enabled.
