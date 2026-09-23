from __future__ import annotations

import json
from pathlib import Path

import pytest
from guardrail_bench.cli import artifact_main, artifact_parser, parser
from guardrail_bench.deployment import export_site

ROOT = Path(__file__).parents[2]


def test_original_run_cli_remains_supported() -> None:
    args = parser().parse_args(["--config", "fixture.yaml", "--sample-rate", "0.01", "--no-progress"])
    assert args.config == Path("fixture.yaml")
    assert args.sample_rate == 0.01
    assert args.progress is False


def test_migration_cli_defaults_to_dry_run() -> None:
    args = artifact_parser().parse_args(["migrate", "legacy"])
    assert args.write is False
    assert args.output_dir == Path("results/preview/migrated")


def test_publish_cli_requires_key_before_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GUARDRAIL_PSEUDONYM_KEY", raising=False)
    output = tmp_path / "published"
    with pytest.raises(SystemExit) as error:
        artifact_main(
            [
                "publish",
                str(tmp_path / "missing"),
                "--publication-root",
                str(output),
                "--pseudonym-key-id",
                "test",
            ]
        )
    assert error.value.code == 2
    assert not output.exists()


def test_empty_index_cli_and_private_file_exclusion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    result = json.loads(capsys.readouterr().out)
    assert result["runs"] == []
    assert result["as_of"] is None
    index_bytes = (published / "index.json").read_bytes()
    artifact_main(["index", "--publication-root", str(published)])
    assert (published / "index.json").read_bytes() == index_bytes
    preview = tmp_path / "results/preview"
    preview.mkdir(parents=True)
    (preview / "index.json").write_text('{"private":"secret"}')
    legacy = published / "latest"
    legacy.mkdir()
    (legacy / "predictions.jsonl").write_text('{"source_id":"private"}')
    (published / "unindexed-secret.txt").write_text("secret")
    destination = tmp_path / "export"
    export_site(ROOT / "site", published, destination)
    assert sorted(str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()) == [
        "results/published/index.json",
        "site/app.js",
        "site/index.html",
        "site/styles.css",
    ]
    with pytest.raises(ValueError, match="already exists"):
        export_site(ROOT / "site", published, destination)


def test_preview_index_is_deterministic_and_has_no_artifact_uris(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    published = tmp_path / "published"
    source = tmp_path / "unsafe-run"
    source.mkdir()
    preview = tmp_path / "preview"
    arguments = [
        "index",
        "--publication-root",
        str(published),
        "--preview-root",
        str(preview),
        "--source",
        str(source),
    ]
    artifact_main(arguments)
    capsys.readouterr()
    first = (preview / "index.json").read_bytes()
    artifact_main(arguments)
    capsys.readouterr()
    assert (preview / "index.json").read_bytes() == first
    assert b"_uri" not in first


def test_export_rejects_invalid_index_before_destination_exists(tmp_path: Path) -> None:
    published = tmp_path / "published"
    published.mkdir()
    (published / "index.json").write_text('{"schema_version":"99.0.0","runs":[]}')
    destination = tmp_path / "export"
    with pytest.raises(ValueError):
        export_site(ROOT / "site", published, destination)
    assert not destination.exists()
