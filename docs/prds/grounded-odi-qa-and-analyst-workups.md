# PRD: Grounded ODI Q&A and Analyst Workups

## Problem Statement

CricAtlas is intended to answer cricket questions from an ODI ball-by-ball database, but the current agent is not reliable enough when users ask normal cricket questions in varied language. It can answer some simple prompts, but small wording changes or new but related question shapes can lead to wrong routing, unsupported responses, schema pressure, or brittle rule changes.

The user needs CricAtlas to behave like a trustworthy cricket analysis assistant for general fans, analysts, and coaches. It should understand many phrasings of the same database-grounded question, produce correct SQL-backed evidence, explain data limitations clearly, and avoid inventing answers when the database or current capabilities do not support the request.

## Solution

CricAtlas will focus on ODI database-grounded answers. The assistant will use the LLM for language understanding, then convert that understanding into a strict semantic plan that deterministic code validates, compiles into SQL, executes, validates, and explains.

For Phase 1 behavior, CricAtlas should reliably answer single-query questions across core ODI analytics: player batting stats, player bowling stats, leaderboards, player comparisons, batter-vs-bowler matchups, venue filters, opposition filters, phase filters, year filters, over-range filters, line/length breakdowns, shot-type breakdowns, scoring-zone breakdowns, and simple match facts available in the database.

For later analyst/coach behavior, CricAtlas should support multi-query workups. Tactical prompts should first gather multiple evidence tables from the database, then synthesize strengths, weaknesses, and strategy from those results.

The system must distinguish data limitations from unsupported capabilities and planner uncertainty. It should not silently fall back to brittle rules or polished but untrusted analysis.

## User Stories

1. As a cricket fan, I want to ask for a player’s ODI batting strike rate, so that I can quickly understand their scoring speed.
2. As a cricket fan, I want to ask the same batting-stat question in casual phrasing, so that I do not need to know CricAtlas-specific wording.
3. As a cricket fan, I want player nicknames and common short names to resolve correctly, so that “Kohli,” “Bumrah,” or “Hardik” work naturally.
4. As a cricket analyst, I want CricAtlas to normalize different phrasings into the same semantic plan, so that equivalent questions produce consistent answers.
5. As a cricket analyst, I want the SQL evidence behind an answer to be correct, so that I can trust the result more than the generated prose.
6. As a coach, I want batter statistics filtered by bowling style, so that I can see how a batter performs against pace, spin, wrist spin, or left-arm pace.
7. As a coach, I want batter statistics filtered by length, so that I can identify whether short balls, good length balls, full balls, or yorkers are effective.
8. As a coach, I want batter statistics filtered by line, so that I can inspect which lines suppress scoring or create risk.
9. As a coach, I want bowler statistics filtered by phase, so that I can evaluate powerplay, middle-over, and death-over effectiveness.
10. As a coach, I want player performance filtered by venue, so that I can prepare for ground-specific conditions.
11. As a coach, I want player performance filtered by opposition, so that I can prepare for a specific opponent.
12. As a cricket analyst, I want leaderboards for runs, wickets, strike rate, economy, dot percentage, boundary percentage, false-shot percentage, yorker percentage, and similar metrics, so that I can compare the field.
13. As a cricket analyst, I want top-N and bottom-N leaderboards, so that I can inspect ranked lists at a useful size.
14. As a cricket analyst, I want minimum sample thresholds to be respected, so that rate-based leaderboards are not dominated by tiny samples.
15. As a cricket analyst, I want player-vs-player comparisons, so that I can compare two batters or two bowlers on the same metrics.
16. As a cricket analyst, I want mixed-role comparisons to be rejected clearly when unsupported, so that a batter-vs-bowler comparison is not forced into the wrong metric.
17. As a cricket analyst, I want batter-vs-bowler matchup rankings, so that I can see who dismisses or controls a batter most often.
18. As a cricket analyst, I want matchup questions to expose low-sample context, so that I do not overinterpret sparse head-to-head data.
19. As a cricket fan, I want simple match facts from database metadata when available, so that questions like a known final or tournament match can be answered from the dataset.
20. As a cricket fan, I want CricAtlas to say when a fact is not present in the dataset, so that missing data is not confused with a cricket conclusion.
21. As a cricket fan, I want fielding questions such as catches to return a data-limitation response if the database lacks fielding events, so that the assistant does not fabricate fielding records.
22. As a cricket analyst, I want unsupported capabilities to be named clearly, so that I know whether the issue is missing data, missing implementation, or uncertain interpretation.
23. As a cricket analyst, I want planner uncertainty to be surfaced, so that ambiguous prompts do not produce overconfident answers.
24. As a cricket analyst, I want the response to include enough evidence context, so that I can see what data was used.
25. As a cricket analyst, I want raw internal enum values to be hidden from user-facing output, so that tables and summaries read naturally.
26. As a coach, I want broad tactical questions to become evidence-gathering workups later, so that strategy is based on facts rather than free-form model opinion.
27. As a coach, I want “How should we bowl to this batter?” to inspect bowling style, line, length, false shots, scoring zones, and dismissals, so that recommendations are grounded.
28. As a coach, I want tactical answers to state what was checked, so that I can judge whether the recommendation is complete enough.
29. As a coach, I want tactical answers to mention limitations, so that I know when sample size or missing data weakens the plan.
30. As a developer, I want the LLM to handle language variation while deterministic code handles correctness, so that the system is adaptable without unsafe SQL generation.
31. As a developer, I want golden tests grouped by canonical intent and paraphrases, so that broad language coverage can improve quickly without adding one-off tests only.
32. As a developer, I want tests to assert normalized plans and SQL evidence before prose, so that failures point to the actual reasoning or query problem.
33. As a developer, I want the older deterministic fallback to be treated as development/offline help, so that production behavior does not hide planner failures behind brittle rules.
34. As a developer, I want V2 to be improved rather than replaced by a separate V3 initially, so that existing metric registry, validators, SQL builders, traces, and tests remain useful.

## Implementation Decisions

- CricAtlas will remain ODI database-grounded for this PRD. External cricket knowledge is out of scope.
- The LLM’s responsibility is language understanding, not statistical truth or arbitrary SQL generation.
- The backend’s responsibility is to validate semantic plans, build SQL from approved primitives, execute queries, validate results, and expose evidence.
- Semantic V2 remains the main path. A separate V3 should not be introduced unless the V2 refactor becomes too invasive.
- The existing metric registry, semantic plan shape, capability validation, SQL builders, result validation, and trace concepts should be preserved and strengthened.
- The planner should become LLM-first for production behavior. Deterministic fallback may remain for offline/development use but should not silently mask failed LLM planning in production.
- Phase 1 should prioritize single-query reliability before broad tactical planning.
- The normalized semantic plan should capture operation, entity, metric, grouping, filters, sort, limit, sample policy, and unsupported reason where relevant.
- Supported single-query operations should include aggregate, leaderboard/rank, player comparison, split comparison where already supported, and matchup.
- Factual database lookups should be supported when the answer can be grounded in database match metadata.
- Tactical prompts should eventually use a multi-query workup operation rather than a single forced query.
- Multi-query workups should decompose broad analyst/coach prompts into evidence probes before synthesis.
- Standalone questions, comparison questions, contextual follow-ups, and analyst workups are separate question families with separate acceptance tests.
- A bowling-plan analyst workup is not a player comparison, even when it compares evidence across bowling styles, lines, or lengths.
- A suggested follow-up must not be displayed unless its exact chained chat flow is verified with the preceding answer context.
- Product readiness is judged at the real chat API and UI boundary. An executor test or direct semantic-service test alone does not establish product readiness.
- A suggested follow-up becomes visible only after its chained backend-history test and browser click-through test both pass.
- A contextual follow-up inherits the previous player, metric, and filters. It changes only the details explicitly replaced by the user and asks for clarification when the remaining meaning is materially ambiguous.
- A failed or unclear question does not replace the last successful conversation context. The next short follow-up either reuses that last successful context explicitly or asks for clarification before querying.
- A contextual follow-up asks for clarification only when two or more reasonable interpretations would produce different answers. Clear changes, such as replacing the opposition with Australia, continue without an unnecessary question.
- A comparison follow-up inherits every compared player, comparison metric, and filter, then replaces only the detail explicitly changed by the user. For example, “What about powerplay?” changes the phase but keeps both bowlers and the comparison metrics.
- An unqualified batter comparison defaults to runs, batting average, batting strike rate, boundary percentage, and batter dot-ball percentage.
- An unqualified bowler comparison defaults to wickets, bowling average, economy rate, bowling strike rate, bowler dot-ball percentage, and boundary percentage.
- Batting strike rate and bowling strike rate are separate canonical metrics. Bowling strike rate is legal balls bowled divided by bowler-credit wickets, and lower is better.
- Any unqualified player strike-rate question asks whether the user means batting or bowling strike rate instead of guessing from the player’s likely role.
- Strike-rate answers always use the full label “Batting Strike Rate” or “Bowling Strike Rate” so the interpretation is visible.
- Bowling strike rate is displayed as “N/A — no wickets taken” when the filtered sample contains zero bowler-credit wickets; zero and infinity are never displayed as the metric value.
- Bowling strike-rate rankings exclude zero-wicket rows because they have no valid metric value, and the answer states that those rows were excluded. Descriptive comparisons keep the row and show N/A.
- The first suggested follow-up after a general player comparison should offer a phase-wise comparison. Team-wise comparison can follow after phase-wise comparison is product-ready.
- A team-wise comparison is exploratory and includes every opposition team with available evidence. A question naming one opposition, such as Australia, filters the comparison to that team instead.
- The exploratory team-wise view gives each compared player a separate opposition table. It does not add a third difference table or narrate every opposition row.
- Each player’s team-wise table includes only opposition teams for which that player has recorded evidence. Missing opposition rows are omitted rather than added as “No recorded data.”
- Deterministic code calculates differences between aligned opposition rows. The LLM may use those calculated values for a short summary of only the clearest high or low differences; it must not perform the arithmetic itself.
- The team-wise summary contains at most three standout differences.
- The summary uses different metrics for its highlights where possible rather than repeating the same metric three times.
- A phase-wise comparison returns powerplay, middle overs, and death overs together in one answer rather than requiring three separate questions.
- The phase-wise answer uses one combined table containing every compared player and all three phases.
- Every phase-wise comparison row includes its relevant sample size, such as balls faced for batters or legal balls bowled for bowlers.
- A descriptive comparison reports the actual statistic even for a small sample. Showing the sample size is sufficient; a low-sample warning is not required unless the answer makes a ranking, superiority, or tactical claim.
- Rate and percentage rankings default to a minimum of 60 balls: balls faced for batters and legal balls bowled for bowlers. A user-supplied minimum replaces this default.
- The response contract should distinguish at least three failure meanings: data limitation, unsupported capability, and planner uncertainty.
- Data limitation means the requested cricket fact is not available in the database.
- Unsupported capability means the data may exist, but the current semantic/query layer cannot express or execute the request safely.
- Planner uncertainty means the system cannot confidently understand the user’s intended metric, entity, or filter.
- User-facing answers should be concise and correct. Polished language is less important than correct evidence.
- User-facing output must not leak raw internal enum values.
- Sample-size and data limitations should be visible when they affect interpretation.
- Player, team, venue, phase, line, length, shot, scoring-zone, opposition, and bowling-style aliases should be normalized before query execution.
- The system should ask clarifying questions only when required anchors are missing or ambiguity is material.
- Broad tactical questions may be partially supported later, but they must clearly state what evidence was checked and what remains unchecked.
- The GitHub repository name should eventually align with the product name CricAtlas, though this is not core to the Q&A behavior.

## Testing Decisions

- The primary correctness seam is the semantic answer path: a user question should produce a normalized plan, SQL evidence, result columns, status, and response evidence.
- Tests should prioritize external behavior at the semantic service or API level rather than private helper behavior.
- Good tests should assert operation, entity, metric, grouping, filters, sort direction, status, executed SQL source, result columns, and limitation status.
- Final answer prose should be tested lightly: no raw enum leakage, no hallucinated support, and limitation language appears when needed.
- Paraphrase-group tests should be introduced for Phase 1. Each canonical intent should have multiple phrasings that must produce the same normalized plan and SQL evidence.
- Golden factual chat tests are prior art and should continue to guard broad supported/unsupported behavior.
- Semantic trace tests are prior art and should continue to guard plan shape, SQL builder selection, and result columns.
- Chat contract tests are prior art and should continue to ensure normal chat does not fall back to legacy behavior when Semantic V2 is enabled.
- Unsupported/data-limitation tests should verify that missing fielding data, unsupported external facts, mixed-role comparisons, and ambiguous prompts do not produce fabricated supported answers.
- Tactical workup tests, when introduced, should assert the selected evidence probes and resulting synthesis contract rather than only the final recommendation text.
- Comparison tests must cover the real chat flow, not only the comparison executor or semantic service.
- Suggested-follow-up tests must send the displayed suggestion with the actual preceding chat history and verify that the player, metric, and filters are preserved.
- Contextual-follow-up tests must also cover short natural replies such as “What about leg spin?”, not only replies containing explicit phrases such as “the player” or “his”.
- Chained tests must cover a failed middle turn followed by another short follow-up and verify that the last successful context is not lost.
- Clarification tests must distinguish genuinely ambiguous follow-ups from clear context replacements.
- Comparison chains must verify that short follow-ups preserve all compared players and metrics while changing only the requested filter.
- The phase-wise comparison suggestion must remain hidden until its exact chained chat flow passes end to end.
- Suggested-follow-up release tests must cover both the backend with real preceding history and the browser action that clicks the suggestion and receives the correct answer.
- Team-wise comparison tests must cover both the all-oppositions exploratory view and a directly requested single-opposition filter.
- Team-wise table tests must verify that opposition teams without player evidence are omitted.
- Team-wise summary tests must verify that every stated difference comes from deterministic comparison evidence and that the response does not narrate every opposition row.
- Team-wise summary tests must verify that no more than three differences are narrated.
- Team-wise summary tests must verify metric variety when the evidence contains meaningful differences across multiple metrics.
- Phase-wise comparison tests must verify that all three ODI phases are returned together for every compared player.
- Phase-wise comparison tests must verify the combined player-and-phase table shape.
- Phase-wise comparison tests must verify that each row includes the correct role-specific sample size.
- Descriptive comparison tests must not reject or hide a player’s actual phase value only because its sample is small.
- Ranking tests must verify the 60-ball role-specific default and verify that an explicit user threshold overrides it.
- Strike-rate tests must verify that batting questions use runs per 100 balls and bowling questions use legal balls per wicket.
- Ambiguous strike-rate tests must verify that the system asks one clear batting-or-bowling question without executing either metric first, regardless of the named player’s likely role.
- Strike-rate answer tests must verify that the full batting or bowling metric label is visible.
- Bowling strike-rate tests must cover a zero-wicket sample and verify the explicit N/A explanation.
- Bowling strike-rate ranking tests must exclude zero-wicket rows, while descriptive comparison tests must retain those rows with N/A.

## Out of Scope

- External cricket knowledge outside the ODI database.
- Web browsing or live cricket updates.
- Full predictive modeling.
- Full tactical/coach workups in the first implementation slice.
- Arbitrary LLM-generated SQL.
- Non-ODI formats.
- Major schema expansion unless required to expose facts already present in the dataset.
- Frontend redesign beyond whatever is necessary to display statuses, evidence, and limitations clearly.

## Further Notes

- The immediate product priority is reliability on many phrasings of Phase 1 database-grounded questions.
- Once single-query reliability is strong, the next product step is multi-query analyst workups for coaching and planning.
- The system should move fast by testing intent families with paraphrases rather than adding only small batches of unrelated one-off questions.
