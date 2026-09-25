# Conversational Guardrail Benchmark

An open, reproducible comparison of TypeSafe AI Jev and general-purpose LLMs as conversational guardrail classifiers.

## Guardrails

The project will evaluate four binary classification tasks:

1. Harmful jailbreak attempts — WildJailbreak
2. Adversarial or jailbreak techniques — WildJailbreak
3. Abuse disclosures — SonderMind Guardrail Evals
4. Financial-advice detection — FinSafeGuard

Implementation proceeds in that order. WildJailbreak supports dataset loading, deterministic sampling, model execution, durable evidence, validated public bundles, and a static multi-run comparison page.

## Local development

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are required. The default test suite is fully offline:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy
```

Run the end-to-end fixture (no credentials or network access):

```bash
uv run guardrail-bench --config benchmark/config/fixture.yaml
```

Interactive runs show a progress bar on stderr, including completed predictions,
elapsed time, estimated time remaining, and the error count. Progress is disabled
automatically when stderr is redirected; use `--progress` to force it or
`--no-progress` to disable it explicitly.

Run the static result viewer from the repository root:

```bash
python -m http.server 8000
# open http://localhost:8000/site/
```

The viewer discovers `results/published/index.json`. An empty catalogue displays an
explicit no-results state. The legacy `results/published/latest/` directory is retained
for old consumers; it is not a discovery source or part of the deployable export.

## Validation and multi-run comparison

Run the offline fixture, then inspect its publication eligibility:

```bash
uv run guardrail-bench --config benchmark/config/fixture.yaml
uv run guardrail-bench validate results/runs/<run-id>
```

Each new run persists its authoritative selected cohort before inference and records
configured-system and task-content identities. Git commit, committed tree, and working
tree status are captured immediately before execution. A modified, untracked, staged,
or unavailable source tree makes the run preview-only. Commit the implementation and
use a clean checkout before generating evidence intended for public comparison.
Validation also checks expected cohort-by-system coverage, duplicates, identities,
aggregate reconstruction, and cost provenance. Provider errors remain terminal rows
and reduce coverage; they never become negative decisions.

To publish a validated run, provision a stable secret in `GUARDRAIL_PSEUDONYM_KEY`
through your environment or secret manager, then run:

```bash
uv run guardrail-bench publish results/runs/<run-id> --pseudonym-key-id production-v1
uv run guardrail-bench index
uv run guardrail-bench validate results/published/runs/<run-id> --public
```

The key is required and never written into public artifacts. Keep it stable within
the named namespace; intentional rotation must use a new key ID. Rotation changes
public case IDs and cohort compatibility. Public records contain HMAC pseudonyms,
approved labels, typed error categories, standardized usage, timing and nullable cost.
Source IDs, conversations, provider payloads, free-form errors and credentials remain
private. Publication preserves the original evidence and rejects a conflicting bundle
at an existing run path. Index generation is separate and deterministic: timestamps
come from immutable publication metadata, and every bundle file is checksummed.

Create a sanitized local catalogue for runs excluded from publication:

```bash
uv run guardrail-bench index --preview-root results/preview --source results/runs/<run-id>
# Open http://localhost:8000/site/?preview=1
```

Preview metadata contains safe validation summaries; invalid evidence does not gain
public artifact links. Do not deploy the repository root. Build a fresh static export
that validates indexed artifacts and includes only the viewer and public bundles:

```bash
uv run guardrail-bench export-site /tmp/guardrail-public-site
python -m http.server 8000 --directory /tmp/guardrail-public-site
# Open http://localhost:8000/site/
```

The exporter excludes `results/preview/`, raw runs, the legacy alias, and all other
repository files. It refuses an existing output directory or a checksum mismatch.
It prepares all files before atomically creating the destination.

In the viewer, select a task/cohort, then two or more systems and an explicit reference.
Shared URLs pin exact run IDs. Duplicate results default to the latest completed valid
publication run, with a lexicographic run-ID tie break; alternatives remain selectable.
Quality, cost, and latency have independent eligibility and compatibility checks.
Different cohorts or task definitions disable all three comparisons; pricing or
execution differences disable only the relevant family. When some calls lack cost,
the site shows the sum of known per-case costs as a lower bound with its coverage;
the complete total remains unavailable for rankings and deltas. Missing cost is
never treated as zero. Case filters expose disagreements, correctness, errors and
source strata without exposing upstream conversation text. Provenance panels
explain each result.

## Legacy migration and schema policy

Migration is a dry run by default. It must replay the recorded selection against the
pinned dataset using the known sampler; predictions cannot supply the expected cohort.
The checked-in legacy fixture demonstrates the compatibility report:

```bash
uv run guardrail-bench migrate results/published/latest --config benchmark/config/fixture.yaml
```

It currently reports `migration.dataset_mismatch`: the fixture's observed schema has
changed since that artifact was recorded, so its authoritative cohort cannot be
replayed safely. For a compatible v1 run, review the dry-run report and then add
`--write` to create preview-only normalized evidence.

Written migration output defaults to `results/preview/migrated/`. The original files
remain byte-for-byte unchanged. Historical snapshot or working-tree evidence is never
invented. An unexplained legacy zero cost becomes null/unavailable, and missing clean
code evidence keeps the migration preview-only. Compatibility failures report which
independent evidence is needed. A dry run does not start inference.

Raw evidence, normalized comparison contracts, and catalogue schemas are versioned
independently. Readers reject unsupported major versions and unknown fields. Changes
to the meaning of normalized artifacts require a semantics-major change; post-hoc
metric changes alter metric compatibility, while prompt, label-map, threshold and
parser changes alter evaluation identity. Configured-system fingerprints include known
output-affecting parameters and versioned adapter defaults. Identity bytes use RFC 8785
canonical JSON and SHA-256, preserving explicit nulls and array order.

For a live run, copy `benchmark/config/live.example.yaml`, accept the WildJailbreak
dataset's AI2 Responsible Use Guidelines on Hugging Face, then authenticate locally:

```bash
hf auth login
```

The Hugging Face libraries automatically use the credential stored by that command.
For ephemeral or CI environments, provide a fine-grained User Access Token with
gated-repository read access as `HF_TOKEN` instead. Enable only the model adapters you
intend to pay for. The example is pinned to a verified immutable upstream revision
and uses the `train` configuration. The runner rejects mutable revisions before model
calls. Use `--sample-rate 0.01` for an exploratory run or `--sample-rate 1.0` for a
publication run. A live run also requires both `execution.cost_cap_usd` and a
`cost_reservation_usd` on every enabled paid adapter; the runner rejects missing or
undersized controls before loading data or making model calls. The cap may be
overridden explicitly with `--cost-cap-usd`.

To read a previously downloaded copy of the pinned WildJailbreak training TSV, set
`dataset.source: cached` in a copy of the live YAML. This mode uses only the matching
revision in the Hugging Face Hub cache and fails before model calls if the file is
absent. It still scans the entire TSV locally to form the deterministic sample. The
default `dataset.source: stream` retains the remote loader. The cached mode currently
supports only the WildJailbreak `train` configuration and split.

Every initial paid call and retry atomically reserves its full configured allowance
before the request starts. When a provider returns a finite, non-negative billed cost
that does not exceed the reservation, that reservation is reconciled to actual spend,
making the unused allowance available to later calls. Missing or untrustworthy billing
metadata keeps the reservation held, so it cannot reopen budget accidentally. Paid
calls pass through one gate: cap exhaustion, an HTTP 402/recognizable insufficient-
credit response, invalid reported cost, or a reported charge above its reservation
prevents later provider requests. Select a conservative reservation from current
pricing, maximum input size, output-token limits, and any provider extras.

Run manifests distinguish `cost_admitted_usd` (the cumulative reservations admitted),
`cost_reserved_usd` (the current amount held against the cap, including unreconciled
reservations), and `cost_actual_usd` (valid provider-reported spend). Missing billing
data remains included in the held amount but is excluded from actual spend. Each
prediction also records its reconciled provider charge separately from its nullable
total cost: a retry can have a known charge while an earlier attempt has unknown
billing. Validation sums these reconciled charges against the manifest actual spend.

The four configs in `benchmark/config/development/` run the pinned 1% cohort for
each WildJailbreak task and adapter. They use the local cached TSV, the same seed,
one paid attempt per case, and no retries. The harmful task selects 1,614 cases;
the technique task selects 2,614. Jev does not report billed USD, so its full
`$0.001` per-call reservations remain held: the Jev caps are `$1.614` and `$2.614`.
The Jev reservation is about 25 times the largest input-only estimate in the
completed 484-case run; TypeSafe's published input price is `$0.042` per million
tokens, but account-specific charges may differ. OpenRouter reports billed cost,
allowing unused reservations to be released. Its `$0.005` per-call reservation is
about 14 times the largest reported charge in the completed 484-case run. The
OpenRouter caps of `$8.07` and `$13.07` cover every reservation even if calls do not
report billed cost. These caps are admission limits, not forecasts or provider-side
spending limits. Review them before running with your own keys.

This process-local cap controls which calls the runner admits; it cannot undo a single
provider charge that violates the configured reservation. Use a dedicated provider key
with a matching provider-side spending limit as the external hard stop. The checked-in
values are examples to review, not price guarantees. No live smoke test has been run as
part of the offline implementation.

Secrets are read only from the environment:

- `TYPESAFE_API_KEY` for TypeSafe AI Jev;
- `OPENROUTER_API_KEY` for the default OpenRouter baseline;
- `HF_TOKEN` for the gated WildJailbreak dataset in ephemeral or CI environments;
  local development can use the credential stored by `hf auth login` instead.

OpenRouter uses its OpenAI-compatible chat-completions endpoint. Model names retain
their OpenRouter provider prefix (for example, `openai/gpt-4.1-mini`). The optional
`OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` variables populate OpenRouter's
attribution headers. Models used for this benchmark must support structured JSON
Schema output. OpenRouter request metadata supplies billed cost; the runner records
that value when available, so model prices do not need to be maintained here.

Do not put secrets in YAML. `.env` is ignored, but the runner does not load it implicitly.

## Implementation decisions

- **Upstream pin:** the live configuration pins WildJailbreak commit
  `5ddc12a7894f842b0619b8e1c7ee496b198af009`, verified with its documented `train`
  configuration on 2026-09-20. The dataset is gated, so live loading additionally
  requires accepting the AI2 Responsible Use Guidelines and authenticating through
  `hf auth login` or `HF_TOKEN`. Fixture runs use the immutable local revision
  `fixture-v1`.
- **Upstream normalization:** the adapter accepts the documented/common label fields (`data_type`, `label`, or `source_label`), stable IDs when present, and either a message-list conversation or a prompt field. It fingerprints the observed source columns and fails closed on an unknown label or missing prompt.
- **Sampling:** each stratum receives `floor(size × rate)` rows. A run is rejected instead of silently rounding an empty stratum up to one, so the configured rate remains honest.
- **Jev integration:** the adapter uses Jev's typed `adecide` contract and preserves unavailable probability/usage fields as absent/zero rather than inventing them. The optional import is lazy so the offline suite remains dependency-free. Jev's package support changes independently, so a minimal paid smoke test is required after installing a compatible release.
- **LLM baseline:** OpenRouter's OpenAI-compatible Chat Completions API is the sole general-purpose baseline. The semantic task question is passed unchanged as the system instruction; only provider serialization differs.
- **Errors and cost:** exhausted errors remain typed records and are excluded from classification metrics. Coverage exposes their impact. Public costs are nullable with explicit provenance and known-cost coverage; raw usage remains available privately for reproducible recalculation.
- **Jev cost estimation:** Jev reports token counts rather than a billed dollar amount. The runner estimates Jev spend from the published $0.042 per million input-token rate, records that estimate separately from provider-reported actual cost, and retains reservations when token usage is unavailable. Gateway markup is not included in this estimate.
- **Live cost gate:** paid adapters require a run cap and conservative per-attempt reservations. The cap must cover one fully retried attempt for every enabled paid adapter, and every retry reserves again. Trustworthy provider-reported costs reconcile reservations to actual spend; missing or invalid billing data remains held fail-closed. Provider-reported overages and insufficient-funds responses stop later paid calls and mark the run incomplete.
- **Durable interruption state:** the runner creates `run-status.json` before adapter execution and fsyncs each completed prediction to `predictions.partial.jsonl`. Normal artifacts are still written for cap- or funds-stopped runs, but both their manifest and checkpoint are marked `incomplete` with a reason. An unexpected interruption leaves the already-checkpointed predictions available for diagnosis.
- **Publication:** `rate == 1.0` marks the run kind as publication. Eligibility additionally requires complete, valid, safe evidence from a clean source tree. Valid exploratory runs remain prominently labelled. The static site never launches evaluations.

## Terminology and implementation details

- **Versioned schemas** are the Pydantic contracts for benchmark configuration,
  predictions, manifests, and aggregate result files. They are not a dataset schema;
  `schema_version` lets readers reject incompatible artifact formats.
- **CLI overrides** are limited to `--sample-rate`, `--seed`, `--output-dir`, and `--cost-cap-usd`.
  They override those YAML values without changing the checked-in configuration.
- **Immutable live-revision validation** requires a live Hugging Face revision to be
  a full 40-character commit SHA rather than a movable branch or tag. Fixture files
  are exempt. This makes a later run fetch the same dataset snapshot.
- **Reproducibility metadata** includes the code revision, dataset name/revision,
  observed column fingerprint, task and classifier versions, sample rate and seed,
  per-label counts, adapter/model parameters, pricing-table version, and timestamps.
- **The two WildJailbreak tasks** reuse its four upstream labels. The harmful-
  jailbreak task evaluates adversarial harmful versus adversarial benign and excludes
  both vanilla labels. The technique task treats both adversarial labels as positive
  and both vanilla labels as negative.
- **Fixture/live loading** means tests can read the small checked-in JSONL file while
  real runs use the Hugging Face `datasets` loader at the pinned revision. Both paths
  normalize rows into the same internal conversation record.
- **Schema fingerprinting** hashes the sorted observed source column names and their
  Python value types. It detects an upstream structural change; it is not a hash of
  the dataset rows or their contents.
- **Per-label stratification** samples each eligible source label independently, so
  a class is not accidentally omitted. A minimum-stratum check rejects a rate when
  `floor(label_count × rate)` is zero for any required label.
- **The fake adapter** is a deterministic, offline-only test double. It recognizes
  markers in synthetic fixtures so runner, metrics, and artifact tests do not spend
  money or contact a provider; it is not a benchmarked guardrail.
- **Cost estimation** uses recorded usage and versioned pricing. Public aggregate cost
  is unavailable if any relevant row has unknown cost; known count and coverage remain
  visible. Legacy numeric estimate fields are not proof of known billing.
- **Cost reservations versus estimates:** reservations are conservative dispatch
  accounting and are recorded separately from provider-reported prediction cost. They
  are not substituted for missing provider cost, so aggregate cost remains evidence-
  based while the gate remains fail-closed.
- **Exploratory versus publication** is determined solely by sampling: any partial
  sample is exploratory and only a 100% sample is publication. The site highlights
  exploratory artifacts and marks results potentially stale when a supplied current
  dataset revision differs from the pinned evaluated revision.
- **`adecide`** is Jev's asynchronous typed decision function. It receives benchmark
  state plus the `_JevAnswer` Pydantic output type and returns a validated Boolean
  decision without blocking the async runner.

## Principles

- Use externally defined labels and pin every dataset revision.
- Give each system the same conversation and semantically equivalent classifier question.
- Keep benchmark definitions in configuration rather than hard-coded orchestration.
- Make sampled runs deterministic and stratified by label.
- Publish precision, recall, F1, confusion matrices, cost, and latency—not accuracy alone.
- Record enough metadata to reproduce each result.
- Never rerun paid evaluations automatically when an upstream dataset changes.
- Clearly distinguish exploratory sampled runs from publication runs.

## Planned changes

Reviewed sampled runs are the current milestone. The full WildJailbreak,
SonderMind, and FinSafeGuard runs are deferred to the final phase in
[`openspec/roadmap.md`](openspec/roadmap.md), after all three sampled benchmarks
have been assessed and their costs approved.

1. `wildjailbreak-vertical-slice`
2. WildJailbreak adversarial-technique refinements
3. SonderMind abuse-disclosure benchmark
4. FinSafeGuard financial-advice benchmark
5. Dataset revision monitoring and stale-result notifications
6. Public deployment and custom-domain hardening
7. Full runs for all three benchmark sets, with separate cost approval

## OpenSpec workflow

Install OpenSpec with Node.js 20.19 or newer:

```bash
npm install -g @fission-ai/openspec@latest
openspec validate wildjailbreak-vertical-slice
openspec validate multi-run-benchmark-comparison --strict
```

Review the active change and its remaining live-verification tasks in `openspec/changes/wildjailbreak-vertical-slice/` before running paid adapters.
