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
    groups: dict[tuple[str, str, str], list[Prediction]] = defaultdict(list)
    for prediction in predictions:
        groups[(prediction.adapter_id, prediction.model_id, prediction.evaluated_system_id or "")].append(prediction)
    results = []
    for (adapter_id, model_id, _), records in sorted(groups.items()):
        successful = [record for record in records if record.error is None]
        tp = sum(record.decision is True and record.ground_truth for record in successful)
        tn = sum(record.decision is False and not record.ground_truth for record in successful)
        fp = sum(record.decision is True and not record.ground_truth for record in successful)
        fn = sum(record.decision is False and record.ground_truth for record in successful)
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        latencies = [record.latency_ms for record in successful]
        known_costs = [record.cost_usd for record in records if record.cost_usd is not None]
        total_cost = sum(known_costs) if len(known_costs) == len(records) else None
        results.append(
            SystemMetrics(
                adapter_id=adapter_id,
                system_id=records[0].system_id,
                evaluated_system_id=records[0].evaluated_system_id,
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
                cost_per_1000_examples_usd=(None if total_cost is None else _ratio(total_cost * 1000, len(records))),
                cost_known_count=len(known_costs),
                cost_coverage=_ratio(len(known_costs), len(records)),
                input_tokens=sum(record.usage.input_tokens for record in records),
                output_tokens=sum(record.usage.output_tokens for record in records),
            )
        )
    return results
