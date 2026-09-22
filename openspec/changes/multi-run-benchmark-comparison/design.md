# Design: Multi-Run Benchmark Comparison

## Overview

Retain the current architecture—Python generates static, publishable artifacts consumed by a framework-free site—and add a validated catalogue and comparison projection.

```text
Per-run raw evidence
  -> authoritative cohort + normalized predictions and manifest
  -> validation and compatibility classification
  -> strict public projection + deterministic public/preview indexes
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

Each publishable run has a stable directory beneath `results/published/runs/<run_id>/` containing its manifest, aggregate, authoritative `cohort.json`, strict public per-example records, and a validation report. Artifact bytes receive SHA-256 digests in the index.

The private authoritative cohort is written from dataset selection before any model request and digested over dataset identity plus internal membership. Publication projects it to `cohort.json`, containing dataset identity, a pseudonym namespace/key ID, and a canonically sorted member list with `public_case_id`, ground truth, and an allowlisted source-label stratum. The manifest references both the private authoritative digest and public projection digest; only the latter is published. Neither is reconstructed from prediction rows.

### Published index

`results/published/index.json` is a versioned catalogue containing only complete, publication-safe, schema-valid bundles. `results/preview/index.json` is an opt-in local/internal catalogue outside the deployable publication root that may additionally describe incomplete or invalid bundles without exposing unsafe artifact URIs. Preview entries are constructed only from sanitized validator output—safe run identifiers, stable rule IDs, counts, and approved state fields—rather than copied from invalid artifacts. Deployment tests assert that `results/preview/` is excluded. Both indexes contain enough metadata to populate selectors and decide which detailed artifacts to load, but do not duplicate all predictions.

`latest` may remain as a convenience alias during migration, but the site does not use it as its only data source.

## Canonical System Identity

Replace untyped model dictionaries at publication boundaries with a strict model identity:

```yaml
system_id: sha256:...
adapter_id: openai
adapter_version: 1.0.0
provider: openai
requested_model_id: gpt-example
resolved_snapshot: 2026-09-01     # non-null only when immutable
snapshot_status: immutable         # immutable | provider_alias | unavailable
display_name: GPT Example
parameters:                        # secret-free, output-affecting values only
  temperature: 0
  max_output_tokens: 1024
configuration_fingerprint: sha256:...
```

The fingerprint is computed from canonical JSON containing adapter/provider identity, adapter version, requested model ID, resolved snapshot when available, snapshot status, explicit output-affecting parameters, versioned adapter defaults, and provider request mode. Undocumented provider defaults or routing are recorded as unresolved reproducibility warnings and are never fabricated as effective values. Credentials, request IDs, timestamps, and task/classifier fields are excluded.

`system_id` identifies a configured system, not a run. `run_id` identifies one execution. A friendly name is presentation metadata and cannot establish identity.

Canonical JSON follows RFC 8785 JSON Canonicalization Scheme over explicitly versioned fingerprint input models: absent optional fields are omitted and explicit nulls are retained before canonicalization. IDs use a `sha256:` digest of these canonical UTF-8 bytes rather than delimiter-dependent field concatenation. Golden vectors cover Unicode, numeric, absent/null, map-order, and array-order cases.

Snapshot invariants are strict: `immutable` requires a non-null provider-guaranteed immutable `resolved_snapshot`; `provider_alias` requires a known mutable requested alias and a null resolved snapshot; `unavailable` requires a null resolved snapshot when the provider exposes neither an immutable resolution nor documented alias semantics. The requested model ID is always retained.

## Evaluation and Result Identity

An `evaluation_id` is derived from canonical inference/task-definition content: task ID, semantic question/prompt, label mapping, decision threshold, and parser/classifier version. The readable `task_version` remains display metadata, while the digest prevents an unversioned prompt or mapping change from being conflated. Post-hoc metric definitions do not alter system or evaluation identity.

Every prediction and per-system aggregate entry is keyed by an `evaluated_system_id` derived from `(system_id, evaluation_id)`. This directly addresses task-aware identity: the same configured model retains one `system_id`, but two task questions or classifier definitions can never share an evaluated-result identity.

## Benchmark and Comparison Identity

Compatibility is evaluated independently for each metric family rather than through one all-or-nothing key.

The **quality key** contains:

- dataset name, immutable revision, split, configuration, and schema fingerprint;
- evaluation ID;
- public cohort digest, pseudonym key ID, and sample count;
- quality metric-definition version; and
- normalized artifact-semantics major version.

The **cost key** contains the quality key plus currency, pricing version, cost method, and billing policy; it is null when any of those provenance fields is unavailable. Cost rankability is a separate per-result state and requires `cost_coverage == 1.0`. The **latency key** contains the quality key plus timing-definition version, execution mode, concurrency, retry and timeout policy, provider routing/region class, and warm-up policy; it is null and non-rankable when any required execution field is unavailable.

Two results are directly comparable for a metric family only when that family's key matches and both have acceptable validation status. Quality may remain rankable while cost or latency is displayed only as an absolute, non-rankable value. Compatibility reports include a state and exact differing field paths for every family.

Runs with different system sets may still contribute individual systems when their keys match. Duplicate results are never silently averaged. For each `(quality_key, evaluated_system_id)`, the default is the valid, complete publication run with greatest `completed_at`, breaking ties by lexicographic `run_id`; the UI discloses alternatives, permits an explicit override, and encodes exact run IDs in shared URLs.

## Validation Model

Validation produces a report with `valid`, `warnings`, `errors`, rule IDs, affected paths, and a validator version. It runs before publication-index generation.

### Schema checks

- Parse every manifest, aggregate, and prediction through its declared schema version.
- Reject unsupported schema major versions and unknown fields.
- Require finite numeric values in declared ranges and UTC timestamps.

### Provenance checks

- Require dataset, task/evaluation, code, pricing, system, and evaluated-system identity fields.
- Require a model snapshot status; warn rather than fabricate an immutable snapshot.
- Recompute and verify configuration and cohort fingerprints.
- Require repository identity, commit revision, committed-tree digest, and `working_tree_state` (`clean`, `dirty`, or `unavailable`). Dirty or unavailable code is preview-only and non-rankable.

Code provenance is captured from the repository root immediately before execution. The implementation records trimmed stdout from `git rev-parse HEAD` as the commit revision and `git rev-parse HEAD^{tree}` as the committed-tree digest, then evaluates `git status --porcelain=v1 --untracked-files=all --ignore-submodules=none`. The working tree is `clean` only when all three commands succeed and the status output is empty. Any staged, unstaged, untracked, or modified-submodule entry makes it `dirty`. A non-Git source directory, a failed command, or missing or malformed output makes it `unavailable`; the implementation must not infer cleanliness from a commit SHA alone. Ignored files remain outside the cleanliness decision because Git does not identify them as source-tree changes.

### Completeness and uniqueness checks

- Verify the independently written cohort digest, combine the run's evaluation ID with every manifest-declared system ID, and derive the expected Cartesian product of cohort members and those evaluated-system IDs.
- Reject duplicate prediction identities.
- Ensure every expected identity has exactly one terminal record.
- Keep provider errors as explicit prediction errors rather than missing rows or negative decisions.
- Verify published files and declared checksums.

### Aggregate consistency checks

- Recompute coverage, confusion matrix, precision, recall, F1, accuracy, latency, cost coverage, and cost from predictions.
- Compare recomputed values with aggregates using explicit floating-point tolerances.
- Ensure manifest cost totals and aggregate system totals reconcile under the existing fail-closed billing rules.

Published cost is `cost_usd: number | null` plus `cost_status: reported | estimated | unavailable`, currency, pricing version, and cost method where applicable. Aggregate cost is null unless every relevant row has known cost; `cost_known_count` and `cost_coverage` remain visible. Missing cost is never coerced to zero.

### Publication checks

- Construct published predictions through a strict `extra=forbid` DTO that allows only pseudonymous case ID, `evaluated_system_id`, approved label/ground-truth fields, decision, optional score, stable sanitized error code/category, latency, standardized token counts, and provenance-aware cost fields.
- Exclude internal source IDs, conversation text, credentials, headers, arbitrary provider fields, raw payloads, request IDs, and free-form error messages. Published system parameters use adapter-versioned safe-field allowlists.
- Derive `public_case_id` with HMAC-SHA-256 over dataset identity and internal source ID. A controlled publication configuration supplies one stable secret per pseudonym namespace and a non-secret key ID; missing key material fails closed before public projection. The key is never published. Rotation creates a new key ID, public cohort digest, and non-comparable alignment namespace rather than silently joining IDs. A fixed non-secret fixture key is used only by tests.
- Reject `incomplete`, invalid, dirty-code, and publication-unsafe runs from the public index. Incomplete and invalid metadata may appear in the preview index; publication-safety failures never expose artifact URIs.
- Preserve `exploratory` runs with prominent labelling.
- Record staleness separately from validity.

## Index Shape

The published index contains:

```json
{
  "schema_version": "1.0.0",
  "as_of": "2026-09-22T00:00:00Z",
  "source_set_digest": "sha256:...",
  "validator_version": "1.0.0",
  "runs": [
    {
      "run_id": "...",
      "task_id": "adversarial_technique",
      "task_version": "1.0.0",
      "run_kind": "publication",
      "status": "complete",
      "validation_status": "valid",
      "systems": [
        {
          "system_id": "sha256:...",
          "evaluated_system_id": "sha256:...",
          "quality_key": "sha256:...",
          "cost_key": null,
          "latency_key": "sha256:...",
          "rankability": {
            "quality": {"eligible": true, "reason": null},
            "cost": {"eligible": false, "reason": "missing_cost_provenance"},
            "latency": {"eligible": true, "reason": null}
          }
        }
      ],
      "aggregate_uri": "runs/.../aggregate.json",
      "predictions_uri": "runs/.../predictions.jsonl",
      "cohort_uri": "runs/.../cohort.json",
      "validation_report_uri": "runs/.../validation-report.json",
      "artifact_digests": {}
    }
  ]
}
```

The exact index schema will be implemented as strict Pydantic models and versioned independently from individual run artifacts. Comparison keys and intrinsic per-metric rankability eligibility belong to each system result, identified by both `system_id` and `evaluated_system_id`, because cost coverage and execution provenance can differ within one run. Each ineligible state carries a stable reason; pairwise comparability remains a separate result of comparing two eligible entries' keys. Runs, systems, digest entries, and object keys have specified canonical ordering. `as_of` is a nullable field containing the maximum immutable `published_at` in the included bundles, or JSON `null` when there are no included bundles. `source_set_digest` hashes RFC-8785 canonical JSON of tuples `(run_id, manifest_digest, cohort_digest, aggregate_digest, predictions_digest, validation_report_digest)` sorted by `run_id`; for an empty index it is the SHA-256 digest of the RFC-8785 canonical empty array. Wall-clock command time belongs only in a non-published generation report. Identical inputs therefore produce byte-identical index output.

## Site Interaction

### Benchmark header and selectors

The page first selects a task/version and compatible cohort, then allows multi-selecting systems/runs. Query parameters encode the selection so comparisons can be shared.

When the public index has no runs, the page renders an explicit no-published-results state without attempting to choose a task, cohort, system, or reference result.

### Summary matrix

Rows contain F1, precision, recall, accuracy, coverage, errors, latency p50/p95, total cost, and cost per 1,000 examples. Columns represent selected systems. Each column shows display name, canonical model ID, snapshot status, and run date.

Absolute values remain primary. Deltas and rankings are shown independently for quality, cost, and latency only when the relevant compatibility key matches, cost coverage is sufficient where applicable, and an explicit reference system is selected.

### Case explorer

Predictions align by stable public case ID. Filters include source label, correct/incorrect, provider error, and disagreement. Sorting includes disagreement, score, latency, and cost when available.

The detail view shows ground truth and each selected system's decision, score, sanitized error category, latency, standardized usage, and provenance-aware cost. It does not show internal source IDs or withheld source conversation text.

### Provenance panel

For every selected result, show run ID, system/evaluation identity, provider, model ID, snapshot status, parameters, dataset revision, schema fingerprint, task/classifier version, cohort digest, sampling details, repository/commit/tree and working-tree state, pricing version, metric-family compatibility, schema version, validation report, timestamps, and run state.

### Non-comparable selections

The UI may display non-comparable runs for inspection, but it suppresses winner language, rankings, and deltas only for the affected metric families. It lists the exact key fields that differ.

## Migration

Version-1 artifacts are parsed without allowing model defaults to masquerade as serialized evidence. A migration command derives canonical identities only when all required values are present. When snapshot information is absent, it records `snapshot_status: unavailable`; it never guesses a snapshot.

Legacy cost is recomputed only when raw usage, exact pricing version, currency, and billing method are available. A serialized or defaulted zero alone is not evidence of known zero cost; otherwise migration records null/unavailable cost and null aggregates. The dry-run report explains every unavailable or incompatible field.

Migration reconstructs a legacy cohort only by replaying the recorded selection against the immutable dataset revision with a known sampling algorithm; prediction rows are not an authoritative cohort source. Migration writes a new published bundle and leaves the original run directory unchanged. If identity or cohort information cannot be derived independently, migration returns an actionable validation error and the run remains preview-only.

## Testing Strategy

- Unit tests for canonical JSON and identity/cohort fingerprints.
- Schema tests for strict system identity, validation report, and published index models.
- Validation tests covering missing provenance, duplicates, missing rows, aggregate drift, invalid numbers, checksum mismatch, and unknown or unsafe public fields.
- Compatibility tests for each metric-family key dimension.
- Migration tests using the existing fixture artifacts.
- Static-site tests with two compatible systems, three or more systems, per-metric incompatible runs, incomplete runs, errors, duplicate runs, and missing optional scores or cost.
- Offline end-to-end test: fixture execution -> validation -> publication index -> comparison rendering.

## Remaining Open Decisions

- The maximum systems shown simultaneously in case detail; four is the proposed initial limit.
- Whether historical pricing tables should be downloadable from the public site.
