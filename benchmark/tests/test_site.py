from pathlib import Path


def test_static_site_contract() -> None:
    root = Path(__file__).parents[2]
    html = (root / "site/index.html").read_text()
    script = (root / "site/app.js").read_text()
    assert 'id="systems"' in html and 'id="metadata"' in html
    assert "aggregate.json" in script
    assert "POTENTIALLY STALE" in script
    assert "INCOMPLETE" in script and "incomplete_reason" in script
    assert "run_kind" in script and "sample_count" in script
