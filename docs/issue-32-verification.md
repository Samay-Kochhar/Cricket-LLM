# Issue 32: structured contextual meaning patches

Successful canonical answers now return conversation state version 1 containing
the complete versioned canonical cricket meaning. Contextual turns are interpreted
as typed add, replace, or remove operations over that meaning. They no longer
reconstruct a standalone question from prose when canonical state is available.

Patch targets cover phase, venue, year and year mode, opposition, bowling style,
batter handedness, metric, result limit, minimum sample, and the existing comparison
view. Applying a patch preserves all unmentioned family fields, including player
roles, participants, comparison metrics, split axes and values, and trend grouping.
The patched result runs through the existing direct, ranking, breakdown, matchup,
comparison, split, or trend compiler and the normal validators.

Ambiguous metric changes and attempts to turn a split axis into a row filter return
a targeted clarification. The previous versioned meaning stays in conversation
state. Complete new questions ignore stale canonical state, while old state payloads
without a canonical meaning retain the prior compatibility path.

## Verification

The issue-specific suite covers 20 patch scenarios across all seven canonical
families, plus consecutive patches, pronouns, aliases, replacement with `instead`,
removal, ambiguity, split-axis safety, model-free production planning, versioned
state persistence, and an exact suggested-follow-up chain.

| Check | Result |
| --- | ---: |
| Issue-specific tests | 86 passed |
| Full repository suite | 904 passed; 2 unrelated Streamlit environment failures |
| Captured-production context replay | 10/10 |
| Full frozen-150 replay | 137/150 |
| Frontend production build | Passed |
| New patch module static check | Passed |

The two full-suite failures are confined to the existing matchup explorer. The
local environment has Streamlit 1.37.1, below the repository's declared
`streamlit>=1.42.0`, so that environment rejects the screen's `width` argument
and does not provide `segmented_control`. No issue 32 code is reached by either
failing test.

The full frozen score and all family scores are unchanged from issue 31: behavior
7/20, breakdown 20/20, comparison 16/16, context 10/10, direct 20/20, matchup
16/16, ranking 24/24, split 14/14, and trend 10/10.

## Saved artifacts

Evidence is stored under `tests/evals/results/releases/issue-32/`:

- `production-context.jsonl` and `production-context.summary.json`
- `frozen-150-replay.jsonl` and `frozen-150-replay.summary.json`

## Reproduce

```sh
python scripts/verify_issues.py --issue 32
python -m pytest tests -q
```

Re-execute the captured production planner responses through the chat and database
path:

```sh
python -m scripts.replay_planner_capture \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --capture tests/evals/results/releases/issue-31/frozen-150-replay.jsonl \
  --output /tmp/issue32-frozen-replay.jsonl \
  --summary /tmp/issue32-frozen-replay.summary.json
```
