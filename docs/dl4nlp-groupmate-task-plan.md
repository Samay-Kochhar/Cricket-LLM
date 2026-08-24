# DL4NLP Group Task Plan

## Project task

CricAtlas converts a natural-language ODI cricket question into a structured
JSON query plan. The plan is validated, converted to SQL, executed on DuckDB,
and returned as a database answer.

We compare four model settings:

| Model | What it does | What changes |
|---|---|---|
| CricAtlas + Gemini API | Current CricAtlas system | Gemini generates the plan |
| Qwen 3.5 9B Instruct | Open-source zero-shot baseline | Qwen replaces Gemini; no training |
| Qwen 3.5 4B Instruct | Smaller zero-shot comparison | A smaller Qwen model replaces Gemini; no training |
| Fine-tuned Qwen 3.5 9B Instruct | Modified open-source model | The same Qwen model is trained with QLoRA |

Only the language model changes. All four settings must use the same task
format, plan fields, normalization, validation, SQL generation, ODI database,
100 test questions, and scoring.

## Shared final test set

Use:

```text
tests/evals/dl4nlp_cricket_analyst_supported_100.yaml
```

The file contains 100 realistic ODI analyst questions, the correct structured
plans, and database-generated answer keys.

Rules:

- Do not train on these 100 questions.
- Do not copy or closely paraphrase them into the training data.
- Do not change the test set after seeing a model's score.
- Run every model on the same questions in the same order.

The test categories are:

| Question type | Questions |
|---|---:|
| Single metric | 19 |
| Leaderboard | 26 |
| Breakdown | 28 |
| Player comparison | 10 |
| Split comparison | 9 |
| Matchup | 8 |
| Total | 100 |

## Shared evaluation

Report one main score:

**Full JSON exact-match accuracy:** standardize the predicted and
reference JSON plans, then compare every field used to execute the query. A
question receives one point only when the complete executable plans match.
Any mismatch receives zero points.

JSON key order and spacing do not matter. Do not use keyword matching or
partial credit.

The plans should still be validated and executed so that the complete system
can be demonstrated. Invalid JSON count, validation failures, runtime,
category-level accuracy, and final database answers are useful diagnostics,
but they are not additional headline scores in the presentation.

## Hanny: Two Qwen zero-shot baselines

### Goal

Compare Qwen 3.5 9B and Qwen 3.5 4B without cricket-specific training.

### Fixed inference settings

- Models: `Qwen 3.5 9B Instruct` and `Qwen 3.5 4B Instruct`
- Temperature: `0`
- Maximum generated tokens: `512`
- Seed: `42`, if supported
- Output: one JSON plan only
- Attempts: one normal generation, then the existing validation-and-repair
  step if the plan is rejected

### Tasks

1. Load Qwen 3.5 9B using the available runner.
2. Replace only the Gemini generation call with Qwen.
3. Keep the rest of the CricAtlas pipeline unchanged.
4. Run all 100 final test questions once.
5. Save one record per question with the question ID, predicted plan, executed
   result, runtime, and any validation error.
6. Save the records as:

```text
results/qwen35_9b_base_predictions.jsonl
```

7. Score the predictions:

```bash
python -m scripts.score_dl4nlp_predictions \
  --predictions results/qwen35_9b_base_predictions.jsonl
```

8. Return the overall plan score, category scores, invalid JSON count, average
   runtime, and three useful success/failure examples.

9. Repeat the same procedure with Qwen 3.5 4B and save:

```text
results/qwen35_4b_base_predictions.jsonl
```

Working plan-accuracy values used in the presentation are `43/100` for Qwen
3.5 9B and `34/100` for Qwen 3.5 4B.

## Parimal: QLoRA fine-tuning

### Goal

Test whether training the same Qwen model on cricket question-to-plan examples
improves its results.

### Training and validation data

Create a separate dataset with:

- `800` training examples
- `100` validation examples
- `0` final test questions used for training

Recommended training distribution:

| Question type | Training examples |
|---|---:|
| Single metric | 150 |
| Leaderboard | 150 |
| Breakdown | 150 |
| Player comparison | 150 |
| Split comparison | 100 |
| Matchup | 100 |
| Total | 800 |

Each record contains a natural-language question and its correct JSON query
plan. The training target is not SQL and not the numerical answer.

Example:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Convert the ODI cricket question into the CricAtlas JSON query plan. Return JSON only."
    },
    {
      "role": "user",
      "content": "Compare Bumrah and Starc in death overs."
    },
    {
      "role": "assistant",
      "content": "{\"operation\":\"player_compare\",\"entity\":\"bowler\",\"metric\":\"economy_rate\",\"filters\":{\"players\":[\"Jasprit Bumrah\",\"Mitchell Starc\"],\"phase\":\"death\"}}"
    }
  ]
}
```

Validate every target with the CricAtlas plan validator before training.

### Exact QLoRA starting configuration

| Setting | Value |
|---|---|
| Base model | Qwen 3.5 9B Instruct |
| Quantization | 4-bit NF4 |
| Target layers | `q_proj`, `k_proj`, `v_proj`, `o_proj` |
| LoRA rank | `16` |
| LoRA alpha | `32` |
| LoRA dropout | `0.05` |
| Epochs | `3` |
| Learning rate | `2e-4` |
| Maximum sequence length | `1024` |
| Micro batch | `2` |
| Gradient accumulation | `8` |
| Effective batch | `16` |
| Optimizer | Paged AdamW 8-bit |
| Warmup | `5%` |
| Seed | `42` |

Choose the checkpoint with the highest structured-plan exact match on the
separate 100-example validation set.

### Tasks

1. Generate and validate the 800 training and 100 validation records.
2. Check that no final test question occurs in either file.
3. Fine-tune Qwen with the QLoRA settings above.
4. Save the adapter and record training loss, validation score, hardware, and
   training time.
5. Run the fine-tuned model on the untouched 100-question final test set.
6. Keep the same inference settings and downstream CricAtlas pipeline as the
   base-model run.
7. Save predictions as:

```text
results/qwen35_9b_finetuned_predictions.jsonl
```

8. Score them with the same scorer and return the same evidence as Hanny.

## Results table to complete

| System | Full-plan exact match |
|---|---:|
| Qwen 3.5 4B base | 34/100 working value |
| Qwen 3.5 9B base | 43/100 working value |
| Fine-tuned Qwen 3.5 9B | 53/100 working value |
| CricAtlas + Gemini | 59/100 |

## What Hanny and Parimal must send back

- prediction JSONL file;
- scorer output;
- overall full-plan exact-match score;
- category-level scores;
- exact model, quantization, prompt, and runtime settings;
- three useful successes and three useful failures;
- main failure pattern;
- for fine-tuning: dataset counts, QLoRA settings, training/validation results,
  and adapter location.

## Presentation ownership

- **Samay:** slides `1-8`
- **Hanny:** slides `9-11` and one conclusion line on slide `17`
- **Parimal:** slides `12-15` and the final conclusion lines on slide `17`
- **Samay:** slides `1-8`, slide `16`, and one conclusion line on slide `17`

Use only scorer output in the final numerical comparison.
