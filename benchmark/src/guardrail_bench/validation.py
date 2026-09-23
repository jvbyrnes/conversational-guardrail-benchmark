"""Offline validation. Reports never copy untrusted values or exception messages."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import Field

from guardrail_bench.models import AggregateResult, Prediction, RunManifest, StrictModel, require_compatible_schema

VALIDATOR_VERSION = "1.0.0"
PUBLIC_WARNING_LOCATIONS = {
    ("provenance.snapshot_unresolved", "manifest.systems.snapshot_status"),
}


class ValidationIssue(StrictModel):
    rule_id: str
    path: str


class ValidationReport(StrictModel):
    validator_version: str = VALIDATOR_VERSION
    valid: bool = True
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    def reject(self, rule: str, path: str) -> None:
        self.valid = False
        self.errors.append(ValidationIssue(rule_id=rule, path=path))

    def warn(self, rule: str, path: str) -> None:
        self.warnings.append(ValidationIssue(rule_id=rule, path=path))


def public_report_is_safe(report: ValidationReport) -> bool:
    """Only generator-owned, value-free warnings may cross the public boundary."""
    return (
        report.validator_version == VALIDATOR_VERSION
        and report.valid
        and not report.errors
        and all((warning.rule_id, warning.path) in PUBLIC_WARNING_LOCATIONS for warning in report.warnings)
    )


def safe_run_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value))


def matches_fingerprint(value: Any, expected: str) -> bool:
    from guardrail_bench.comparison import fingerprint

    try:
        return fingerprint(value) == expected
    except (TypeError, ValueError, UnicodeError):
        return False


def metric_differences(left: Any, right: Any, path: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        return [
            p
            for key in sorted(set(left) | set(right))
            for p in metric_differences(left.get(key), right.get(key), f"{path}.{key}".strip("."))
        ]
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [
            p for i, (a, b) in enumerate(zip(left, right, strict=True)) for p in metric_differences(a, b, f"{path}.{i}")
        ]
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return [] if math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9) else [path]
    return [] if left == right else [path]


def load_run(directory: Path) -> tuple[RunManifest, list[Prediction], AggregateResult]:
    manifest = RunManifest.model_validate_json((directory / "manifest.json").read_text())
    predictions = [
        Prediction.model_validate_json(line)
        for line in (directory / "predictions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    result = AggregateResult.model_validate_json((directory / "aggregate.json").read_text())
    require_compatible_schema(manifest.schema_version)
    require_compatible_schema(result.schema_version)
    for prediction in predictions:
        require_compatible_schema(prediction.schema_version)
    return manifest, predictions, result


def validate_run(directory: Path) -> ValidationReport:
    from guardrail_bench.comparison import (
        PrivateCohort,
        dataset_identity,
        evaluated_system_id,
    )
    from guardrail_bench.metrics import aggregate

    report = ValidationReport()
    try:
        manifest, predictions, result = load_run(directory)
    except (ValueError, OSError):
        report.reject("schema.invalid", "run")
        return report
    if not safe_run_id(manifest.run_id):
        report.reject("publication.unsafe_run_id", "manifest.run_id")
    if manifest.status != "complete":
        report.reject("run.incomplete", "manifest.status")
    for name in ("started_at", "completed_at"):
        value = getattr(manifest, name)
        if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            report.reject("schema.utc_required", f"manifest.{name}")
    if manifest.completed_at < manifest.started_at:
        report.reject("schema.timestamp_order", "manifest.completed_at")
    if not manifest.code_provenance or manifest.code_provenance.working_tree_state != "clean":
        report.reject("provenance.code_not_clean", "manifest.code_provenance")
    elif manifest.code_revision != manifest.code_provenance.commit_revision:
        report.reject("provenance.code_revision_mismatch", "manifest.code_revision")
    if not manifest.evaluation or not manifest.systems:
        report.reject("provenance.identity_missing", "manifest.systems")
        return report
    for system in manifest.systems.values():
        if not matches_fingerprint(system.fingerprint_input(), system.system_id) or (
            system.configuration_fingerprint != system.system_id
        ):
            report.reject("provenance.system_fingerprint", "manifest.systems")
        if system.snapshot_status != "immutable":
            report.warn("provenance.snapshot_unresolved", "manifest.systems.snapshot_status")
    if not matches_fingerprint(manifest.evaluation.fingerprint_input(), manifest.evaluation.evaluation_id):
        report.reject("provenance.evaluation_fingerprint", "manifest.evaluation")
    if (
        manifest.task_id != manifest.evaluation.task_id
        or manifest.classifier_version != manifest.evaluation.classifier_version
    ):
        report.reject("provenance.evaluation_mismatch", "manifest.evaluation")
    try:
        cohort = PrivateCohort.model_validate_json((directory / "cohort.json").read_text())
        if cohort.digest != manifest.private_cohort_digest or cohort.dataset != dataset_identity(manifest.dataset):
            report.reject("cohort.integrity", "cohort")
    except (ValueError, OSError):
        report.reject("cohort.integrity", "cohort")
        return report
    if len(cohort.members) != manifest.sample_count:
        report.reject("cohort.sample_count", "manifest.sample_count")
    for member in cohort.members:
        if manifest.evaluation.label_mapping.get(member.source_label) != member.ground_truth:
            report.reject("cohort.ground_truth", "cohort.members")
            break
    members = {member.source_id: member for member in cohort.members}
    expected = {
        (member.source_id, evaluated_system_id(system.system_id, manifest.evaluation.evaluation_id))
        for member in cohort.members
        for system in manifest.systems.values()
    }
    actual = Counter((row.source_id, row.evaluated_system_id) for row in predictions)
    if any(count > 1 for count in actual.values()):
        report.reject("predictions.duplicate", "predictions")
    if set(actual) != expected:
        report.reject("predictions.cartesian_coverage", "predictions")
    for row in predictions:
        prediction_system = manifest.systems.get(row.adapter_id)
        prediction_member = members.get(row.source_id)
        if (
            prediction_system is None
            or row.system_id != prediction_system.system_id
            or row.evaluation_id != manifest.evaluation.evaluation_id
            or row.evaluated_system_id
            != evaluated_system_id(prediction_system.system_id, manifest.evaluation.evaluation_id)
            or row.run_id != manifest.run_id
            or row.task_id != manifest.task_id
            or row.model_id != prediction_system.requested_model_id
        ):
            report.reject("predictions.identity", "predictions")
            break
        if prediction_member is None or (row.ground_truth, row.source_label) != (
            prediction_member.ground_truth,
            prediction_member.source_label,
        ):
            report.reject("cohort.labels", "predictions")
            break
    if result.manifest != manifest:
        report.reject("aggregate.manifest_mismatch", "aggregate.manifest")
    recomputed = [item.model_dump(mode="json") for item in aggregate(predictions)]
    for path in metric_differences(
        recomputed, [item.model_dump(mode="json") for item in result.systems], "aggregate.systems"
    ):
        report.reject("aggregate.drift", path)
    reported_cost = sum(row.cost_usd or 0 for row in predictions if row.cost_status == "reported")
    if not math.isclose(reported_cost, manifest.cost_actual_usd, rel_tol=1e-9, abs_tol=1e-9):
        report.reject("cost.reported_total_mismatch", "manifest.cost_actual_usd")
    return report
