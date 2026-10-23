# Compare bowling and venue batting (#55, #57)

Built on merged #60 (`2a0be96`). This patch also supplies the detailed filtered
batting comparison required by the still-open prerequisite #54.

Compare now offers Batting / Bowling modes. Both players receive the same
validated phase, paired inclusive years and canonical venue context. Its chart
uses the selected metric, exposes higher/lower preference, retains unavailable
rates as null, flags samples below 24 balls and assigns no overall winner.
Empty contexts retain both players with zero counts and unavailable rates.

Venue Explorer adds batting mode to the existing bowling view. Aliases combine
under the canonical identity before phase/year filtering, aggregation, sample
eligibility, null-metric exclusion and top N. The chart stays above the expanded
table. Batting uses 24 balls faced by default; distinct matches and an explicit
zero minimum are supported. Mode switches retain the applied context and minimum
while selecting valid metric/sample defaults. Reset retains the active mode.
Both API and Streamlit use the same service contracts; Next.js reads those APIs.
See `metric-catalog.md` for formulas, denominators, direction and tie policies.

Existing styling, player and venue controls, table/chart placement, and workbench
navigation are preserved. Changes to the stylesheet are scoped to the new mode
selectors. The five new/existing data-independent explorer test modules now run
in CI, alongside the existing checks.

## Validation

Checks use an isolated export of the committed base with only this patch copied
in. Local ignored ODI CSV/DuckDB inputs are linked for data-dependent tests.
Unrelated chat ranking work and original untracked tests are excluded. All 15
original modified/untracked files were checked against their starting SHA-256
hashes and remain unchanged.

- Focused backend/API and Streamlit checks: 60 passed (3 dependency warnings).
- Real-network Playwright integration: 3 passed. Includes mode switches in both
  explorers, shared contexts, chart metric values, samples, reset, chart/table
  order, alias links, and the existing bowling leaderboard regression test.
- Next.js production build and application TypeScript check: passed.
- Real-data visual checks: Next.js bowling comparison and venue batting;
  Streamlit bowling comparison and venue batting, including the detailed table
  and chart placement. A radio control initially delayed its selection until
  the API responded; browser tests caught it and the control now responds
  immediately, reverting to the applied mode if the request fails.
- Full isolated Python suite: 1,610 passed, 3 dependency warnings, in 646.82 seconds.

Full standalone TypeScript checking also includes the existing E2E fixture and
reports its pre-existing null-assignment inference error in unchanged
`frontend/e2e/explorer.spec.ts:232`. The application check and production build
pass. Preview navigation worked, but two snapshot attempts failed with
`Preview automation snapshot timed out after 15000ms.` Visual checks used the
repository's Playwright setup with installed Chrome. Python checks use the
compatible temporary Streamlit 1.55 environment.


## CI follow-up: Streamlit 1.66.1

CI resolved the floating Streamlit dependency to 1.66.1, while the initial local
suite used 1.55. A minimal form probe reproduced the difference: calling
`AppTest.run()` after each unsubmitted form edit discards those edits in 1.66.1;
batching edits and running only on submission retains them. Three venue tests
were exercising the former pattern, which is not how browser forms submit.
The tests now batch edits before clicking Apply. Application code, assertions
and dependencies are unchanged. Running against the version resolved by CI
would have caught the mismatch before the first push.

- Exact CI test selection in the isolated export with Streamlit 1.66.1: 70 passed.
- Focused explorer selection with Streamlit 1.55: 60 passed.
- The original failing three tests pass in both versions; no assertions were removed.
