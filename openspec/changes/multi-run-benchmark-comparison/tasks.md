# Tasks

## 1. Contract and Compatibility

- [ ] 1.1 Add strict canonical system identity, model snapshot status, task version, and metric version models
- [ ] 1.2 Define canonical JSON serialization and SHA-256 fingerprints for configured systems and selected source-ID cohorts
- [ ] 1.3 Define the comparison-key model and direct-comparability function
- [ ] 1.4 Add schema-major compatibility checks and document the versioning policy
- [ ] 1.5 Test each identity and comparison-key field independently

## 2. Artifact Validation

- [ ] 2.1 Add structured validation reports with stable rule IDs, errors, warnings, affected paths, and validator version
- [ ] 2.2 Validate required provenance and verify system/cohort fingerprints
- [ ] 2.3 Validate expected prediction coverage and reject duplicate `(source_id, system_id)` records
- [ ] 2.4 Recompute all aggregate metrics, latency, usage, and cost from per-example records
- [ ] 2.5 Verify artifact checksums and publication-safe field policy
- [ ] 2.6 Add tests for missing provenance, duplicates, missing records, aggregate drift, invalid numbers, checksum mismatch, and unsafe fields

## 3. Published Catalogue

- [ ] 3.1 Add strict models for a versioned published run index
- [ ] 3.2 Write validated runs to stable `results/published/runs/<run_id>/` bundles
- [ ] 3.3 Generate `results/published/index.json` atomically from validated bundles
- [ ] 3.4 Preserve exploratory, incomplete, stale, invalid, and rankable states explicitly
- [ ] 3.5 Retain `latest` only as a documented compatibility alias during migration
- [ ] 3.6 Add deterministic index-generation and checksum tests

## 4. Existing Artifact Migration

- [ ] 4.1 Implement a dry-run migration report for version-1 artifacts
- [ ] 4.2 Derive system identity without guessing unavailable model snapshots
- [ ] 4.3 Derive and verify the selected source-ID cohort digest
- [ ] 4.4 Write migrated bundles without modifying original run evidence
- [ ] 4.5 Test migration with the checked-in fixture artifacts and actionable failure cases

## 5. Multi-Run Results Site

- [ ] 5.1 Load the published index instead of hard-coding the `latest` aggregate
- [ ] 5.2 Add task/cohort selection and shareable multi-system selection
- [ ] 5.3 Render the comparison summary matrix with an explicit reference system
- [ ] 5.4 Suppress deltas and rankings for incompatible or invalid selections and explain differing fields
- [ ] 5.5 Add a source-ID-aligned case explorer with disagreement, correctness, label, and error filters
- [ ] 5.6 Add per-system provenance panels with exact model and version information
- [ ] 5.7 Keep upstream conversation text absent from the public UI and artifacts
- [ ] 5.8 Add responsive handling for more than two selected systems

## 6. Verification and Documentation

- [ ] 6.1 Add a second compatible fixture system and fixtures for incompatible runs
- [ ] 6.2 Extend the offline end-to-end test through validation, index generation, and site rendering
- [ ] 6.3 Add static-site tests for two systems, three or more systems, missing scores, errors, and non-comparable states
- [ ] 6.4 Document validation, migration, publication, and local comparison commands
- [ ] 6.5 Validate this OpenSpec change
- [ ] 6.6 Run two minimal real-adapter smoke tests under explicit cost caps only after all publication gates pass
- [ ] 6.7 Run the deterministic 1% development benchmark and review errors before seeking approval for a full run
