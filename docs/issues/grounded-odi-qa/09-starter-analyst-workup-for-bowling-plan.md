# Starter Analyst Workup For One Tactical Prompt

Labels: `ready-for-agent`

## What to build

Build the first narrow multi-query analyst workup for a tactical prompt, preferably “How should we bowl to a named batter?” The answer should gather several database evidence probes first, then synthesize a grounded bowling plan from those results.

The goal is not full tactical intelligence. The goal is a thin, complete, verifiable workup path.

## Acceptance criteria

- [ ] A supported tactical prompt for a named batter selects multiple evidence probes before synthesis.
- [ ] Evidence probes include relevant supported dimensions such as bowling style, line, length, false shots, scoring zones, and dismissals where available.
- [ ] The final answer states what was checked before recommending a plan.
- [ ] The final answer mentions sample-size or data limitations where relevant.
- [ ] Unsupported or underspecified tactical prompts ask for clarification or return a clear limitation state.

## Blocked by

- #1
- #2
- #5
- #6
