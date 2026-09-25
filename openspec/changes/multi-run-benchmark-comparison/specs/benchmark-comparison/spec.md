# Delta for Benchmark Comparison

## ADDED Requirements

### Requirement: Canonical system identity

The system SHALL assign every configured system a canonical identity containing adapter and adapter version, provider, requested model ID, resolved snapshot when available, snapshot status, effective output-affecting parameters and defaults, request mode, and a deterministic configuration fingerprint.

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

#### Scenario: The same system evaluates different tasks

- **GIVEN** one configured system evaluates two different task questions or label mappings
- **WHEN** identities are derived
- **THEN** both results retain the same `system_id`
- **AND** receive different task-content-derived `evaluation_id` values
- **AND** receive different combined `evaluated_system_id` values

### Requirement: Authoritative evaluation identity

The system SHALL derive evaluation identity from canonical inference/task-definition content including task ID, semantic question, label mapping, decision threshold, and parser/classifier version; post-hoc metric definitions SHALL remain in comparison identity rather than system or evaluation identity.

#### Scenario: Task content changes without a readable version bump

- **GIVEN** a task question or label mapping changes while its readable version is unchanged
- **WHEN** evaluation identity is recomputed
- **THEN** the evaluation ID changes
- **AND** the results cannot be conflated or quality-ranked directly

### Requirement: Deterministic comparison identity

The system SHALL derive separate quality, cost, and latency comparison keys from the fields that materially affect each metric family and report differing field paths.

#### Scenario: Equivalent runs are selected

- **GIVEN** two valid results have identical quality, cost, and latency key fields
- **WHEN** the site compares them
- **THEN** it may display deltas and rankings for all three metric families

#### Scenario: Selected source cohorts differ

- **GIVEN** two results have different authoritative public cohort digests or pseudonym key IDs
- **WHEN** the site compares them
- **THEN** it labels quality, cost, and latency non-comparable
- **AND** suppresses rankings, winner language, and metric deltas for all three families because cost and latency keys embed the quality key
- **AND** identifies the cohort as a differing field

#### Scenario: Classifier versions differ

- **GIVEN** two results use different classifier versions
- **WHEN** the site compares them
- **THEN** it labels quality, cost, and latency non-comparable even if their task IDs match
- **AND** suppresses rankings and deltas for all three families because cost and latency keys embed the quality key

#### Scenario: Pricing methods differ

- **GIVEN** two results have the same quality key but different pricing versions, billing methods, or currencies
- **WHEN** the site compares them
- **THEN** quality rankings and deltas may remain available
- **AND** cost rankings and deltas are suppressed with exact differing fields

#### Scenario: Cost coverage is incomplete

- **GIVEN** a result has known cost comparison-key provenance but cost coverage below `1.0`
- **WHEN** rankability is derived
- **THEN** its cost key retains the provenance identity
- **AND** its per-result cost rankability is ineligible with reason `incomplete_cost_coverage`

#### Scenario: Execution conditions differ

- **GIVEN** two results have the same quality key but different timing definitions, concurrency, retry/timeout policy, routing or region class, or warm-up policy
- **WHEN** the site compares them
- **THEN** quality rankings and deltas may remain available
- **AND** latency rankings and deltas are suppressed with exact differing fields

### Requirement: Independently persisted cohort

The system SHALL write and digest an authoritative cohort manifest from dataset selection before any model request and SHALL derive expected predictions by combining the run evaluation ID with manifest-declared system IDs, then taking the Cartesian product of cohort members and those evaluated-system IDs.

#### Scenario: A source is missing from every system

- **GIVEN** an authoritative cohort member has no prediction row for any system
- **WHEN** completeness validation runs
- **THEN** validation fails for every missing expected identity
- **AND** the cohort is not reconstructed from the remaining predictions

#### Scenario: Cohort membership is tampered with

- **GIVEN** a published cohort member or its ground truth differs from the digested manifest
- **WHEN** validation runs
- **THEN** validation fails with a stable cohort-integrity rule ID

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

- **GIVEN** two published predictions have the same public case ID and evaluated-system identity in one run
- **WHEN** validation runs
- **THEN** completeness validation fails
- **AND** neither record is silently selected

#### Scenario: Published predictions retain result identity

- **GIVEN** a validated run contains predictions from one or more configured systems
- **WHEN** the strict public prediction DTO is projected
- **THEN** every record includes its `evaluated_system_id`
- **AND** records can be grouped and checked for uniqueness by `(public_case_id, evaluated_system_id)`
- **AND** projection or validation fails when that identity is missing

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

#### Scenario: Published cost is only partially known

- **GIVEN** any relevant prediction has unavailable cost
- **WHEN** aggregate validation runs
- **THEN** total cost and cost per 1,000 examples are unavailable rather than partial or zero
- **AND** cost known count and cost coverage are reported
- **AND** per-result cost rankability is ineligible unless cost coverage equals `1.0`
- **AND** the cost key is null only when required cost-provenance fields are unavailable

#### Scenario: Code provenance is dirty or unavailable

- **GIVEN** a run cannot prove a clean committed source tree
- **WHEN** publication validation runs
- **THEN** it is non-rankable and excluded from the public index
- **AND** it may be described in the preview index

#### Scenario: Clean code provenance is captured

- **GIVEN** `git rev-parse HEAD` and `git rev-parse HEAD^{tree}` succeed from the repository root
- **AND** `git status --porcelain=v1 --untracked-files=all --ignore-submodules=none` succeeds with empty output immediately before execution
- **WHEN** code provenance is captured
- **THEN** the run records the returned commit revision and committed-tree digest
- **AND** `working_tree_state` is `clean`

#### Scenario: A source-tree change is detected

- **GIVEN** Git reports any staged, unstaged, untracked, or modified-submodule status entry immediately before execution
- **WHEN** code provenance is captured
- **THEN** `working_tree_state` is `dirty`
- **AND** the run is preview-only and non-rankable

#### Scenario: Git evidence is unavailable

- **GIVEN** the source directory is not a Git work tree, a required Git command fails, or its output is missing or malformed
- **WHEN** code provenance is captured
- **THEN** `working_tree_state` is `unavailable`
- **AND** the run is preview-only and non-rankable

#### Scenario: A published field contains sensitive data

- **GIVEN** an artifact contains a credential, secret header, upstream conversation text, or unapproved raw provider payload
- **WHEN** publication validation runs
- **THEN** publication is rejected

#### Scenario: A public prediction contains an unknown field

- **GIVEN** a projected prediction contains an internal source ID, free-form error message, arbitrary provider field, request ID, or any field outside the versioned allowlist
- **WHEN** publication validation runs
- **THEN** strict schema validation rejects it

#### Scenario: A public case identifier is generated

- **GIVEN** an internal source ID is selected
- **WHEN** the public cohort and predictions are projected
- **THEN** they use the same HMAC-SHA-256 pseudonymous case ID scoped by dataset identity
- **AND** publish the pseudonym key identifier but neither the key nor internal source ID

#### Scenario: Pseudonym key material is unavailable or rotates

- **GIVEN** the configured namespace key is unavailable
- **WHEN** public projection is requested
- **THEN** publication fails closed before writing public artifacts
- **AND** when a new key ID is intentionally introduced, its cases form a new non-comparable alignment namespace

### Requirement: Versioned published run index

The system SHALL generate byte-deterministic versioned public and preview indexes for static-site discovery.

#### Scenario: Valid runs are indexed

- **GIVEN** one or more validated published bundles
- **WHEN** the index is generated
- **THEN** every entry includes run state, system summaries, artifact URIs, and artifact digests
- **AND** every system summary includes `system_id`, `evaluated_system_id`, metric-family comparison keys, and per-metric rankability state
- **AND** index generation is deterministic for the same inputs

#### Scenario: Systems in one run have different rankability

- **GIVEN** a multi-system run in which one system has complete cost provenance and another does not
- **WHEN** the index is generated
- **THEN** the first system summary has a non-null cost key and rankable cost state
- **AND** the second system summary has a null cost key and ineligible cost state with a stable reason
- **AND** neither system inherits the other's comparison keys or rankability

#### Scenario: An index is regenerated from identical bundles

- **GIVEN** the same validated bundle bytes and publication metadata
- **WHEN** index generation runs more than once
- **THEN** the resulting public index bytes are identical
- **AND** its `as_of` value is derived from immutable input metadata rather than the wall clock

#### Scenario: No bundle is publishable

- **GIVEN** no discovered bundle passes public-index validation
- **WHEN** the public index is generated
- **THEN** it contains an empty `runs` array and `as_of` is JSON `null`
- **AND** `source_set_digest` is the SHA-256 digest of the RFC-8785 canonical empty array
- **AND** generation succeeds deterministically

#### Scenario: The public index is empty

- **GIVEN** the site loads a valid public index with an empty `runs` array
- **WHEN** the comparison page renders
- **THEN** it shows an explicit no-published-results state
- **AND** it does not attempt to select a task, cohort, system, or reference result

#### Scenario: Invalid run is encountered

- **GIVEN** a bundle fails validation
- **WHEN** the public index is generated
- **THEN** the run is absent from the public index and excluded from rankable results
- **AND** the generation report explains the exclusion
- **AND** the public index exposes no URI for an unsafe artifact
- **AND** a non-sensitive validation summary may appear only in the preview index

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
- **THEN** it writes a normalized bundle in the public or preview namespace according to its validation and rankability outcome
- **AND** leaves the original run files byte-for-byte unchanged

#### Scenario: Snapshot metadata is absent during migration

- **GIVEN** a legacy artifact lacks an immutable model snapshot
- **WHEN** migration executes
- **THEN** it records the snapshot as unavailable
- **AND** does not infer a snapshot from the current provider state

#### Scenario: Legacy zero cost has no supporting evidence

- **GIVEN** a version-1 prediction contains zero cost but lacks trustworthy billing evidence or enough versioned usage data to recompute it
- **WHEN** migration executes
- **THEN** cost is migrated as unavailable and null
- **AND** zero is not treated as a known measured value

#### Scenario: Legacy cleanliness cannot be proven

- **GIVEN** a legacy artifact records a commit but not working-tree state
- **WHEN** migration executes
- **THEN** the run is preview-only and non-rankable
- **AND** migration does not assume the working tree was clean

#### Scenario: Legacy cohort cannot be reconstructed independently

- **GIVEN** a legacy artifact's immutable dataset and recorded selection cannot be replayed with a known sampling algorithm
- **WHEN** migration executes
- **THEN** prediction rows are not accepted as the authoritative expected cohort
- **AND** migration emits an actionable compatibility error and keeps the run preview-only

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

#### Scenario: Duplicate results exist for one evaluated system and cohort

- **GIVEN** multiple valid complete publication runs share a quality key and evaluated-system ID
- **WHEN** no run is explicitly selected
- **THEN** the run with greatest completion timestamp is selected
- **AND** a timestamp tie is resolved by lexicographic run ID
- **AND** alternatives and the selection rule are visible
- **AND** an explicit override pins exact run IDs in the shareable URL

#### Scenario: Missing metric is displayed

- **GIVEN** a valid system does not expose an optional score or cost field
- **WHEN** the page renders it
- **THEN** the value appears as unavailable
- **AND** is not treated as zero

#### Scenario: Some per-case costs are known

- **GIVEN** a valid result has known per-case costs but incomplete cost coverage
- **WHEN** the page renders its cost summary
- **THEN** it shows the sum of known costs as a lower bound with the known and total case counts
- **AND** keeps total-cost rankings and deltas unavailable

### Requirement: Source-aligned case comparison

The static site SHALL align per-example predictions by stable public case ID and support inspection of disagreements, errors, correctness, and source-label strata without publishing internal source IDs or conversation text.

#### Scenario: Systems disagree

- **GIVEN** selected systems return different decisions for a public case ID
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
- **WHEN** it is displayed from the opt-in preview index
- **THEN** it is visibly incomplete and non-rankable
- **AND** its incomplete reason is shown
- **AND** it is absent from the public index

#### Scenario: Valid result is potentially stale

- **GIVEN** a valid result's pinned revision differs from current-revision metadata
- **WHEN** it is displayed
- **THEN** validity remains distinct from the potentially-stale warning
- **AND** no paid rerun is triggered
