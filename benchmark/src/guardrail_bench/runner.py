from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from guardrail_bench.adapters import (
    JEV_PRICING_VERSION,
    FakeAdapter,
    JevAdapter,
    ModelAdapter,
    OpenRouterAdapter,
    call_with_retry,
)
from guardrail_bench.artifacts import append_checkpoint, create_checkpoint, finish_checkpoint, write_artifacts
from guardrail_bench.budget import CostBudget
from guardrail_bench.config import AdapterConfig, BenchmarkConfig
from guardrail_bench.dataset import load_wildjailbreak
from guardrail_bench.metrics import aggregate
from guardrail_bench.models import AggregateResult, Prediction, RunManifest
from guardrail_bench.sampling import stratified_sample
from guardrail_bench.tasks import get_task


class ProgressReporter(Protocol):
    def start(self, total: int) -> None: ...

    def advance(self, prediction: Prediction) -> None: ...


def _adapter(config: AdapterConfig) -> ModelAdapter:
    if config.kind == "fake":
        return FakeAdapter(config.id, config.model)
    if config.kind == "jev":
        return JevAdapter(config.id, config.model, config.parameters)
    if config.kind == "openrouter":
        return OpenRouterAdapter(config.id, config.model, config.parameters)
    raise ValueError(f"unsupported adapter kind: {config.kind}")


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _estimated_cost(result: Any) -> float:
    fields = result.usage.provider_fields
    value = fields.get("cost", fields.get("estimated_cost", 0.0))
    return float(value)


def _pricing_version(enabled: list[AdapterConfig]) -> str:
    versions = ["provider-reported+reservation-v2"]
    if any(item.kind == "jev" for item in enabled):
        versions.append(JEV_PRICING_VERSION)
    return "+".join(versions)


async def run(
    config: BenchmarkConfig, *, progress: ProgressReporter | None = None
) -> tuple[RunManifest, list[Prediction], AggregateResult]:
    started = datetime.now(UTC)
    enabled = [item for item in config.adapters if item.enabled]
    if not enabled:
        raise ValueError("at least one adapter must be enabled")
    duplicate_ids = sorted(
        adapter_id for adapter_id, count in Counter(item.id for item in enabled).items() if count > 1
    )
    if duplicate_ids:
        raise ValueError(f"duplicate enabled adapter IDs: {', '.join(duplicate_ids)}")
    budget = (
        CostBudget.from_float(config.execution.cost_cap_usd)
        if config.execution.cost_cap_usd is not None
        else None
    )

    task = get_task(config.task)
    examples, dataset_metadata = load_wildjailbreak(config.dataset)
    selected, strata = stratified_sample(examples, task, config.sample.rate, config.sample.seed)
    identity = json.dumps(
        {
            "dataset": config.dataset.revision,
            "task": task.task_id,
            "version": task.version,
            "rate": config.sample.rate,
            "seed": config.sample.seed,
            "sources": [e.source_id for e in selected],
            "models": [(a.id, a.model, a.parameters, a.cost_reservation_usd) for a in enabled],
            "cost_cap_usd": config.execution.cost_cap_usd,
        },
        sort_keys=True,
    )
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
    run_directory = config.output_dir / run_id

    async def classify(adapter: ModelAdapter, adapter_config: AdapterConfig, example_index: int) -> Prediction:
        example = selected[example_index]
        result, latency = await call_with_retry(
            adapter,
            example.conversation,
            task,
            retries=config.execution.retries,
            timeout_seconds=config.execution.timeout_seconds,
            budget=budget if adapter_config.kind != "fake" else None,
            cost_reservation_usd=adapter_config.cost_reservation_usd,
        )
        return Prediction(
            run_id=run_id,
            source_id=example.source_id,
            source_label=example.source_label,
            ground_truth=bool(task.ground_truth(example.source_label)),
            task_id=task.task_id,
            classifier_version=task.version,
            adapter_id=adapter.adapter_id,
            model_id=adapter.model_id,
            decision=result.decision,
            score=result.score,
            latency_ms=latency,
            usage=result.usage,
            estimated_cost_usd=_estimated_cost(result),
            error=result.error,
        )

    adapters = [(_adapter(item), item) for item in enabled]
    expected_predictions = len(selected) * len(adapters)
    create_checkpoint(run_directory, run_id, expected_predictions, started)
    if progress is not None:
        progress.start(expected_predictions)
    checkpoint_lock = asyncio.Lock()

    async def classify_and_checkpoint(
        adapter: ModelAdapter, adapter_config: AdapterConfig, example_index: int
    ) -> Prediction:
        prediction = await classify(adapter, adapter_config, example_index)
        async with checkpoint_lock:
            append_checkpoint(run_directory, [prediction], expected_predictions)
            if progress is not None:
                progress.advance(prediction)
        return prediction

    predictions: list[Prediction] = []
    pending: list[Coroutine[Any, Any, Prediction]] = []
    try:
        for index in range(len(selected)):
            for adapter, adapter_config in adapters:
                pending.append(classify_and_checkpoint(adapter, adapter_config, index))
                if len(pending) == config.execution.concurrency:
                    completed_batch = list(await asyncio.gather(*pending))
                    predictions.extend(completed_batch)
                    pending.clear()
        if pending:
            completed_batch = list(await asyncio.gather(*pending))
            predictions.extend(completed_batch)
    except BaseException as exc:
        finish_checkpoint(
            run_directory,
            status="incomplete",
            reason=f"run interrupted by {type(exc).__name__}",
        )
        raise
    completed = datetime.now(UTC)
    blocking_errors = [
        prediction.error
        for prediction in predictions
        if prediction.error is not None and prediction.error.kind in {"cost_cap", "insufficient_funds"}
    ]
    insufficient_funds = next(
        (error for error in blocking_errors if error.kind == "insufficient_funds"),
        None,
    )
    incomplete_reason = (
        insufficient_funds.message
        if insufficient_funds is not None
        else blocking_errors[0].message if blocking_errors else None
    )
    status: Literal["complete", "incomplete"] = "incomplete" if incomplete_reason is not None else "complete"
    manifest = RunManifest(
        run_id=run_id,
        code_revision=_git_revision(),
        dataset=dataset_metadata,
        task_id=task.task_id,
        classifier_version=task.version,
        sample_rate=config.sample.rate,
        sample_count=len(selected),
        seed=config.sample.seed,
        strata=strata,
        run_kind="publication" if config.sample.rate == 1 else "exploratory",
        models={
            item.id: {
                "kind": item.kind,
                "model": item.model,
                "parameters": item.parameters,
                "cost_reservation_usd": item.cost_reservation_usd,
            }
            for item in enabled
        },
        pricing_version=_pricing_version(enabled),
        cost_cap_usd=config.execution.cost_cap_usd,
        cost_reserved_usd=float(budget.reserved_usd) if budget is not None else 0,
        cost_admitted_usd=float(budget.admitted_usd) if budget is not None else 0,
        cost_actual_usd=float(budget.actual_usd) if budget is not None else 0,
        status=status,
        incomplete_reason=incomplete_reason,
        started_at=started,
        completed_at=completed,
        wall_clock_duration_ms=(completed - started).total_seconds() * 1000,
    )
    result = AggregateResult(
        manifest=manifest,
        systems=aggregate(predictions),
        potentially_stale=(
            config.dataset.current_revision is not None and config.dataset.current_revision != config.dataset.revision
        ),
    )
    write_artifacts(run_directory, manifest, predictions, result)
    finish_checkpoint(run_directory, status=status, reason=incomplete_reason)
    return manifest, predictions, result
