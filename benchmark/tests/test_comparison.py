import subprocess
from pathlib import Path

import pytest
from guardrail_bench.comparison import (
    CostKey,
    DatasetIdentity,
    LatencyKey,
    QualityKey,
    SystemIdentity,
    canonical_json,
    capture_code_provenance,
    compare_keys,
    evaluated_system_id,
    fingerprint,
    make_evaluation_identity,
    make_system_identity,
    rankability,
)
from guardrail_bench.config import AdapterConfig
from guardrail_bench.tasks import get_task
from pydantic import ValidationError


def test_rfc8785_golden_vectors() -> None:
    assert canonical_json({"z": -0.0, "a": [1e30, 1e-7, 0.000001, 1.0]}) == (b'{"a":[1e+30,1e-7,0.000001,1],"z":0}')
    assert canonical_json({"\ue000": 1, "😀": 2}) == '{"😀":2,"\ue000":1}'.encode()
    assert fingerprint({}) != fingerprint({"optional": None})
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint([1, 2]) != fingerprint([2, 1])
    assert fingerprint([]) == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    for invalid in (float("nan"), float("inf"), "\ud800"):
        with pytest.raises(ValueError):
            canonical_json(invalid)


def test_system_and_task_identity() -> None:
    config = AdapterConfig(id="friendly", kind="openrouter", model="provider/model", parameters={"temperature": 0})
    system = make_system_identity(config)
    assert system.system_id == fingerprint(system.fingerprint_input())
    assert system.system_id == make_system_identity(config.model_copy(update={"id": "renamed"})).system_id
    for field, value in (("model", "provider/other"), ("parameters", {"temperature": 0.1})):
        assert system.system_id != make_system_identity(config.model_copy(update={field: value})).system_id
    task = get_task("adversarial_technique")
    evaluation = make_evaluation_identity(task)
    assert evaluation.evaluation_id == fingerprint(evaluation.fingerprint_input())
    for field, value in (
        ("question", "A different prompt?"),
        ("decision_threshold", 0.9),
        ("parser_version", "2.0.0"),
        ("label_mapping", {"test": True}),
    ):
        changed = make_evaluation_identity(task.model_copy(update={field: value}))
        assert evaluation.evaluation_id != changed.evaluation_id
        assert evaluated_system_id(system.system_id, evaluation.evaluation_id) != evaluated_system_id(
            system.system_id, changed.evaluation_id
        )
    with pytest.raises(ValidationError):
        SystemIdentity.model_validate({**system.model_dump(), "snapshot_status": "immutable"})
    with pytest.raises(ValueError, match="unsupported output parameters"):
        make_system_identity(config.model_copy(update={"parameters": {"api_key": "secret"}}))


def quality() -> QualityKey:
    return QualityKey(
        dataset=DatasetIdentity(
            name="dataset", revision="a" * 40, split="train", config_name=None, schema_fingerprint="schema"
        ),
        evaluation_id="evaluation",
        public_cohort_digest="cohort",
        pseudonym_key_id="key",
        sample_count=10,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("evaluation_id", "other"),
        ("public_cohort_digest", "other"),
        ("pseudonym_key_id", "other"),
        ("sample_count", 11),
        ("quality_metric_version", "2"),
        ("artifact_semantics_major", 2),
    ],
)
def test_quality_dimensions(field: str, value: object) -> None:
    key = quality()
    report = compare_keys(key, key.model_copy(update={field: value}))
    assert report.state == "incompatible"
    assert report.differing_paths == [field]


@pytest.mark.parametrize("field", ["name", "revision", "split", "config_name", "schema_fingerprint"])
def test_dataset_dimensions(field: str) -> None:
    key = quality()
    changed = key.model_copy(update={"dataset": key.dataset.model_copy(update={field: "other"})})
    assert compare_keys(key, changed).differing_paths == [f"dataset.{field}"]


def test_independent_families() -> None:
    key = quality()
    cost = CostKey(quality=key, currency="USD", pricing_version="1", cost_method="reported", billing_policy="all")
    latency = LatencyKey(
        quality=key,
        timing_definition_version="1",
        execution_mode="async",
        concurrency=4,
        retry_policy="none",
        timeout_policy="30s",
        routing_region_class="local",
        warmup_policy="none",
    )
    for field in ("currency", "pricing_version", "cost_method", "billing_policy"):
        assert compare_keys(cost, cost.model_copy(update={field: "other"})).differing_paths == [field]
    for field in (
        "timing_definition_version",
        "execution_mode",
        "concurrency",
        "retry_policy",
        "timeout_policy",
        "routing_region_class",
        "warmup_policy",
    ):
        value = 5 if field == "concurrency" else "other"
        assert compare_keys(latency, latency.model_copy(update={field: value})).differing_paths == [field]
    state = rankability(quality=key, cost=cost, latency=None, cost_coverage=0.5)
    assert state.quality.eligible
    assert state.cost.reason == "partial_cost_coverage"
    assert state.latency.reason == "missing_execution_provenance"
    assert compare_keys(cost, None).state == "unavailable"
    assert compare_keys(cost, cost, left_eligible=False).state == "ineligible"


def test_code_provenance_tracks_clean_dirty_and_unavailable(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True, stderr=subprocess.DEVNULL).strip()

    assert capture_code_provenance(tmp_path).working_tree_state == "unavailable"
    git("init")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("remote", "add", "origin", "https://example.com/repository.git")
    (tmp_path / "source").write_text("committed")
    git("add", "source")
    git("commit", "-m", "fixture")
    provenance = capture_code_provenance(tmp_path)
    assert provenance.working_tree_state == "clean"
    assert provenance.commit_revision == git("rev-parse", "HEAD")
    assert provenance.committed_tree_digest == git("rev-parse", "HEAD^{tree}")
    (tmp_path / "untracked").write_text("new")
    assert capture_code_provenance(tmp_path).working_tree_state == "dirty"
    (tmp_path / "untracked").unlink()
    (tmp_path / "source").write_text("changed")
    assert capture_code_provenance(tmp_path).working_tree_state == "dirty"
    git("add", "source")
    assert capture_code_provenance(tmp_path).working_tree_state == "dirty"


@pytest.mark.asyncio
async def test_cohort_exists_before_first_inference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import guardrail_bench.runner as runner
    from guardrail_bench.adapters import FakeAdapter
    from guardrail_bench.comparison import PrivateCohort
    from guardrail_bench.config import load_config

    root = Path(__file__).resolve().parents[2]
    config = load_config(root / "benchmark/config/fixture.yaml", output_dir=tmp_path)
    original = runner._adapter

    def checked_adapter(config: AdapterConfig) -> FakeAdapter:
        cohort_files = list(tmp_path.glob("*/cohort.json"))
        assert len(cohort_files) == 1
        cohort = PrivateCohort.model_validate_json(cohort_files[0].read_text())
        assert cohort.members
        return original(config)  # type: ignore[return-value]

    monkeypatch.setattr(runner, "_adapter", checked_adapter)
    manifest, predictions, _ = await runner.run(config)
    cohort = PrivateCohort.model_validate_json((tmp_path / manifest.run_id / "cohort.json").read_text())
    assert cohort.digest == manifest.private_cohort_digest
    assert len(predictions) == len(cohort.members) * len(manifest.systems)


@pytest.mark.parametrize("status", [" M source", "M  source", "?? extra", " M dependency", "A  source"])
def test_git_status_entries_are_dirty(status: str, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[str, ...]] = []

    def output(command: list[str], **kwargs: object) -> str:
        args = tuple(command[1:])
        commands.append(args)
        return {
            ("rev-parse", "--show-toplevel"): "/tmp/repository\n",
            ("rev-parse", "HEAD"): "a" * 40 + "\n",
            ("rev-parse", "HEAD^{tree}"): "b" * 40 + "\n",
            ("status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"): status + "\n",
            ("config", "--get", "remote.origin.url"): "https://example.com/repo.git\n",
        }[args]

    monkeypatch.setattr(subprocess, "check_output", output)
    assert capture_code_provenance().working_tree_state == "dirty"
    assert ("status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none") in commands


@pytest.mark.parametrize("failed", ["--show-toplevel", "HEAD", "HEAD^{tree}", "--porcelain=v1"])
def test_git_command_failure_is_unavailable(failed: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def output(command: list[str], **kwargs: object) -> str:
        if failed in command:
            raise subprocess.CalledProcessError(128, command)
        if "--show-toplevel" in command:
            return "/tmp/repository\n"
        if "rev-parse" in command:
            return "a" * 40 + "\n"
        return ""

    monkeypatch.setattr(subprocess, "check_output", output)
    assert capture_code_provenance().working_tree_state == "unavailable"


@pytest.mark.parametrize("malformed", ["", "unknown", "a" * 39, "z" * 40, "a" * 40 + "\nextra"])
def test_malformed_git_revision_is_unavailable(malformed: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def output(command: list[str], **kwargs: object) -> str:
        if "--show-toplevel" in command:
            return "/tmp/repository"
        if "HEAD" in command:
            return malformed
        if "HEAD^{tree}" in command:
            return "b" * 40
        return ""

    monkeypatch.setattr(subprocess, "check_output", output)
    assert capture_code_provenance().working_tree_state == "unavailable"


@pytest.mark.asyncio
async def test_retry_cost_and_usage_include_all_attempts() -> None:
    from guardrail_bench.adapters import AdapterResult, call_with_retry
    from guardrail_bench.models import PredictionError, Usage

    class Retrying:
        adapter_id = "test"
        model_id = "test"
        calls = 0

        async def classify(self, *args: object) -> AdapterResult:
            self.calls += 1
            return AdapterResult(
                True if self.calls == 2 else None,
                error=None if self.calls == 2 else PredictionError(kind="rate_limit", message="retry", retryable=True),
                usage=Usage(input_tokens=10, output_tokens=2, provider_fields={"cost": 0.01}),
            )

    result, _ = await call_with_retry(Retrying(), (), get_task("adversarial_technique"), retries=1, timeout_seconds=1)
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 4
    assert result.usage.provider_fields["cost"] == 0.02


@pytest.mark.asyncio
async def test_retry_unknown_cost_does_not_become_known() -> None:
    from guardrail_bench.adapters import AdapterResult, call_with_retry
    from guardrail_bench.models import PredictionError, Usage

    class Retrying:
        adapter_id = "test"
        model_id = "test"
        calls = 0

        async def classify(self, *args: object) -> AdapterResult:
            self.calls += 1
            if self.calls == 1:
                return AdapterResult(None, error=PredictionError(kind="timeout", message="unknown", retryable=True))
            return AdapterResult(True, usage=Usage(provider_fields={"cost": 0.01}))

    result, _ = await call_with_retry(Retrying(), (), get_task("adversarial_technique"), retries=1, timeout_seconds=1)
    assert "cost" not in result.usage.provider_fields
