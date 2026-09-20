from __future__ import annotations

import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from guardrail_bench.models import AggregateResult, Prediction, RunCheckpoint, RunManifest


def _write_checkpoint(directory: Path, checkpoint: RunCheckpoint) -> None:
    temporary = directory / "run-status.json.tmp"
    with temporary.open("w") as handle:
        handle.write(checkpoint.model_dump_json(indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(directory / "run-status.json")


def create_checkpoint(directory: Path, run_id: str, expected_predictions: int, started_at: datetime) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    _write_checkpoint(
        directory,
        RunCheckpoint(
            run_id=run_id,
            status="running",
            expected_predictions=expected_predictions,
            predictions_completed=0,
            started_at=started_at,
            updated_at=started_at,
        ),
    )


def append_checkpoint(directory: Path, predictions: list[Prediction], expected_predictions: int) -> None:
    if not predictions:
        return
    checkpoint = RunCheckpoint.model_validate_json((directory / "run-status.json").read_text())
    with (directory / "predictions.partial.jsonl").open("a") as handle:
        for prediction in predictions:
            handle.write(prediction.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _write_checkpoint(
        directory,
        checkpoint.model_copy(
            update={
                "predictions_completed": checkpoint.predictions_completed + len(predictions),
                "expected_predictions": expected_predictions,
                "updated_at": datetime.now(UTC),
            }
        ),
    )


def finish_checkpoint(
    directory: Path, *, status: Literal["complete", "incomplete"], reason: str | None
) -> None:
    checkpoint = RunCheckpoint.model_validate_json((directory / "run-status.json").read_text())
    _write_checkpoint(
        directory,
        RunCheckpoint.model_validate(
            {
                **checkpoint.model_dump(),
                "status": status,
                "reason": reason,
                "updated_at": datetime.now(UTC),
            }
        ),
    )


def write_artifacts(
    directory: Path, manifest: RunManifest, predictions: list[Prediction], aggregate: AggregateResult
) -> None:
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
