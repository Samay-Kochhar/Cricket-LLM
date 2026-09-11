# Issue 27: canonical breakdown meanings

Breakdowns now use `CanonicalMeaningResolver` and a family-specific compiler for
line, length, bowling style, shot type, field zone, phase, batter hand, and year.
The axis is resolved independently of metric ownership and player/filter resolution.
The compiler preserves sorting and sample policy and returns every eligible
category unless the question explicitly limits the result.

The independent test pack covers 20 meanings with three transformations each,
plus the frozen 20-question family and targeted contracts for model disagreement,
explicit roles, abbreviated names, exact style subtypes, delivery filters, category
limits, count/rate distinctions, and unavailable players. Aggregate SQL now respects
an absent category limit instead of silently truncating to ten rows.

## Frozen release evidence

The full 150-question replay executes captured model responses through the actual
chat/database path, with web grounding and narrative generation disabled. Its
inputs combine the issue 26 full production capture, issue 35's newer direct/ranking
capture, and issue 27's initial live breakdown capture. The saved raw responses are
replayed through the corrected code; this is not a mocked plan or development
fallback run. The initial issue 27 capture scored 15/20 and exposed reconciliation
failures that the implementation fixes; its replay scores 20/20.

| Family | Strict passes |
| --- | ---: |
| Direct | 20/20 |
| Ranking | 24/24 |
| Breakdown | 20/20 |
| Matchup | 8/16 |
| Comparison | 0/16 |
| Split | 5/14 |
| Trend | 8/10 |
| Context | 6/10 |
| Behavior | 5/20 |
| **Total** | **96/150** |

There are no strict-pass regressions against the saved issue 26 full production
capture. This is a breakdown-family completion, not an overall product accuracy
claim: 54 frozen cases in other families still fail. The complete failure list and
stage-level evidence are retained in `frozen-150-replay.summary.json` and its JSONL.

## Original presentation family

All 28 original breakdown questions were run against the live production planner
and local ODI database. The stored semantic review passes **26/28**, retaining the
existing family threshold. Automatic top-row comparison passes **24/28**. It treats
`RHB` versus the displayed `right-hand batter` as different; the semantic review
recognizes their equivalence. All breakdowns return the complete category set,
so the old exact-plan expectation of a ten-row limit intentionally differs.

Two unresolved old expectation differences remain conservative semantic failures:

- The Klaasen line question does not state a spin filter, although its stored
  answer key and prior review require one. The answer uses the explicit question's
  unrestricted scope rather than inventing a filter.
- The Warner question asks for the most dot balls, while its saved answer key uses
  dot-ball percentage. The answer reports a count; the mismatch is disclosed and
  the count is not relabelled as a percentage.

The review compares all visible responses and their requested numeric fields with
the stored database answer keys. Rounded percentages and public category labels
are equivalent. No new incorrect numeric claim was identified. The review is by
Codex, not an independent human evaluation.

## Compatibility changes

Dismissal breakdown tests now expect batter dismissals rather than bowler-credit
wickets: these differ for non-bowler dismissals. “Who dismissed this batter” remains
on the matchup path. Model-repair tests for migrated breakdowns now expect one
language extraction with canonical fallback instead of a second executable-plan
repair. Their player catalog fixtures include the players they ask about.

The replay harness suppresses uncaptured web grounding, just as it already
suppresses narrative generation. It still rejects an uncaptured planner call or
network access; no model response is invented during replay.

## Reproduction

Use the `odi-analyst-workbench` environment (the base environment's Streamlit 1.37
is older than the project's requirement and fails the existing matchup UI tests).

```sh
python scripts/verify_issues.py --issue 27
python -m pytest tests -q
python -m mypy --explicit-package-bases \
  backend/app/cricket_analytics/canonical_meaning.py \
  backend/app/cricket_analytics/query_builders/aggregate_builder.py \
  --follow-imports=silent

python -m scripts.replay_planner_capture \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --family breakdown \
  --capture tests/evals/results/releases/issue-27/production-breakdowns.jsonl \
  --output /tmp/issue27-breakdown-reexecution.jsonl \
  --summary /tmp/issue27-breakdown-reexecution.summary.json
```

The release artifacts are in `tests/evals/results/releases/issue-27/`:
`production-breakdowns` retains the initial live failures; `breakdown-replay` and
`frozen-150-replay` contain executed replay evidence; `presentation-final` contains
all 28 live presentation answers; `presentation-review.yaml` and
`presentation-semantic.summary.json` disclose the review decisions.

Final verification: **656 tests passed** in the configured environment;
`verify_issues.py --issue 27` passed all **82** selected contracts. Focused type
checking passed for canonical meaning and aggregate SQL compilation.

To reconstruct the complete capture input without modifying any frozen artifact:

```sh
python - <<'PY'
import json
from pathlib import Path
root = Path('tests/evals/results/releases')
def records(name):
    return [json.loads(line) for line in (root / name).read_text().splitlines()]
base = records('issue-26/cricatlas-issue26-production-release.jsonl')
replacement = {}
for name in ('issue-35/production-targets.jsonl', 'issue-27/production-breakdowns.jsonl'):
    replacement.update({row['case_id']: row for row in records(name)})
Path('/tmp/issue27-capture.jsonl').write_text(''.join(
    json.dumps(replacement.get(row['case_id'], row)) + '\n' for row in base
))
PY
python -m scripts.replay_planner_capture \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --capture /tmp/issue27-capture.jsonl \
  --output /tmp/issue27-full-reexecution.jsonl \
  --summary /tmp/issue27-full-reexecution.summary.json
```

A fresh live production evaluation after the fixes also passed **20/20** breakdown
questions, with no failures. Its complete responses, model attempts, SQL evidence,
and score are saved in `production-final.jsonl` and `production-final.summary.json`.
