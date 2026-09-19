from __future__ import annotations

import json
from pathlib import Path

import pytest
from guardrail_bench.config import load_config
from guardrail_bench.models import AggregateResult
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
    }
    loaded = AggregateResult.model_validate_json((directory / "aggregate.json").read_text())
    assert loaded == aggregate
    assert "conversation" not in (directory / "predictions.jsonl").read_text()
    rows = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
    assert aggregate.systems[0].successful == len(rows)
