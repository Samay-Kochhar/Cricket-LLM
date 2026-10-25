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

## Local Compare / compact filter follow-up (2026-10-23)

Compare context controls now occupy two native Streamlit column rows: phase,
venue and metric; year toggle and both inclusive endpoints. Context controls and
Compare share a form so pending edits are submitted together. Player selection
and mode switching remain outside the form, retaining the disabled submit rule.
The UI explains how to select a single year and when draft context applies.
Venue's existing form now uses two rows too: sample unit, minimum, metric and
phase; year toggle and endpoints. Widget keys, defaults, apply/reset behavior,
mode handling, and output order are unchanged. Native columns retain Streamlit's
responsive stacking; no fixed-width CSS was added. Player Explorer already uses
a two-column selector row; Matchups already uses two player columns and three
context columns, so neither needed edits.

Compare phase labels are presentation-only. `first6` remains the intentionally
supported opening-six-over analysis slice (`over <= 6`), which is a subset of
ODI powerplay (`over <= 10`), not a claim that ODI powerplay lasts six overs.
Middle remains `over > 10 AND over <= 40`; death remains `over > 40`. The option
IDs, SQL predicates, API and metric contracts are unchanged. Help text gives the
recorded-over boundaries explicitly.

### Resubmission diagnosis and limits

The reported general failure has **not been conclusively reproduced**. Before
and after the change, AppTest with the real database correctly updates repeated
valid year submissions. Reversed endpoints reproduce a validation error and
recover after correction. No backend cache or aggregation failure was found.
A possible browser issue is a pending number-input edit triggering its own rerun
when Compare is clicked; the form removes independent context-control reruns.
This is a robustness change, not a proven root-cause resolution. AppTest sets
widget values directly and cannot prove that browser focus/blur race is fixed.

A temporary server using the original committed Compare module was also tested
through preview DOM interactions. An uncommitted typed year can remain visible
while the active-filter caption retains its previous year; focusing the button
and submitting applies it. That demonstrates the distinction between draft and
applied state, but does not conclusively reproduce the user's physical-click
failure. The temporary server was stopped; the user's port 8501 server was left
running.

### Validation

- Streamlit 1.61.1 (the running app environment): 48 focused tests pass across
  Compare/Venue mode controls, venue filtering, player charts, matchups, and
  shared explorer backend contracts.
- Streamlit 1.66.1 (the previous CI-compatible environment): same 48 tests pass.
- New repeated-submit tests cover both modes, single years, inclusive ranges,
  empty years, identical resubmits, table/chart values, reversed-range recovery,
  and disabling the year filter. Existing context/mode/apply/reset tests pass.
- Real-database AppTest, 2023 → 2022 → 2024 → 2023: Kohli/Sharma runs are
  [1377, 1255] → [302, 249] → [44, 149] → [1377, 1255]. Bumrah/Starc legal
  balls are [773, 731] → [284, 410] → [0, 272] → [773, 731].
- Live preview DOM confirms Compare phase/venue/metric inputs share a desktop
  row; live form submissions show the 2023 then 2022 applied captions and changed
  chart data. Snapshot calls repeatedly timed out, and the resize setting did
  not change the measured viewport; screenshot and narrow-width visual QA remain
  unverified. Chrome fallback returned `Debugger unattached`.
- `git diff --check` passes. Original unrelated dirty files were not edited or
  staged. No commit, push, merge or PR content update was performed.

Manual check on http://127.0.0.1:8501 (rerun/reload if file-change notice appears):
1. Open Compare, select Virat Kohli and Rohit Sharma, and tick the year filter.
2. Set both endpoints to 2023 and click Compare players. Expect runs 1377 / 1255.
3. Set both endpoints to 2022 and click Compare players once. Expect the active
   caption to say 2022–2022 and runs 302 / 249. Repeat with 2024 (44 / 149).
4. Switch to Bowling, choose Jasprit Bumrah and Mitchell Starc, repeat years
   2023 and 2022. Expect legal balls 773 / 731 and 284 / 410 respectively.
5. Try From 2024 / Through 2023: expect validation, then correct both to 2024
   and submit again. Untick the year filter and submit to restore all years.
6. In Venue Explorer, explore a venue, change the sample/metric/phase/year
   controls, Apply, switch modes, and Reset. Check compact rows at desktop width
   and stacking with a narrow browser window.

## Follow-up: remove six-over selector and apply edited Compare years (2026-10-25)

This supersedes the six-over presentation and year-checkbox behavior described
above. The optional six-over analysis slice was inherited from the shared phase
catalog. It has been removed from the Streamlit Compare and Venue selectors at
the user's request. The backend phase contract is unchanged.

A regression test now reproduces a concrete ignored-edit flow: compare all years,
enter a year, then submit again without separately enabling the year checkbox.
Before the fix, `test_compare_year_edits_apply_without_separate_opt_in` failed
with `assert None == 2022`; both the browser and applied filter caption continued
to show all years. This does not establish that every reported repeat-submit
failure has the same cause. Browser submissions with the checkbox enabled did
update from 2022 to 2023 before the fix.

Compare no longer has a separate year opt-in. Both year fields start blank and
are applied directly on submission. Both blank means all years; one filled means
that single year; both filled means an inclusive range. Clearing both restores
all years. Reversed endpoints still show the existing validation error and a
corrected submission recovers.

Focused Compare/Venue tests: 15 passed on both the local Streamlit environment
and Streamlit 1.66.1. Covers repeated submissions, table/chart data, empty years,
reversed-range recovery, single endpoints, all-years restoration, and absence
of the six-over option.

Live browser verification found that the existing server still served the older
Compare module after source edits. Restarting the port-8501 server loaded the
new code. A real Chrome/Playwright run then passed consecutive submissions for
Kohli/Sharma: 2023 (1377/1255 runs), 2022 (302/249), and 2023 again (1377/1255).
It asserted the active-year caption and actual Plotly values after each submit,
and confirmed the six-over choice is absent. The temporary browser harness was
removed after verification. The server remains running with the updated code.

## Venue year submission and collapsible filters (2026-10-25)

Venue reproduced the same ignored-year problem in both modes: entering 2022
without the separate opt-in left the applied year as null. It now uses the same
blank/single-year/inclusive-range behavior as Compare. Year widgets remain
clearable after applying a range. Every successful apply rebuilds the form with
its applied defaults so the next edit cannot inherit mismatched defaults.
Empty leaderboards are saved as the applied result and remain empty on later
reruns; the previous successful result is no longer resurrected.

The horizontal controls and Apply/Reset buttons live in a collapsible Filter
batters / Filter bowlers panel, initially collapsed. Applied-filter captions,
chart, and table stay outside it.

Validation: 17 focused tests passed in both local and Streamlit 1.66.1 runtimes.
Tests cover both Venue modes, consecutive year edits, clearing to all years,
a single endpoint, empty results across reruns, and the existing reset and
validation cases. Real Chrome confirmed Delhi batting chart values change
between 2023 and 2022, return exactly on selecting 2023 again, clear to all years,
and remain visible with the filter panel collapsed. The server was restarted
with the updated source; the temporary browser harness was removed.

## Venue filters before the first exploration (2026-10-25)

The collapsible filter panel now sits between venue selection and Explore venue,
including before any result exists. A single form contains the filter controls,
Apply/Reset and Explore venue. Explore submits the current draft filters on both
the first and later runs, rather than discarding them and loading defaults.
The panel remains available for edits above the result.

Validation: 19 focused tests pass in the local and Streamlit 1.66.1 environments,
including initial filtered exploration and subsequent Explore submissions in both
modes. Live preview confirmed the panel precedes Explore before any analysis;
Delhi's first Explore applied 2023 directly, and the next Explore applied 2022.
Server restarted with current source and health check passes.

## Numeric table sorting (2026-10-25)

Venue and Compare formatted rate columns into strings before passing them to
Streamlit. Sorting their column headers therefore used text ordering, putting
101.00 before 26.00. This affected batting/bowling averages, strike rates,
economy, and percentages in both modes. Five regression cases reproduced the
string column types before the fix, including the exact reported values.

Both surfaces now use `streamlit_explorer_tables.render_numeric_table`: raw
numeric values and true nulls are retained, numeric dtypes are explicit (also
for entirely missing columns), and NumberColumn handles two-decimal display.
The regression module is included in CI's focused selection. Initial backend
ranking and metric definitions are unchanged.

Audit: Player tables pass repository numeric rows directly; Matchups passes the
numeric service response directly; chat tables likewise pass their response
rows directly. Their metric-card/hover formatting does not enter sortable table
data. Next.js's shared sortable result table compares numeric values numerically;
its Venue/Compare tables do not implement column-header sorting. No matching
conversion bug was found in those other surfaces.

Validation: 24 focused tests passed with local Streamlit and 1.66.1; 14 existing
Player/Matchup tests passed locally. The regression checks both Venue/Compare
modes and exact reported averages ascending/descending, with missing values
remaining null. Live preview clicked the actual Delhi batting-average column
header and read the grid's accessible rows: ascending 39.75 … 93.50, 118.00,
and descending 118.00, 93.50 … 39.75. The server was restarted with the fix.

Release check: all 85 tests in the updated Python CI selection passed with
Streamlit 1.66.1 in an isolated export of the staged files. Unrelated working
changes were excluded from the export and commit.
