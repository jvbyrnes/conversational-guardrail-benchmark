# Proposal: Multi-Run Benchmark Comparison

## Intent

Extend the completed WildJailbreak vertical slice so benchmark outputs remain unambiguous as real model runs accumulate, and so the public results site can compare two or more selected model versions for one benchmark task.

The current artifacts preserve substantial run provenance, but the site reads only `results/published/latest/aggregate.json`. Model configuration is stored in a flexible dictionary, compatibility between runs is not evaluated explicitly, and there is no published catalogue through which the UI can discover and align multiple runs. This change introduces a validated comparison contract without discarding the existing per-run evidence.

## Scope

- Define a typed, canonical identity for every evaluated system, including provider, adapter, model ID, immutable snapshot when available, configuration fingerprint, and display label.
- Define the compatibility key that determines whether two results can be ranked directly.
- Add artifact validation for provenance, expected prediction coverage, uniqueness, aggregate reconstruction, and publication safety.
- Generate a versioned published run index from validated per-run artifacts.
- Keep raw per-run predictions immutable and derive comparison data from them.
- Extend the static site with benchmark/task selection, multi-run selection, a summary comparison table, and case-level disagreement inspection.
- Display exact model, dataset, classifier, sample, code, pricing, and run provenance in the comparison flow.
- Preserve explicit incomplete, exploratory, stale, invalid, and non-comparable states.
- Cover the full flow with fixture-based, network-free tests.

## Out of Scope

- Running paid benchmarks automatically.
- Changing WildJailbreak label mappings or classifier meaning.
- A server-side database, authenticated API, or user accounts.
- Statistical significance claims or repeated-trial analysis.
- Comparing unlike tasks through a synthetic global leaderboard.
- Publishing upstream conversation text.
- Hosting and deployment configuration.

## Success Criteria

- Every displayed result identifies the exact provider, adapter, model ID, model snapshot or explicit absence, and configuration fingerprint that produced it.
- A validation command rejects ambiguous, internally inconsistent, incomplete, or unsafe artifacts before they enter the published index.
- Aggregate metrics can be reconstructed from the published per-example records.
- The static site discovers available results from a versioned index rather than a hard-coded `latest` path.
- A user can select at least two compatible systems for one task and compare quality, coverage, confusion counts, latency, and cost.
- A user can inspect source-ID-aligned predictions and filter to disagreements or errors without exposing source conversation text.
- The site warns when runs are exploratory, incomplete, stale, invalid, or not directly comparable and suppresses misleading rankings or deltas.
- Existing version-1 run artifacts either migrate deterministically or produce an actionable compatibility error.

## Risks

- Providers do not always expose immutable model snapshots. The contract records snapshot availability explicitly and fingerprints all known configuration instead of implying stronger reproducibility than exists.
- Cross-run comparisons can be misleading when samples differ. Direct ranking requires an identical comparison key and source-ID cohort; other pairs remain inspectable but are labelled non-comparable.
- A multi-model case explorer could expose unsafe source text. Published records continue to use source IDs, labels, decisions, scores, and errors only.
- Changing artifact schemas can strand existing results. A schema-major compatibility check and deterministic migration path mitigate this.
- Too many selected models can make side-by-side output unreadable. The first UI uses a summary matrix for all selected systems and limits the detailed case view to a manageable selected subset.

## Recommended Delivery Slice

First validate and index the existing fixture run plus one second fixture model, then build the comparison page against those real artifacts. Run paid smoke tests only after the validation and publication gates are passing.
