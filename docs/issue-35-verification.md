# Issue 35: compact language extraction

Direct player statistics and player rankings supported by the canonical compiler now
request `LanguageMeaningCandidate` v1 from Gemini Flash. Its schema contains language
facts: named entities and roles, relationships, metric phrases, dimensions, expressed
filters and values, ordering, limits, sample thresholds, and ambiguity candidates.
It has no executable plan, database, presentation, or statistical-default fields.

The canonical resolver normalizes those facts and reconciles them with deterministic
language evidence. Explicit players, metrics, filters and thresholds remain authoritative.
Only `compile_canonical_meaning` constructs the migrated executable plan, which still
passes the existing plan and explicit-scope validators before database execution.
The old plan-valued candidate interface has been removed from the resolver.

Breakdown, matchup, comparison, split, trend and other families without a canonical
compiler retain their legacy planning path. This change does not claim those families
have been migrated. Regression tests retain their existing behavior and repair coverage.

Malformed or unavailable Flash output falls back to resolved deterministic meaning,
with a typed trace reason. Unresolved meaning produces uncertainty or clarification.
Pro is allowed only after a valid Flash candidate leaves unresolved or materially
ambiguous meaning, using the same compact schema and a typed call reason. Pro cannot
discard earlier constraints or settle distinct valid alternatives merely by guessing.
Clarifications use the existing chat clarification surface.

## Verification

The final production capture used the 44 direct/ranking cases selected from the
unchanged frozen 150-question benchmark. The saved Stats Desk site was not queried.

| Check | Result |
| --- | ---: |
| Direct production questions | 20/20 |
| Ranking production questions | 24/24 |
| Flash extraction calls | 44 |
| Pro calls / plan-repair calls | 0 / 0 |
| Valid extraction contracts | 43/44 |
| Correct resolved canonical meaning | 44/44 |
| Correct compiled plans | 44/44 |
| Plan validation | 44/44 |
| Database evidence and response contracts | 44/44 |
| Independent additional meaning packs | 25 packs, two phrasings each |

One Flash response reached its output-token limit. The deterministic candidate
preserved the complete ranking meaning, including its limit and sample threshold,
without another model call. Extraction-contract accuracy measures schema/finish
validity, not the model's independent semantic accuracy; canonical accuracy measures
the reconciled meaning against the frozen expectations.

Both offline rescoring and re-executing the captured model responses through the real
chat/database path produce the **identical full summary**, including stage accuracy
and model-call reasons. The offline execution blocks network access. The summary
SHA-256 is `e98232504ba793d10b4600a79b4b960b9dcb766b0b017f2bdf02d39077c61e2c`.

The 150-case issue-impact artifact substitutes the final 44 newly captured cases into
the saved #26 impact baseline and preserves all 106 non-target records verbatim.
It remains **67/150**, with **zero regressions** and identical non-target family scores:
behavior 2/20, breakdown 14/20, comparison 0/16, context 0/10, matchup 7/16,
split 0/14, trend 0/10. This is a controlled saved-response comparison, not a fresh
106-case live-model run or a claim of broad product readiness.

The full suite passes in the repository's `odi-analyst-workbench` Python environment.
The system Python environment has an older Streamlit version and reproduces two
unrelated UI-test failures on the unchanged baseline. Static checking of the three
planner/meaning modules also passes.

## Saved artifacts

All final evidence lives under `tests/evals/results/releases/issue-35/`:

- `production-targets.jsonl` and `production-targets.summary.json`: final live capture.
- `offline-replay.summary.json`: offline rescore.
- `executed-replay.jsonl` and `executed-replay.summary.json`: offline chat/database execution.
- `impact-replay.jsonl` and `impact-replay.summary.json`: full frozen benchmark impact comparison.

## Reproduce

Activate the project environment, then run:

```sh
python scripts/verify_issues.py --issue 35
python -m pytest tests -q
```

Rescore the live capture without any model access:

```sh
python scripts/odi_correctness_gate.py --replay \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --family direct --family ranking \
  --output tests/evals/results/releases/issue-35/production-targets.jsonl \
  --summary /tmp/issue35-rescore.json
```

Re-execute captured responses through the application and database offline, using a
new output file to avoid resuming an existing execution:

```sh
python -m scripts.replay_planner_capture \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --family direct --family ranking \
  --capture tests/evals/results/releases/issue-35/production-targets.jsonl \
  --output /tmp/issue35-reexecution.jsonl \
  --summary /tmp/issue35-reexecution.summary.json
```

A new live capture uses `odi_correctness_gate.py --release` with the same benchmark
and family selection and new output/summary paths. It requires the configured Gemini
credentials and network access.
