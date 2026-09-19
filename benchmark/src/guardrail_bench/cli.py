from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from guardrail_bench.config import load_config
from guardrail_bench.runner import run


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run a reproducible guardrail benchmark")
    result.add_argument("--config", type=Path, required=True)
    result.add_argument("--sample-rate", type=float)
    result.add_argument("--seed", type=int)
    result.add_argument("--output-dir", type=Path)
    return result


def main() -> None:
    args = parser().parse_args()
    config = load_config(args.config, rate=args.sample_rate, seed=args.seed, output_dir=args.output_dir)
    manifest, _, _ = asyncio.run(run(config))
    print(config.output_dir / manifest.run_id)


if __name__ == "__main__":
    main()
