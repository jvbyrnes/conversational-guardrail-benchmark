from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from datetime import UTC, datetime

from guardrail_bench.adapters import (
    FakeAdapter,
    JevAdapter,
    ModelAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
    call_with_retry,
)
from guardrail_bench.artifacts import write_artifacts
from guardrail_bench.config import AdapterConfig, BenchmarkConfig
from guardrail_bench.dataset import load_wildjailbreak
from guardrail_bench.metrics import aggregate
from guardrail_bench.models import AggregateResult, Prediction, RunManifest
from guardrail_bench.pricing import load_pricing
from guardrail_bench.sampling import stratified_sample
from guardrail_bench.tasks import get_task


def _adapter(config: AdapterConfig) -> ModelAdapter:
    if config.kind == "fake":
        return FakeAdapter(config.id, config.model)
    if config.kind == "jev":
        return JevAdapter(config.id, config.model, config.parameters)
    if config.kind == "openrouter":
        return OpenRouterAdapter(config.id, config.model, config.parameters)
    return OpenAIAdapter(config.id, config.model, config.parameters)


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def run(config: BenchmarkConfig) -> tuple[RunManifest, list[Prediction], AggregateResult]:
    started = datetime.now(UTC)
    task = get_task(config.task)
    examples, dataset_metadata = load_wildjailbreak(config.dataset)
    selected, strata = stratified_sample(examples, task, config.sample.rate, config.sample.seed)
    enabled = [item for item in config.adapters if item.enabled]
    if not enabled:
        raise ValueError("at least one adapter must be enabled")
    pricing = load_pricing(config.pricing_file)
    identity = json.dumps(
        {
            "dataset": config.dataset.revision,
            "task": task.task_id,
            "version": task.version,
            "rate": config.sample.rate,
            "seed": config.sample.seed,
            "sources": [e.source_id for e in selected],
            "models": [(a.id, a.model, a.parameters) for a in enabled],
        },
        sort_keys=True,
    )
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
    semaphore = asyncio.Semaphore(config.execution.concurrency)

    async def classify(adapter: ModelAdapter, example_index: int) -> Prediction:
        example = selected[example_index]
        async with semaphore:
            result, latency = await call_with_retry(
                adapter,
                example.conversation,
                task,
                retries=config.execution.retries,
                timeout_seconds=config.execution.timeout_seconds,
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
            estimated_cost_usd=pricing.cost(adapter.model_id, result.usage),
            error=result.error,
        )

    adapters = [_adapter(item) for item in enabled]
    predictions = list(
        await asyncio.gather(*(classify(adapter, index) for adapter in adapters for index in range(len(selected))))
    )
    completed = datetime.now(UTC)
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
        models={item.id: {"kind": item.kind, "model": item.model, "parameters": item.parameters} for item in enabled},
        pricing_version=pricing.version,
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
    write_artifacts(config.output_dir / run_id, manifest, predictions, result)
    return manifest, predictions, result
