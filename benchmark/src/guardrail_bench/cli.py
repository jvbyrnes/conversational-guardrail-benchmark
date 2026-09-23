from __future__ import annotations

import argparse
import asyncio
import os
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
    def __init__(self, *, force_terminal: bool | None = None) -> None:
        self._errors = 0
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=Console(stderr=True, force_terminal=force_terminal),
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
    result = argparse.ArgumentParser(
        description="Run a reproducible guardrail benchmark",
        epilog=(
            "Artifact commands: validate, publish, index, migrate, export-site. "
            "Run 'guardrail-bench <command> --help' for command options."
        ),
    )
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


def artifact_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Validate, publish, and compare benchmark evidence")
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate private run evidence or a public bundle")
    validate.add_argument("directory", type=Path)
    validate.add_argument("--public", action="store_true", help="validate a projected public bundle")
    publish = commands.add_parser("publish", help="project a valid run into an immutable public bundle")
    publish.add_argument("directory", type=Path)
    publish.add_argument("--publication-root", type=Path, default=Path("results/published"))
    publish.add_argument("--pseudonym-key-id", required=True)
    publish.add_argument("--key-env", default="GUARDRAIL_PSEUDONYM_KEY")
    index = commands.add_parser("index", help="rebuild deterministic public and optional local preview indexes")
    index.add_argument("--publication-root", type=Path, default=Path("results/published"))
    index.add_argument("--preview-root", type=Path)
    index.add_argument("--source", type=Path, action="append", default=[])
    migrate = commands.add_parser("migrate", help="inspect legacy compatibility; write only with --write")
    migrate.add_argument("directory", type=Path)
    migrate.add_argument("--output-dir", type=Path, default=Path("results/preview/migrated"))
    migrate.add_argument("--config", type=Path)
    migrate.add_argument("--write", action="store_true")
    export = commands.add_parser("export-site", help="export only site assets and validated public bundles")
    export.add_argument("destination", type=Path)
    export.add_argument("--site-root", type=Path, default=Path("site"))
    export.add_argument("--publication-root", type=Path, default=Path("results/published"))
    return result


def artifact_main(argv: list[str]) -> None:
    from guardrail_bench.publication import generate_index, publish_run, validate_bundle
    from guardrail_bench.validation import validate_run

    command_parser = artifact_parser()
    args = command_parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = validate_bundle(args.directory) if args.public else validate_run(args.directory)
            print(report.model_dump_json(indent=2))
            if not report.valid:
                raise SystemExit(1)
        elif args.command == "publish":
            key = os.environ.get(args.key_env)
            if not key:
                command_parser.error(f"publication key environment variable {args.key_env} is required")
            path = publish_run(
                args.directory,
                args.publication_root,
                pseudonym_key=key.encode("utf-8"),
                pseudonym_key_id=args.pseudonym_key_id,
            )
            print(path)
        elif args.command == "index":
            catalogue = generate_index(
                args.publication_root, preview_root=args.preview_root, source_directories=args.source
            )
            print(catalogue.model_dump_json(indent=2))
        elif args.command == "migrate":
            from guardrail_bench.migration import migrate_run

            config = load_config(args.config) if args.config else None
            migration_report = migrate_run(args.directory, args.output_dir, dry_run=not args.write, config=config)
            print(migration_report.model_dump_json(indent=2))
            if migration_report.errors:
                raise SystemExit(1)
        elif args.command == "export-site":
            from guardrail_bench.deployment import export_site

            print(export_site(args.site_root, args.publication_root, args.destination))
    except (ValueError, OSError) as exc:
        command_parser.exit(1, f"{args.command} failed: {exc}\n")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"validate", "publish", "index", "migrate", "export-site"}:
        artifact_main(sys.argv[1:])
        return
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
        force_terminal = True if args.progress is True else None
        with CliProgress(force_terminal=force_terminal) as progress:
            manifest, _, _ = asyncio.run(run(config, progress=progress))
    else:
        manifest, _, _ = asyncio.run(run(config))
    print(config.output_dir / manifest.run_id)


if __name__ == "__main__":
    main()
