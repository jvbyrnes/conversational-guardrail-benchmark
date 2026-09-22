# Design: Multi-Run Benchmark Comparison

## Overview

Retain the current architecture—Python generates static, publishable artifacts consumed by a framework-free site—and add a validated catalogue and comparison projection.

```text
Per-run raw evidence
  -> normalized predictions and manifest
  -> validation and compatibility classification
  -> published run index + per-run artifacts
  -> static multi-run comparison site
```

The Python package remains the authority for schema validation, compatibility, and aggregate calculation. The browser renders declared states and must not invent compatibility rules or recompute authoritative metrics independently.

## Existing Baseline

The repository already provides:

- strict Pydantic models for predictions, manifests, checkpoints, and aggregates;
- immutable dataset revision and schema fingerprint fields;
- task, classifier, code, sampling, pricing, timing, usage, and cost metadata;
- durable partial prediction checkpoints;
- JSON, JSONL, and CSV run artifacts;
- a static results page for one `latest` aggregate;
- offline fixture tests.

This change extends those contracts rather than introducing a parallel result format.

## Result Layers

### Run evidence

The existing run directory remains the durable source of truth. Completed prediction records are not overwritten during publication or comparison generation.

### Published run bundle

Each publishable run has a stable directory beneath `results/published/runs/<run_id>/` containing its manifest, aggregate, and redacted per-example records. Artifact bytes receive SHA-256 digests in the index.

### Published index

`results/published/index.json` is a versioned catalogue of validated run summaries. It contains enough metadata to populate selectors and decide which detailed artifacts to load, but it does not duplicate all predictions.

`latest` may remain as a convenience alias during migration, but the site does not use it as its only data source.

## Canonical System Identity

Replace untyped model dictionaries at publication boundaries with a strict model identity:

```yaml
system_id: openai:gpt-example:2026-09-01:<configuration-fingerprint>
adapter_id: openai
provider: openai
model_id: gpt-example
model_snapshot: 2026-09-01        # null only when unavailable
snapshot_status: immutable         # immutable | provider_alias | unavailable
display_name: GPT Example
parameters:                        # secret-free, output-affecting values only
  temperature: 0
  max_output_tokens: 1024
configuration_fingerprint: sha256:...
```

The fingerprint is computed from canonical JSON containing adapter/provider identity, model ID and snapshot, output-affecting parameters, classifier version, and provider request mode. Credentials, request IDs, and timestamps are excluded.

`system_id` identifies a configured system, not a run. `run_id` identifies one execution. A friendly name is presentation metadata and cannot establish identity.

## Benchmark and Comparison Identity

The existing `task_id` is the initial benchmark identifier. Add an explicit `task_version` if it is not already fully represented by `classifier_version` and label mapping. A comparison key contains:

- dataset name, immutable revision, split, configuration, and schema fingerprint;
- task ID and task version;
- classifier version;
- sampling rate, seed, selected source-ID cohort digest, and sample count;
- metric definition version;
- artifact schema major version.

Two systems are **directly comparable** only when all comparison-key fields match and both have acceptable validation status. Matching only the dataset name or task ID is insufficient.

Runs with different system sets may still contribute individual systems to a comparison when their comparison keys match. Duplicate results for the same `system_id` and comparison key remain separate runs; the UI must require or apply a documented selection rule rather than silently averaging them.

## Validation Model

Validation produces a report with `valid`, `warnings`, `errors`, rule IDs, affected paths, and a validator version. It runs before publication-index generation.

### Schema checks

- Parse every manifest, aggregate, and prediction through its declared schema version.
- Reject unsupported schema major versions and unknown required fields.
- Require finite numeric values in declared ranges and UTC timestamps.

### Provenance checks

- Require dataset, task, classifier, code, pricing, and system identity fields.
- Require a model snapshot status; warn rather than fabricate an immutable snapshot.
- Recompute and verify configuration and cohort fingerprints.
- Reject secret-looking fields at publication boundaries.

### Completeness and uniqueness checks

- Derive the expected `(source_id, system_id)` set from the manifest and selected cohort.
- Reject duplicate prediction identities.
- Ensure every expected identity has exactly one terminal record.
- Keep provider errors as explicit prediction errors rather than missing rows or negative decisions.
- Verify published files and declared checksums.

### Aggregate consistency checks

- Recompute coverage, confusion matrix, precision, recall, F1, accuracy, latency, and cost from predictions.
- Compare recomputed values with aggregates using explicit floating-point tolerances.
- Ensure manifest cost totals and aggregate system totals reconcile under the existing fail-closed billing rules.

### Publication checks

- Reject conversation text, credentials, secret headers, and unapproved raw provider payloads.
- Reject `incomplete` runs from ranked comparison; optionally index them as visibly non-rankable.
- Preserve `exploratory` runs with prominent labelling.
- Record staleness separately from validity.

## Index Shape

The published index contains:

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-09-22T00:00:00Z",
  "validator_version": "1.0.0",
  "runs": [
    {
      "run_id": "...",
      "comparison_key": "sha256:...",
      "task_id": "adversarial_technique",
      "task_version": "1.0.0",
      "run_kind": "publication",
      "status": "complete",
      "validation_status": "valid",
      "systems": [],
      "aggregate_uri": "runs/.../aggregate.json",
      "predictions_uri": "runs/.../predictions.jsonl",
      "artifact_digests": {}
    }
  ]
}
```

The exact index schema will be implemented as strict Pydantic models and versioned independently from individual run artifacts.

## Site Interaction

### Benchmark header and selectors

The page first selects a task/version and compatible cohort, then allows multi-selecting systems/runs. Query parameters encode the selection so comparisons can be shared.

### Summary matrix

Rows contain F1, precision, recall, accuracy, coverage, errors, latency p50/p95, total cost, and cost per 1,000 examples. Columns represent selected systems. Each column shows display name, canonical model ID, snapshot status, and run date.

Absolute values remain primary. Deltas are shown only for directly comparable selections and use an explicitly selected reference system.

### Case explorer

Predictions align by stable source ID. Filters include source label, correct/incorrect, provider error, and disagreement. Sorting includes disagreement, score, latency, and cost when available.

The detail view shows ground truth and each selected system's decision, score, error, latency, usage, and cost. It does not show withheld source conversation text.

### Provenance panel

For every selected result, show run ID, system identity, provider, model ID, snapshot status, parameters, dataset revision, schema fingerprint, task/classifier version, cohort digest, sampling details, code revision, pricing version, schema version, validation report, timestamps, and run state.

### Non-comparable selections

The UI may display non-comparable runs for inspection, but it suppresses winner language, rankings, and deltas. It lists the exact comparison-key fields that differ.

## Migration

Version-1 artifacts are parsed through the current models. A migration command derives canonical system identities only when all required values are present. When snapshot information is absent, it records `snapshot_status: unavailable`; it never guesses a snapshot.

Migration writes a new published bundle and leaves the original run directory unchanged. If identity or cohort information cannot be derived, migration returns an actionable validation error.

## Testing Strategy

- Unit tests for canonical JSON and identity/cohort fingerprints.
- Schema tests for strict system identity, validation report, and published index models.
- Validation tests covering missing provenance, duplicates, missing rows, aggregate drift, invalid numbers, checksum mismatch, and secret-like fields.
- Compatibility tests for each comparison-key dimension.
- Migration tests using the existing fixture artifacts.
- Static-site tests with two compatible systems, three or more systems, incompatible runs, incomplete runs, errors, and missing optional scores.
- Offline end-to-end test: fixture execution -> validation -> publication index -> comparison rendering.

## Open Decisions

- Whether `task_version` should be a new field or a digest derived from task definition content.
- Whether incomplete runs appear in the public index by default or only in an internal preview index.
- The maximum systems shown simultaneously in case detail; four is the proposed initial limit.
- Whether validation reports are embedded in the index or linked as separate artifacts.
- Whether historical pricing tables should be downloadable from the public site.
