from __future__ import annotations

import hashlib
import math
from collections import defaultdict

from guardrail_bench.models import SourceExample, StratumCount, TaskDefinition


def _key(example: SourceExample, seed: int) -> tuple[bytes, str]:
    digest = hashlib.sha256(f"{seed}\0{example.source_id}".encode()).digest()
    return digest, example.source_id


def stratified_sample(
    examples: list[SourceExample], task: TaskDefinition, rate: float, seed: int
) -> tuple[list[SourceExample], dict[str, StratumCount]]:
    if not 0 < rate <= 1:
        raise ValueError("sample rate must be in (0, 1]")
    strata: dict[str, list[SourceExample]] = defaultdict(list)
    seen: set[str] = set()
    for example in examples:
        if example.source_id in seen:
            raise ValueError(f"duplicate source ID: {example.source_id}")
        seen.add(example.source_id)
        if task.ground_truth(example.source_label) is not None:
            strata[example.source_label].append(example)
    required = {label for label, value in task.label_mapping.items() if value is not None}
    missing = required - strata.keys()
    if missing:
        raise ValueError(f"eligible dataset is missing required strata: {', '.join(sorted(missing))}")
    selected: list[SourceExample] = []
    counts: dict[str, StratumCount] = {}
    for label in sorted(required):
        ordered = sorted(strata[label], key=lambda item: _key(item, seed))
        count = len(ordered) if rate == 1 else math.floor(len(ordered) * rate)
        if count < 1:
            minimum = 1 / len(ordered)
            raise ValueError(f"sample rate {rate} selects no rows from {label}; use at least {minimum:.6g}")
        chosen = ordered[:count]
        selected.extend(chosen)
        counts[label] = StratumCount(eligible=len(ordered), selected=count)
    selected.sort(key=lambda item: _key(item, seed))
    return selected, counts
