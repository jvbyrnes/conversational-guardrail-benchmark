# Delta for Benchmark Runner

## ADDED Requirements

### Requirement: Pinned WildJailbreak source

The system SHALL load WildJailbreak using an immutable configured dataset revision and SHALL record that revision with every run.

#### Scenario: Dataset is loaded

- **GIVEN** a valid immutable WildJailbreak revision
- **WHEN** the runner prepares a benchmark
- **THEN** it loads data from that exact revision
- **AND** records the dataset name, revision, split, source schema fingerprint, and retrieval time

#### Scenario: Dataset revision is missing

- **GIVEN** no immutable revision is configured
- **WHEN** a run is requested
- **THEN** the system rejects the run before making model calls

### Requirement: Harmful-jailbreak label mapping

The system SHALL define the harmful-jailbreak task over adversarial examples only.

#### Scenario: Harmful adversarial example

- **GIVEN** an example labelled `adversarial_harmful`
- **WHEN** it is mapped for the harmful-jailbreak task
- **THEN** its ground truth is `true`

#### Scenario: Benign adversarial example

- **GIVEN** an example labelled `adversarial_benign`
- **WHEN** it is mapped for the harmful-jailbreak task
- **THEN** its ground truth is `false`

#### Scenario: Vanilla example

- **GIVEN** an example labelled `vanilla_harmful` or `vanilla_benign`
- **WHEN** it is considered for the harmful-jailbreak task
- **THEN** it is excluded rather than assigned a binary label

### Requirement: Adversarial-technique label mapping

The system SHALL map both adversarial classes to `true` and both vanilla classes to `false`.

#### Scenario: Adversarial example

- **GIVEN** an example labelled `adversarial_harmful` or `adversarial_benign`
- **WHEN** it is mapped for the adversarial-technique task
- **THEN** its ground truth is `true`

#### Scenario: Vanilla example

- **GIVEN** an example labelled `vanilla_harmful` or `vanilla_benign`
- **WHEN** it is mapped for the adversarial-technique task
- **THEN** its ground truth is `false`

### Requirement: Deterministic stratified sampling

The system SHALL accept a sample rate in `(0, 1]` and an integer seed and SHALL sample independently within each original-label stratum.

#### Scenario: Development sample is repeated

- **GIVEN** the same dataset revision, task, sample rate, and seed
- **WHEN** two samples are generated
- **THEN** they contain the same source IDs in the same order

#### Scenario: Full run is requested

- **GIVEN** a sample rate of `1.0`
- **WHEN** the sample is generated
- **THEN** every eligible example is included

#### Scenario: Sample cannot represent every class

- **GIVEN** a rate that would select no examples from a required stratum
- **WHEN** the run is validated
- **THEN** the system rejects it with an actionable error

### Requirement: Equivalent classifier definitions

The system SHALL store one versioned semantic classifier definition per task and use it across every adapter without changing the positive-class meaning.

#### Scenario: Multiple systems are evaluated

- **WHEN** Jev and an LLM baseline classify an example
- **THEN** both receive the same normalized conversation
- **AND** both answer the same semantic yes-or-no question
- **AND** the classifier-definition version is recorded

### Requirement: Provider-independent predictions

Every adapter SHALL return a boolean decision, optional score, latency, raw usage, cost estimate, model identifier, and typed error state.

#### Scenario: Provider call fails

- **WHEN** an adapter exhausts its retry policy
- **THEN** the record contains a typed error
- **AND** the failure is not silently converted into a prediction

### Requirement: Reproducible run metadata

The system SHALL record dataset and code revisions, task and classifier versions, sample rate/count, strata, seed, model identifiers and parameters, pricing version, timestamps, and run kind.

#### Scenario: Partial run is produced

- **GIVEN** a sample rate below `1.0`
- **WHEN** artifacts are generated
- **THEN** the run kind is `exploratory`

#### Scenario: Full run is produced

- **GIVEN** a sample rate of `1.0`
- **WHEN** artifacts are generated
- **THEN** the run kind is `publication`

### Requirement: Metrics, latency, and cost

For each task and system, the system SHALL calculate precision, recall, F1, accuracy, confusion counts, error count, coverage, p50/p95 latency, total cost, and cost per 1,000 examples.

#### Scenario: Aggregate metrics are calculated

- **GIVEN** completed prediction records
- **WHEN** aggregation runs
- **THEN** classification metrics use non-error predictions only
- **AND** coverage and errors are reported alongside them

### Requirement: Versioned result artifacts

The system SHALL write a run manifest, aggregate JSON, and per-example JSONL/CSV without publishing upstream prompt text by default.

#### Scenario: Artifacts are generated

- **WHEN** a run completes
- **THEN** per-example records reference stable source IDs
- **AND** aggregates can be recomputed from those records
- **AND** every artifact schema has an explicit version

### Requirement: Static result presentation

The system SHALL provide a static page showing quality, confusion counts, coverage, latency, cost, and reproducibility metadata from generated JSON.

#### Scenario: Exploratory result is displayed

- **GIVEN** an exploratory artifact
- **WHEN** the page renders it
- **THEN** a prominent exploratory label and exact sample count are shown

#### Scenario: Result is not current

- **GIVEN** a pinned revision different from supplied current-revision metadata
- **WHEN** the page renders it
- **THEN** it marks the result potentially stale
- **AND** it does not trigger a paid evaluation
