from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from guardrail_bench import SCHEMA_VERSION


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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

    def ground_truth(self, label: str) -> bool | None:
        if label not in self.label_mapping:
            raise ValueError(f"unknown source label: {label}")
        return self.label_mapping[label]


class Usage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    provider_fields: dict[str, Any] = Field(default_factory=dict)


class PredictionError(StrictModel):
    kind: Literal["timeout", "rate_limit", "provider", "invalid_response", "configuration"]
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
    estimated_cost_usd: float = Field(default=0, ge=0)
    error: PredictionError | None = None

    @model_validator(mode="after")
    def decision_xor_error(self) -> Prediction:
        if (self.decision is None) == (self.error is None):
            raise ValueError("exactly one of decision or error is required")
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
    started_at: datetime
    completed_at: datetime
    wall_clock_duration_ms: float = Field(ge=0)


class ConfusionMatrix(StrictModel):
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int


class SystemMetrics(StrictModel):
    adapter_id: str
    model_id: str
    attempted: int
    successful: int
    errors: int
    coverage: float
    precision: float
    recall: float
    f1: float
    accuracy: float
    confusion: ConfusionMatrix
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    total_cost_usd: float
    cost_per_1000_examples_usd: float


class AggregateResult(StrictModel):
    schema_version: str = SCHEMA_VERSION
    manifest: RunManifest
    systems: list[SystemMetrics]
    potentially_stale: bool = False


def require_compatible_schema(version: str) -> None:
    if version.split(".", 1)[0] != SCHEMA_VERSION.split(".", 1)[0]:
        raise ValueError(f"unsupported schema version {version}; expected {SCHEMA_VERSION} major")
