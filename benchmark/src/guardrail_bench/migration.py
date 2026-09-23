"""Conservative legacy migration with independently replayed selection."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from guardrail_bench.comparison import (
    CodeProvenance,
    CohortMember,
    PrivateCohort,
    dataset_identity,
    evaluated_system_id,
    make_evaluation_identity,
    make_system_identity,
)
from guardrail_bench.config import BenchmarkConfig
from guardrail_bench.dataset import load_wildjailbreak
from guardrail_bench.metrics import aggregate
from guardrail_bench.models import AggregateResult, Prediction, RunManifest, StrictModel
from guardrail_bench.sampling import stratified_sample
from guardrail_bench.tasks import get_task
from guardrail_bench.validation import ValidationIssue, safe_run_id

LEGACY_EVALUATION_IDS = {
    ("harmful_jailbreak", "1.0.0"): "sha256:31542a8b61ab0d7654a44a79c8a9bb13b114fec9b16751c1d3c691a3b45f415b",
    ("adversarial_technique", "1.0.0"): "sha256:24ca84e2948e986fa3081a23da9fe6ea20e5615d082949b27640ee4dc0b67f06",
}
LEGACY_SAMPLERS = {"1": "stratified-sha256-v1"}


class MigrationReport(StrictModel):
    schema_version: str = "1.0.0"
    dry_run: bool
    migrated: bool = False
    publication_eligible: bool = False
    output_directory: str | None = None
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


def migrate_run(
    directory: Path, output_root: Path, *, dry_run: bool = True, config: BenchmarkConfig | None = None
) -> MigrationReport:
    report = MigrationReport(dry_run=dry_run)

    def error(rule: str, path: str) -> None:
        report.errors.append(ValidationIssue(rule_id=rule, path=path))

    try:
        raw = json.loads((directory / "manifest.json").read_text())
        schema_major = raw.get("schema_version", "").split(".")[0]
        if schema_major not in LEGACY_SAMPLERS:
            raise ValueError("unsupported version")
        manifest = RunManifest.model_validate(raw)
        rows_raw = [
            json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines() if line.strip()
        ]
        rows = [Prediction.model_validate(row) for row in rows_raw]
    except (ValueError, OSError):
        error("migration.schema", "manifest")
        return report
    if not safe_run_id(manifest.run_id):
        error("publication.unsafe_run_id", "manifest.run_id")
    if config is None:
        error("migration.selection_replay_requires_config", "config")
        return report
    if (
        config.dataset.name,
        config.dataset.revision,
        config.dataset.split,
        config.dataset.config_name,
        config.task,
        config.sample.rate,
        config.sample.seed,
    ) != (
        manifest.dataset.name,
        manifest.dataset.revision,
        manifest.dataset.split,
        manifest.dataset.config_name,
        manifest.task_id,
        manifest.sample_rate,
        manifest.seed,
    ):
        error("migration.selection_config_mismatch", "config")
        return report
    task = get_task(config.task)
    if task.version != manifest.classifier_version:
        error("migration.task_definition_unavailable", "manifest.classifier_version")
        return report
    examples, metadata = load_wildjailbreak(config.dataset)
    if dataset_identity(metadata) != dataset_identity(manifest.dataset):
        error("migration.dataset_mismatch", "dataset")
        return report
    selected, strata = stratified_sample(examples, task, manifest.sample_rate, manifest.seed)
    if len(selected) != manifest.sample_count or strata != manifest.strata:
        error("migration.selection_replay_mismatch", "cohort")
        return report
    evaluation = make_evaluation_identity(task)
    if LEGACY_EVALUATION_IDS.get((manifest.task_id, manifest.classifier_version)) != evaluation.evaluation_id:
        error("migration.historical_task_definition_unavailable", "manifest.classifier_version")
        return report
    systems = {}
    for item in config.adapters:
        if not item.enabled:
            continue
        legacy = manifest.models.get(item.id)
        if not legacy or any(
            legacy.get(key) != value
            for key, value in (("kind", item.kind), ("model", item.model), ("parameters", item.parameters))
        ):
            error("migration.system_config_mismatch", "manifest.models")
            continue
        identity = make_system_identity(item)
        # Legacy fixture names also cannot prove provider-guaranteed historical snapshots.
        identity = identity.model_copy(update={"resolved_snapshot": None, "snapshot_status": "unavailable"})
        from guardrail_bench.comparison import fingerprint

        digest = fingerprint(identity.fingerprint_input())
        systems[item.id] = identity.model_copy(update={"system_id": digest, "configuration_fingerprint": digest})
    if set(systems) != set(manifest.models):
        error("migration.system_set_mismatch", "manifest.models")
    cohort = PrivateCohort(
        dataset=dataset_identity(metadata),
        members=sorted(
            [
                CohortMember(
                    source_id=example.source_id,
                    source_label=example.source_label,
                    ground_truth=bool(task.ground_truth(example.source_label)),
                )
                for example in selected
            ],
            key=lambda member: member.source_id,
        ),
    )
    if report.errors:
        return report
    report.warnings.extend(
        [
            ValidationIssue(rule_id="migration.snapshot_unavailable", path="systems"),
            ValidationIssue(rule_id="migration.cost_unavailable", path="predictions.cost_usd"),
            ValidationIssue(rule_id="migration.code_unavailable", path="code_provenance"),
        ]
    )
    manifest = manifest.model_copy(
        update={
            "systems": systems,
            "evaluation": evaluation,
            "private_cohort_digest": cohort.digest,
            "code_provenance": CodeProvenance(
                repository=None,
                commit_revision=manifest.code_revision,
                committed_tree_digest=None,
                working_tree_state="unavailable",
            ),
        }
    )
    normalized = []
    for row in rows:
        row_identity = systems.get(row.adapter_id)
        if row_identity is None:
            error("migration.prediction_identity", "predictions")
            return report
        normalized.append(
            row.model_copy(
                update={
                    "system_id": row_identity.system_id,
                    "evaluation_id": evaluation.evaluation_id,
                    "evaluated_system_id": evaluated_system_id(row_identity.system_id, evaluation.evaluation_id),
                    "cost_usd": None,
                    "cost_status": "unavailable",
                    "currency": None,
                    "cost_method": None,
                    "billing_policy": None,
                }
            )
        )
    if not dry_run:
        target = output_root / manifest.run_id
        if target.resolve() == directory.resolve() or directory.resolve() in target.resolve().parents:
            error("migration.evidence_immutable", "output_root")
            return report
        target.mkdir(parents=True, exist_ok=False)
        (target / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
        (target / "cohort.json").write_text(cohort.model_dump_json(indent=2) + "\n")
        (target / "predictions.jsonl").write_text("".join(row.model_dump_json() + "\n" for row in normalized))
        migrated_aggregate = AggregateResult(manifest=manifest, systems=aggregate(normalized))
        (target / "aggregate.json").write_text(migrated_aggregate.model_dump_json(indent=2) + "\n")
        report.output_directory = str(target)
        report.migrated = True
    return report
