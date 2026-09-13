# Issue 31: canonical annual trend meaning

Annual trend questions now resolve to a dedicated canonical meaning before plan
execution. The meaning keeps the named player and role, requested metric, year
scope and mode, phase, venue, opposition, bowling style, and per-year sample
policy. Its compiler always groups by year, sorts years ascending, and leaves the
result untruncated.

Temporal wording is normalized independently of those cricket constraints.
Annual, annually, yearly, by year, each year, season by season, year over year,
season to season, year-wise, trend, and change-from-year forms converge on the
same annual meaning. `from 2018 onward` now has the same inclusive year-scope
meaning as `since 2018`.

The canonical compiler remains authoritative when a compact model extraction
mislabels the family, metric, ordering, or limit. Ambiguous unqualified strike
rate for a known bowler continues to request clarification.

## Verification

The independent meaning pack exercises more than 20 combinations across temporal
synonyms, tense changes, aliases, year-scope placement, batting and bowling
metrics, and phase, venue, opposition, and bowling-style filters. It invokes the
production planner configuration with a captured compact-language response rather
than the development fallback.

The full frozen-150 captured-production replay improved from **135/150** to
**137/150**. Trend improved from **8/10** to **10/10**. Every other family score
was unchanged: behavior 7/20, breakdown 20/20, comparison 16/16, context 10/10,
direct 20/20, matchup 16/16, ranking 24/24, and split 14/14.

The issue-specific suite passes 188 tests. The complete repository suite passes
881 tests. Static checking of the new trend module passes.

A fresh live Gemini capture could not be produced because the signed-in Codex
account reached its usage limit. The frozen replay still executes all 150 saved
production responses through the real chat, planner, database, and response path.

## Saved artifacts

The full replay and summary are under
`tests/evals/results/releases/issue-31/`:

- `frozen-150-replay.jsonl`
- `frozen-150-replay.summary.json`

## Reproduce

```sh
python scripts/verify_issues.py --issue 31
python -m pytest tests -q
```

Re-execute the frozen captured-production responses:

```sh
python -m scripts.replay_planner_capture \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --capture tests/evals/results/releases/issue-30/frozen-150-replay.jsonl \
  --output /tmp/issue31-frozen-replay.jsonl \
  --summary /tmp/issue31-frozen-replay.summary.json
```
