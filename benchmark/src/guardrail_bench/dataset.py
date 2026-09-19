from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from guardrail_bench.config import DatasetConfig
from guardrail_bench.models import DatasetMetadata, Message, Role, SourceExample
from guardrail_bench.tasks import LABELS


def _fingerprint(columns: Iterable[str]) -> str:
    canonical = json.dumps(sorted(columns), separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def normalize_row(row: dict[str, Any], index: int) -> SourceExample:
    label = row.get("data_type") or row.get("label") or row.get("source_label")
    if label not in LABELS:
        raise ValueError(f"row {index}: unsupported WildJailbreak label {label!r}")
    source_id = row.get("id") or row.get("source_id")
    if source_id is None:
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
        source_id = f"wildjailbreak-{digest[:24]}"
    if isinstance(row.get("conversation"), list):
        messages = tuple(Message.model_validate(message) for message in row["conversation"])
    else:
        prompt = row.get("adversarial") or row.get("prompt") or row.get("instruction")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"row {index}: no supported conversation or prompt field")
        messages = (Message(role=Role.USER, content=prompt),)
    return SourceExample(source_id=str(source_id), source_label=str(label), conversation=messages)


def load_wildjailbreak(config: DatasetConfig) -> tuple[list[SourceExample], DatasetMetadata]:
    rows: list[dict[str, Any]]
    if config.fixture_path:
        rows = [json.loads(line) for line in config.fixture_path.read_text().splitlines() if line.strip()]
    else:
        try:
            from datasets import load_dataset  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("install the 'dataset' extra to load WildJailbreak") from exc
        dataset = load_dataset(config.name, config.config_name, split=config.split, revision=config.revision)
        rows = [dict(row) for row in dataset]
    if not rows:
        raise ValueError("dataset is empty")
    columns = set().union(*(row.keys() for row in rows))
    examples = [normalize_row(row, index) for index, row in enumerate(rows)]
    return examples, DatasetMetadata(
        name=config.name,
        revision=config.revision,
        split=config.split,
        config_name=config.config_name,
        schema_fingerprint=_fingerprint(columns),
        retrieved_at=datetime.now(UTC),
    )
