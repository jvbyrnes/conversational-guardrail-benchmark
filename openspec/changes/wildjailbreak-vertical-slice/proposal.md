# Proposal: WildJailbreak Vertical Slice

## Intent

Build the first complete, reproducible path through the benchmark: load a pinned WildJailbreak revision, derive two well-defined binary classification tasks, run TypeSafe AI Jev and configurable LLM baselines on an identical deterministic sample, calculate comparable quality/cost/latency metrics, and render the results on a minimal static website.

This change establishes the architecture that later SonderMind and FinSafeGuard integrations will reuse.

## Scope

- Create a Python benchmark CLI and configuration model.
- Download WildJailbreak from a pinned immutable revision.
- Normalize source rows into a common conversation-example schema.
- Derive two separate classifiers from the four mutually exclusive source labels:
  - harmful jailbreak attempt;
  - adversarial or jailbreak technique.
- Support deterministic stratified sampling through a configurable sample rate and seed.
- Support full publication runs with a sample rate of `1.0`.
- Implement a common model-adapter contract for Jev and LLM classifiers.
- Require semantically equivalent, versioned classifier questions across adapters.
- Capture per-example predictions, scores when available, latency, token usage, and estimated cost.
- Calculate aggregate metrics and generate versioned JSON/CSV artifacts.
- Render aggregate results and run metadata on a static public-results page.
- Provide fixture-based tests that do not require network access or paid APIs.

## Out of Scope

- SonderMind and FinSafeGuard adapters.
- Final provider/model selection beyond the adapter contract.
- Automatic paid reruns.
- Scheduled upstream-revision monitoring and notifications.
- Statistical significance testing across repeated runs.
- Publishing full prompt text from upstream datasets.
- Production hosting configuration or custom-domain setup.

## Success Criteria

- A developer can run a deterministic 1–5% development evaluation by editing one configuration value or passing one CLI option.
- Repeating a run with the same dataset revision, configuration, and seed selects the same source IDs.
- The harmful-jailbreak and adversarial-technique tasks use the explicit label mappings in the delta spec.
- Jev and every LLM adapter receive the same normalized conversation and the same versioned classifier meaning.
- The runner writes validated per-example and aggregate artifacts containing full reproducibility metadata.
- The static page renders directly from the generated aggregate artifact.
- Tests cover label mapping, stratification, metrics, schemas, and an offline end-to-end fixture.
- A full run is clearly marked as a publication run; partial runs are clearly marked exploratory.

## Risks

- Source schemas may change even when a dataset name remains stable. Pinning an immutable revision and recording schema fingerprints mitigates this.
- Jev probabilities and LLM boolean outputs may not be directly calibrated. Primary metrics use thresholded decisions while preserving raw scores where available.
- Provider-reported token and cost data may differ. Cost calculation records both raw usage and the pricing-table version.
- A tiny sample may omit a stratum. Configuration validation will reject samples that cannot preserve every required class.
- Publishing source text may create licensing or safety concerns. Public artifacts use source IDs and predictions by default.
