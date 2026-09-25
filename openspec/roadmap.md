# Benchmark rollout roadmap

The three benchmark sets are WildJailbreak, SonderMind Guardrail Evals, and
FinSafeGuard. A reviewed sample is the current deliverable for each set. Full
dataset evaluations are deferred until all three sampled benchmarks and their
supporting publication workflow have been reviewed.

## 1. WildJailbreak sampled results

- [x] Run the pinned 1% harmful-jailbreak cohort with Jev and Luna on the same
  1,614 cases; validate both run artifacts.
- [ ] Review the harmful-jailbreak label mappings, disagreements, three Luna
  timeouts, cost coverage, and latency limitations before drawing conclusions.
- [ ] Run and validate the pinned 1% adversarial-technique cohort with Jev and
  Luna, then review its coverage, errors, disagreements, cost, and latency.
- [ ] Present valid results with their sample rate, counts, seed, and exploratory
  status. Record limitations and any changes needed before the next dataset.

## 2. SonderMind sampled results

- [ ] Define the abuse-disclosure task, source access and license conditions,
  immutable dataset identity, label mapping, and representative fixtures in its
  own OpenSpec change.
- [ ] Implement and test the dataset integration, then run and review a
  deterministic stratified development sample across the selected systems.
- [ ] Choose the sample rate after inspecting dataset and stratum sizes; aim
  for 1% only if every required class has enough cases for useful review.

## 3. FinSafeGuard sampled results

- [ ] Define the financial-advice task, source access and license conditions,
  immutable dataset identity, label mapping, and representative fixtures in its
  own OpenSpec change.
- [ ] Implement and test the dataset integration, then run and review a
  deterministic stratified development sample across the selected systems.
- [ ] Choose the sample rate after inspecting dataset and stratum sizes; aim
  for 1% only if every required class has enough cases for useful review.

## 4. Final full runs across all three sets

- [ ] After the sampled results and publication workflow are reviewed, estimate
  total calls, runtime, and provider spend for all three full datasets.
- [ ] Obtain explicit approval for the budgets and timing before any full paid
  run. A decision to use sampled results for now does not authorize full runs.
- [ ] Run, validate, and publish the full WildJailbreak, SonderMind, and
  FinSafeGuard evaluations with their exact dataset, cohort, model, and code
  provenance. Keep earlier sampled results visibly exploratory.
