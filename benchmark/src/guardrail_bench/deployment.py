"""Build a static export without copying private evidence or preview metadata."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path


def export_site(site_root: Path, publication_root: Path, destination: Path) -> Path:
    """Validate all referenced bytes before atomically creating a new export directory."""
    from guardrail_bench.comparison import fingerprint
    from guardrail_bench.publication import PublicManifest, PublishedIndex, _bytes, validate_bundle

    if destination.exists():
        raise ValueError("export destination already exists; choose a new directory")
    index_path = publication_root / "index.json"
    index_bytes = index_path.read_bytes()
    index = PublishedIndex.model_validate_json(index_bytes)
    if _bytes(index) != index_bytes:
        raise ValueError("public index is not in canonical generated form")
    # Inspect the schema-validated wire representation to avoid coupled DTO accessors.
    wire = json.loads(index.model_dump_json())
    files: dict[Path, bytes] = {Path("results/published/index.json"): index_bytes}
    for name in ("index.html", "app.js", "styles.css"):
        files[Path("site") / name] = (site_root / name).read_bytes()
    bundle_names = {"manifest.json", "aggregate.json", "cohort.json", "predictions.jsonl", "validation-report.json"}
    source_set = []
    published_dates = []
    if [entry["run_id"] for entry in wire["runs"]] != sorted(entry["run_id"] for entry in wire["runs"]):
        raise ValueError("public index runs are not canonically ordered")
    for entry in wire["runs"]:
        run_id = entry["run_id"]
        if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
            raise ValueError("unsafe run ID in public index")
        bundle = publication_root / "runs" / run_id
        if not bundle.resolve().is_relative_to(publication_root.resolve()):
            raise ValueError("public bundle escapes publication root")
        report = validate_bundle(bundle)
        if not report.valid:
            raise ValueError(f"public bundle {run_id} failed validation")
        expected_prefix = f"runs/{run_id}/"
        for field in ("manifest_uri", "aggregate_uri", "cohort_uri", "predictions_uri", "validation_report_uri"):
            if field in entry:
                uri = entry[field]
                if not isinstance(uri, str) or uri not in {expected_prefix + name for name in bundle_names}:
                    raise ValueError(f"invalid {field} in public index")
        digests = entry["artifact_digests"]
        if set(digests) != bundle_names:
            raise ValueError("public index must checksum every allowlisted bundle artifact")
        for name in sorted(bundle_names):
            source = bundle / name
            if source.is_symlink():
                raise ValueError("public bundle artifacts must not be symlinks")
            content = source.read_bytes()
            if digests[name] != "sha256:" + hashlib.sha256(content).hexdigest():
                raise ValueError(f"public index checksum mismatch for {run_id}/{name}")
            files[Path("results/published/runs") / run_id / name] = content
        files[Path("results/published/runs") / run_id / "checksums.json"] = (bundle / "checksums.json").read_bytes()
        manifest = PublicManifest.model_validate_json((bundle / "manifest.json").read_text())
        if (
            entry["task_id"] != manifest.task_id
            or entry["task_version"] != manifest.task_version
            or entry["run_kind"] != manifest.run_kind
            or entry["completed_at"] != manifest.completed_at.isoformat().replace("+00:00", "Z")
            or entry["potentially_stale"] != manifest.potentially_stale
            or entry["systems"] != [summary.model_dump(mode="json") for summary in manifest.summaries]
        ):
            raise ValueError(f"public index metadata mismatch for {run_id}")
        published_dates.append(manifest.published_at)
        source_set.append(
            [
                run_id,
                *[
                    digests[name]
                    for name in (
                        "manifest.json",
                        "cohort.json",
                        "aggregate.json",
                        "predictions.jsonl",
                        "validation-report.json",
                    )
                ],
            ]
        )
    if index.source_set_digest != fingerprint(source_set):
        raise ValueError("public index source-set digest mismatch")
    if index.as_of != (max(published_dates) if published_dates else None):
        raise ValueError("public index as-of timestamp mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".site-export-", dir=destination.parent))
    try:
        for relative, content in files.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination
