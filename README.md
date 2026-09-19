# Conversational Guardrail Benchmark

An open, reproducible comparison of TypeSafe AI Jev and general-purpose LLMs as conversational guardrail classifiers.

## Guardrails

The project will evaluate four binary classification tasks:

1. Harmful jailbreak attempts — WildJailbreak
2. Adversarial or jailbreak techniques — WildJailbreak
3. Abuse disclosures — SonderMind Guardrail Evals
4. Financial-advice detection — FinSafeGuard

Implementation proceeds in that order. The first change is an end-to-end WildJailbreak vertical slice: dataset loading, deterministic sampling, model execution, metrics, result artifacts, and a minimal public results page.

## Principles

- Use externally defined labels and pin every dataset revision.
- Give each system the same conversation and semantically equivalent classifier question.
- Keep benchmark definitions in configuration rather than hard-coded orchestration.
- Make sampled runs deterministic and stratified by label.
- Publish precision, recall, F1, confusion matrices, cost, and latency—not accuracy alone.
- Record enough metadata to reproduce each result.
- Never rerun paid evaluations automatically when an upstream dataset changes.
- Clearly distinguish exploratory sampled runs from publication runs.

## Planned changes

1. `wildjailbreak-vertical-slice`
2. WildJailbreak adversarial-technique refinements
3. SonderMind abuse-disclosure benchmark
4. FinSafeGuard financial-advice benchmark
5. Dataset revision monitoring and stale-result notifications
6. Public deployment and custom-domain hardening

## OpenSpec workflow

Install OpenSpec with Node.js 20.19 or newer:

```bash
npm install -g @fission-ai/openspec@latest
openspec validate wildjailbreak-vertical-slice
```

Review the active change in `openspec/changes/wildjailbreak-vertical-slice/` before implementation. Implementation tasks are deliberately unchecked.
