from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from guardrail_bench.adapters import OpenRouterAdapter
from guardrail_bench.config import AdapterConfig, BenchmarkConfig, DatasetConfig, load_config
from guardrail_bench.dataset import load_wildjailbreak
from guardrail_bench.metrics import aggregate
from guardrail_bench.models import Prediction, PredictionError
from guardrail_bench.runner import _pricing_version
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


def test_live_dataset_loader_uses_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeDataset:
        def __iter__(self):
            return iter([{"id": "a", "data_type": "adversarial_harmful", "adversarial": "prompt"}])

    def fake_load_dataset(*args: object, **kwargs: object) -> FakeDataset:
        calls.update(kwargs)
        return FakeDataset()

    monkeypatch.setitem(sys.modules, "datasets", ModuleType("datasets"))
    sys.modules["datasets"].load_dataset = fake_load_dataset  # type: ignore[attr-defined]
    config = DatasetConfig(
        name="allenai/wildjailbreak",
        revision="5ddc12a7894f842b0619b8e1c7ee496b198af009",
        split="train",
    )

    load_wildjailbreak(config)

    assert calls["streaming"] is True


def test_cached_live_loader_uses_pinned_local_tsv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "train.tsv"
    path.write_text("vanilla\tadversarial\tcompletion\tdata_type\n")
    hub_calls: dict[str, object] = {}
    dataset_calls: dict[str, object] = {}

    class FakeDataset:
        def __iter__(self):
            return iter(
                [{"vanilla": "", "adversarial": "prompt", "completion": "", "data_type": "adversarial_harmful"}]
            )

    def fake_hf_hub_download(**kwargs: object) -> str:
        hub_calls.update(kwargs)
        return str(path)

    def fake_load_dataset(*args: object, **kwargs: object) -> FakeDataset:
        dataset_calls["path"] = args[0]
        dataset_calls.update(kwargs)
        return FakeDataset()

    monkeypatch.setitem(sys.modules, "huggingface_hub", ModuleType("huggingface_hub"))
    sys.modules["huggingface_hub"].hf_hub_download = fake_hf_hub_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datasets", ModuleType("datasets"))
    sys.modules["datasets"].load_dataset = fake_load_dataset  # type: ignore[attr-defined]
    config = DatasetConfig(
        name="allenai/wildjailbreak",
        revision="5ddc12a7894f842b0619b8e1c7ee496b198af009",
        config_name="train",
        split="train",
        source="cached",
    )

    examples, _ = load_wildjailbreak(config)

    assert len(examples) == 1
    assert hub_calls == {
        "repo_id": config.name,
        "repo_type": "dataset",
        "filename": "train/train.tsv",
        "revision": config.revision,
        "local_files_only": True,
    }
    assert dataset_calls == {
        "path": "csv",
        "data_files": {"train": str(path)},
        "delimiter": "\t",
        "split": "train",
        "streaming": True,
    }


def test_cached_live_loader_fails_if_file_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(**kwargs: object) -> str:
        raise FileNotFoundError("not cached")

    monkeypatch.setitem(sys.modules, "huggingface_hub", ModuleType("huggingface_hub"))
    sys.modules["huggingface_hub"].hf_hub_download = missing  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datasets", ModuleType("datasets"))
    sys.modules["datasets"].load_dataset = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    config = DatasetConfig(
        name="allenai/wildjailbreak",
        revision="5ddc12a7894f842b0619b8e1c7ee496b198af009",
        config_name="train",
        split="train",
        source="cached",
    )
    with pytest.raises(RuntimeError, match="not in the Hugging Face cache"):
        load_wildjailbreak(config)


def test_wildjailbreak_vanilla_rows_use_the_vanilla_prompt() -> None:
    examples = fixture_examples()
    vanilla = next(example for example in examples if example.source_id == "vh-1")
    assert vanilla.conversation[0].content == "[negative] harmful request without bypass framing"


def test_wildjailbreak_falls_back_when_labeled_prompt_column_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "fallback.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "fallback",
                "data_type": "adversarial_benign",
                "vanilla": "usable prompt",
                "adversarial": "",
            }
        )
        + "\n"
    )
    config = DatasetConfig(name="fixture", revision="fixture", split="test", fixture_path=path)

    examples = load_wildjailbreak(config)[0]

    assert examples[0].conversation[0].content == "usable prompt"


def test_schema_fingerprint_includes_observed_value_types(tmp_path: Path) -> None:
    def fingerprint(value: object) -> str:
        path = tmp_path / "fixture.jsonl"
        path.write_text(
            json.dumps({"id": "row", "data_type": "vanilla_benign", "vanilla": "a prompt", "extra": value}) + "\n"
        )
        config = DatasetConfig(name="fixture", revision="fixture", split="test", fixture_path=path)
        return load_wildjailbreak(config)[1].schema_fingerprint

    assert fingerprint("a prompt") != fingerprint(["a prompt"])
    assert fingerprint("a prompt") != fingerprint({"text": "a prompt"})
    assert fingerprint("a prompt") != fingerprint(1)


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


def test_prediction_rejects_nonfinite_values_and_ambiguous_cost() -> None:
    nonfinite = prediction("1", True, True).model_dump(mode="json")
    nonfinite["latency_ms"] = float("nan")
    with pytest.raises(ValidationError):
        Prediction.model_validate(nonfinite)
    raw = prediction("1", True, True).model_dump(mode="json")
    raw.update({"cost_status": "reported", "cost_usd": None})
    with pytest.raises(ValidationError, match="known cost status"):
        Prediction.model_validate(raw)


def test_config_round_trip() -> None:
    config = load_config(ROOT / "benchmark/config/fixture.yaml")
    assert BenchmarkConfig.model_validate_json(config.model_dump_json()) == config


def test_paid_adapters_require_cost_cap_and_reservation() -> None:
    raw = load_config(ROOT / "benchmark/config/fixture.yaml").model_dump(mode="json")
    raw["adapters"] = [{"id": "paid", "kind": "openrouter", "model": "provider/model"}]

    with pytest.raises(ValidationError, match="cost_cap_usd is required"):
        BenchmarkConfig.model_validate(raw)

    raw["execution"]["cost_cap_usd"] = 0.1
    with pytest.raises(ValidationError, match="cost_reservation_usd is required"):
        BenchmarkConfig.model_validate(raw)


def test_jev_pricing_version_is_manifested() -> None:
    assert "typesafe-published-input-v2026-09-22" in _pricing_version(
        [AdapterConfig(id="jev", kind="jev", model="jev-latest", cost_reservation_usd=0.005)]
    )


def test_cost_cap_covers_one_fully_retried_attempt_per_paid_adapter() -> None:
    raw = load_config(ROOT / "benchmark/config/fixture.yaml").model_dump(mode="json")
    raw["adapters"] = [
        {
            "id": "paid",
            "kind": "openrouter",
            "model": "provider/model",
            "cost_reservation_usd": 0.02,
        }
    ]
    raw["execution"].update({"retries": 2, "cost_cap_usd": 0.05})

    with pytest.raises(ValidationError, match="must be at least 0.06"):
        BenchmarkConfig.model_validate(raw)


def test_cost_cap_cli_override_is_applied_before_validation() -> None:
    raw_path = ROOT / "benchmark/config/live.example.yaml"
    config = load_config(raw_path, cost_cap_usd=0.75)
    assert config.execution.cost_cap_usd == 0.75


@pytest.mark.asyncio
async def test_openrouter_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = await OpenRouterAdapter("router", "openai/gpt-4.1-mini").classify(
        fixture_examples()[0].conversation, get_task("adversarial_technique")
    )
    assert result.error is not None
    assert result.error.kind == "configuration"
    assert result.error.message == "OPENROUTER_API_KEY is not set"
