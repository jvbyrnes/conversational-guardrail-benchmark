# Tasks

## 1. Contract and Compatibility

- [ ] 1.1 Add strict canonical system, evaluation, evaluated-system, model snapshot status, task version, and metric version models
- [ ] 1.2 Define RFC 8785 canonical JSON and SHA-256 fingerprints with golden vectors for configured systems, task-definition content, and selected cohorts
- [ ] 1.3 Define quality, cost, and latency comparison-key models with per-family compatibility states and differing field paths
- [ ] 1.4 Add schema-major compatibility checks and document the versioning policy
- [ ] 1.5 Test each identity and comparison-key field independently, including task changes that do not bump a readable version

## 2. Artifact Validation

- [ ] 2.1 Add structured validation reports with stable rule IDs, errors, warnings, affected paths, and validator version
- [ ] 2.2 Validate required provenance and verify system/cohort fingerprints
- [ ] 2.3 Materialize and digest authoritative `cohort.json` before inference and validate the cohort-by-system Cartesian product
- [ ] 2.4 Validate expected prediction coverage and reject duplicate `(public_case_id, evaluated_system_id)` records
- [ ] 2.5 Recompute all aggregate metrics, latency, usage, cost coverage, and nullable cost from per-example records
- [ ] 2.6 Capture repository, commit, committed-tree digest, and clean/dirty/unavailable working-tree provenance and enforce public rankability
- [ ] 2.7 Define strict public DTOs, adapter-versioned safe-parameter allowlists, sanitized errors, and keyed pseudonymous case IDs with fail-closed provisioning and explicit rotation semantics
- [ ] 2.8 Verify artifact checksums and reject unknown or unsafe public fields
- [ ] 2.9 Add tests for a source missing from all systems, cohort tampering, missing provenance, duplicates, aggregate drift, invalid numbers, checksum mismatch, dirty trees, unsafe fields, and pseudonym consistency

## 3. Published Catalogue

- [ ] 3.1 Add strict models for a versioned published run index
- [ ] 3.2 Write validated runs to stable `results/published/runs/<run_id>/` bundles
- [ ] 3.3 Generate canonical byte-deterministic `results/published/index.json` atomically without wall-clock-derived fields
- [ ] 3.4 Generate sanitized opt-in `results/preview/index.json` outside the deployable root and test its deployment exclusion
- [ ] 3.5 Preserve exploratory, incomplete, stale, invalid, clean-code, and per-metric rankability states explicitly
- [ ] 3.6 Retain `latest` only as a documented compatibility alias during migration
- [ ] 3.7 Add byte-for-byte deterministic public and preview index generation, RFC 8785 ordering, stable timestamp/source-set digest, and checksum golden tests

## 4. Existing Artifact Migration

- [ ] 4.1 Implement a dry-run migration report for version-1 artifacts
- [ ] 4.2 Derive system and task-content evaluation identities without guessing unavailable model snapshots
- [ ] 4.3 Reconstruct and verify the authoritative cohort only by replaying recorded selection against the immutable dataset with a known sampler; never derive it from predictions
- [ ] 4.4 Migrate cost as known only from trustworthy serialized evidence or reproducible versioned calculation; otherwise emit null/unavailable
- [ ] 4.5 Treat legacy runs without clean working-tree evidence as preview-only and non-rankable
- [ ] 4.6 Write migrated bundles without modifying original run evidence
- [ ] 4.7 Test migration with checked-in fixtures, ambiguous zero costs, missing code state, and actionable failure cases

## 5. Multi-Run Results Site

- [ ] 5.1 Load the published index instead of hard-coding the `latest` aggregate
- [ ] 5.2 Add task/cohort selection and shareable multi-system selection that pins exact run IDs
- [ ] 5.3 Render the comparison summary matrix with an explicit reference system
- [ ] 5.4 Suppress deltas and rankings independently for incompatible quality, cost, or latency and explain differing fields
- [ ] 5.5 Add a public-case-ID-aligned case explorer with disagreement, correctness, label, and error filters
- [ ] 5.6 Add per-system provenance panels with exact model and version information
- [ ] 5.7 Keep upstream conversation text absent from the public UI and artifacts
- [ ] 5.8 Add responsive handling for more than two selected systems
- [ ] 5.9 Implement and disclose deterministic duplicate-run selection with explicit alternatives and override

## 6. Verification and Documentation

- [ ] 6.1 Add a second compatible fixture system plus pricing-, execution-, cohort-, task-, and schema-incompatible fixtures
- [ ] 6.2 Extend the offline end-to-end test through validation, index generation, and site rendering
- [ ] 6.3 Add static-site tests for two systems, three or more systems, missing scores/costs, errors, preview-only states, duplicates, and per-metric non-comparability
- [ ] 6.4 Document validation, migration, publication, and local comparison commands
- [ ] 6.5 Validate this OpenSpec change
- [ ] 6.6 Run two minimal real-adapter smoke tests under explicit cost caps only after all publication gates pass
- [ ] 6.7 Run the deterministic 1% development benchmark and review errors before seeking approval for a full run
