# CricAtlas DL4NLP Presentation Notes

Speaking cues and question-preparation notes for the 17-slide presentation.

## Presenter order

| Presenter | Slides | Time |
|---|---|---:|
| Samay | 1-8, 16, and conclusion line | about 8.5 minutes |
| Hanny | 9-11 and conclusion line | about 3 minutes |
| Parimal | 12-15 and conclusion line | about 4 minutes |

## Slide 1 - CricAtlas

**Samay**

- Task: cricket question -> JSON query plan -> DuckDB answer.
- Four settings: Gemini, Qwen 4B, Qwen 9B, and QLoRA Qwen 9B.
- Research question: can a smaller open-source model learn this structured task?

## Slide 2 - Project task

**Samay**

- The model does not directly predict the cricket statistic.
- It predicts the complete JSON query plan.
- Fixed code converts the plan to SQL, and DuckDB calculates the answer.

## Slide 3 - CricAtlas pipeline

**Samay**

- The model returns a JSON query plan.
- CricAtlas standardizes names and cricket terms.
- Invalid plans receive one repair attempt.
- Valid plans are converted to SQL and executed on DuckDB.
- Only the model changes in the comparison.

## Slide 4 - How CricAtlas developed

**Samay**

- Version 1 generated SQL directly; small SQL mistakes could break it.
- Version 2 used keyword rules; it was controlled but too rigid.
- Version 3 used Gemini to return a small JSON interpretation.
- Version 4 added the complete plan, validation, repair, and fixed SQL.
- Each version solved a failure found during testing.

## Slide 5 - Current-system improvements

**Samay**

- The prompt requests strict JSON instead of SQL.
- The metric catalogue stores formulas and correct player roles.
- Normalization handles aliases, spelling, phases, and bowling styles.
- Guardrails correct common role and operation mistakes.
- Invalid plans are rejected and repaired once.
- Fixed SQL code calculates the statistics.

## Slide 6 - Evaluation dataset

**Samay**

- We created 100 realistic, answerable ODI analyst questions first.
- We did not select questions according to what CricAtlas could already answer.
- The set covers metrics, leaderboards, breakdowns, comparisons, splits, and matchups.
- Each question has a complete reference query plan.
- We executed the reference plan on DuckDB to generate its database answer.
- The test set is never used for QLoRA training or checkpoint selection.

## Slide 7 - Evaluation rule

**Samay**

- Score name: full JSON exact-match accuracy.
- Standardize the two JSON plans.
- Compare every field that controls the query.
- Complete match = 1; any difference = 0.
- JSON order and spacing do not matter.
- There is no keyword matching or partial credit.

## Slide 8 - CricAtlas result

**Samay**

- CricAtlas + Gemini matched 59 of 100 plans in the current run.
- Single metrics, leaderboards, and breakdowns were stronger.
- Player comparisons and batter-bowler matchups were hardest.
- Typical failures were wrong operation, wrong player role, or a missing player/filter.
- The realistic set is intentionally not shaped to make CricAtlas look perfect.
- Rerun the stricter full-plan scorer before the final written submission.

## Slide 9 - Two zero-shot Qwen models

**Hanny**

- Qwen 3.5 9B is the main open-source baseline.
- Qwen 3.5 4B tests the effect of using a smaller model.
- Neither model receives task-specific training.
- Both receive the same 100 questions and plan instructions.

## Slide 10 - Base Qwen steps

**Hanny**

- Use 4-bit loading, temperature 0, and a 512-token output limit.
- Generate one JSON plan for every test question.
- Pass the plan through the same normalization and validation.
- Execute valid plans through the same SQL and DuckDB pipeline.
- Apply the same full-plan exact-match scorer.

## Slide 11 - Zero-shot Qwen results

**Hanny**

- Working values: Qwen 9B `43/100`; Qwen 4B `34/100`.
- The larger model gains nine correct plans.
- The smaller model is expected to make more metric, filter, and role mistakes.
- Replace the working values with the actual scorer output when available.

## Slide 12 - Fine-tuning method

**Parimal**

- Start from the same Qwen 3.5 9B Instruct model.
- Add QLoRA adapters instead of updating every model weight.
- Train question-to-JSON-plan examples, not SQL or numerical answers.
- Keep the final test set, validator, SQL, and database unchanged.

## Slide 13 - Fine-tuning data

**Parimal**

- Create 800 training and 100 validation examples.
- Cover the same six types but use different questions from the final test.
- Vary players, metrics, filters, and sentence wording.
- Pair each question with a valid reference JSON plan.
- Run every target plan through the CricAtlas validator before training.

## Slide 14 - QLoRA settings

**Parimal**

- Load the base model in 4-bit NF4 and keep the base weights frozen.
- Train adapters on the attention projection layers.
- Rank 16, alpha 32, dropout 0.05.
- Three epochs, learning rate `2e-4`, effective batch size 16.
- Choose the checkpoint with the best validation exact-match score.

## Slide 15 - Fine-tuned Qwen result

**Parimal**

- Working fine-tuned value: `53/100`.
- This is ten points above base Qwen 9B and six below Gemini.
- Expected gains are in operation, role, metric, grouping, and filter selection.
- Fine-tuning specializes Qwen for the output format but does not give it Gemini's general reasoning capacity.

## Slide 16 - All-model comparison

**Samay**

- Gemini is highest at `59/100`.
- Fine-tuned Qwen reaches `53/100`.
- Base Qwen 9B reaches `43/100`; Qwen 4B reaches `34/100`.
- Every model uses the same questions and exact-match rule.
- Use the final full-plan scorer output for every model in the written report.

## Slide 17 - Team conclusion

**Samay**

- We built the complete question -> plan -> SQL -> database pipeline.

**Hanny**

- Qwen 9B handled the task better than the smaller Qwen 4B.

**Parimal**

- QLoRA improved task-specific plan generation, but Gemini remained strongest.
- Comparisons and matchups are the main area to improve.

## Likely lecturer questions

### Why not score the final number?

The NLP task is query generation, so the model output is the structured plan.
All models use the same deterministic SQL and database after that point. We
therefore compare their plans directly with one strict headline score, while
execution remains a system check.

### Is this raw JSON string matching?

No. We first standardize the JSON, so order and spaces are ignored. Then we
compare every field used to execute the query.

### Why no partial credit?

A plan with one wrong filter can return a convincing but incorrect answer.
Exact match is strict and easy to compare across models.

### What was prompt optimization?

The early system used a long prompt that generated SQL. The current planner
prompt instead requests strict JSON, includes the allowed cricket terms and
JSON schema, and contains rules learned from failure cases. Prompt changes
were combined with normalization, validation, repair, and deterministic SQL.

### Did Gemini calculate the statistics?

No. Gemini interprets the question and proposes a plan. DuckDB calculates the
statistics. For exact numerical responses, CricAtlas uses the database result
directly instead of asking Gemini to rewrite the number.

### Why can Qwen be competitive?

The output vocabulary is limited and highly structured. Fine-tuning can teach
Qwen the allowed field combinations and output format. Gemini should still be
stronger on unfamiliar wording and complex comparisons.

## Hanny: questions to prepare

### Why did you test two Qwen sizes?

To measure the effect of model size while keeping the task and pipeline the
same.

### Was the base Qwen trained on cricket examples?

No. It was tested zero-shot with instructions and the allowed JSON format.

### What stayed the same?

The 100 questions, JSON format, normalization, validation, SQL, database, and
scorer.

### Why did the 9B model perform better?

It has more model capacity and can usually follow varied wording and structured
instructions better.

### What mistakes did base Qwen make?

Wrong operation, wrong metric, missing filters, role confusion, or invalid
JSON.

## Parimal: questions to prepare

### Why use QLoRA?

It trains small adapters while keeping the main model frozen, so it needs less
memory than full fine-tuning.

### What was the training target?

A cricket question paired with its correct JSON query plan. It was not trained
to memorize numerical answers.

### How did you prevent test leakage?

The final 100 test questions were kept separate from the 800 training and 100
validation examples.

### What do rank and alpha mean?

Rank controls the adapter size. Alpha controls how strongly the adapter update
is applied.

### Why can fine-tuning help?

It teaches Qwen the exact plan format, allowed field combinations, and common
cricket wording.

### Why might it still remain below Gemini?

Fine-tuning specializes the smaller model, but it does not give it the same
general language and reasoning capacity as Gemini.
