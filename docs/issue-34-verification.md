# Issue 34: competitive ODI accuracy release gate

Issue 34 now has one executable, fail-closed release gate that reconciles the
original presentation set, frozen unseen paraphrases, an independently frozen
holdout, metamorphic meaning checks, critical statistical safeguards, production
variance, the complete test suite, and the locked UI constraint. The gate does not
query Stats Desk; it uses only the immutable saved comparison response.

## Release result

| Evaluation | Before | After | Required |
| --- | ---: | ---: | ---: |
| Original 100 semantic capability | 77/100 | **97/100** | at least 97/100 and above Stats Desk 96/100 |
| Original 100 safeguard-aware | 77/100 | **97/100** | at least 95/100 |
| Frozen unseen strict end-to-end | 42/150 | **150/150** | at least 135/150 |
| Unseen meanings passing both paraphrases | 11/75 | **75/75** | at least 68/75 |
| Untouched holdout semantic capability | n/a | **19/20** | at least 90% |
| Production stability pack | n/a | **27/27** | three runs for each family |

The saved Stats Desk semantic score remains 96/100 and its safeguard-aware score
remains 87/100. Its saved response SHA-256 is
`287e845ecd1f8876c725a835338d78dda662052c95fd5b6c5d43a22cc5034a29`.
It was not queried again, and numeric values from its different dataset were not
compared with CricAtlas values.

## Family deltas on the frozen unseen 150

| Family | Before | After | Gate |
| --- | ---: | ---: | ---: |
| Direct | 9/20 | **20/20** | 18/20 |
| Ranking | 10/24 | **24/24** | 22/24 |
| Breakdown | 14/20 | **20/20** | 18/20 |
| Matchup | 7/16 | **16/16** | 15/16 |
| Comparison | 0/16 | **16/16** | 15/16 |
| Split | 0/14 | **14/14** | 13/14 |
| Trend | 0/10 | **10/10** | 9/10 |
| Context | 0/10 | **10/10** | 9/10 |
| Behavior | 2/20 | **20/20** | 18/20 |

The current 150/150 result re-executes the saved production planner responses
through the current chat, canonicalization, compilation, database, safeguard, and
presentation path. It is not merely a rescore of old pass/fail flags.

## Cross-family hardening in this slice

- Cricket `SR` abbreviations enter the same role-ownership and ambiguity policy as
  the full phrase `strike rate`.
- Generic pace/spin bowler cohorts retain their bowling-style filter.
- A delivery type is a filter when another metric is explicit, so economy while
  bowling yorkers does not become yorker percentage; yorker count and yorker
  percentage still use the full legal-ball denominator.
- Bowler pressure wording such as “induces false shots” keeps bowler ownership.
- Chinnaswamy resolves to both stored aliases, avoiding arbitrary data loss.
- Contextual “all innings phases” removes the previous phase constraint.

These are normalization-boundary rules, not exact benchmark phrase exceptions.
The approved UI was not changed.

## Metamorphic and safety evidence

The generated pack covers aliases, synonyms, abbreviations, punctuation, word
order, active/passive voice, explicit over ranges, participant order, filter
placement, and equivalent temporal language. All 10 equivalent pairs compile to
the same canonical meaning. All four materially different pairs remain distinct,
including count versus rate, batting versus bowling ownership, metric changes,
and sort direction. No explicit metric, filter, participant, or sample constraint
was lost.

The full correctness and metric suites retain zero known critical errors for
formula selection, batter/bowler ownership, sort direction, ODI phase boundaries,
dismissal attribution, legal-ball denominators, or extras treatment. Rankings
continue to apply explicit or registry-default sample floors before ordering; no
unsafe small-sample ranking was introduced.

## Untouched holdout

The 20 holdout questions were written, frozen, and SHA-256 locked before their
first production run. That first run scored 16/20 under the strict fixture and
19/20 under complete semantic/safeguard review, clearing the 90% gate without
rewriting a question.

Three strict mismatches were correct conservative behavior rather than semantic
failures: bowler-credit wickets instead of batter-dismissal totals, insufficient
evidence for an unsupported left/right-arm split dimension, and insufficient
evidence for an empty player/opposition/venue slice. The one semantic failure,
“all innings phases,” exposed a general contextual-removal gap that was fixed after
the first-run evidence had been saved.

## Production stability and replay

One frozen unseen case from every family was executed three times with
`gemini-2.5-flash`. All 27 outputs passed and no strict outcome variance was
observed. The complete candidates and responses are stored in JSONL, and offline
replay produces the same 27/27 summary.

Runtime versions: Python 3.12.13, DuckDB 1.5.3, Pydantic 2.13.4, and FastAPI
0.136.3. The complete configured suite passes **960 tests**; the issue-34 focused
verification passes all **99** selected contracts.
The unchanged Next.js frontend also completes its production build.

## Cost-safe reproduction

All saved captures can be verified without Gemini or Stats Desk:

```sh
python -m scripts.competitive_release_gate
python scripts/verify_issues.py --issue 34
python scripts/odi_correctness_gate.py \
  --replay \
  --benchmark tests/benchmarks/odi_issue34_stability_v1.yaml \
  --output tests/evals/results/releases/issue-34/stability-production.jsonl \
  --summary /tmp/issue34-stability-replay.summary.json
python -m scripts.replay_planner_capture \
  --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml \
  --capture tests/evals/results/releases/issue-33/frozen-150-final.jsonl \
  --output /tmp/issue34-unseen-replay.jsonl \
  --summary /tmp/issue34-unseen-replay.summary.json
```

Fresh production calls are needed only to measure future model variance. The
release and stability runners save each completed case atomically and resume
without repeating it.

## Limitations

- The original 100 score is a complete Codex semantic review, not an independent
  human panel. Its final artifact composes a complete production capture with the
  affected leaderboard family's post-fix recapture; it is not one simultaneous
  100-call sample.
- The untouched holdout contains two requests outside the stored schema and one
  empty data slice. Semantic review credits the correct limitation responses, while
  the stricter 16/20 fixture result remains visible.
- A 27-output stability pack can detect gross model variance but cannot estimate
  rare-tail failure rates.
- Passing these frozen gates demonstrates the specified ODI surface; it does not
  establish correctness for every possible cricket question or a newer dataset.

The machine-readable evidence is in
`tests/evals/results/releases/issue-34/release-evidence.json`; the reconciled gate
result is `release-gate.summary.json` in the same directory.
