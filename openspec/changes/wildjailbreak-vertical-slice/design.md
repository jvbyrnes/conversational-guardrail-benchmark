# Design: WildJailbreak Vertical Slice

## Overview

Use a small Python package for dataset preparation, execution, and aggregation, with generated artifacts consumed by a framework-free static site.

```text
Pinned dataset -> task mapping -> stratified sample -> model adapters
              -> per-example records -> aggregation -> static site
```

The runner owns expensive and secret-bearing work. The site receives only publishable artifacts and has no database, API, authentication, or model credentials.

## Proposed Repository Shape

```text
benchmark/
  config/
  src/guardrail_bench/
    datasets/
    tasks/
    adapters/
    execution/
    metrics/
    artifacts/
  tests/fixtures/
results/published/
site/
openspec/
```

## Core Interfaces

### Dataset adapter

A dataset adapter resolves a configured immutable revision, loads a split, validates the upstream schema, and emits normalized source examples. It never decides provider prompts or model parameters.

### Task definition

A task definition owns eligibility rules, source-label-to-boolean mapping, the semantic classifier question, and a version. Tasks are configuration/data where practical.

| Task | Positive | Negative | Excluded |
|---|---|---|---|
| Harmful jailbreak | `adversarial_harmful` | `adversarial_benign` | both vanilla classes |
| Adversarial technique | both adversarial classes | both vanilla classes | none |

### Model adapter

Each adapter accepts a normalized conversation and task definition and returns the common prediction type. Provider-specific serialization remains inside the adapter.

For generative LLMs, request strict structured output with a boolean decision. Preserve provider/model identifiers and raw usage. Store confidence only when the API exposes a defensible score; do not invent one from prose.

For Jev, convert the same semantic question into the supported typed boolean/probability request while keeping the positive-class meaning unchanged.

### Execution engine

The engine resolves configuration, prepares the deterministic sample once, and sends the identical selected examples to all enabled adapters. Concurrency and retries are bounded and configurable. Failed calls remain explicit errors.

Every enabled paid adapter requires a conservative per-attempt USD reservation and the run requires a USD cost cap. The engine atomically reserves before every initial call and retry, then reconciles a finite, non-negative provider-reported cost that does not exceed the reservation to actual spend, releasing only the unused allowance for later requests. Missing or untrustworthy billing data keeps the reservation held fail-closed. Paid attempts remain serialized through the budget gate so accounting is atomic; a provider-reported overage or insufficient-funds response stops later requests. The configured cap must fund one fully retried attempt for every enabled paid adapter. Manifests distinguish cumulative admitted reservations, current cap-held commitments, and valid actual reported spend. A matching provider-side key limit remains necessary because a local gate cannot reverse a provider charge that exceeds its declared reservation.

### Artifact writer

Each run receives a stable run ID and directory. Schemas are versioned. Public artifacts omit conversation text by default and include source IDs, labels, predictions, scores, timings, usage, and costs.

The writer creates a versioned run-status checkpoint before adapter execution and durably appends each completed prediction to a partial JSONL file. Cap exhaustion, insufficient provider funds, or an unexpected interruption leaves completed predictions recoverable. Cap- and funds-stopped final artifacts are explicitly marked incomplete with a reason.

## Configuration

Support YAML configuration with CLI overrides. At minimum:

```yaml
dataset:
  name: allenai/wildjailbreak
  revision: <immutable-commit>
  split: eval

task: harmful_jailbreak
sample:
  rate: 0.05
  seed: 20260918
```

Secrets are supplied only through environment variables and are never included in artifacts.

## Sampling Decision

Stratify using original source labels, not merely derived booleans, so the adversarial-technique task retains representation from all four classes. Derive a deterministic pseudo-random ordering from the seed and stable source ID, then select within each stratum. This avoids dependence on upstream row order.

Reject a configuration when the requested rate cannot select at least one example from every required stratum. Record eligible counts and selected counts for each stratum.

## Metrics Decision

Calculate binary metrics from successful predictions and separately report coverage. Do not treat provider errors as classifier negatives. Preserve exact confusion-matrix counts. Latency reports p50 and p95 across successful calls plus wall-clock run duration. Cost retains provider usage fields, price inputs, and pricing-table version.

## Publication Decision

The site displays only designated artifacts in `results/published/`. An exploratory result may be previewed but must carry a visible badge. A publication result requires `sample.rate == 1.0`; this first change does not add a human approval gate.

## Revision Monitoring Boundary

This change records immutable revisions and allows the site to consume current-revision metadata. A later OpenSpec change will add scheduled upstream checks and notification behavior. That monitor may mark results stale but must never launch a paid rerun automatically.

## Testing Strategy

- Unit tests for all four label mappings.
- Property or repeated-run tests for deterministic sampling.
- Tests for invalid sample rates and undersized strata.
- Metric tests against hand-calculated confusion matrices.
- Schema round-trip tests for run and prediction artifacts.
- Adapter contract tests using fakes.
- Offline end-to-end fixture producing site-consumable artifacts.
- No paid or network calls in the default test suite.
- Offline tests for cap preflight, retry reservations, overage/funds fail-fast behavior, and incomplete-run checkpoint recovery.

## Open Decisions Deferred to Implementation Review

- Exact Jev SDK/API integration method and model identifier.
- First general-purpose LLM provider/model.
- WildJailbreak configuration/split names after inspecting the pinned release.
- Whether provider-native batch APIs are worthwhile for the full run.
- Static hosting provider and custom domain.
