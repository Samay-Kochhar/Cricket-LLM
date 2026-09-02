# CricAtlas ODI accuracy evaluation — 2 September 2026

## Bottom line

CricAtlas is not yet at Stats Desk's question-coverage level. On the original 100-question presentation set, human semantic review scores CricAtlas at 77/100 and the saved one-time Stats Desk run at 96/100. Applying CricAtlas-style sample-size safeguards reduces the Stats Desk result to 87/100.

The new frozen unseen-paraphrase gate is substantially harder. CricAtlas passes 42/150 questions under its strict production contract. Only 11 of 75 underlying meanings pass both unseen phrasings; 20 pass one phrasing; 44 pass neither. This shows that the remaining problem is not data freshness or format coverage. It is reliable interpretation and routing across different wording.

## Results

| Evaluation | CricAtlas | Stats Desk | Meaning |
| --- | ---: | ---: | --- |
| Original presentation 100 — semantic capability | 77/100 | 96/100 | Human review of whether the requested analysis was answered |
| Original presentation 100 — safeguard-aware | 77/100 | 87/100 | Also penalizes unsafe small-sample claims |
| New unseen production paraphrases | 42/150 | Not run | Strict end-to-end contract on questions neither product was tuned against |

Stats Desk was queried once for the original 100 only. Its complete saved responses are retained in `tests/evals/results/aryaman_stats_desk_presentation_100.jsonl`; the external site must not be queried again for this comparison.

## Original 100: current CricAtlas capability

| Family | Correct | Total |
| --- | ---: | ---: |
| Direct metric | 19 | 19 |
| Leaderboard | 23 | 26 |
| Breakdown | 26 | 28 |
| Matchup | 8 | 8 |
| Player comparison | 0 | 10 |
| Split comparison | 1 | 9 |

The current version reliably handles direct metrics, matchups, most leaderboards, and most breakdowns. It still fails most player comparisons and split comparisons in live production planning. The original exact-plan score from the presentation cannot be compared directly with this semantic score because the normalized-plan schema changed; raw exact equality now penalizes harmless schema differences.

## New unseen 150: strict production result

| Family | Correct | Total |
| --- | ---: | ---: |
| Direct | 9 | 20 |
| Ranking | 10 | 24 |
| Breakdown | 14 | 20 |
| Matchup | 7 | 16 |
| Comparison | 0 | 16 |
| Split | 0 | 14 |
| Trend | 0 | 10 |
| Multi-turn context | 0 | 10 |
| Safe behavior | 2 | 20 |

This is a strict engineering gate, not a claim that every failed visible answer is useless. A small number of failures are normalization mismatches such as `LHB` versus “left-hand batter,” a named phase versus an equivalent over range, or an explicit-sample flag. Most failures are genuine, however: unsupported planner outcomes, unnecessary clarification, lost filters, wrong metrics, missing comparisons, missing trends, broken follow-up context, and incorrect failure classifications.

## Highest-priority improvement order

1. Make production comparison and split routes deterministic after Gemini identifies the intent. These families currently score 0/30 on the unseen set.
2. Add deterministic year-trend routing and preserve phase/year filters. Trends currently score 0/10.
3. Repair conversation-state carry-over for follow-up filters. Context currently scores 0/10.
4. Normalize aliases before validation: abbreviated player names, handedness, phase wording, bowling style, venue aliases, and explicit over ranges.
5. Separate ambiguity detection from planner failure. Clear questions should not ask for clarification, while genuinely ambiguous questions should.
6. Classify unsupported and missing-data requests deterministically so predictions, weather, salaries, catches, and captaincy receive the correct safe response.
7. Rerun this exact frozen benchmark after each vertical improvement; do not rewrite the questions to fit the implementation.

## Reproducibility and evidence

- Original question set: `tests/evals/dl4nlp_cricket_analyst_supported_100.yaml`
- Current CricAtlas original-100 responses: `tests/evals/results/cricatlas_presentation_100_current.jsonl`
- Current CricAtlas human review: `tests/evals/results/cricatlas_presentation_100_review.yaml`
- Saved Stats Desk responses: `tests/evals/results/aryaman_stats_desk_presentation_100.jsonl`
- Saved Stats Desk human review: `tests/evals/results/aryaman_stats_desk_presentation_100_review.yaml`
- Frozen unseen question set: `tests/benchmarks/odi_unseen_paraphrases_v1.yaml`
- Unseen per-question pass/fail results: `tests/evals/results/cricatlas_odi_unseen_150.jsonl`
- Unseen compact summary and exact failure reasons: `tests/evals/results/cricatlas_odi_unseen_150.summary.json`

The live gate writes every completed case immediately and resumes from its JSONL file. This prevents API cost and evidence loss if a long run is interrupted.

## Production accuracy release gate

The frozen unseen baseline remains **42/150 strict passes**. Do not edit
`tests/benchmarks/odi_unseen_paraphrases_v1.yaml` or either original 100-question
input to improve a score. Release artifacts use schema version 1 and summaries
use scoring version 1, so future scoring changes create a new scoring version
without rewriting questions or captured responses.

Run a new production release from the repository root with Gemini configured:

```bash
python scripts/odi_correctness_gate.py \
  --release \
  --fresh \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --output tests/evals/results/releases/cricatlas_odi_unseen_release.jsonl \
  --summary tests/evals/results/releases/cricatlas_odi_unseen_release.summary.json
```

If the run is interrupted, repeat the command without `--fresh`. Completed case
IDs are loaded from the artifact and their production model calls are not
repeated. Each newly completed question is fsynced into a complete temporary
snapshot and atomically replaces the previous artifact.

The release aborts without saving the current case when every production-model
attempt fails at the transport or provider layer (for example `http_429`). This
keeps quota, billing, model-access, and network failures out of product accuracy
and leaves the case eligible for a later resume.

Rescore the saved release without Gemini, a running application server, or
Stats Desk:

```bash
python scripts/odi_correctness_gate.py \
  --replay \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --output tests/evals/results/releases/cricatlas_odi_unseen_release.jsonl \
  --summary tests/evals/results/releases/cricatlas_odi_unseen_release.summary.json
```

To report regressions and improvements, add
`--previous path/to/previous-release.jsonl` to either command. The summary
reconciles strict, semantic-capability, safeguard-aware, family, paraphrase-pair,
and planner-overlap totals before it is written. Failed cases record the first
failing stage from the fixed stage vocabulary: meaning extraction,
canonicalization, compilation, validation, execution, result validation,
conversation-state application, or response policy.

The release artifact recursively redacts credentials, authorization values,
cookies, passwords, secrets, and tokens. The saved one-time Stats Desk responses
remain comparison-only inputs; neither the production release nor offline replay
queries Stats Desk.
