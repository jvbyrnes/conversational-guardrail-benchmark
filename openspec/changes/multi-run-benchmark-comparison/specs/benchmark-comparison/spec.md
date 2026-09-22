# Delta for Benchmark Comparison

## ADDED Requirements

### Requirement: Canonical system identity

The system SHALL assign every evaluated system a canonical identity containing adapter, provider, model ID, model snapshot status, output-affecting parameters, and a deterministic configuration fingerprint.

#### Scenario: Provider exposes an immutable snapshot

- **GIVEN** a provider exposes an immutable model snapshot
- **WHEN** the run manifest is created
- **THEN** the snapshot is recorded with status `immutable`
- **AND** it contributes to the configuration fingerprint

#### Scenario: Provider does not expose an immutable snapshot

- **GIVEN** only a mutable model alias is available
- **WHEN** the run manifest is created
- **THEN** the alias is recorded with status `provider_alias` or `unavailable` as appropriate
- **AND** the system does not claim an immutable version
- **AND** the run timestamp and all known configuration remain visible

#### Scenario: Friendly labels collide

- **GIVEN** two systems have the same display name but different canonical identity fields
- **WHEN** results are indexed
- **THEN** they remain distinct systems

### Requirement: Deterministic comparison identity

The system SHALL derive a comparison key from dataset, task, classifier, cohort, metric, and schema-version fields that materially affect comparability.

#### Scenario: Equivalent runs are selected

- **GIVEN** two valid results have identical comparison-key fields
- **WHEN** the site compares them
- **THEN** it may display deltas and rank their metrics

#### Scenario: Selected source cohorts differ

- **GIVEN** two results have different selected source-ID cohort digests
- **WHEN** the site compares them
- **THEN** it labels them non-comparable
- **AND** suppresses rankings, winner language, and metric deltas
- **AND** identifies the cohort as a differing field

#### Scenario: Classifier versions differ

- **GIVEN** two results use different classifier versions
- **WHEN** the site compares them
- **THEN** it labels them non-comparable even if their task IDs match

### Requirement: Structured pre-publication validation

The system SHALL validate schemas, provenance, completeness, uniqueness, aggregate consistency, checksums, and publication safety before a result becomes rankable.

#### Scenario: Provenance is complete

- **GIVEN** a run contains all required immutable or explicitly unavailable identity fields
- **WHEN** validation runs
- **THEN** provenance validation succeeds
- **AND** the report records the validator version

#### Scenario: Model identity is ambiguous

- **GIVEN** a run omits its canonical model ID or snapshot status
- **WHEN** validation runs
- **THEN** validation fails with a stable rule ID and affected field path
- **AND** the run is not rankable

#### Scenario: Prediction records are duplicated

- **GIVEN** two predictions have the same source ID and system identity in one run
- **WHEN** validation runs
- **THEN** completeness validation fails
- **AND** neither record is silently selected

#### Scenario: An expected prediction failed at the provider

- **GIVEN** a provider request exhausted its retry policy
- **WHEN** completeness validation runs
- **THEN** the typed error record satisfies row presence
- **AND** it reduces coverage rather than becoming a negative decision

#### Scenario: Aggregate values drift

- **GIVEN** a stored aggregate differs from values recomputed from per-example records beyond declared tolerance
- **WHEN** validation runs
- **THEN** validation fails
- **AND** the report identifies each inconsistent metric

#### Scenario: A published field contains sensitive data

- **GIVEN** an artifact contains a credential, secret header, upstream conversation text, or unapproved raw provider payload
- **WHEN** publication validation runs
- **THEN** publication is rejected

### Requirement: Versioned published run index

The system SHALL generate a versioned index of validated run bundles for static-site discovery.

#### Scenario: Valid runs are indexed

- **GIVEN** one or more validated published bundles
- **WHEN** the index is generated
- **THEN** every entry includes run state, comparison key, system summaries, artifact URIs, and artifact digests
- **AND** index generation is deterministic for the same inputs

#### Scenario: Invalid run is encountered

- **GIVEN** a bundle fails validation
- **WHEN** the public index is generated
- **THEN** the run is excluded from rankable results
- **AND** the generation report explains the exclusion

#### Scenario: Existing latest alias remains

- **GIVEN** version-1 consumers still use `results/published/latest`
- **WHEN** the new index is introduced
- **THEN** the alias may remain during a documented migration period
- **AND** the comparison site discovers runs from the index

### Requirement: Immutable evidence and derived comparison data

The system SHALL preserve original run evidence and generate normalized, indexed, and comparison artifacts without overwriting it.

#### Scenario: Existing run is migrated

- **GIVEN** a supported version-1 run artifact
- **WHEN** migration executes
- **THEN** it writes a new validated published bundle
- **AND** leaves the original run files byte-for-byte unchanged

#### Scenario: Snapshot metadata is absent during migration

- **GIVEN** a legacy artifact lacks an immutable model snapshot
- **WHEN** migration executes
- **THEN** it records the snapshot as unavailable
- **AND** does not infer a snapshot from the current provider state

### Requirement: Multi-system summary comparison

The static site SHALL allow a user to select two or more systems for one comparison cohort and view their quality, coverage, latency, cost, run state, and identity together.

#### Scenario: Two compatible systems are selected

- **WHEN** the comparison page renders
- **THEN** it shows aligned metrics in a summary matrix
- **AND** identifies the reference system used for deltas
- **AND** displays exact model IDs and snapshot statuses

#### Scenario: More than two systems are selected

- **WHEN** the comparison page renders
- **THEN** the summary remains usable without truncating system identity
- **AND** the detail view uses a bounded or scrollable layout

#### Scenario: Missing metric is displayed

- **GIVEN** a valid system does not expose an optional score or cost field
- **WHEN** the page renders it
- **THEN** the value appears as unavailable
- **AND** is not treated as zero

### Requirement: Source-aligned case comparison

The static site SHALL align per-example predictions by stable source ID and support inspection of disagreements, errors, correctness, and source-label strata without publishing conversation text.

#### Scenario: Systems disagree

- **GIVEN** selected systems return different decisions for a source ID
- **WHEN** the user filters to disagreements
- **THEN** the case is listed with ground truth and each system decision

#### Scenario: One system errors

- **GIVEN** one selected system has a typed error and another has a prediction
- **WHEN** the case is displayed
- **THEN** the error remains visually distinct from both boolean decisions
- **AND** latency, usage, and cost are shown when available

#### Scenario: User opens provenance

- **WHEN** the user opens provenance for a selected result
- **THEN** the page shows run, system, dataset, task, classifier, cohort, code, pricing, schema, validation, and timestamp metadata

### Requirement: Explicit comparison states

The site SHALL distinguish validity, completeness, publication kind, staleness, and comparability as separate states.

#### Scenario: Exploratory run is compared

- **GIVEN** a valid run has a sample rate below `1.0`
- **WHEN** it is displayed
- **THEN** it has a prominent exploratory label and exact cohort details

#### Scenario: Incomplete run is displayed

- **GIVEN** a run has incomplete status
- **WHEN** it is displayed in an allowed preview context
- **THEN** it is visibly incomplete and non-rankable
- **AND** its incomplete reason is shown

#### Scenario: Valid result is potentially stale

- **GIVEN** a valid result's pinned revision differs from current-revision metadata
- **WHEN** it is displayed
- **THEN** validity remains distinct from the potentially-stale warning
- **AND** no paid rerun is triggered
