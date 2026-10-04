from __future__ import annotations

import json
from pathlib import Path

import pytest
from guardrail_bench.cli import artifact_main, artifact_parser, parser
from guardrail_bench.comparison import canonical_json
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


def _headline() -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "status": "exploratory",
        "task_id": "harmful_jailbreak",
        "task_version": "1.0.0",
        "dataset": {
            "name": "allenai/wildjailbreak",
            "revision": "5ddc12a7894f842b0619b8e1c7ee496b198af009",
        },
        "sample": {"rate": 0.01, "count": 1614, "seed": 20260918},
        "systems": [
            {
                "system": "jev",
                "run_id": "20260925T004541177372Z-a4c027600058",
                "cost_basis": "estimated_input_tokens",
                "metrics": {
                    "attempted": 1614,
                    "successful": 1614,
                    "errors": 0,
                    "coverage": 1.0,
                    "precision": 0.9543918918918919,
                    "recall": 0.6831922611850061,
                    "f1": 0.7963354474982383,
                    "accuracy": 0.8209417596034696,
                    "confusion": {
                        "true_positive": 565,
                        "true_negative": 760,
                        "false_positive": 27,
                        "false_negative": 262,
                    },
                    "latency_p50_ms": 823.6430835677311,
                    "latency_p95_ms": 1079.114856227534,
                    "cost_known_count": 1614,
                    "cost_coverage": 1.0,
                    "known_cost_usd": 0.036729378,
                    "total_cost_usd": 0.036729378,
                },
            },
            {
                "system": "luna",
                "run_id": "20260925T014904391035Z-ba0833bb4475",
                "cost_basis": "provider_reported_partial",
                "metrics": {
                    "attempted": 1614,
                    "successful": 1611,
                    "errors": 3,
                    "coverage": 0.9981412639405205,
                    "precision": 0.9475524475524476,
                    "recall": 0.6561743341404358,
                    "f1": 0.7753934191702433,
                    "accuracy": 0.8050900062073246,
                    "confusion": {
                        "true_positive": 542,
                        "true_negative": 755,
                        "false_positive": 30,
                        "false_negative": 284,
                    },
                    "latency_p50_ms": 2346.385792014189,
                    "latency_p95_ms": 3548.438541998621,
                    "cost_known_count": 1611,
                    "cost_coverage": 0.9981412639405205,
                    "known_cost_usd": 0.2342294,
                    "total_cost_usd": None,
                },
            },
        ],
    }


def _write_headline(path: Path, headline: dict[str, object]) -> bytes:
    content = canonical_json(headline) + b"\n"
    path.write_bytes(content)
    return content


def test_export_includes_only_the_checked_in_canonical_headline_summary(tmp_path: Path) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    headline_bytes = (ROOT / "results/published/headline.json").read_bytes()
    (published / "headline.json").write_bytes(headline_bytes)

    destination = tmp_path / "export"
    export_site(ROOT / "site", published, destination)
    assert (destination / "results/published/headline.json").read_bytes() == headline_bytes


def test_export_includes_the_exact_reviewed_case_samples_with_the_headline(tmp_path: Path) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    for name in ("headline.json", "review-samples.json"):
        (published / name).write_bytes((ROOT / "results/published" / name).read_bytes())

    destination = tmp_path / "export"
    export_site(ROOT / "site", published, destination)
    assert (destination / "results/published/review-samples.json").read_bytes() == (
        ROOT / "results/published/review-samples.json"
    ).read_bytes()
    assert b"wildjailbreak-" not in (destination / "results/published/review-samples.json").read_bytes()


def test_export_rejects_tampered_reviewed_case_samples(tmp_path: Path) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    (published / "headline.json").write_bytes((ROOT / "results/published/headline.json").read_bytes())
    samples = json.loads((ROOT / "results/published/review-samples.json").read_text())
    samples["groups"][0]["samples"][0]["prompt"] = "tampered"
    (published / "review-samples.json").write_bytes(canonical_json(samples) + b"\n")

    with pytest.raises(ValueError, match="review samples"):
        export_site(ROOT / "site", published, tmp_path / "tampered-samples")


@pytest.mark.parametrize(
    ("path", "unsafe_value"),
    [
        (("title",), "Jev wins; prompt=https://private.test"),
        (("notes",), ["Authorization: Bearer secret"]),
        (("systems", 0, "cost_note"), "winner; secret prompt"),
        (("systems", 0, "display_name"), "Jev <script>"),
        (("systems", 0, "provider"), "https://private.test"),
        (("systems", 0, "model_id"), "private/customer/model"),
        (("systems", 0, "run_id"), "private-run-id"),
        (("systems", 0, "system"), "jev-winner"),
        (("systems", 0, "cost_basis"), "see https://private.test"),
    ],
)
def test_export_rejects_free_form_headline_content(
    tmp_path: Path, path: tuple[str | int, ...], unsafe_value: object
) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    headline = _headline()
    target: object = headline
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = unsafe_value  # type: ignore[index]
    _write_headline(published / "headline.json", headline)

    with pytest.raises(ValueError, match="headline"):
        export_site(ROOT / "site", published, tmp_path / "unsafe-export")


@pytest.mark.parametrize(
    ("metric", "invalid_value"),
    [
        ("coverage", 0.5),
        ("precision", 0.5),
        ("recall", 0.5),
        ("f1", 0.5),
        ("accuracy", 0.5),
        ("cost_coverage", 0.5),
        ("known_cost_usd", None),
        ("total_cost_usd", 0.04),
        ("latency_p95_ms", 1.0),
    ],
)
def test_export_rejects_inconsistent_headline_metrics(
    tmp_path: Path, metric: str, invalid_value: object
) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    headline = _headline()
    headline["systems"][0]["metrics"][metric] = invalid_value  # type: ignore[index]
    _write_headline(published / "headline.json", headline)

    with pytest.raises(ValueError, match="headline"):
        export_site(ROOT / "site", published, tmp_path / f"invalid-{metric}")


def test_export_rejects_coherent_headline_metric_tampering(tmp_path: Path) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    headline = _headline()
    headline["systems"][1]["metrics"].update(  # type: ignore[index]
        cost_known_count=1600,
        cost_coverage=1600 / 1614,
    )
    _write_headline(published / "headline.json", headline)

    with pytest.raises(ValueError, match="headline"):
        export_site(ROOT / "site", published, tmp_path / "tampered-export")


def test_export_rejects_headline_sample_or_identity_inconsistency(tmp_path: Path) -> None:
    published = tmp_path / "results/published"
    artifact_main(["index", "--publication-root", str(published)])
    mutations = []
    wrong_attempted = _headline()
    wrong_attempted["systems"][1]["metrics"].update(  # type: ignore[index]
        attempted=1615,
        errors=4,
        coverage=0.9975232198142415,
        cost_coverage=0.9975232198142415,
    )
    mutations.append(wrong_attempted)
    duplicate_system = _headline()
    duplicate_system["systems"][1]["system"] = "jev"  # type: ignore[index]
    mutations.append(duplicate_system)
    duplicate_run = _headline()
    duplicate_run["systems"][1]["run_id"] = duplicate_run["systems"][0]["run_id"]  # type: ignore[index]
    mutations.append(duplicate_run)
    partial_total = _headline()
    partial_total["systems"][1]["metrics"]["total_cost_usd"] = 0.2342294  # type: ignore[index]
    mutations.append(partial_total)

    for index, headline in enumerate(mutations):
        _write_headline(published / "headline.json", headline)
        with pytest.raises(ValueError, match="headline"):
            export_site(ROOT / "site", published, tmp_path / f"inconsistent-{index}")


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
