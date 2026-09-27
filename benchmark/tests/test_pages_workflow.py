from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/pages.yml"


def test_pages_workflow_builds_and_deploys_only_the_validated_export() -> None:
    text = WORKFLOW.read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    build = workflow["jobs"]["build"]
    deploy = workflow["jobs"]["deploy"]

    assert workflow["on"] == {"push": {"branches": ["main"]}, "workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}
    assert build["permissions"] == {"contents": "read"}
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["needs"] == "build"

    build_steps = build["steps"]
    assert {step.get("run") for step in build_steps} >= {
        "uv sync --frozen --extra dev",
        "uv run pytest",
        "uv run guardrail-bench export-site _site",
    }
    uses = {step["uses"] for step in build_steps + deploy["steps"] if "uses" in step}
    assert uses == {
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7",
        "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d",
        "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9",
        "actions/deploy-pages@368f82528645a54fb793d4d04e342629a3f51346",
    }
    upload = next(
        step for step in build_steps if str(step.get("uses", "")).startswith("actions/upload-pages-artifact@")
    )
    assert upload["with"] == {"path": "_site"}

    forbidden = (
        "path: .\n",
        "path: results\n",
        "path: results/preview",
        "path: results/runs",
        "path: results/published/latest",
    )
    assert not any(value in text for value in forbidden)
