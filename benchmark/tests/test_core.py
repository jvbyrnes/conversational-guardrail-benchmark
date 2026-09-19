from __future__ import annotations

from pathlib import Path

import pytest
from guardrail_bench.adapters import OpenRouterAdapter
from guardrail_bench.config import BenchmarkConfig, DatasetConfig, load_config
from guardrail_bench.dataset import load_wildjailbreak
from guardrail_bench.metrics import aggregate
from guardrail_bench.models import Prediction, PredictionError
from guardrail_bench.sampling import stratified_sample
from guardrail_bench.tasks import get_task
from pydantic import ValidationError

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "label,expected",
    [("adversarial_harmful", True), ("adversarial_benign", False), ("vanilla_harmful", None), ("vanilla_benign", None)],
)
def test_harmful_mapping(label: str, expected: bool | None) -> None:
    assert get_task("harmful_jailbreak").ground_truth(label) is expected


@pytest.mark.parametrize(
    "label,expected",
    [
        ("adversarial_harmful", True),
        ("adversarial_benign", True),
        ("vanilla_harmful", False),
        ("vanilla_benign", False),
    ],
)
def test_adversarial_mapping(label: str, expected: bool) -> None:
    assert get_task("adversarial_technique").ground_truth(label) is expected


def fixture_examples():
    config = DatasetConfig(
        name="fixture",
        revision="fixture",
        split="test",
        fixture_path=ROOT / "benchmark/tests/fixtures/wildjailbreak.jsonl",
    )
    return load_wildjailbreak(config)[0]


def test_sampling_is_deterministic_stratified_and_full() -> None:
    examples = fixture_examples()
    task = get_task("adversarial_technique")
    first, counts = stratified_sample(examples, task, 0.5, 7)
    second, _ = stratified_sample(list(reversed(examples)), task, 0.5, 7)
    assert [item.source_id for item in first] == [item.source_id for item in second]
    assert all(count.selected == 1 for count in counts.values())
    full, _ = stratified_sample(examples, task, 1, 7)
    assert len(full) == 8
    changed, _ = stratified_sample(examples, task, 0.5, 8)
    assert [item.source_id for item in first] != [item.source_id for item in changed]


def test_sampling_rejects_too_small_rate() -> None:
    with pytest.raises(ValueError, match="selects no rows"):
        stratified_sample(fixture_examples(), get_task("adversarial_technique"), 0.1, 1)


def test_live_revision_must_be_immutable() -> None:
    with pytest.raises(ValidationError, match="40-character"):
        DatasetConfig(name="x", revision="mutable-branch", split="train")


def prediction(source: str, truth: bool, decision: bool | None, error: bool = False) -> Prediction:
    return Prediction(
        run_id="r",
        source_id=source,
        source_label="x",
        ground_truth=truth,
        task_id="t",
        classifier_version="1",
        adapter_id="a",
        model_id="m",
        decision=decision,
        latency_ms=10,
        error=PredictionError(kind="provider", message="x") if error else None,
    )


def test_metrics_ignore_errors_and_round_trip() -> None:
    records = [
        prediction("1", True, True),
        prediction("2", False, False),
        prediction("3", False, True),
        prediction("4", True, False),
        prediction("5", True, None, True),
    ]
    metric = aggregate(records)[0]
    assert metric.confusion.model_dump() == {
        "true_positive": 1,
        "true_negative": 1,
        "false_positive": 1,
        "false_negative": 1,
    }
    assert metric.accuracy == metric.precision == metric.recall == metric.f1 == 0.5
    assert metric.coverage == 0.8
    assert Prediction.model_validate_json(records[0].model_dump_json()) == records[0]


def test_config_round_trip() -> None:
    config = load_config(ROOT / "benchmark/config/fixture.yaml")
    assert BenchmarkConfig.model_validate_json(config.model_dump_json()) == config


@pytest.mark.asyncio
async def test_openrouter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = await OpenRouterAdapter("router", "openai/gpt-4.1-mini").classify(
        fixture_examples()[0].conversation, get_task("adversarial_technique")
    )
    assert result.error is not None
    assert result.error.kind == "configuration"
    assert result.error.message == "OPENROUTER_API_KEY is not set"
