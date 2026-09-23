"""Versioned, secret-free identity and metric-family compatibility contracts."""

from __future__ import annotations

import hashlib
import math
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from guardrail_bench.config import AdapterConfig
    from guardrail_bench.models import DatasetMetadata, TaskDefinition


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_min_length=1)


def canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_unset=True)
    return rfc8785.dumps(value)


def fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


class SystemFingerprintInput(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    adapter_id: str
    adapter_version: str
    provider: str
    requested_model_id: str
    resolved_snapshot: str | None
    snapshot_status: Literal["immutable", "provider_alias", "unavailable"]
    parameters: dict[str, Any]
    adapter_defaults: dict[str, Any]
    request_mode: str

    @model_validator(mode="after")
    def snapshot_invariant(self) -> SystemFingerprintInput:
        if (self.snapshot_status == "immutable") != (self.resolved_snapshot is not None):
            raise ValueError("only immutable snapshots require a nonempty resolved_snapshot")
        return self


class SystemIdentity(SystemFingerprintInput):
    system_id: str
    configuration_fingerprint: str
    display_name: str
    reproducibility_warnings: list[str] = Field(default_factory=list)

    def fingerprint_input(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in SystemFingerprintInput.model_fields}


class EvaluationIdentity(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    evaluation_id: str
    task_id: str
    task_version: str
    question: str
    label_mapping: dict[str, bool | None]
    decision_threshold: float = Field(ge=0, le=1)
    parser_version: str
    classifier_version: str

    def fingerprint_input(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"evaluation_id", "task_version"})


def evaluated_system_id(system_id: str, evaluation_id: str) -> str:
    return fingerprint({"schema_version": "1.0.0", "system_id": system_id, "evaluation_id": evaluation_id})


def make_evaluation_identity(task: TaskDefinition) -> EvaluationIdentity:
    content: dict[str, Any] = {
        "schema_version": "1.0.0",
        "task_id": task.task_id,
        "question": task.question,
        "label_mapping": task.label_mapping,
        "decision_threshold": task.decision_threshold,
        "parser_version": task.parser_version,
        "classifier_version": task.version,
    }
    return EvaluationIdentity(**content, evaluation_id=fingerprint(content), task_version=task.version)


ADAPTER_VERSION = "1.0.0"
SAFE_PARAMETERS: dict[tuple[str, str], set[str]] = {
    ("fake", ADAPTER_VERSION): set(),
    ("openrouter", ADAPTER_VERSION): {
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "seed",
        "frequency_penalty",
        "presence_penalty",
        "stop",
    },
    ("jev", ADAPTER_VERSION): {"temperature", "top_p", "max_tokens", "seed"},
}


def validate_system_parameters(kind: str, adapter_version: str, parameters: dict[str, Any]) -> None:
    """Apply the same versioned parameter contract before inference and publication."""
    allowed = SAFE_PARAMETERS.get((kind, adapter_version))
    if allowed is None or set(parameters) - allowed:
        raise ValueError(f"unsupported output parameters for {kind} adapter version {adapter_version}")
    for name, value in parameters.items():
        if value is None:
            continue
        if name == "stop":
            valid = isinstance(value, str) or (
                isinstance(value, list) and all(isinstance(item, str) for item in value)
            )
        elif name in {"max_tokens", "max_completion_tokens", "seed"}:
            valid = isinstance(value, int) and not isinstance(value, bool) and (name == "seed" or value >= 0)
        else:
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if not valid:
            raise ValueError(f"unsupported output parameter value for {kind}.{name}")


def make_system_identity(config: AdapterConfig) -> SystemIdentity:
    validate_system_parameters(config.kind, ADAPTER_VERSION, config.parameters)
    fake = config.kind == "fake"
    content = SystemFingerprintInput(
        schema_version="1.0.0",
        adapter_id=config.kind,
        adapter_version=ADAPTER_VERSION,
        provider={"fake": "fixture", "jev": "typesafe", "openrouter": "openrouter"}[config.kind],
        requested_model_id=config.model,
        resolved_snapshot=config.model if fake else None,
        snapshot_status="immutable" if fake else "unavailable",
        parameters=config.parameters,
        adapter_defaults={},
        request_mode={"fake": "deterministic", "jev": "system-one-noul", "openrouter": "chat-json-schema"}[config.kind],
    ).model_dump(mode="json")
    digest = fingerprint(content)
    return SystemIdentity(
        **content,
        system_id=digest,
        configuration_fingerprint=digest,
        display_name=config.id,
        reproducibility_warnings=[] if fake else ["provider_defaults_unresolved", "snapshot_unavailable"],
    )


class DatasetIdentity(ContractModel):
    name: str
    revision: str
    split: str
    config_name: str | None
    schema_fingerprint: str


def dataset_identity(dataset: DatasetMetadata) -> DatasetIdentity:
    return DatasetIdentity(**dataset.model_dump(exclude={"retrieved_at"}))


class CohortMember(ContractModel):
    source_id: str
    source_label: str
    ground_truth: bool


class PrivateCohort(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    dataset: DatasetIdentity
    members: list[CohortMember]

    @model_validator(mode="after")
    def unique_sorted_members(self) -> PrivateCohort:
        ids = [member.source_id for member in self.members]
        if ids != sorted(set(ids)):
            raise ValueError("cohort members must be unique and sorted by source_id")
        return self

    @property
    def digest(self) -> str:
        return fingerprint(self.model_dump(mode="json"))


class CodeProvenance(ContractModel):
    repository: str | None
    commit_revision: str | None
    committed_tree_digest: str | None
    working_tree_state: Literal["clean", "dirty", "unavailable"]

    @model_validator(mode="after")
    def clean_evidence_is_complete(self) -> CodeProvenance:
        digest = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"
        if self.working_tree_state == "clean" and (
            self.repository is None
            or self.commit_revision is None
            or self.committed_tree_digest is None
            or re.fullmatch(digest, self.commit_revision) is None
            or re.fullmatch(digest, self.committed_tree_digest) is None
        ):
            raise ValueError("clean provenance requires repository, commit, and tree evidence")
        return self


def capture_code_provenance(root: Path | None = None) -> CodeProvenance:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()

    repository = commit = tree = None
    try:
        repository_root = git("rev-parse", "--show-toplevel")
        if not repository_root:
            raise ValueError("missing repository root")
        root = Path(repository_root)
        commit = git("rev-parse", "HEAD")
        tree = git("rev-parse", "HEAD^{tree}")
        status = git("status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none")
        if not all(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) for value in (commit, tree)):
            raise ValueError("malformed git revision")
        try:
            repository = git("config", "--get", "remote.origin.url") or None
            # A remote may embed credentials; never persist those in provenance.
            if repository and ("@" in repository.split("://", 1)[-1].split("/", 1)[0]) and "://" in repository:
                repository = None
        except subprocess.CalledProcessError:
            repository = None
        state: Literal["clean", "dirty", "unavailable"] = (
            "dirty" if status else "clean" if repository else "unavailable"
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        state = "unavailable"
        commit = None
        tree = None
    return CodeProvenance(
        repository=repository, commit_revision=commit, committed_tree_digest=tree, working_tree_state=state
    )


class QualityKey(ContractModel):
    dataset: DatasetIdentity
    evaluation_id: str
    public_cohort_digest: str
    pseudonym_key_id: str
    sample_count: int = Field(ge=1)
    quality_metric_version: str = "1.0.0"
    artifact_semantics_major: int = Field(default=1, ge=1)


class CostKey(ContractModel):
    quality: QualityKey
    currency: str
    pricing_version: str
    cost_method: str
    billing_policy: str


class LatencyKey(ContractModel):
    quality: QualityKey
    timing_definition_version: str
    execution_mode: str
    concurrency: int = Field(ge=1)
    retry_policy: str
    timeout_policy: str
    routing_region_class: str
    warmup_policy: str


class Eligibility(ContractModel):
    eligible: bool
    reason: str | None = None

    @model_validator(mode="after")
    def reason_matches(self) -> Eligibility:
        if self.eligible == (self.reason is not None):
            raise ValueError("ineligible results require a reason; eligible results cannot have one")
        return self


class Rankability(ContractModel):
    quality: Eligibility
    cost: Eligibility
    latency: Eligibility


class Compatibility(ContractModel):
    state: Literal["comparable", "incompatible", "unavailable", "ineligible"]
    differing_paths: list[str] = Field(default_factory=list)


def differing_paths(left: Any, right: Any, prefix: str = "") -> list[str]:
    if isinstance(left, BaseModel):
        left = left.model_dump(mode="json")
    if isinstance(right, BaseModel):
        right = right.model_dump(mode="json")
    if isinstance(left, dict) and isinstance(right, dict):
        paths = []
        for key in sorted(left.keys() | right.keys()):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                paths.append(path)
            else:
                paths.extend(differing_paths(left[key], right[key], path))
        return paths
    return [] if left == right else [prefix]


def compare_keys(
    left: ContractModel | None, right: ContractModel | None, *, left_eligible: bool = True, right_eligible: bool = True
) -> Compatibility:
    if left is None or right is None:
        return Compatibility(state="unavailable")
    paths = differing_paths(left, right)
    if not left_eligible or not right_eligible:
        return Compatibility(state="ineligible", differing_paths=paths)
    return Compatibility(state="incompatible" if paths else "comparable", differing_paths=paths)


def rankability(
    *,
    quality: QualityKey,
    cost: CostKey | None,
    latency: LatencyKey | None,
    cost_coverage: float,
    valid: bool = True,
    complete: bool = True,
    working_tree_state: str = "clean",
) -> Rankability:
    reason = (
        "invalid"
        if not valid
        else "incomplete"
        if not complete
        else ("unverified_code" if working_tree_state != "clean" else None)
    )

    def eligibility(family_reason: str | None) -> Eligibility:
        final = reason or family_reason
        return Eligibility(eligible=final is None, reason=final)

    return Rankability(
        quality=eligibility(None),
        cost=eligibility(
            "missing_cost_provenance" if cost is None else "partial_cost_coverage" if cost_coverage != 1 else None
        ),
        latency=eligibility("missing_execution_provenance" if latency is None else None),
    )
