from __future__ import annotations

import asyncio
import json
from pathlib import Path

import guardrail_bench.runner as runner
import pytest
from guardrail_bench.adapters import AdapterResult
from guardrail_bench.config import BenchmarkConfig, load_config
from guardrail_bench.models import AggregateResult, Message, PredictionError, RunCheckpoint, TaskDefinition, Usage
from guardrail_bench.runner import run

ROOT = Path(__file__).parents[2]


@pytest.mark.asyncio
async def test_offline_end_to_end(tmp_path: Path) -> None:
    config = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path)
    manifest, predictions, aggregate = await run(config)
    directory = tmp_path / manifest.run_id
    assert manifest.run_kind == "publication"
    assert manifest.wall_clock_duration_ms >= 0
    assert len(predictions) == 8
    assert {path.name for path in directory.iterdir()} == {
        "manifest.json",
        "aggregate.json",
        "predictions.jsonl",
        "predictions.csv",
        "predictions.partial.jsonl",
        "run-status.json",
    }
    checkpoint = RunCheckpoint.model_validate_json((directory / "run-status.json").read_text())
    assert checkpoint.status == "complete"
    assert checkpoint.predictions_completed == checkpoint.expected_predictions == 8
    loaded = AggregateResult.model_validate_json((directory / "aggregate.json").read_text())
    assert loaded == aggregate
    assert "conversation" not in (directory / "predictions.jsonl").read_text()
    rows = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
    assert aggregate.systems[0].successful == len(rows)


@pytest.mark.asyncio
async def test_runner_rejects_duplicate_enabled_adapter_ids(tmp_path: Path) -> None:
    config = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path)
    config.adapters.append(config.adapters[0].model_copy())

    with pytest.raises(ValueError, match="duplicate enabled adapter IDs: fake"):
        await run(config)


@pytest.mark.asyncio
async def test_runner_batches_classification_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path)
    config.execution = config.execution.model_copy(update={"concurrency": 2})
    gather_sizes: list[int] = []
    original_gather = asyncio.gather

    def tracking_gather(*awaitables: object):  # type: ignore[no-untyped-def]
        gather_sizes.append(len(awaitables))
        return original_gather(*awaitables)

    monkeypatch.setattr(asyncio, "gather", tracking_gather)
    await run(config)

    assert gather_sizes == [2, 2, 2, 2]


@pytest.mark.asyncio
async def test_runner_stops_paid_calls_at_reserved_cost_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PaidAdapter:
        adapter_id = "paid"
        model_id = "provider/model"

        def __init__(self) -> None:
            self.calls = 0

        async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
            self.calls += 1
            return AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004}))

    adapter = PaidAdapter()
    raw = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path).model_dump(mode="json")
    raw["adapters"] = [
        {
            "id": "paid",
            "kind": "openrouter",
            "model": "provider/model",
            "cost_reservation_usd": 0.01,
        }
    ]
    raw["execution"].update({"retries": 0, "cost_cap_usd": 0.02})
    config = BenchmarkConfig.model_validate(raw)
    monkeypatch.setattr(runner, "_adapter", lambda _: adapter)

    manifest, predictions, aggregate = await run(config)

    assert adapter.calls == 2
    assert manifest.cost_cap_usd == 0.02
    assert manifest.cost_reserved_usd == 0.02
    assert manifest.status == "incomplete"
    assert manifest.incomplete_reason is not None
    assert sum(item.error is not None and item.error.kind == "cost_cap" for item in predictions) == 6
    assert aggregate.systems[0].successful == 2
    directory = tmp_path / manifest.run_id
    checkpoint = RunCheckpoint.model_validate_json((directory / "run-status.json").read_text())
    assert checkpoint.status == "incomplete"
    assert checkpoint.predictions_completed == checkpoint.expected_predictions == 8


@pytest.mark.asyncio
async def test_runner_stops_after_provider_reports_insufficient_funds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnfundedAdapter:
        adapter_id = "paid"
        model_id = "provider/model"

        def __init__(self) -> None:
            self.calls = 0

        async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
            self.calls += 1
            return AdapterResult(
                None,
                error=PredictionError(kind="insufficient_funds", message="provider reported insufficient funds"),
            )

    adapter = UnfundedAdapter()
    raw = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path).model_dump(mode="json")
    raw["adapters"] = [
        {
            "id": "paid",
            "kind": "openrouter",
            "model": "provider/model",
            "cost_reservation_usd": 0.01,
        }
    ]
    raw["execution"].update({"retries": 0, "cost_cap_usd": 0.08})
    config = BenchmarkConfig.model_validate(raw)
    monkeypatch.setattr(runner, "_adapter", lambda _: adapter)

    manifest, predictions, _ = await run(config)

    assert adapter.calls == 1
    assert manifest.status == "incomplete"
    assert manifest.incomplete_reason == "provider reported insufficient funds"
    assert predictions[0].error is not None and predictions[0].error.kind == "insufficient_funds"
    assert all(item.error is not None for item in predictions)


@pytest.mark.asyncio
async def test_malformed_provider_cost_still_writes_incomplete_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MalformedCostAdapter:
        adapter_id = "paid"
        model_id = "provider/model"

        def __init__(self) -> None:
            self.calls = 0

        async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
            self.calls += 1
            return AdapterResult(
                False,
                usage=Usage(provider_fields={"cost": "not-a-number", "request_id": "offline-fixture"}),
            )

    adapter = MalformedCostAdapter()
    raw = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path).model_dump(mode="json")
    raw["adapters"] = [
        {
            "id": "paid",
            "kind": "openrouter",
            "model": "provider/model",
            "cost_reservation_usd": 0.01,
        }
    ]
    raw["execution"].update({"retries": 0, "cost_cap_usd": 0.08})
    config = BenchmarkConfig.model_validate(raw)
    monkeypatch.setattr(runner, "_adapter", lambda _: adapter)

    manifest, predictions, aggregate = await run(config)

    assert adapter.calls == 1
    assert manifest.status == "incomplete"
    assert predictions[0].error is not None and predictions[0].error.kind == "cost_cap"
    assert predictions[0].estimated_cost_usd == 0
    assert predictions[0].usage.provider_fields == {"request_id": "offline-fixture"}
    directory = tmp_path / manifest.run_id
    assert AggregateResult.model_validate_json((directory / "aggregate.json").read_text()) == aggregate
    assert len((directory / "predictions.partial.jsonl").read_text().splitlines()) == len(predictions)


@pytest.mark.asyncio
async def test_interrupted_run_keeps_completed_prediction_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class InterruptingAdapter:
        adapter_id = "fake"
        model_id = "interrupting"

        def __init__(self) -> None:
            self.calls = 0

        async def classify(self, conversation: tuple[Message, ...], task: TaskDefinition) -> AdapterResult:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulated interruption")
            return AdapterResult(False)

    config = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path)
    config.execution = config.execution.model_copy(update={"concurrency": 1})
    monkeypatch.setattr(runner, "_adapter", lambda _: InterruptingAdapter())

    with pytest.raises(RuntimeError, match="simulated interruption"):
        await run(config)

    directory = next(tmp_path.iterdir())
    checkpoint = RunCheckpoint.model_validate_json((directory / "run-status.json").read_text())
    partial = (directory / "predictions.partial.jsonl").read_text().splitlines()
    assert checkpoint.status == "incomplete"
    assert checkpoint.predictions_completed == 1
    assert len(partial) == 1
