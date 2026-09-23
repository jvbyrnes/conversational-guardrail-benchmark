"""Run the framework-free site's logic and DOM rendering against offline fixtures."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_static_site_behavior() -> None:
    root = Path(__file__).parents[2]
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the site's offline behavior tests")
    result = subprocess.run(
        [node, "--test", "site/tests/app.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_static_site_contract() -> None:
    root = Path(__file__).parents[2]
    html = (root / "site/index.html").read_text()
    script = (root / "site/app.js").read_text()
    assert 'id="systems"' in html and 'id="metadata"' in html
    assert "published/latest" not in script + html
    assert "innerHTML" not in script
