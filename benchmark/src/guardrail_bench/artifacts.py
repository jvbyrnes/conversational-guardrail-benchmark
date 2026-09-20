from __future__ import annotations

import csv
import json
from pathlib import Path

from guardrail_bench.models import AggregateResult, Prediction, RunManifest


def write_artifacts(
    directory: Path, manifest: RunManifest, predictions: list[Prediction], aggregate: AggregateResult
) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    (directory / "aggregate.json").write_text(aggregate.model_dump_json(indent=2) + "\n")
    with (directory / "predictions.jsonl").open("w") as handle:
        for prediction in predictions:
            handle.write(prediction.model_dump_json() + "\n")
    rows = []
    for prediction in predictions:
        data = prediction.model_dump(mode="json")
        data["usage"] = json.dumps(data["usage"], sort_keys=True)
        data["error"] = json.dumps(data["error"], sort_keys=True) if data["error"] else ""
        rows.append(data)
    with (directory / "predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
