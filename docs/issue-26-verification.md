# Issue 26 verification

Issue 26 routes direct player metrics and player leaderboards through one canonical
cricket-meaning interface before a database plan is compiled. The interface owns
aliases, player roles, metric meaning, count-versus-rate distinctions, filters,
ranking order, limits, and sample policy. Gemini and deterministic interpretations
are candidates only; neither executes directly.

## Frozen benchmark results

| Verification view | Overall | Direct | Ranking |
| --- | ---: | ---: | ---: |
| Saved production baseline (2026-09-02) | 42/150 | 9/20 | 10/24 |
| Issue 26 deterministic full report | 69/150 | 20/20 | 24/24 |
| Issue 26 live production capture | 70/150 | 20/20 | 24/24 |
| Issue-impact captured replay | 67/150 | 20/20 | 24/24 |

The issue-impact replay substitutes the newly captured direct/ranking responses into
the saved production baseline and retains every saved non-target response. It raises
the two target families by 25 strict passes while every other family stays exactly
at its saved baseline. This separates the code change's effect from run-to-run Gemini
variation in unrelated families. The complete live run is also retained: its lower
breakdown and matchup counts are visible in the report rather than being attributed
to this deterministic slice.

The exact offline replay of the live artifact produced the same summary SHA-256 as
the live run: `e8a543244724d17300d7627ad68af45effdcda446f7c1ba2fe92f4bbdf316f1a`.

## Reproducible evidence

- `tests/evals/results/releases/issue-26/cricatlas-issue26-production-release.jsonl`
  is the complete 150-case captured-production artifact.
- `tests/evals/results/releases/issue-26/cricatlas-issue26-production-release.summary.json`
  is its live score.
- `tests/evals/results/releases/issue-26/cricatlas-issue26-production-replay.summary.json`
  is the offline replay score.
- `tests/evals/results/releases/issue-26/cricatlas-issue26-impact-replay.jsonl`
  is the saved-baseline/non-target plus new-target impact artifact.
- `tests/evals/results/releases/issue-26/cricatlas-issue26-impact-replay.summary.json`
  proves the family-level non-regression comparison.

Run the local contract with:

```bash
python scripts/verify_issues.py --issue 26
```

Replay the captured live production artifact without Gemini:

```bash
python scripts/odi_correctness_gate.py \
  --replay \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --output tests/evals/results/releases/issue-26/cricatlas-issue26-production-release.jsonl
```
