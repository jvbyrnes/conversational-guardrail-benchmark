"""Strict public contract for the reviewed headline-only comparison."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from guardrail_bench.comparison import canonical_json, fingerprint
from guardrail_bench.models import ConfusionMatrix, StrictModel

_TOLERANCE = 1e-9
# This is deliberately a one-off contract for the exact reviewed public summary,
# not a reusable schema for publishing arbitrary internally consistent results.
_EXPECTED_REVIEWED_PAYLOAD_FINGERPRINT = "sha256:3be43fceab7798f07d65fa9e0dd71e9ac3b7df091eea8a5545f1dc0977e60d09"


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _matches(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=_TOLERANCE, abs_tol=_TOLERANCE)


class HeadlineDataset(StrictModel):
    name: Literal["allenai/wildjailbreak"]
    revision: Literal["5ddc12a7894f842b0619b8e1c7ee496b198af009"]


class HeadlineSample(StrictModel):
    rate: float = Field(ge=0.01, le=0.01)
    count: Literal[1614]
    seed: Literal[20260918]


class HeadlineMetrics(StrictModel):
    attempted: int = Field(ge=1)
    successful: int = Field(ge=0)
    errors: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    accuracy: float = Field(ge=0, le=1)
    confusion: ConfusionMatrix
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    cost_known_count: int = Field(ge=0)
    cost_coverage: float = Field(ge=0, le=1)
    known_cost_usd: float | None = Field(default=None, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def derived_values_are_consistent(self) -> HeadlineMetrics:
        if self.successful + self.errors != self.attempted:
            raise ValueError("successful plus errors must equal attempted")
        if self.cost_known_count > self.attempted:
            raise ValueError("known cost count cannot exceed attempted")

        confusion = self.confusion
        tp = confusion.true_positive
        tn = confusion.true_negative
        fp = confusion.false_positive
        fn = confusion.false_negative
        if tp + tn + fp + fn != self.successful:
            raise ValueError("confusion counts must equal successful predictions")

        expected = {
            "coverage": _ratio(self.successful, self.attempted),
            "precision": _ratio(tp, tp + fp),
            "recall": _ratio(tp, tp + fn),
            "accuracy": _ratio(tp + tn, self.successful),
            "cost_coverage": _ratio(self.cost_known_count, self.attempted),
        }
        expected["f1"] = _ratio(
            2 * expected["precision"] * expected["recall"],
            expected["precision"] + expected["recall"],
        )
        for field, value in expected.items():
            if not _matches(getattr(self, field), value):
                raise ValueError(f"{field} does not match its derived value")

        if (self.latency_p50_ms is None) != (self.latency_p95_ms is None):
            raise ValueError("latency percentiles must both be present or absent")
        if self.latency_p50_ms is not None and self.latency_p95_ms is not None:
            if self.latency_p95_ms < self.latency_p50_ms:
                raise ValueError("latency p95 must be at least p50")

        if self.cost_known_count == 0:
            if self.known_cost_usd is not None:
                raise ValueError("known cost must be unavailable when no costs are known")
        elif self.known_cost_usd is None:
            raise ValueError("known cost is required when any costs are known")

        if self.cost_known_count == self.attempted:
            if self.total_cost_usd is None:
                raise ValueError("complete cost coverage requires a total cost")
            if self.known_cost_usd is None or not _matches(self.total_cost_usd, self.known_cost_usd):
                raise ValueError("complete total cost must equal known cost")
        elif self.total_cost_usd is not None:
            raise ValueError("partial cost coverage cannot publish a total cost")
        return self


class JevHeadlineSystem(StrictModel):
    system: Literal["jev"]
    run_id: Literal["20260925T004541177372Z-a4c027600058"]
    cost_basis: Literal["estimated_input_tokens"]
    metrics: HeadlineMetrics


class LunaHeadlineSystem(StrictModel):
    system: Literal["luna"]
    run_id: Literal["20260925T014904391035Z-ba0833bb4475"]
    cost_basis: Literal["provider_reported_partial"]
    metrics: HeadlineMetrics


HeadlineSystem = Annotated[JevHeadlineSystem | LunaHeadlineSystem, Field(discriminator="system")]


class HeadlineComparison(StrictModel):
    schema_version: Literal["1.1.0"] = "1.1.0"
    status: Literal["exploratory"]
    task_id: Literal["harmful_jailbreak"]
    task_version: Literal["1.0.0"]
    dataset: HeadlineDataset
    sample: HeadlineSample
    systems: list[HeadlineSystem] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def systems_are_complete_and_unique(self) -> HeadlineComparison:
        if {system.system for system in self.systems} != {"jev", "luna"}:
            raise ValueError("headline must contain exactly the reviewed systems")
        if len({system.run_id for system in self.systems}) != len(self.systems):
            raise ValueError("headline run IDs must be unique")
        if any(system.metrics.attempted != self.sample.count for system in self.systems):
            raise ValueError("each attempted count must equal the sample count")
        if fingerprint(self.model_dump(mode="json")) != _EXPECTED_REVIEWED_PAYLOAD_FINGERPRINT:
            raise ValueError("headline payload does not match the exact reviewed summary")
        return self


def headline_bytes(headline: HeadlineComparison) -> bytes:
    """Return deterministic public bytes, retaining explicit unavailable values."""
    return canonical_json(headline.model_dump(mode="json")) + b"\n"
