from __future__ import annotations

import math
from collections import defaultdict

from guardrail_bench.models import ConfusionMatrix, Prediction, SystemMetrics


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def aggregate(predictions: list[Prediction]) -> list[SystemMetrics]:
    groups: dict[tuple[str, str], list[Prediction]] = defaultdict(list)
    for prediction in predictions:
        groups[(prediction.adapter_id, prediction.model_id)].append(prediction)
    results = []
    for (adapter_id, model_id), records in sorted(groups.items()):
        successful = [record for record in records if record.error is None]
        tp = sum(record.decision is True and record.ground_truth for record in successful)
        tn = sum(record.decision is False and not record.ground_truth for record in successful)
        fp = sum(record.decision is True and not record.ground_truth for record in successful)
        fn = sum(record.decision is False and record.ground_truth for record in successful)
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        latencies = [record.latency_ms for record in successful]
        total_cost = sum(record.estimated_cost_usd for record in records)
        results.append(
            SystemMetrics(
                adapter_id=adapter_id,
                model_id=model_id,
                attempted=len(records),
                successful=len(successful),
                errors=len(records) - len(successful),
                coverage=_ratio(len(successful), len(records)),
                precision=precision,
                recall=recall,
                f1=_ratio(2 * precision * recall, precision + recall),
                accuracy=_ratio(tp + tn, len(successful)),
                confusion=ConfusionMatrix(true_positive=tp, true_negative=tn, false_positive=fp, false_negative=fn),
                latency_p50_ms=_percentile(latencies, 0.5),
                latency_p95_ms=_percentile(latencies, 0.95),
                total_cost_usd=total_cost,
                cost_per_1000_examples_usd=_ratio(total_cost * 1000, len(records)),
            )
        )
    return results
