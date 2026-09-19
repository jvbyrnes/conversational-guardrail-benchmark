from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from guardrail_bench.models import Usage


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_per_million_usd: float
    output_per_million_usd: float


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    models: dict[str, ModelPrice]

    def cost(self, model: str, usage: Usage) -> float:
        price = self.models.get(model)
        if price is None:
            return 0.0
        return (
            usage.input_tokens * price.input_per_million_usd + usage.output_tokens * price.output_per_million_usd
        ) / 1_000_000


def load_pricing(path: Path) -> Pricing:
    return Pricing.model_validate(yaml.safe_load(path.read_text()))
