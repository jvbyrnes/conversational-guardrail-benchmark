"""Strict, deterministic public projections of immutable private run evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from guardrail_bench.comparison import (
    CodeProvenance,
    CostKey,
    DatasetIdentity,
    EvaluationIdentity,
    LatencyKey,
    PrivateCohort,
    QualityKey,
    SystemIdentity,
    canonical_json,
    dataset_identity,
    evaluated_system_id,
    fingerprint,
)
from guardrail_bench.models import StrictModel, SystemMetrics
from guardrail_bench.validation import (
    VALIDATOR_VERSION,
    ValidationReport,
    load_run,
    metric_differences,
    public_report_is_safe,
    safe_run_id,
    validate_run,
)


class PublicModel(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PublicUsage(PublicModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class PublicPrediction(PublicModel):
    public_case_id: str = Field(pattern=r"^hmac-sha256:[a-f0-9]{64}$")
    evaluated_system_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_label: Literal["adversarial_harmful", "adversarial_benign", "vanilla_harmful", "vanilla_benign"]
    ground_truth: bool
    decision: bool | None
    score: float | None = Field(ge=0, le=1)
    error: (
        Literal[
            "timeout",
            "rate_limit",
            "provider",
            "invalid_response",
            "configuration",
            "cost_cap",
            "insufficient_funds",
        ]
        | None
    )
    latency_ms: float = Field(ge=0)
    usage: PublicUsage
    cost_usd: float | None = Field(ge=0)
    cost_status: Literal["reported", "estimated", "unavailable"]
    currency: str | None
    pricing_version: str | None
    cost_method: str | None

    @model_validator(mode="after")
    def terminal_and_cost(self) -> PublicPrediction:
        if (self.decision is None) == (self.error is None):
            raise ValueError("exactly one terminal outcome required")
        if (self.cost_usd is None) != (self.cost_status == "unavailable"):
            raise ValueError("cost status mismatch")
        cost_provenance = (self.currency, self.pricing_version, self.cost_method)
        complete_provenance = all(value is not None for value in cost_provenance)
        absent_provenance = all(value is None for value in cost_provenance)
        if self.cost_usd is not None and not complete_provenance:
            raise ValueError("known cost requires complete provenance")
        if self.cost_usd is None and not (complete_provenance or absent_provenance):
            raise ValueError("unavailable cost provenance must be complete or absent")
        return self


class PublicMember(PublicModel):
    public_case_id: str = Field(pattern=r"^hmac-sha256:[a-f0-9]{64}$")
    ground_truth: bool
    source_label: Literal["adversarial_harmful", "adversarial_benign", "vanilla_harmful", "vanilla_benign"]


class PublicCohort(PublicModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset: DatasetIdentity
    pseudonym_key_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    members: list[PublicMember]


class Eligibility(PublicModel):
    eligible: bool
    reason: str | None

    @model_validator(mode="after")
    def reason_matches_state(self) -> Eligibility:
        if self.eligible == (self.reason is not None):
            raise ValueError("ineligible results require a reason; eligible results cannot have one")
        return self


class ComparisonKeyFields(PublicModel):
    quality: QualityKey
    cost: CostKey | None
    latency: LatencyKey | None


class SystemSummary(PublicModel):
    system_id: str
    evaluated_system_id: str
    identity: SystemIdentity
    quality_key: str
    cost_key: str | None
    latency_key: str | None
    key_fields: ComparisonKeyFields
    rankability: dict[str, Eligibility]

    @model_validator(mode="after")
    def exact_rankability_families(self) -> SystemSummary:
        if set(self.rankability) != {"quality", "cost", "latency"}:
            raise ValueError("rankability requires exactly quality, cost, and latency")
        return self


class PublicManifest(PublicModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    dataset: DatasetIdentity
    evaluation: EvaluationIdentity
    task_id: str
    task_version: str
    systems: list[SystemIdentity]
    code_provenance: CodeProvenance
    public_cohort_digest: str
    pseudonym_key_id: str
    sample_count: int = Field(ge=1)
    sample_rate: float = Field(gt=0, le=1)
    seed: int
    pricing_version: str
    run_kind: Literal["publication", "exploratory"]
    status: Literal["complete"] = "complete"
    started_at: datetime
    completed_at: datetime
    published_at: datetime
    potentially_stale: bool
    summaries: list[SystemSummary]

    @model_validator(mode="after")
    def ordered_utc_timestamps(self) -> PublicManifest:
        timestamps = (self.started_at, self.completed_at, self.published_at)
        offsets = [value.utcoffset() for value in timestamps]
        if any(offset is None or offset.total_seconds() != 0 for offset in offsets):
            raise ValueError("all timestamps must be UTC")
        if not self.started_at <= self.completed_at <= self.published_at:
            raise ValueError("timestamps must be ordered")
        return self


class PublicAggregate(PublicModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    systems: list[SystemMetrics]


class IndexEntry(PublicModel):
    run_id: str
    task_id: str
    task_version: str
    run_kind: Literal["publication", "exploratory"]
    status: Literal["complete"] = "complete"
    validation_status: Literal["valid"] = "valid"
    completed_at: datetime
    potentially_stale: bool
    systems: list[SystemSummary]
    manifest_uri: str
    aggregate_uri: str
    predictions_uri: str
    cohort_uri: str
    validation_report_uri: str
    artifact_digests: dict[str, str]


class PublishedIndex(PublicModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    as_of: datetime | None
    source_set_digest: str
    validator_version: Literal["1.0.0"] = "1.0.0"
    runs: list[IndexEntry]


def _bytes(value: Any) -> bytes:
    return canonical_json(value.model_dump(mode="json") if isinstance(value, StrictModel) else value) + b"\n"


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def public_case_id(dataset: DatasetIdentity, source_id: str, key: bytes) -> str:
    if not key:
        raise ValueError("publication pseudonym key is required")
    message = canonical_json({"dataset": dataset.model_dump(mode="json"), "source_id": source_id})
    return "hmac-sha256:" + hmac.new(key, message, hashlib.sha256).hexdigest()


# Adapter implementations accept only these versioned output-affecting knobs.
SAFE_PARAMETERS = {
    "fake": set(),
    "openrouter": {"temperature", "max_tokens", "max_output_tokens", "top_p", "seed"},
    "jev": {"temperature", "max_tokens", "max_output_tokens", "top_p", "seed"},
}


def _safe_system(system: SystemIdentity) -> None:
    allowed = SAFE_PARAMETERS.get(system.provider)
    if allowed is None:
        allowed = SAFE_PARAMETERS.get(system.adapter_id)
    if allowed is None or set(system.parameters) - allowed or set(system.adapter_defaults) - allowed:
        raise ValueError("publication unsafe system parameters")
    if any(
        not isinstance(value, (int, float, bool, type(None)))
        for value in [*system.parameters.values(), *system.adapter_defaults.values()]
    ):
        raise ValueError("publication unsafe parameter values")


def publish_run(
    directory: Path,
    publication_root: Path,
    *,
    pseudonym_key: bytes,
    pseudonym_key_id: str,
    published_at: datetime | None = None,
) -> Path:
    if not pseudonym_key:
        raise ValueError("publication pseudonym key is required")
    report = validate_run(directory)
    if not report.valid:
        raise ValueError("run failed validation: " + ", ".join(issue.rule_id for issue in report.errors))
    manifest, rows, result = load_run(directory)
    assert manifest.evaluation and manifest.code_provenance
    cohort = PrivateCohort.model_validate_json((directory / "cohort.json").read_text())
    for system in manifest.systems.values():
        _safe_system(system)
    public_cohort = PublicCohort.model_validate(
        {
            "dataset": dataset_identity(manifest.dataset),
            "pseudonym_key_id": pseudonym_key_id,
            "members": sorted(
                [
                    {
                        "public_case_id": public_case_id(cohort.dataset, member.source_id, pseudonym_key),
                        "ground_truth": member.ground_truth,
                        "source_label": member.source_label,
                    }
                    for member in cohort.members
                ],
                key=lambda member: member["public_case_id"],
            ),
        }
    )
    cohort_digest = fingerprint(public_cohort.model_dump(mode="json"))
    projected = sorted(
        [
            PublicPrediction.model_validate(
                {
                    "public_case_id": public_case_id(cohort.dataset, row.source_id, pseudonym_key),
                    "evaluated_system_id": row.evaluated_system_id,
                    "source_label": row.source_label,
                    "ground_truth": row.ground_truth,
                    "decision": row.decision,
                    "score": row.score,
                    "error": row.error.kind if row.error else None,
                    "latency_ms": row.latency_ms,
                    "usage": PublicUsage(input_tokens=row.usage.input_tokens, output_tokens=row.usage.output_tokens),
                    "cost_usd": row.cost_usd,
                    "cost_status": row.cost_status,
                    "currency": row.currency,
                    "pricing_version": manifest.pricing_version if row.currency is not None else None,
                    "cost_method": row.cost_method,
                }
            )
            for row in rows
        ],
        key=lambda r: (r.public_case_id, r.evaluated_system_id),
    )
    summaries = []
    for identity in sorted(manifest.systems.values(), key=lambda s: s.system_id):
        eid = evaluated_system_id(identity.system_id, manifest.evaluation.evaluation_id)
        metrics = next(m for m in result.systems if m.evaluated_system_id == eid)
        quality = {
            "dataset": cohort.dataset.model_dump(mode="json"),
            "evaluation_id": manifest.evaluation.evaluation_id,
            "public_cohort_digest": cohort_digest,
            "pseudonym_key_id": pseudonym_key_id,
            "sample_count": manifest.sample_count,
            "quality_metric_version": "1.0.0",
            "artifact_semantics_major": 1,
        }
        system_rows = [row for row in rows if row.evaluated_system_id == eid]
        provenance = {
            (row.currency, manifest.pricing_version, row.cost_method, row.billing_policy)
            for row in system_rows
            if row.currency and row.cost_method and row.billing_policy
        }
        cost = None
        if len(provenance) == 1:
            currency, pricing, method, billing_policy = next(iter(provenance))
            cost = {
                "quality": quality,
                "currency": currency,
                "pricing_version": pricing,
                "cost_method": method,
                "billing_policy": billing_policy,
            }
        latency = None
        try:
            latency = LatencyKey.model_validate({"quality": quality, **manifest.execution_provenance}).model_dump(
                mode="json"
            )
        except ValueError:
            pass
        cost_reason = None
        if cost is None:
            cost_reason = "missing_cost_provenance"
        elif metrics.cost_coverage < 1:
            cost_reason = "incomplete_cost_coverage"
        summaries.append(
            SystemSummary(
                system_id=identity.system_id,
                evaluated_system_id=eid,
                identity=identity,
                quality_key=fingerprint(quality),
                cost_key=fingerprint(cost) if cost else None,
                latency_key=fingerprint(latency) if latency else None,
                key_fields=ComparisonKeyFields.model_validate({"quality": quality, "cost": cost, "latency": latency}),
                rankability={
                    "quality": Eligibility(eligible=True, reason=None),
                    "cost": Eligibility(
                        eligible=cost is not None and metrics.cost_coverage == 1,
                        reason=cost_reason,
                    ),
                    "latency": Eligibility(
                        eligible=latency is not None,
                        reason=None if latency else "missing_execution_provenance",
                    ),
                },
            )
        )
    public_manifest = PublicManifest(
        run_id=manifest.run_id,
        dataset=cohort.dataset,
        evaluation=manifest.evaluation,
        task_id=manifest.task_id,
        task_version=manifest.classifier_version,
        systems=sorted(manifest.systems.values(), key=lambda system: system.system_id),
        code_provenance=manifest.code_provenance,
        public_cohort_digest=cohort_digest,
        pseudonym_key_id=pseudonym_key_id,
        sample_count=manifest.sample_count,
        sample_rate=manifest.sample_rate,
        seed=manifest.seed,
        pricing_version=manifest.pricing_version,
        run_kind=manifest.run_kind,
        started_at=manifest.started_at,
        completed_at=manifest.completed_at,
        published_at=published_at or manifest.completed_at,
        potentially_stale=result.potentially_stale,
        summaries=summaries,
    )
    target = publication_root / "runs" / manifest.run_id
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest.json": _bytes(public_manifest),
        "cohort.json": _bytes(public_cohort),
        "aggregate.json": _bytes(PublicAggregate(systems=result.systems)),
        "predictions.jsonl": b"".join(_bytes(row) for row in projected),
        "validation-report.json": _bytes(report),
    }
    payload["checksums.json"] = _bytes({name: _digest(data) for name, data in sorted(payload.items())})
    if target.exists():
        if all((target / name).read_bytes() == data for name, data in payload.items()):
            return target
        raise ValueError("published run is immutable; use a new run ID")
    staging = Path(tempfile.mkdtemp(prefix=".publication-", dir=target.parent))
    try:
        for name, data in payload.items():
            (staging / name).write_bytes(data)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


ARTIFACTS = ("manifest.json", "cohort.json", "aggregate.json", "predictions.jsonl", "validation-report.json")


def validate_bundle(directory: Path) -> ValidationReport:
    from guardrail_bench.metrics import aggregate
    from guardrail_bench.models import Prediction, PredictionError, Usage

    report = ValidationReport()
    try:
        manifest = PublicManifest.model_validate_json((directory / "manifest.json").read_text())
        cohort = PublicCohort.model_validate_json((directory / "cohort.json").read_text())
        stored = PublicAggregate.model_validate_json((directory / "aggregate.json").read_text())
        rows = [
            PublicPrediction.model_validate_json(line)
            for line in (directory / "predictions.jsonl").read_text().splitlines()
            if line.strip()
        ]
        prior = ValidationReport.model_validate_json((directory / "validation-report.json").read_text())
        checksums = json.loads((directory / "checksums.json").read_text())
        checksums_invalid = set(checksums) != set(ARTIFACTS) or any(
            checksums[name] != _digest((directory / name).read_bytes()) for name in ARTIFACTS
        )
        if checksums_invalid:
            report.reject("artifacts.checksum", "artifacts")
        if not public_report_is_safe(prior):
            report.reject("validation.prior_invalid", "validation-report")
        if not safe_run_id(manifest.run_id) or manifest.run_id != directory.name:
            report.reject("publication.unsafe_run_id", "manifest.run_id")
        if manifest.code_provenance.working_tree_state != "clean":
            report.reject("provenance.code_not_clean", "manifest.code_provenance")
        cohort_invalid = (
            fingerprint(cohort.model_dump(mode="json")) != manifest.public_cohort_digest
            or cohort.dataset != manifest.dataset
            or cohort.pseudonym_key_id != manifest.pseudonym_key_id
        )
        if cohort_invalid:
            report.reject("cohort.integrity", "cohort")
        ids = [member.public_case_id for member in cohort.members]
        if ids != sorted(set(ids)) or len(ids) != manifest.sample_count:
            report.reject("cohort.integrity", "cohort.members")
        identities = {}
        for system in manifest.systems:
            _safe_system(system)
            fingerprint_invalid = (
                fingerprint(system.fingerprint_input()) != system.system_id
                or system.configuration_fingerprint != system.system_id
            )
            if fingerprint_invalid:
                report.reject("provenance.system_fingerprint", "manifest.systems")
            identities[evaluated_system_id(system.system_id, manifest.evaluation.evaluation_id)] = system
        if fingerprint(manifest.evaluation.fingerprint_input()) != manifest.evaluation.evaluation_id:
            report.reject("provenance.evaluation_fingerprint", "manifest.evaluation")
        expected_quality = {
            "dataset": cohort.dataset.model_dump(mode="json"),
            "evaluation_id": manifest.evaluation.evaluation_id,
            "public_cohort_digest": manifest.public_cohort_digest,
            "pseudonym_key_id": manifest.pseudonym_key_id,
            "sample_count": manifest.sample_count,
            "quality_metric_version": "1.0.0",
            "artifact_semantics_major": 1,
        }
        summaries = {summary.evaluated_system_id: summary for summary in manifest.summaries}
        if set(summaries) != set(identities) or len(summaries) != len(manifest.summaries):
            report.reject("comparison.summary_set", "manifest.summaries")
        for result_id, summary in summaries.items():
            if (
                summary.system_id != identities[result_id].system_id
                or summary.identity != identities[result_id]
                or summary.key_fields.quality.model_dump(mode="json") != expected_quality
                or summary.quality_key != fingerprint(expected_quality)
            ):
                report.reject("comparison.quality_key", "manifest.summaries")
            for family, key_type in (("cost", CostKey), ("latency", LatencyKey)):
                fields = getattr(summary.key_fields, family)
                key = getattr(summary, f"{family}_key")
                if fields is None:
                    if key is not None or summary.rankability[family].eligible:
                        report.reject("comparison.key_state", f"manifest.summaries.{family}")
                    continue
                parsed = key_type.model_validate(fields)
                if parsed.quality.model_dump(mode="json") != expected_quality or key != fingerprint(
                    fields.model_dump(mode="json")
                ):
                    report.reject("comparison.key_integrity", f"manifest.summaries.{family}")
        for timestamp_name in ("started_at", "completed_at", "published_at"):
            timestamp = getattr(manifest, timestamp_name)
            if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
                report.reject("schema.utc_required", f"manifest.{timestamp_name}")
        expected = {(case, eid) for case in ids for eid in identities}
        actual = [(row.public_case_id, row.evaluated_system_id) for row in rows]
        if len(actual) != len(set(actual)):
            report.reject("predictions.duplicate", "predictions")
        if set(actual) != expected:
            report.reject("predictions.cartesian_coverage", "predictions")
        members = {m.public_case_id: m for m in cohort.members}
        internal = []
        for row in rows:
            member = members.get(row.public_case_id)
            if member is None or (member.ground_truth, member.source_label) != (row.ground_truth, row.source_label):
                report.reject("cohort.labels", "predictions")
            identity = identities.get(row.evaluated_system_id)
            if identity is None:
                continue
            # Synthetic IDs are used only in memory to reuse the authoritative metric implementation.
            internal.append(
                Prediction(
                    run_id=manifest.run_id,
                    source_id=row.public_case_id,
                    source_label=row.source_label,
                    ground_truth=row.ground_truth,
                    task_id=manifest.task_id,
                    classifier_version=manifest.task_version,
                    adapter_id=identity.display_name,
                    model_id=identity.requested_model_id,
                    system_id=identity.system_id,
                    evaluation_id=manifest.evaluation.evaluation_id,
                    evaluated_system_id=row.evaluated_system_id,
                    decision=row.decision,
                    score=row.score,
                    latency_ms=row.latency_ms,
                    usage=Usage(**row.usage.model_dump()),
                    cost_usd=row.cost_usd,
                    cost_status=row.cost_status,
                    currency=row.currency,
                    cost_method=row.cost_method,
                    billing_policy="published-cost-provenance" if row.currency is not None else None,
                    error=PredictionError(kind=row.error, message="") if row.error else None,
                )
            )
        recomputed_metrics = aggregate(internal)
        recomputed = sorted(
            [metric.model_dump(mode="json") for metric in recomputed_metrics],
            key=lambda metric: metric["evaluated_system_id"],
        )
        original = sorted(
            [metric.model_dump(mode="json") for metric in stored.systems],
            key=lambda metric: metric["evaluated_system_id"],
        )
        for path in metric_differences(recomputed, original, "aggregate.systems"):
            report.reject("aggregate.drift", path)
        metrics_by_result = {metric.evaluated_system_id: metric for metric in recomputed_metrics}
        rows_by_result = {
            result_id: [row for row in rows if row.evaluated_system_id == result_id] for result_id in identities
        }
        for result_id, summary in summaries.items():
            metric = metrics_by_result.get(result_id)
            if metric is None:
                continue
            expected_cost_eligible = summary.key_fields.cost is not None and metric.cost_coverage == 1
            expected_cost_reason = None
            if summary.key_fields.cost is None:
                expected_cost_reason = "missing_cost_provenance"
            elif metric.cost_coverage < 1:
                expected_cost_reason = "incomplete_cost_coverage"
            cost_state = summary.rankability["cost"]
            if cost_state.eligible != expected_cost_eligible or cost_state.reason != expected_cost_reason:
                report.reject("comparison.cost_rankability", "manifest.summaries.cost")
            if summary.rankability["quality"] != Eligibility(eligible=True, reason=None):
                report.reject("comparison.quality_rankability", "manifest.summaries.quality")
            latency_expected = summary.key_fields.latency is not None
            latency_state = summary.rankability["latency"]
            if latency_state.eligible != latency_expected:
                report.reject("comparison.latency_rankability", "manifest.summaries.latency")
            if summary.key_fields.cost is not None:
                expected_provenance = {
                    (
                        summary.key_fields.cost.currency,
                        summary.key_fields.cost.pricing_version,
                        summary.key_fields.cost.cost_method,
                    )
                }
                actual_provenance = {
                    (row.currency, row.pricing_version, row.cost_method)
                    for row in rows_by_result[result_id]
                    if row.currency is not None
                }
                if actual_provenance != expected_provenance:
                    report.reject("comparison.cost_provenance", "manifest.summaries.cost")
    except (ValueError, OSError, KeyError, TypeError):
        report.reject("publication.schema_or_safety", "bundle")
    return report


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def generate_index(
    publication_root: Path, preview_root: Path | None = None, source_directories: list[Path] | None = None
) -> PublishedIndex:
    if preview_root and (
        preview_root.resolve() == publication_root.resolve()
        or publication_root.resolve() in preview_root.resolve().parents
    ):
        raise ValueError("preview root must be outside publication root")
    entries = []
    dates = []
    sources = []
    preview = []
    directories = sorted((publication_root / "runs").glob("*"))
    for directory in directories:
        if not directory.is_dir() or not safe_run_id(directory.name):
            continue
        report = validate_bundle(directory)
        if not report.valid:
            preview.append(
                {
                    "run_id": directory.name,
                    "status": "unavailable",
                    "run_kind": "unavailable",
                    "validation_status": "invalid",
                    "rule_ids": sorted({issue.rule_id for issue in report.errors}),
                }
            )
            continue
        manifest = PublicManifest.model_validate_json((directory / "manifest.json").read_text())
        digests = {name: _digest((directory / name).read_bytes()) for name in sorted(ARTIFACTS)}
        prefix = f"runs/{manifest.run_id}/"
        entries.append(
            IndexEntry(
                run_id=manifest.run_id,
                task_id=manifest.task_id,
                task_version=manifest.task_version,
                run_kind=manifest.run_kind,
                completed_at=manifest.completed_at,
                potentially_stale=manifest.potentially_stale,
                systems=manifest.summaries,
                manifest_uri=prefix + "manifest.json",
                aggregate_uri=prefix + "aggregate.json",
                predictions_uri=prefix + "predictions.jsonl",
                cohort_uri=prefix + "cohort.json",
                validation_report_uri=prefix + "validation-report.json",
                artifact_digests=digests,
            )
        )
        dates.append(manifest.published_at)
        sources.append([manifest.run_id, *[digests[name] for name in ARTIFACTS]])
    index = PublishedIndex(as_of=max(dates) if dates else None, source_set_digest=fingerprint(sources), runs=entries)
    _atomic_write(publication_root / "index.json", _bytes(index))
    if preview_root:
        for directory in sorted(source_directories or []):
            report = validate_run(directory)
            redacted_id = "redacted-" + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
            state: dict[str, Any] = {}
            try:
                source_manifest, _, source_aggregate = load_run(directory)
                state = {
                    "status": source_manifest.status,
                    "run_kind": source_manifest.run_kind,
                    "potentially_stale": source_aggregate.potentially_stale,
                    "incomplete_reason": "run.incomplete" if source_manifest.status == "incomplete" else None,
                }
            except (OSError, ValueError):
                pass
            preview.append(
                {
                    "run_id": directory.name if safe_run_id(directory.name) else redacted_id,
                    "validation_status": "valid" if report.valid else "invalid",
                    "rule_ids": sorted({issue.rule_id for issue in report.errors}),
                    **state,
                }
            )
        _atomic_write(
            preview_root / "index.json",
            _bytes(
                {
                    "schema_version": "1.0.0",
                    "as_of": None,
                    "validator_version": VALIDATOR_VERSION,
                    "runs": sorted(preview, key=lambda r: r["run_id"]),
                }
            ),
        )
    return index
