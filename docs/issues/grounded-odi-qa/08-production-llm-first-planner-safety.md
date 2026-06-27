# Production LLM-First Planner Safety

Labels: `ready-for-agent`

## What to build

Make Semantic V2 production behavior LLM-first and validator-gated. The LLM should handle language understanding, while deterministic code validates the semantic plan and builds SQL. Deterministic fallback may remain for development/offline use, but production should not silently treat fallback guesses as trusted planning.

## Acceptance criteria

- [ ] Production Semantic V2 planning requires a validated LLM plan before executing supported answers.
- [ ] Invalid LLM plans go through repair where supported, then fail clearly if still invalid.
- [ ] Development/offline fallback behavior is explicit and controlled by configuration.
- [ ] Chat/API behavior does not fall back to legacy analytics when Semantic V2 returns unsupported.
- [ ] Tests cover LLM-planner success, invalid-plan rejection, and fallback-disabled behavior.

## Blocked by

- #1
- #6
