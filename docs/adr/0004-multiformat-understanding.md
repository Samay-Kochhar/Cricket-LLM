# Share one reading contract across multi-format planners

Decision date: 2026-11-12.

Multi-format chat uses `UnderstandingPlan` as the boundary between reading a
question and calculating its answer. The deterministic reader and optional Gemini
reader emit the same fields. Neither supplies numbers or SQL. Database executors
apply competition, gender, dates, phase, bowling classification, venue, opponent,
sample and comparison filters from that plan.

Validation resolves database identities and checks supported fields. It never
replaces the supplied role, metric, operation or filters. Unsupported requested
parts stop execution with an explicit explanation. Named-player gender inference
belongs to reading; validation does not silently remove a gender filter.

Player aliases and initials come from the database, with conservative spelling
matching. Material identity ambiguity remains unresolved. Ordinary ranking and
cricket vocabulary is excluded from single-token player matches. Database
competition names extend the fixed abbreviation vocabulary. The product's
documented “franchise/other leagues” group means all domestic T20 competitions.

Answers reuse the existing table and collapsed evidence components. Coverage
comes from the selected competition and dates, with missing classification or
line/length values counted in the denominator. Every analytical response ends
its evidence notes with the Afghanistan limitation; named Afghanistan players
also receive a direct limitation in the visible answer. Source brands are not
part of the multi-format answer text.

Career batting totals include a batter's own non-striker dismissals without
adding their partner's runs or balls. Per-delivery matchups and classification
breakdowns count dismissals of the striker on that delivery, including wickets
on wides. Retired hurt and not-out events are excluded. A six requires an actual
boundary, rather than merely six runs recorded on a delivery.

The evaluation split is fixed before development: 58 development questions and
52 holdout questions. Independently authored gold readings score interpretation
separately from identity validation and numerical execution. Holdout answers
remain unopened until the implementation and model prompt are frozen. Each paid
model reading is saved with a hash of model, knowledge pack and question;
subsequent evaluation replays that capture offline. Errors remain cached too.

Live chat defaults to the deterministic reader. `MULTIFORMAT_PLANNER_MODEL`
enables a selected Gemini reading model without changing ODI model selection;
`MULTIFORMAT_PLANNER_OFFLINE=true` restricts it to saved captures. Live captures
are stored under `data/planner_cache`, while evaluation captures stay with the
evaluation artifacts. If no usable model reading exists, the deterministic
reader supplies the interpretation and the answer explicitly identifies that
fallback. The failed response stays cached; repeated requests do not make
another paid call. A valid model plan is never replaced merely because its
meaning or requested metrics fail validation. Model evaluation must keep raw
reading errors separate from answers successfully produced by fallback.

The original holdout was subsequently inspected and used for fixes, so its later
scores are regression results, not unseen-test results. A separate independently
authored, sealed 40-question set was run against frozen source. Preserve its
original answers and grades before further fixes; do not relabel replays as new
unseen evidence. Unqualified player rankings default to runs or wickets; filtered
line/length rankings operate on actual deliveries, excluding a partner's
non-striker dismissal. Named category rankings exclude ineligible sample rows.
