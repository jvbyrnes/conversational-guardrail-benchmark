from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from guardrail_bench.adapters import AdapterResult
from guardrail_bench.comparison import CodeProvenance, canonical_json, fingerprint
from guardrail_bench.config import AdapterConfig, BenchmarkConfig, load_config
from guardrail_bench.deployment import export_site
from guardrail_bench.models import PredictionError, Usage
from guardrail_bench.publication import generate_index, publish_run, validate_bundle
from guardrail_bench.validation import validate_run

ROOT = Path(__file__).parents[2]


@pytest.fixture
async def publishable_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import guardrail_bench.runner as runner

    provenance = CodeProvenance(
        repository="https://example.test/benchmark.git",
        commit_revision="a" * 40,
        committed_tree_digest="b" * 40,
        working_tree_state="clean",
    )
    monkeypatch.setattr(runner, "capture_code_provenance", lambda: provenance)
    config = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path / "raw")
    config.adapters.append(AdapterConfig(id="fake-second", kind="fake", model="deterministic-fake-v2"))
    manifest, _, _ = await runner.run(config)
    return config.output_dir / manifest.run_id


def rewrite_checksum(bundle: Path, name: str) -> None:
    checksums = json.loads((bundle / "checksums.json").read_text())
    checksums[name] = "sha256:" + hashlib.sha256((bundle / name).read_bytes()).hexdigest()
    (bundle / "checksums.json").write_text(json.dumps(checksums))


@pytest.mark.asyncio
async def test_publish_index_export_round_trip_is_deterministic(publishable_run: Path, tmp_path: Path) -> None:
    assert validate_run(publishable_run).valid
    public_root = tmp_path / "published"
    bundle = publish_run(
        publishable_run,
        public_root,
        pseudonym_key=b"non-secret-offline-fixture-key",
        pseudonym_key_id="fixture-v1",
    )
    assert validate_bundle(bundle).valid
    assert {path.name for path in bundle.iterdir()} == {
        "manifest.json",
        "aggregate.json",
        "cohort.json",
        "predictions.jsonl",
        "validation-report.json",
        "checksums.json",
    }
    public_text = "\n".join(path.read_text() for path in bundle.iterdir())
    assert "source_id" not in public_text
    assert "fixture failure" not in public_text
    assert "ah-1" not in public_text
    cohort_ids = {member["public_case_id"] for member in json.loads((bundle / "cohort.json").read_text())["members"]}
    prediction_ids = {
        json.loads(line)["public_case_id"] for line in (bundle / "predictions.jsonl").read_text().splitlines()
    }
    assert prediction_ids == cohort_ids

    index = generate_index(public_root)
    assert len(index.runs) == 1
    assert len(index.runs[0].systems) == 2
    assert all(system.rankability["quality"].eligible for system in index.runs[0].systems)
    assert all(system.rankability["cost"].eligible for system in index.runs[0].systems)
    assert all(system.rankability["latency"].eligible for system in index.runs[0].systems)
    first_bytes = (public_root / "index.json").read_bytes()
    assert generate_index(public_root) == index
    assert (public_root / "index.json").read_bytes() == first_bytes

    destination = tmp_path / "export"
    export_site(ROOT / "site", public_root, destination)
    exported_bundle = destination / "results/published/runs" / bundle.name
    assert validate_bundle(exported_bundle).valid
    assert not (destination / "results/preview").exists()
    assert not (destination / "results/published/latest").exists()


@pytest.mark.asyncio
async def test_validation_rejects_missing_rows_duplicates_and_aggregate_drift(
    publishable_run: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "missing"
    shutil.copytree(publishable_run, missing)
    lines = (missing / "predictions.jsonl").read_text().splitlines()
    (missing / "predictions.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    assert "predictions.cartesian_coverage" in {issue.rule_id for issue in validate_run(missing).errors}

    drift = tmp_path / "drift"
    shutil.copytree(publishable_run, drift)
    aggregate = json.loads((drift / "aggregate.json").read_text())
    aggregate["systems"][0]["f1"] = 0.123
    (drift / "aggregate.json").write_text(json.dumps(aggregate))
    assert "aggregate.drift" in {issue.rule_id for issue in validate_run(drift).errors}

    cohort_tamper = tmp_path / "cohort-tamper"
    shutil.copytree(publishable_run, cohort_tamper)
    cohort = json.loads((cohort_tamper / "cohort.json").read_text())
    cohort["members"][0]["ground_truth"] = not cohort["members"][0]["ground_truth"]
    (cohort_tamper / "cohort.json").write_text(json.dumps(cohort))
    assert "cohort.integrity" in {issue.rule_id for issue in validate_run(cohort_tamper).errors}

    cross_system = tmp_path / "cross-system"
    shutil.copytree(publishable_run, cross_system)
    cross_rows = (cross_system / "predictions.jsonl").read_text().splitlines()
    first = json.loads(cross_rows[0])
    second = json.loads(cross_rows[1])
    first["evaluated_system_id"] = second["evaluated_system_id"]
    cross_rows[0] = json.dumps(first)
    (cross_system / "predictions.jsonl").write_text("\n".join(cross_rows) + "\n")
    assert "predictions.identity" in {issue.rule_id for issue in validate_run(cross_system).errors}

    public_root = tmp_path / "published"
    bundle = publish_run(
        publishable_run,
        public_root,
        pseudonym_key=b"fixture-key",
        pseudonym_key_id="fixture-v1",
    )
    duplicate = tmp_path / bundle.name
    shutil.copytree(bundle, duplicate)
    rows = (duplicate / "predictions.jsonl").read_text().splitlines()
    (duplicate / "predictions.jsonl").write_text("\n".join([*rows, rows[0]]) + "\n")
    rewrite_checksum(duplicate, "predictions.jsonl")
    rules = {issue.rule_id for issue in validate_bundle(duplicate).errors}
    assert "predictions.duplicate" in rules
    assert "aggregate.drift" in rules

    checksum_tamper = tmp_path / "checksum" / bundle.name
    checksum_tamper.parent.mkdir()
    shutil.copytree(bundle, checksum_tamper)
    with (checksum_tamper / "predictions.jsonl").open("a") as handle:
        handle.write("\n")
    assert "artifacts.checksum" in {issue.rule_id for issue in validate_bundle(checksum_tamper).errors}


@pytest.mark.asyncio
async def test_public_projection_rejects_unknown_fields_and_tampered_keys(
    publishable_run: Path, tmp_path: Path
) -> None:
    public_root = tmp_path / "published"
    bundle = publish_run(
        publishable_run,
        public_root,
        pseudonym_key=b"fixture-key",
        pseudonym_key_id="fixture-v1",
    )
    unsafe = tmp_path / bundle.name
    shutil.copytree(bundle, unsafe)
    lines = (unsafe / "predictions.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    first["source_id"] = "secret-internal-id"
    lines[0] = json.dumps(first)
    (unsafe / "predictions.jsonl").write_text("\n".join(lines) + "\n")
    rewrite_checksum(unsafe, "predictions.jsonl")
    assert not validate_bundle(unsafe).valid

    tampered = tmp_path / "tampered" / bundle.name
    tampered.parent.mkdir()
    shutil.copytree(bundle, tampered)
    manifest = json.loads((tampered / "manifest.json").read_text())
    manifest["summaries"][0]["quality_key"] = "sha256:" + "0" * 64
    (tampered / "manifest.json").write_text(json.dumps(manifest))
    rewrite_checksum(tampered, "manifest.json")
    assert "comparison.quality_key" in {issue.rule_id for issue in validate_bundle(tampered).errors}

    nested = tmp_path / "nested" / bundle.name
    nested.parent.mkdir()
    shutil.copytree(bundle, nested)
    nested_manifest = json.loads((nested / "manifest.json").read_text())
    nested_manifest["summaries"][0]["key_fields"]["raw_payload"] = {"authorization": "secret"}
    (nested / "manifest.json").write_text(json.dumps(nested_manifest))
    rewrite_checksum(nested, "manifest.json")
    assert not validate_bundle(nested).valid

    report_tamper = tmp_path / "report" / bundle.name
    report_tamper.parent.mkdir()
    shutil.copytree(bundle, report_tamper)
    validation_report = json.loads((report_tamper / "validation-report.json").read_text())
    validation_report["warnings"].append({"rule_id": "arbitrary.secret", "path": "authorization-token"})
    (report_tamper / "validation-report.json").write_text(json.dumps(validation_report))
    rewrite_checksum(report_tamper, "validation-report.json")
    assert "validation.prior_invalid" in {issue.rule_id for issue in validate_bundle(report_tamper).errors}


@pytest.mark.asyncio
async def test_partial_cost_cannot_be_marked_rankable_and_index_cannot_override_manifest(
    publishable_run: Path, tmp_path: Path
) -> None:
    public_root = tmp_path / "published"
    bundle = publish_run(
        publishable_run,
        public_root,
        pseudonym_key=b"fixture-key",
        pseudonym_key_id="fixture-v1",
    )
    partial = tmp_path / "partial" / bundle.name
    partial.parent.mkdir()
    shutil.copytree(bundle, partial)
    rows = (partial / "predictions.jsonl").read_text().splitlines()
    first = json.loads(rows[0])
    first["cost_usd"] = None
    first["cost_status"] = "unavailable"
    rows[0] = json.dumps(first)
    (partial / "predictions.jsonl").write_text("\n".join(rows) + "\n")
    aggregate = json.loads((partial / "aggregate.json").read_text())
    metric = next(item for item in aggregate["systems"] if item["evaluated_system_id"] == first["evaluated_system_id"])
    metric["cost_known_count"] -= 1
    metric["cost_coverage"] = metric["cost_known_count"] / metric["attempted"]
    metric["total_cost_usd"] = None
    metric["cost_per_1000_examples_usd"] = None
    (partial / "aggregate.json").write_text(json.dumps(aggregate))
    rewrite_checksum(partial, "predictions.jsonl")
    rewrite_checksum(partial, "aggregate.json")
    assert "comparison.cost_rankability" in {issue.rule_id for issue in validate_bundle(partial).errors}

    generate_index(public_root)
    index_path = public_root / "index.json"
    index = json.loads(index_path.read_text())
    index["runs"][0]["systems"][0]["quality_key"] = "sha256:" + "0" * 64
    index_path.write_bytes(canonical_json(index) + b"\n")
    with pytest.raises(ValueError, match="metadata mismatch"):
        export_site(ROOT / "site", public_root, tmp_path / "export")


def test_empty_index_has_canonical_empty_source_digest(tmp_path: Path) -> None:
    index = generate_index(tmp_path / "published")
    assert index.as_of is None
    assert index.runs == []
    assert index.source_set_digest == ("sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945")


@pytest.mark.asyncio
async def test_retry_with_unknown_earlier_bill_validates_and_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import guardrail_bench.runner as runner

    class PaidAdapter:
        adapter_id = "paid"
        model_id = "provider/model"
        calls = 0

        async def classify(self, *_: object) -> AdapterResult:
            self.calls += 1
            if self.calls == 1:
                return AdapterResult(
                    None,
                    error=PredictionError(kind="rate_limit", message="retry", retryable=True),
                )
            return AdapterResult(False, usage=Usage(provider_fields={"cost": 0.004}))

    raw = load_config(ROOT / "benchmark/config/fixture.yaml", output_dir=tmp_path / "raw").model_dump(mode="json")
    raw["adapters"] = [
        {
            "id": "paid",
            "kind": "openrouter",
            "model": "provider/model",
            "parameters": {
                "max_completion_tokens": 16,
                "frequency_penalty": 0.1,
                "presence_penalty": 0,
                "stop": ["END"],
            },
            "cost_reservation_usd": 0.01,
        }
    ]
    raw["execution"].update({"retries": 1, "cost_cap_usd": 0.2})
    config = BenchmarkConfig.model_validate(raw)
    monkeypatch.setattr(runner, "_adapter", lambda _: PaidAdapter())
    monkeypatch.setattr(
        runner,
        "capture_code_provenance",
        lambda: CodeProvenance(
            repository="https://example.test/benchmark.git",
            commit_revision="a" * 40,
            committed_tree_digest="b" * 40,
            working_tree_state="clean",
        ),
    )

    manifest, rows, _ = await runner.run(config)
    assert manifest.cost_actual_usd == pytest.approx(0.032)
    assert rows[0].cost_usd is None
    assert rows[0].reconciled_cost_usd == pytest.approx(0.004)
    assert rows[1].cost_usd == rows[1].reconciled_cost_usd == pytest.approx(0.004)
    source = config.output_dir / manifest.run_id
    assert validate_run(source).valid
    bundle = publish_run(source, tmp_path / "published", pseudonym_key=b"fixture-key", pseudonym_key_id="fixture-v1")
    assert validate_bundle(bundle).valid
    tampered = tmp_path / "tampered-raw"
    shutil.copytree(source, tampered)
    lines = (tampered / "predictions.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    first["reconciled_cost_usd"] = 0
    lines[0] = json.dumps(first)
    (tampered / "predictions.jsonl").write_text("\n".join(lines) + "\n")
    assert "cost.reported_total_mismatch" in {issue.rule_id for issue in validate_run(tampered).errors}


@pytest.mark.asyncio
async def test_public_billing_policy_is_checked_against_predictions(publishable_run: Path, tmp_path: Path) -> None:
    bundle = publish_run(
        publishable_run, tmp_path / "published", pseudonym_key=b"fixture-key", pseudonym_key_id="fixture-v1"
    )
    tampered = tmp_path / "tampered" / bundle.name
    tampered.parent.mkdir()
    shutil.copytree(bundle, tampered)
    manifest = json.loads((tampered / "manifest.json").read_text())
    summary = manifest["summaries"][0]
    summary["key_fields"]["cost"]["billing_policy"] = "changed-policy"
    summary["cost_key"] = fingerprint(summary["key_fields"]["cost"])
    (tampered / "manifest.json").write_text(json.dumps(manifest))
    rewrite_checksum(tampered, "manifest.json")
    assert "comparison.cost_provenance" in {issue.rule_id for issue in validate_bundle(tampered).errors}
