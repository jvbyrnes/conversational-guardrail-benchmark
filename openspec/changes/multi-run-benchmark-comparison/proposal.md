# Proposal: Multi-Run Benchmark Comparison

## Intent

Extend the completed WildJailbreak vertical slice so benchmark outputs remain unambiguous as real model runs accumulate, and so the public results site can compare two or more selected model versions for one benchmark task.

The current artifacts preserve substantial run provenance, but the site reads only `results/published/latest/aggregate.json`. Model configuration is stored in a flexible dictionary, compatibility between runs is not evaluated explicitly, and there is no published catalogue through which the UI can discover and align multiple runs. This change introduces a validated comparison contract without discarding the existing per-run evidence.

## Scope

- Define separate canonical identities for configured systems and task evaluations, then combine them for each evaluated result.
- Define metric-family compatibility keys that determine whether quality, cost, and latency can be ranked directly.
- Persist an authoritative selected-cohort manifest before inference so expected prediction coverage is independently verifiable.
- Add artifact validation for provenance, expected prediction coverage, uniqueness, aggregate reconstruction, and publication safety.
- Generate byte-deterministic public and separately stored local preview indexes from validated per-run artifacts.
- Keep raw per-run predictions immutable and derive comparison data from them.
- Publish only strict allowlisted projections with pseudonymous case IDs, sanitized errors, and provenance-aware nullable cost.
- Extend the static site with benchmark/task selection, multi-run selection, a summary comparison table, and case-level disagreement inspection.
- Display exact model, dataset, classifier, sample, clean-code, pricing, and run provenance in the comparison flow.
- Preserve explicit incomplete, exploratory, stale, invalid, and metric-specific non-comparable states; incomplete and invalid runs are preview-only.
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

- Every displayed result identifies its system, evaluation, and evaluated-system identities plus the exact provider, adapter, model ID, model snapshot or explicit absence, and configuration fingerprint that produced it.
- A validation command checks predictions against the independently persisted cohort and rejects ambiguous, internally inconsistent, incomplete, dirty-code, or unsafe artifacts before they enter the public index.
- Aggregate metrics can be reconstructed from the published per-example records.
- The static site discovers available results from a versioned index rather than a hard-coded `latest` path.
- A user can select at least two systems for one task and compare quality, coverage, confusion counts, latency, and cost, with rankings and deltas enabled independently for each compatible metric family.
- A user can inspect public-case-ID-aligned predictions and filter to disagreements or errors without exposing internal source IDs or source conversation text.
- The public site warns when runs are exploratory, stale, or not comparable for a metric family; the preview site additionally shows incomplete and invalid states while suppressing misleading rankings or deltas.
- Existing version-1 run artifacts migrate deterministically without treating an unexplained zero cost as known, or produce an actionable compatibility error.
- Regenerating indexes from identical bundles produces byte-identical output, and duplicate runs use a visible deterministic default while remaining explicitly selectable.

## Risks

- Providers do not always expose immutable model snapshots. The contract records snapshot availability explicitly and fingerprints all known configuration instead of implying stronger reproducibility than exists.
- Cross-run comparisons can be misleading when samples differ. Direct quality ranking requires an identical quality key and authoritative cohort digest; other pairs remain inspectable but are labelled non-comparable.
- A multi-model case explorer could expose gated source text through joinable IDs or free-form provider data. Published records use keyed pseudonymous case IDs and strict field allowlists; raw source IDs, messages, payloads, provider fields, and error text remain private.
- Equal cohorts do not make historical cost or operational latency directly comparable. Pricing/billing provenance and controlled execution metadata gate those metric families separately from quality.
- Legacy zero-valued costs may mean either a real zero or unavailable pricing. Migration treats them as unavailable unless independent evidence proves the value.
- A commit SHA alone does not prove which code executed from a dirty worktree. Public rankability requires clean working-tree provenance.
- Changing artifact schemas can strand existing results. A schema-major compatibility check and deterministic migration path mitigate this.
- Too many selected models can make side-by-side output unreadable. The first UI uses a summary matrix for all selected systems and limits the detailed case view to a manageable selected subset.

## Recommended Delivery Slice

First validate and index the existing fixture run plus one second fixture model, then build the comparison page against those real artifacts. Run paid smoke tests only after the validation and publication gates are passing.
