from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from guardrail_bench.comparison import CodeProvenance
from guardrail_bench.config import load_config
from guardrail_bench.migration import migrate_run
from guardrail_bench.models import Prediction, RunManifest

ROOT = Path(__file__).parents[2]


def tree_digests(directory: Path) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir() if path.is_file()}


@pytest.mark.asyncio
async def test_legacy_migration_is_conservative_and_preserves_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import guardrail_bench.runner as runner

    monkeypatch.setattr(
        runner,
        "capture_code_provenance",
        lambda: CodeProvenance(
            repository="https://example.test/repository.git",
            commit_revision="a" * 40,
            committed_tree_digest="b" * 40,
            working_tree_state="clean",
        ),
    )
    config = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path / "raw")
    manifest, _, _ = await runner.run(config)
    legacy = config.output_dir / manifest.run_id

    legacy_manifest = json.loads((legacy / "manifest.json").read_text())
    for field in (
        "code_provenance",
        "evaluation",
        "systems",
        "private_cohort_digest",
        "execution_provenance",
    ):
        legacy_manifest.pop(field)
    (legacy / "manifest.json").write_text(json.dumps(legacy_manifest))
    legacy_rows = []
    for line in (legacy / "predictions.jsonl").read_text().splitlines():
        row = json.loads(line)
        for field in (
            "system_id",
            "evaluation_id",
            "evaluated_system_id",
            "cost_usd",
            "cost_status",
            "currency",
            "cost_method",
            "billing_policy",
        ):
            row.pop(field)
        legacy_rows.append(row)
    (legacy / "predictions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in legacy_rows))
    before = tree_digests(legacy)

    dry_run = migrate_run(legacy, tmp_path / "migrated", config=config)
    assert not dry_run.errors
    assert dry_run.dry_run
    assert not (tmp_path / "migrated").exists()

    report = migrate_run(legacy, tmp_path / "migrated", dry_run=False, config=config)
    assert not report.errors
    assert report.migrated
    assert report.publication_eligible is False
    assert tree_digests(legacy) == before
    assert report.output_directory is not None
    target = Path(report.output_directory)
    migrated_manifest = RunManifest.model_validate_json((target / "manifest.json").read_text())
    assert migrated_manifest.code_provenance is not None
    assert migrated_manifest.code_provenance.working_tree_state == "unavailable"
    migrated_rows = [
        Prediction.model_validate_json(line) for line in (target / "predictions.jsonl").read_text().splitlines()
    ]
    assert all(row.cost_usd is None and row.cost_status == "unavailable" for row in migrated_rows)
    assert all(row.evaluated_system_id for row in migrated_rows)


def test_checked_in_legacy_result_reports_actionable_incompatibility() -> None:
    config = load_config(ROOT / "benchmark/config/fixture.yaml")
    report = migrate_run(ROOT / "results/published/latest", Path("unused"), config=config)
    assert [issue.rule_id for issue in report.errors] == ["migration.dataset_mismatch"]
