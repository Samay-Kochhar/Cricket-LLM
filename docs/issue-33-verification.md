# Issue 33: post-interpretation response policy

One policy now separates material ambiguity, unsupported capabilities, missing
fields, insufficient qualifying evidence, and planner uncertainty after canonical
meaning interpretation. It never changes a resolved metric or operation.

Standalone `Bumrah's SR` remains ambiguous because both batting and bowling facts
exist. Explicit roles and the versioned role from conversation context resolve the
same wording. Vague metrics, mixed-role comparisons, and ambiguous surnames return
targeted choices. Weather, salary, prediction, and unsupported team requests return
`unsupported_capability`; fielding and captaincy requests return `data_limitation`.

Descriptive questions continue to display observed values and sample sizes without
a ranking threshold. Rankings preserve explicit thresholds or use the metric
registry default, filter non-qualifiers in SQL, disclose the threshold, and return
insufficient evidence when no row qualifies.

## Verification

| Check | Result |
| --- | ---: |
| Policy scenarios | 24 classifications plus contextual and safeguard cases |
| Frozen behavior family | 20/20 |
| Full frozen-150 replay | 150/150 |
| Versioned ODI correctness gate | Passed |
| Full repository suite | 940 passed; 2 unrelated Streamlit environment failures |

The two remaining full-suite failures are confined to the existing matchup
explorer. This local environment has Streamlit 1.37.1, below the repository's
declared `streamlit>=1.42.0`, so it rejects UI APIs used by that screen. No issue
33 policy code is reached by either test.

The saved Stats Desk comparison remains offline-only. Its retained evidence shows
unsafe conclusions involving 2, 13, 19, 20, and 32-ball samples. CricAtlas does not
query that site during verification and continues to enforce its explicit or
documented default thresholds before ranking.

## Saved artifacts

Evidence is stored under `tests/evals/results/releases/issue-33/`:

- `production-behavior-replay.jsonl` and its summary: 20/20
- `frozen-150-final.jsonl` and its summary: 150/150

Both artifacts re-execute the saved production planner capture through the current
chat, policy, compiler, database, and presentation path without network access.

## Reproduce

```sh
python scripts/verify_issues.py --issue 33
python -m scripts.replay_planner_capture \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --capture tests/evals/results/releases/issue-31/frozen-150-replay.jsonl \
  --output /tmp/issue33-replay.jsonl \
  --summary /tmp/issue33-replay.summary.json
```
