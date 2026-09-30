# Issue 47 release report: eight-question capability version

Stable version: `odi-stable-2026-09-30` (git tag), code revision recorded in
`tests/evals/regression/golden-answers.json`.

This report covers the release of the eight priority capabilities (#38–#44),
the browser and Workbench routing slices (#45, #46), and the release-regression
test list that replaces repeated paid evaluations. The approved UI is
unchanged by this issue.

## Outcome

| Check | Result |
| --- | --- |
| Independent read-only reference queries | 9/9 (8 priority facts + stored-over convention) |
| Priority-8, latest fresh production run (d6b5f08) | 7/8 recorded; 8/8 when its saved extraction is replayed at the stable version |
| Priority-8, every recorded extraction replayed at the stable version | 8/8 in all four corpora |
| Frozen 150, one fresh production run (d11f438) | 134/150 recorded (14 fail-safe blocks + 2 intended changes) |
| Frozen 150, every recorded extraction replayed at the stable version | 148/150 in both corpora (only the 2 intended changes) |
| Golden-answer agreement of all six recorded corpora | 474/474 case replays match |
| Offline extraction-variant stress (see below) | see "Release-regression check" |
| Backend test suite | 1,372 passed |
| Browser, real backend (Playwright `integration`) | 17/17 (Chat, Matchups, Workbench) |
| Browser, mocked UI (Playwright `mocked`) | 13/13 (reported separately) |

The written criterion "the frozen 150 passes in one fresh production run" is
**not** met as literally stated: the only fresh 150 run scored 134/150. The
user decided not to repeat paid 150 runs after each fix. The release is
instead gated on the offline test list below, which replays every recorded
production extraction (including all 150 from that fresh run) against stored
golden answers, and on generated extraction variants. No wrong answer was
recorded in any fresh run: every failure was a fail-safe block.

## The eight priority questions

Independent SQL in `scripts/verify_release_references.py`, output in
`tests/evals/results/releases/issue-47/reference-checks.json` (database
SHA-256 `80a3f500a7dfd1eedd7ca5fdca51febf190607217e3d8e2ff07ace2d026d2a08`).

| Question | Independent result | Displayed |
| --- | --- | --- |
| Kohli sixes | 154 | 154 |
| 2019 World Cup final toss | New Zealand (stored winner `-`, tied final) | New Zealand won the toss |
| Kohli caught vs bowled | 170 / 34 | 170 / 34 |
| Rohit SR, required rate > 8 | 354 runs / 298 balls, 118.79 | 118.79 |
| Most runs in successful chases | Virat Kohli 5,791 | Virat Kohli 5,791 |
| Bumrah economy by match lighting | day 4.26 (1,055/1,487); day/night 4.76 (2,454/3,093) | same, labelled with stored categories |
| Lowest bowling-team economy v India | Zimbabwe 5.19 (4,099/4,743), default 60 legal-ball floor disclosed; same leader at 600 | same |
| Bumrah overs 41–50 | **5.78 (1,081/1,123)** | 5.78 |

### Corrected reference: overs 41–50

The issue listed 5.63 from 1,035/1,103. That number was produced by an
off-by-one in the application: stored `over` is the 1-based over number (legal
ball *n* of an innings lies in over ⌈n/6⌉ for 99.995% of legal balls), but the
`over_range` SQL used `over >= start-1 AND over < end`, so "overs 41–50"
counted overs 40–49. Fixed in 68e591f in all three places (aggregate builder,
repository, split executor). Overs 41–50 now equal the death phase (5.78), and
overs 1–10 equal the powerplay. No frozen-150 case compiles to `over_range`,
so no saved answer changed. The user approved this correction before the paid
runs.

## Paid runs and model-call accounting

Every paid run was made once, saved case by case, and never retried to
improve a score. Only planner extraction calls are recorded in the artifacts;
web-grounding requests are not captured by the harness.

| Run | Revision | Result | Gemini calls | Models | Tokens in / out |
| --- | --- | ---: | ---: | --- | --- |
| priority-8 | 68e591f | 7/8 | 6 | gemini-2.5-flash | 891 / 534 |
| priority-8 | d11f438 | 8/8 | 6 | gemini-2.5-flash | 891 / 531 |
| frozen 150 | d11f438 | 134/150 | 134 (132 extraction, 2 ambiguity refinement) | gemini-2.5-flash ×132, gemini-2.5-pro ×2 | 20,261 / 12,816 |
| priority-8 | d6b5f08 | 7/8 | 6 | gemini-2.5-flash | 891 / 719 |

Total: 152 calls. Two of the eight priority questions (toss and team economy)
are answered by registered deterministic stages with no model call.

### What the fresh runs found

Each fresh run exposed an extraction variant that completeness accounting
blocked (fail-safe, never a wrong number). All were fixed with general rules
and negative tests, then verified by replaying the exact saved extraction:

| Run | Variant | Fix |
| --- | --- | --- |
| priority-8 @ 68e591f | Lighting split axis labelled `match_type` | d11f438: an unregistered label counts as the split axis only when the question's registered wording states that axis and no other dimension accounts for it |
| 150 @ d11f438 (14 cases) | Typed operators on ordinary bounds (`between 1–10`, `gte 41`, `gte 2018`, `eq`), `opponent_team`, `dismissed_player`, `spin type` | d6b5f08: an operator compiles only when its implied interval equals the compiled registered scope; registered aliases for opposition and the dismissed-player relationship; shared axis phrases for dimension labels |
| priority-8 @ d6b5f08 | Redundant `player: Kohli` filter restating the subject | f5703ad: a generic player filter compiles only when it repeats an extracted, already-compiled entity |

Root cause of the 150 regressions: #37 added a typed `operator` field and asked
the model to preserve every filter's operator. The saved 2026-09-27 extractions
predate that field, so offline replay could not reveal the change; only a
fresh run could. The release-regression check now warns whenever the
extraction contract changes after the newest recorded corpus.

### Frozen 150 by expected behaviour

| Expected behaviour | Fresh run @ d11f438 | Same extractions replayed @ stable |
| --- | ---: | ---: |
| Database answer | 116/130 | 130/130 |
| Clarification | 8/8 | 8/8 |
| Data limitation | 4/4 | 4/4 |
| Unsupported capability | 6/8 | 6/8 |

The two "unsupported" differences are `unseen-unsupported-team-econ-a/-b`:
issue 44 now answers bowling-team economy with independent evidence. The
frozen benchmark file is unchanged; the intended change is recorded in
`tests/evals/regression/manifest.yaml`.

## Release-regression test list (replaces repeated paid runs)

`scripts/release_regression.py`, configured by `tests/evals/regression/`:

- `golden-answers.json` — the verified answer fingerprint (mode, status,
  failure state, tables, clarification options, answer numbers) of all 158
  benchmark cases at the stable version.
- `stable-baseline.json` — each recorded corpus's per-case outcome at the
  stable version.
- `manifest.yaml` — recorded production corpora (oldest first), which ones
  define golden answers and variants, and intended benchmark deviations.
- `known-limitations.yaml` — question families not answerable yet; reported,
  never blocking. Wrong answers are never excused.

`check` (offline, network disabled) replays every corpus through the real
chat/database path and fails on any wrong answer or any case that matched at
the stable version and no longer does. It also rewrites recorded extractions
into meaning-preserving variants — typed operators, a restated subject filter,
the role moved between fields, a generic dimension label — which must answer
correctly or refuse safely. Safe refusals of variants go to the backlog. It
warns when the extraction prompt/schema source changed since the newest
corpus: only then is a small paid sample (for example the priority-8) worth
approving, and its capture is added as a new corpus.

`record --stable-version <tag>` re-records golden answers; use it only for a
deliberately accepted new stable version.

### Release check at the stable version

`check` result (`tests/evals/regression/last-check.json`): **0 failures**,
no contract-drift warning.

| Corpus (recorded production extractions) | Cases | Match golden |
| --- | ---: | ---: |
| saved-150-2026-09-27 | 150 | 150 |
| saved-priority-8-2026-09-27 | 8 | 8 |
| fresh-priority-8-68e591f | 8 | 8 |
| fresh-150-d11f438 | 150 | 150 |
| fresh-priority-8-d11f438 | 8 | 8 |
| fresh-priority-8-d6b5f08 | 8 | 8 |

| Variant | Applied to | Match | Safe refusal | Needs a model call | Wrong |
| --- | ---: | ---: | ---: | ---: | ---: |
| typed_operators (pre-operator corpora) | 68 | 67 | 1 | 0 | 0 |
| restated_subject | 190 | 190 | 0 | 0 | 0 |
| role_moved | 96 | 96 | 0 | 0 | 0 |
| generic_dimension_label | 85 | 10 | 71 | 4 | 0 |

Backlog (76 items, not blocking): a generic unregistered label such as
"category" for a phase, year, line, length, shot, zone or hand axis is refused
rather than guessed unless the question's registered wording states that axis
(lighting); the Rohit required-rate case refuses when its pre-operator
extraction is given an operator it did not carry. These are robustness
improvements for later, not wrong answers.

The golden answers were recorded from the two committed #47 fresh corpora
(only cases that pass their benchmark, plus the two intended changes); all six
corpora, from three different model runs and the 2026-09-27 snapshot, match
them exactly.

The fixed test list is run by every future versioned change:
`verify_release_references`, the backend suite, `release_regression check`,
and the two Playwright projects. None of it calls Gemini.

## Reproduction (no model calls)

```
PYTHONPATH=. python -m scripts.verify_release_references
PYTHONPATH=. python -m scripts.release_regression check
PYTHONPATH=. python -m scripts.replay_without_network --benchmark tests/benchmarks/odi_unseen_paraphrases_v1.yaml --capture tests/evals/results/releases/issue-47/fresh-150-d11f438.jsonl --output <new file> --summary <new file>
python -m pytest tests -q
```

Use the `odi-analyst-workbench` Conda environment. Replay output files must be
new paths (existing case ids are skipped). A paid run uses
`scripts.odi_correctness_gate --release` and must be approved first.

## Versions and artifacts

Recorded in `tests/evals/results/releases/issue-47/release-metadata.json`:
code revision, database SHA-256, Python and package versions, frontend
versions, extraction schema and prompt hashes, benchmark hashes, call
accounting per run, and the SHA-256 of every artifact.

## Known limitations

- Fresh model extraction varies between runs. Each variant found so far was
  blocked safely, but a new variant can still block an answerable question
  until it is recorded and handled; the variant stress and contract-drift
  warning reduce, not eliminate, this risk.
- The development fallback without Gemini reads "best death-over bowlers" as a
  batter runs ranking (Chat and Workbench alike).
- Known pre-existing issues remain: after an analytics answer, "And Kohli's
  strike rate?" asks an unrelated venue clarification; the plain `dismissals`
  metric credits the batter on strike (Kohli 248) while the dismissal-type
  breakdown credits the dismissed batter (241); aggregate summaries do not
  repeat year filters; `frontend/e2e/explorer.spec.ts:232` has a TypeScript
  type error.
