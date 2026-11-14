# Rules first, AI investigation when the rules cannot account for a question

Decision date: 2026-11-13. Approved for main on 2026-11-14.

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

**Evidence checks do not veto the investigator.** After the rules hand over,
there is no second model or deterministic question schema judging what the AI
may answer. Tables are copied directly from successful query results. Display
labels differing only in case, spaces or underscores are resolved locally; for
unknown or ambiguous labels the original complete query columns are shown.
Neither case requires another model call or a refusal.

Numbers in the narrative, definitions, limitations and titles are cross-checked
against query results (and stated filters where relevant). Unmatched numbers
produce a clearly named evidence note. The answer is still displayed, and the
system does not claim all its numbers were verified. This accepts the risk of
an incorrect narrative while preserving the exact query-result tables for
review. SQL permissions, external access restrictions, result/time limits, and
the requirement for successful query-backed tables remain enforced. This
policy implements the user's 13 November direction that validation should not
clash with an investigation after the rules have handed over.

**Unresolved questions become saved cases.** When no checked answer exists
(model refuses, cannot identify usable query results, hits limits, or no AI is configured),
the reply says plainly that it could not answer and why, and the question,
reason and what was tried are appended to the local, gitignored
`data/unanswered_questions.jsonl` (`UNANSWERED_BACKLOG_PATH` overrides).

**Configuration.** The AI investigation is off unless
`MULTIFORMAT_INVESTIGATION_MODEL` names a model; tests force it off. Every model
successful (or permanently failed) response is cached by request hash under
`data/investigation_cache` (rate limits and server errors return immediately and are never cached), so a
repeated question is not paid twice and evaluations replay offline
(`MULTIFORMAT_INVESTIGATION_OFFLINE=true`). ODI-chat refusals are handed to the
same investigation when it is enabled.


Long-running Streamlit sessions refresh their service bundle when either database
appears or changes (path, modification time and size), or investigation settings
change. Matchup page navigation uses only the lightweight explorer bundle; the
full analysis engine is deferred until submission. Failed/empty chat requests
remain visible as an assistant message on later reruns. When the all-formats
file is missing, explicit non-ODI questions get a direct data-availability reply
instead of an ODI model request. The AI client makes one attempt per turn,
with a 45-second request timeout and a 120-second investigation budget checked
between turns/tools; it does not spend extra time retrying rate limits.
