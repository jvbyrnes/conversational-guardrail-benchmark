from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from guardrail_bench.config import load_config
from guardrail_bench.models import Prediction
from guardrail_bench.runner import run


class CliProgress:
    def __init__(self) -> None:
        self._errors = 0
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=Console(stderr=True),
        )
        self._task_id = self._progress.add_task("Preparing benchmark", total=None)

    def __enter__(self) -> CliProgress:
        self._progress.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._progress.stop()

    def start(self, total: int) -> None:
        self._progress.update(self._task_id, description="Benchmarking", total=total)

    def advance(self, prediction: Prediction) -> None:
        if prediction.error is not None:
            self._errors += 1
        description = "Benchmarking" if self._errors == 0 else f"Benchmarking ({self._errors} errors)"
        self._progress.update(self._task_id, description=description, advance=1)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run a reproducible guardrail benchmark")
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--sample-rate", type=float)
    result.add_argument("--seed", type=int)
    result.add_argument("--output-dir", type=Path)
    result.add_argument("--cost-cap-usd", type=float)
    result.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show progress (default: enabled when stderr is a terminal)",
    )
    return result


def main() -> None:
    args = parser().parse_args()
    config = load_config(
        args.config,
        rate=args.sample_rate,
        seed=args.seed,
        output_dir=args.output_dir,
        cost_cap_usd=args.cost_cap_usd,
    )
    show_progress = sys.stderr.isatty() if args.progress is None else args.progress
    if show_progress:
        with CliProgress() as progress:
            manifest, _, _ = asyncio.run(run(config, progress=progress))
    else:
        manifest, _, _ = asyncio.run(run(config))
    print(config.output_dir / manifest.run_id)


if __name__ == "__main__":
    main()
