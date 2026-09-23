from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DatasetConfig(ConfigModel):
    name: str = "allenai/wildjailbreak"
    revision: str = Field(min_length=7)
    split: str = "train"
    config_name: str | None = None
    fixture_path: Path | None = None
    current_revision: str | None = None

    @model_validator(mode="after")
    def immutable_revision(self) -> DatasetConfig:
        if self.fixture_path is None and (
            len(self.revision) != 40 or not all(c in "0123456789abcdef" for c in self.revision.lower())
        ):
            raise ValueError("live dataset revision must be a full 40-character commit SHA")
        return self


class SampleConfig(ConfigModel):
    rate: float = Field(default=0.05, gt=0, le=1)
    seed: int = 20260918


class AdapterConfig(ConfigModel):
    id: str
    kind: Literal["fake", "jev", "openrouter"]
    model: str
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)
    cost_reservation_usd: float | None = Field(default=None, gt=0)


class ExecutionConfig(ConfigModel):
    routing_region_class: str | None = None
    warmup_policy: Literal["none"] = "none"
    concurrency: int = Field(default=4, ge=1, le=100)
    retries: int = Field(default=2, ge=0, le=10)
    timeout_seconds: float = Field(default=30, gt=0)
    cost_cap_usd: float | None = Field(default=None, gt=0)


class BenchmarkConfig(ConfigModel):
    dataset: DatasetConfig
    task: str
    sample: SampleConfig = Field(default_factory=SampleConfig)
    adapters: list[AdapterConfig]
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    output_dir: Path = Path("results/runs")

    @model_validator(mode="after")
    def require_paid_cost_controls(self) -> BenchmarkConfig:
        paid = [adapter for adapter in self.adapters if adapter.enabled and adapter.kind != "fake"]
        if not paid:
            return self
        if self.execution.cost_cap_usd is None:
            raise ValueError("execution.cost_cap_usd is required when a paid adapter is enabled")
        missing = [adapter.id for adapter in paid if adapter.cost_reservation_usd is None]
        if missing:
            raise ValueError(
                "cost_reservation_usd is required for enabled paid adapters: " + ", ".join(sorted(missing))
            )
        minimum = sum(
            Decimal(str(adapter.cost_reservation_usd)) * (self.execution.retries + 1)
            for adapter in paid
            if adapter.cost_reservation_usd is not None
        )
        cap = Decimal(str(self.execution.cost_cap_usd))
        if cap < minimum:
            raise ValueError(
                f"execution.cost_cap_usd must be at least {minimum} to allow one fully retried "
                "attempt per enabled paid adapter"
            )
        return self


def load_config(
    path: Path,
    *,
    rate: float | None = None,
    seed: int | None = None,
    output_dir: Path | None = None,
    cost_cap_usd: float | None = None,
) -> BenchmarkConfig:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")
    if rate is not None:
        raw.setdefault("sample", {})["rate"] = rate
    if seed is not None:
        raw.setdefault("sample", {})["seed"] = seed
    if output_dir is not None:
        raw["output_dir"] = str(output_dir)
    if cost_cap_usd is not None:
        raw.setdefault("execution", {})["cost_cap_usd"] = cost_cap_usd
    return BenchmarkConfig.model_validate(raw)
