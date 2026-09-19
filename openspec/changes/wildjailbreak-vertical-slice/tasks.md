# Tasks

## 1. Project Foundation

- [ ] 1.1 Initialize a Python 3.12 `uv` project and package layout
- [ ] 1.2 Add typed configuration models and YAML loading with CLI overrides
- [ ] 1.3 Add linting, type checking, pytest, and a network-free default test command
- [ ] 1.4 Add `.gitignore` rules for secrets, caches, downloaded datasets, and unpublished runs
- [ ] 1.5 Document local setup and environment-variable names without committing secrets

## 2. Common Schemas and Definitions

- [ ] 2.1 Define normalized conversation, source example, task definition, prediction, run manifest, and aggregate result schemas
- [ ] 2.2 Define schema-version constants and compatibility checks
- [ ] 2.3 Create versioned harmful-jailbreak and adversarial-technique classifier definitions
- [ ] 2.4 Test schema validation and serialization round trips

## 3. WildJailbreak Integration

- [ ] 3.1 Inspect the upstream dataset release and select an immutable revision and exact split/configuration
- [ ] 3.2 Implement the dataset adapter and upstream schema validation
- [ ] 3.3 Implement both explicit source-label mappings
- [ ] 3.4 Add small synthetic or license-compatible fixtures covering all four classes
- [ ] 3.5 Test eligible, positive, negative, and excluded cases for each task

## 4. Sampling and Run Preparation

- [ ] 4.1 Implement deterministic source-ID-based ordering
- [ ] 4.2 Implement stratification by original source label
- [ ] 4.3 Validate sample rates and minimum stratum representation
- [ ] 4.4 Record eligible/selected stratum counts and run kind
- [ ] 4.5 Test repeated sampling, full sampling, changed seeds, and invalid small samples

## 5. Model Adapters

- [ ] 5.1 Define the asynchronous model-adapter protocol
- [ ] 5.2 Implement a fake adapter for offline tests
- [ ] 5.3 Implement the TypeSafe AI Jev adapter after confirming the supported API contract
- [ ] 5.4 Implement one structured-output LLM adapter
- [ ] 5.5 Add bounded concurrency, retry policy, timeouts, and typed errors
- [ ] 5.6 Verify that adapters use the same normalized conversation and semantic classifier definition
- [ ] 5.7 Test adapter parsing, usage capture, failures, and retry exhaustion

## 6. Metrics, Cost, and Artifacts

- [ ] 6.1 Implement confusion matrix, precision, recall, F1, accuracy, coverage, and error counts
- [ ] 6.2 Implement p50/p95 latency and wall-clock duration reporting
- [ ] 6.3 Implement versioned pricing configuration and cost calculation
- [ ] 6.4 Write run manifest, aggregate JSON, and per-example JSONL/CSV
- [ ] 6.5 Ensure publishable artifacts omit upstream conversation text by default
- [ ] 6.6 Test metric calculations and verify aggregates can be reconstructed from per-example output

## 7. Static Results Site

- [ ] 7.1 Build a framework-free page that reads aggregate JSON
- [ ] 7.2 Display system comparison metrics, confusion counts, coverage, latency, and cost
- [ ] 7.3 Display dataset revision, classifier version, model IDs, sample rate/count, seed, and run dates
- [ ] 7.4 Add prominent exploratory and potentially-stale states
- [ ] 7.5 Link downloadable aggregate and per-example artifacts
- [ ] 7.6 Add a local static-site smoke test

## 8. End-to-End Verification

- [ ] 8.1 Run the offline fixture through preparation, fake adapters, aggregation, and site artifact generation
- [ ] 8.2 Run a minimal live smoke test for each configured real adapter with an explicit cost cap
- [ ] 8.3 Run a deterministic 1% development benchmark for both WildJailbreak tasks
- [ ] 8.4 Review errors and label-mapping samples before any full run
- [ ] 8.5 Run the full publication benchmark only after explicit human approval
- [ ] 8.6 Validate the OpenSpec change and record exact reproduction commands
