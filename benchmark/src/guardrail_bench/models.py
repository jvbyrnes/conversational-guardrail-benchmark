from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from guardrail_bench import SCHEMA_VERSION
from guardrail_bench.comparison import CodeProvenance, EvaluationIdentity, SystemIdentity


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(StrictModel):
    role: Role
    content: str = Field(min_length=1)


class SourceExample(StrictModel):
    source_id: str = Field(min_length=1)
    source_label: str
    conversation: tuple[Message, ...] = Field(min_length=1)


class TaskDefinition(StrictModel):
    task_id: str
    version: str
    question: str
    label_mapping: dict[str, bool | None]
    decision_threshold: float = Field(default=0.5, ge=0, le=1)
    parser_version: str = "1.0.0"

    def ground_truth(self, label: str) -> bool | None:
        if label not in self.label_mapping:
            raise ValueError(f"unknown source label: {label}")
        return self.label_mapping[label]


class Usage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    provider_fields: dict[str, Any] = Field(default_factory=dict)


class PredictionError(StrictModel):
    kind: Literal[
        "timeout",
        "rate_limit",
        "provider",
        "invalid_response",
        "configuration",
        "cost_cap",
        "insufficient_funds",
    ]
    message: str
    retryable: bool = False


class Prediction(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    source_id: str
    source_label: str
    ground_truth: bool
    task_id: str
    classifier_version: str
    adapter_id: str
    model_id: str
    decision: bool | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    latency_ms: float = Field(ge=0)
    usage: Usage = Field(default_factory=Usage)
    system_id: str | None = None
    evaluation_id: str | None = None
    evaluated_system_id: str | None = None
    cost_usd: float | None = Field(default=None, ge=0)
    cost_status: Literal["reported", "estimated", "unavailable"] = "unavailable"
    currency: str | None = None
    cost_method: str | None = None
    billing_policy: str | None = None
    estimated_cost_usd: float = Field(default=0, ge=0)
    error: PredictionError | None = None

    @model_validator(mode="after")
    def decision_xor_error(self) -> Prediction:
        if (self.decision is None) == (self.error is None):
            raise ValueError("exactly one of decision or error is required")
        known_cost = self.cost_status != "unavailable"
        if known_cost != (self.cost_usd is not None):
            raise ValueError("known cost status requires a cost and unavailable cost requires null")
        provenance = (self.currency, self.cost_method, self.billing_policy)
        complete_provenance = all(value is not None for value in provenance)
        absent_provenance = all(value is None for value in provenance)
        if known_cost and not complete_provenance:
            raise ValueError("known cost requires complete provenance")
        if not known_cost and not (complete_provenance or absent_provenance):
            raise ValueError("unavailable cost provenance must be complete or absent")
        return self


class DatasetMetadata(StrictModel):
    name: str
    revision: str
    split: str
    config_name: str | None = None
    schema_fingerprint: str
    retrieved_at: datetime


class StratumCount(StrictModel):
    eligible: int = Field(ge=0)
    selected: int = Field(ge=0)


class RunManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    code_revision: str
    code_provenance: CodeProvenance | None = None
    evaluation: EvaluationIdentity | None = None
    systems: dict[str, SystemIdentity] = Field(default_factory=dict)
    private_cohort_digest: str | None = None
    execution_provenance: dict[str, Any] = Field(default_factory=dict)
    dataset: DatasetMetadata
    task_id: str
    classifier_version: str
    sample_rate: float = Field(gt=0, le=1)
    sample_count: int = Field(ge=1)
    seed: int
    strata: dict[str, StratumCount]
    run_kind: Literal["exploratory", "publication"]
    models: dict[str, dict[str, Any]]
    pricing_version: str
    cost_cap_usd: float | None = Field(default=None, gt=0)
    cost_reserved_usd: float = Field(default=0, ge=0)
    cost_admitted_usd: float = Field(default=0, ge=0)
    cost_actual_usd: float = Field(default=0, ge=0)
    status: Literal["complete", "incomplete"] = "complete"
    incomplete_reason: str | None = None
    started_at: datetime
    completed_at: datetime
    wall_clock_duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def incomplete_reason_matches_status(self) -> RunManifest:
        if (self.status == "incomplete") != (self.incomplete_reason is not None):
            raise ValueError("incomplete runs require a reason and complete runs must not have one")
        return self


class RunCheckpoint(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    status: Literal["running", "complete", "incomplete"]
    expected_predictions: int = Field(ge=1)
    predictions_completed: int = Field(ge=0)
    started_at: datetime
    updated_at: datetime
    reason: str | None = None

    @model_validator(mode="after")
    def reason_matches_status(self) -> RunCheckpoint:
        if self.status == "incomplete" and self.reason is None:
            raise ValueError("incomplete checkpoints require a reason")
        if self.status != "incomplete" and self.reason is not None:
            raise ValueError("only incomplete checkpoints may include a reason")
        if self.predictions_completed > self.expected_predictions:
            raise ValueError("checkpoint predictions exceed expected count")
        return self


class ConfusionMatrix(StrictModel):
    true_positive: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)


class SystemMetrics(StrictModel):
    adapter_id: str
    model_id: str
    attempted: int = Field(ge=0)
    successful: int = Field(ge=0)
    errors: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    accuracy: float = Field(ge=0, le=1)
    confusion: ConfusionMatrix
    latency_p50_ms: float | None = Field(ge=0)
    latency_p95_ms: float | None = Field(ge=0)
    system_id: str | None = None
    evaluated_system_id: str | None = None
    cost_known_count: int = Field(default=0, ge=0)
    cost_coverage: float = Field(default=0, ge=0, le=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float | None = Field(ge=0)
    cost_per_1000_examples_usd: float | None = Field(ge=0)

    @model_validator(mode="after")
    def internally_consistent_counts(self) -> SystemMetrics:
        if self.successful + self.errors != self.attempted:
            raise ValueError("successful plus errors must equal attempted")
        if self.cost_known_count > self.attempted:
            raise ValueError("known cost count cannot exceed attempted")
        return self


class AggregateResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    manifest: RunManifest
    systems: list[SystemMetrics]
    potentially_stale: bool = False


def require_compatible_schema(version: str) -> None:
    if version.split(".", 1)[0] != SCHEMA_VERSION.split(".", 1)[0]:
        raise ValueError(f"unsupported schema version {version}; expected {SCHEMA_VERSION} major")
