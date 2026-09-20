# Conversational Guardrail Benchmark

An open, reproducible comparison of TypeSafe AI Jev and general-purpose LLMs as conversational guardrail classifiers.

## Guardrails

The project will evaluate four binary classification tasks:

1. Harmful jailbreak attempts — WildJailbreak
2. Adversarial or jailbreak techniques — WildJailbreak
3. Abuse disclosures — SonderMind Guardrail Evals
4. Financial-advice detection — FinSafeGuard

Implementation proceeds in that order. The first change is an end-to-end WildJailbreak vertical slice: dataset loading, deterministic sampling, model execution, metrics, result artifacts, and a minimal public results page.

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

Run the static result viewer from the repository root:

```bash
python -m http.server 8000
# open http://localhost:8000/site/
```

For a live run, copy `benchmark/config/live.example.yaml`, replace the deliberately invalid placeholder with a full 40-character WildJailbreak commit SHA, select the verified upstream config/split, and enable only the adapters you intend to pay for. The runner rejects mutable revisions before model calls. Use `--sample-rate 0.01` for an exploratory run or `--sample-rate 1.0` for a publication run.

Secrets are read only from the environment:

- `TYPESAFE_API_KEY` for TypeSafe AI Jev;
- `OPENROUTER_API_KEY` for the default OpenRouter baseline;
- `OPENAI_API_KEY` if an adapter with `kind: openai` is used directly.

OpenRouter uses its OpenAI-compatible chat-completions endpoint. Model names retain
their OpenRouter provider prefix (for example, `openai/gpt-4.1-mini`). The optional
`OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` variables populate OpenRouter's
attribution headers. Models used for this benchmark must support structured JSON
Schema output. OpenRouter request metadata supplies billed cost; the runner records
that value when available, so model prices do not need to be maintained here.

Do not put secrets in YAML. `.env` is ignored, but the runner does not load it implicitly.

## Implementation decisions

- **Upstream pin:** this environment could not reach Hugging Face to verify the current repository commit or live schema. Rather than invent a pin, the checked-in live configuration contains a conspicuous invalid placeholder and validation requires callers to supply a full commit SHA. Fixture runs use the immutable local revision `fixture-v1`.
- **Upstream normalization:** the adapter accepts the documented/common label fields (`data_type`, `label`, or `source_label`), stable IDs when present, and either a message-list conversation or a prompt field. It fingerprints the observed source columns and fails closed on an unknown label or missing prompt.
- **Sampling:** each stratum receives `floor(size × rate)` rows. A run is rejected instead of silently rounding an empty stratum up to one, so the configured rate remains honest.
- **Jev integration:** the adapter uses Jev's typed `adecide` contract and preserves unavailable probability/usage fields as absent/zero rather than inventing them. The optional import is lazy so the offline suite remains dependency-free. Jev's package support changes independently, so a minimal paid smoke test is required after installing a compatible release.
- **LLM baseline:** OpenAI Chat Completions strict JSON Schema was selected as the first general-purpose baseline. The semantic task question is passed unchanged as the system instruction; only provider serialization differs.
- **Errors and cost:** exhausted errors remain typed records and are excluded from classification metrics. Coverage exposes their impact. Unknown model pricing produces a zero estimate; raw token usage is retained so costs can be recomputed after adding a versioned price.
- **Publication:** `rate == 1.0` alone marks a publication run, matching the OpenSpec decision. The static site never launches evaluations and only reads checked-in artifacts.

## Terminology and implementation details

- **Versioned schemas** are the Pydantic contracts for benchmark configuration,
  predictions, manifests, and aggregate result files. They are not a dataset schema;
  `schema_version` lets readers reject incompatible artifact formats.
- **CLI overrides** are limited to `--sample-rate`, `--seed`, and `--output-dir`.
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
- **Cost estimation** multiplies provider-reported input and output token counts by
  the versioned per-million-token prices, then sums predictions. Unknown prices yield
  zero rather than a fabricated estimate, while retaining raw usage.
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

1. `wildjailbreak-vertical-slice`
2. WildJailbreak adversarial-technique refinements
3. SonderMind abuse-disclosure benchmark
4. FinSafeGuard financial-advice benchmark
5. Dataset revision monitoring and stale-result notifications
6. Public deployment and custom-domain hardening

## OpenSpec workflow

Install OpenSpec with Node.js 20.19 or newer:

```bash
npm install -g @fission-ai/openspec@latest
openspec validate wildjailbreak-vertical-slice
```

Review the active change and its remaining live-verification tasks in `openspec/changes/wildjailbreak-vertical-slice/` before running paid adapters.
