from __future__ import annotations

import hashlib
import importlib
import json
from datetime import UTC, datetime
from typing import Any

from guardrail_bench.config import DatasetConfig
from guardrail_bench.models import DatasetMetadata, Message, Role, SourceExample
from guardrail_bench.tasks import LABELS


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    observed_types: dict[str, set[str]] = {}
    for row in rows:
        for column, value in row.items():
            type_name = f"{type(value).__module__}.{type(value).__qualname__}"
            observed_types.setdefault(column, set()).add(type_name)
    canonical = json.dumps(
        {column: sorted(types) for column, types in sorted(observed_types.items())},
        separators=(",", ":"),
    )
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
        prompt_field = "adversarial" if label.startswith("adversarial_") else "vanilla"
        # The pinned TSV contains a small number of rows whose label says
        # adversarial while that column is empty and the usable text is in
        # vanilla. Fall back across the prompt columns before rejecting it.
        prompt = (
            row.get(prompt_field)
            or row.get("vanilla")
            or row.get("adversarial")
            or row.get("prompt")
            or row.get("instruction")
        )
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
            load_dataset = importlib.import_module("datasets").load_dataset
        except ImportError as exc:
            raise RuntimeError("install the 'dataset' extra to load WildJailbreak") from exc
        # Stream the TSV-backed dataset so Arrow does not infer a single column type
        # from an early batch and then fail when later rows contain text values.
        dataset = load_dataset(
            config.name,
            config.config_name,
            split=config.split,
            revision=config.revision,
            streaming=True,
        )
        rows = [dict(row) for row in dataset]
    if not rows:
        raise ValueError("dataset is empty")
    examples = [normalize_row(row, index) for index, row in enumerate(rows)]
    return examples, DatasetMetadata(
        name=config.name,
        revision=config.revision,
        split=config.split,
        config_name=config.config_name,
        schema_fingerprint=_fingerprint(rows),
        retrieved_at=datetime.now(UTC),
    )
