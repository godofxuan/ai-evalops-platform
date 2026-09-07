from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from functools import partial
from pathlib import Path

import pytest

from app.product_experiments.runner import ProductExperimentResult
from scripts.run_product_experiment import write_product_artifacts as export_product_artifacts
from scripts.verify_product_experiment import ProductManifestError, verify_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
write_product_artifacts = partial(export_product_artifacts, export_mode="private")


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["arm", "prompt", "category"])
async def test_export_rejects_semantically_mismatched_pair(tmp_path: Path, field: str) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    candidate = result.arms["candidate"]
    if field == "arm":
        candidate.arm = "baseline"
    else:
        setattr(candidate.cases[0], field, "different-input")
    with pytest.raises(ProductManifestError, match="arm role|paired input"):
        write_product_artifacts(result, output_dir=tmp_path / "invalid", command="test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("dataset_sha256", "f" * 64, "dataset"),
        ("source_sha", "f" * 40, "source"),
    ],
)
async def test_export_rejects_arm_identity_drift_against_frozen_result(
    tmp_path: Path, field: str, value: str, reason: str
) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    setattr(result.arms["candidate"], field, value)
    with pytest.raises(ProductManifestError, match=reason):
        write_product_artifacts(result, output_dir=tmp_path / "invalid", command="test")


def test_manifest_rejects_excessive_json_depth_before_schema_parsing(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text('{"nested":' + "[" * 80 + "0" + "]" * 80 + "}", encoding="utf-8")
    with pytest.raises(ProductManifestError, match="depth"):
        verify_manifest(path)


@pytest.mark.asyncio
async def test_default_export_is_public_summary_without_private_payload(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    secret = "PRIVATE-CANARY-DO-NOT-PUBLISH"
    result.experiment_id = secret
    result.case_comparisons[0].baseline_answer = secret
    result.arms["baseline"].cases[0].answer = secret
    result.input_snapshot = {"internal_url": "https://" + secret + ".internal"}
    export_product_artifacts(result, output_dir=tmp_path, command=secret)
    for filename in ("result.json", "report.html", "manifest.json"):
        assert secret not in (tmp_path / filename).read_text(encoding="utf-8")
    summary = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "evalops.public-experiment-summary/1.0"
    assert summary["private_payload_status"] == "NOT_EXPORTED"
    assert summary["case_count"] == result.case_count
    assert summary["status"] == result.status
    assert "observations" not in summary and "case_comparisons" not in summary
    assert verify_manifest(tmp_path / "manifest.json")["export_mode"] == "public"


@pytest.mark.asyncio
async def test_rehashed_public_report_cannot_add_private_free_text(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    export_product_artifacts(result, output_dir=tmp_path, command="test")
    report = tmp_path / "report.html"
    payload = report.read_bytes() + b"PRIVATE-INTERNAL-URL"
    report.write_bytes(payload)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "report.html":
            entry.update(byte_size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProductManifestError, match="report"):
        verify_manifest(path)


@pytest.mark.asyncio
async def test_export_validates_bundle_before_publication(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    invalid = result.model_copy(update={"case_count": result.case_count + 1})
    output = tmp_path / "invalid"
    with pytest.raises(ProductManifestError, match="case"):
        write_product_artifacts(invalid, output_dir=output, command="test")
    assert not output.exists()


@pytest.mark.asyncio
async def test_failed_export_never_publishes_partial_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    output = tmp_path / "published"
    original_write = Path.write_bytes

    def failing_write(path: Path, payload: bytes) -> int:
        if path.name == "report.html":
            raise OSError("simulated disk failure")
        return original_write(path, payload)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    with pytest.raises(OSError, match="simulated disk failure"):
        write_product_artifacts(result, output_dir=output, command="test")
    assert not output.exists() or not list(output.iterdir())


@pytest.mark.asyncio
async def test_manifest_rejects_filesystem_reported_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    original_check = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == tmp_path / "report.html" or original_check(path),
    )
    with pytest.raises(ProductManifestError, match="symlink|unsafe"):
        verify_manifest(tmp_path / "manifest.json")


@pytest.mark.asyncio
async def test_manifest_rejects_symlink_artifact_even_with_matching_hash(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    output = tmp_path / "bundle"
    write_product_artifacts(result, output_dir=output, command="test")
    original = output / "report.html"
    outside = tmp_path / "outside.html"
    original.rename(outside)
    try:
        original.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"filesystem does not permit symbolic links: {error.winerror}")
    with pytest.raises(ProductManifestError, match="symlink|unsafe"):
        verify_manifest(output / "manifest.json")


def test_manifest_rejects_oversized_input_before_json_parsing(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(ProductManifestError, match="size limit"):
        verify_manifest(path)


@pytest.mark.asyncio
async def test_manifest_rejects_unsupported_artifact_files(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {"path": "unlisted.txt", "sha256": hashlib.sha256(b"x").hexdigest(), "byte_size": 1}
    )
    (tmp_path / "unlisted.txt").write_bytes(b"x")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProductManifestError, match="artifact"):
        verify_manifest(manifest_path)


@pytest.mark.asyncio
async def test_manifest_rejects_ambiguous_duplicate_json_keys(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    result = await run_experiment(
        REPOSITORY_ROOT / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    manifest_path = tmp_path / "manifest.json"
    original = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text('{"production_ready": true,' + original.lstrip()[1:], encoding="utf-8")
    with pytest.raises(ProductManifestError, match="duplicate"):
        verify_manifest(manifest_path)


@pytest.mark.parametrize(
    "status,automated,formal",
    [
        ("DEMO_PASS", 0, 2),
        ("AUTOMATED_PASS_HUMAN_REVIEW_PENDING", 0, 2),
        ("DEMO_FAIL", 1, 1),
        ("AUTOMATED_FAIL", 1, 1),
        ("INPUT_REQUIRED", 2, 2),
        ("INSUFFICIENT_EVIDENCE", 2, 2),
        ("EXECUTION_FAILED", 3, 3),
        ("FUTURE_UNKNOWN_STATUS", 3, 3),
    ],
)
def test_exit_contract_fails_closed(status: str, automated: int, formal: int) -> None:
    from scripts.run_product_experiment import experiment_exit_code

    assert experiment_exit_code(status, gate="automated") == automated
    assert experiment_exit_code(status, gate="formal") == formal


def test_cli_interrupted_input_returns_130_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.run_product_experiment import main

    def interrupted_open(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(Path, "open", interrupted_open)
    monkeypatch.setattr(
        sys, "argv", ["run_product_experiment", "--spec", "interrupted.json", "--validate-only"]
    )
    assert main() == 130
    captured = capsys.readouterr()
    assert json.loads(captured.err)["error_code"] == "experiment_interrupted"
    assert "Traceback" not in captured.err


def test_cli_quality_failure_has_nonzero_exit_and_preserves_report(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    demo = root / "benchmarks/product_demo_v1"
    spec = json.loads((demo / "experiment.json").read_text(encoding="utf-8"))
    cases = json.loads((demo / "cases.json").read_text(encoding="utf-8"))
    for case in cases:
        case["metadata"]["fixture_profiles"]["candidate"]["answer"] = "incorrect answer"
    content = json.dumps(cases).encode()
    (tmp_path / "cases.json").write_bytes(content)
    spec["dataset"]["sha256"] = hashlib.sha256(content).hexdigest()
    spec["policy_path"] = str((demo / spec["policy_path"]).resolve())
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    output = tmp_path / "output"

    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_product_experiment",
            "--spec",
            str(spec_path),
            "--output-dir",
            str(output),
            "--evalops-sha",
            "e" * 40,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert "DEMO_FAIL" in process.stdout, process.stderr
    assert process.returncode == 1
    assert json.loads((output / "result.json").read_text(encoding="utf-8"))["status"] == "DEMO_FAIL"
    assert (output / "report.html").is_file()


def test_cli_formal_gate_does_not_release_a_passing_demo(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_product_experiment",
            "--spec",
            str(root / "benchmarks/product_demo_v1/experiment.json"),
            "--output-dir",
            str(tmp_path / "output"),
            "--evalops-sha",
            "e" * 40,
            "--gate",
            "formal",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert "DEMO_PASS" in process.stdout, process.stderr
    assert process.returncode == 2


def test_cli_preflight_checks_inputs_without_creating_execution_artifacts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "must-not-exist"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_product_experiment",
            "--spec",
            str(root / "benchmarks/product_demo_v1/experiment.json"),
            "--output-dir",
            str(output),
            "--validate-only",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["execution_status"] == "NOT_RUN"
    assert result["case_count"] == 120
    assert result["planned_case_executions"] == 240
    assert not output.exists()


def test_cli_invalid_input_does_not_print_private_validation_values(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    spec = json.loads((root / "benchmarks/product_demo_v1/experiment.json").read_text())
    spec["scope"] = "PRIVATE-VALIDATION-MARKER"
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_product_experiment",
            "--spec",
            str(path),
            "--validate-only",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert process.returncode == 2
    assert "PRIVATE-VALIDATION-MARKER" not in process.stdout + process.stderr
    assert "Traceback" not in process.stderr
    assert json.loads(process.stderr)["error_code"] == "experiment_input_invalid"


def test_cli_export_error_has_safe_runtime_exit(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "PRIVATE-OUTPUT-MARKER"
    output.write_text("existing user file", encoding="utf-8")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_product_experiment",
            "--spec",
            str(root / "benchmarks/product_demo_v1/experiment.json"),
            "--output-dir",
            str(output),
            "--evalops-sha",
            "e" * 40,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert process.returncode == 3
    assert json.loads(process.stderr)["error_code"] == "experiment_execution_or_export_failed"
    assert "PRIVATE-OUTPUT-MARKER" not in process.stdout + process.stderr
    assert output.read_text(encoding="utf-8") == "existing user file"


@pytest.mark.asyncio
async def test_completed_bundle_cannot_omit_both_arm_entries(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    root = REPOSITORY_ROOT
    result = await run_experiment(
        root / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [
        entry
        for entry in manifest["files"]
        if entry["path"] not in {"baseline.json", "candidate.json"}
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProductManifestError, match="arm"):
        verify_manifest(manifest_path)


@pytest.mark.asyncio
async def test_rehashed_arm_must_match_result_identity(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    root = REPOSITORY_ROOT
    result = await run_experiment(
        root / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    arm_path = tmp_path / "candidate.json"
    arm = json.loads(arm_path.read_text(encoding="utf-8"))
    arm["source_sha"] = "f" * 40
    payload = json.dumps(arm).encode()
    arm_path.write_bytes(payload)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "candidate.json":
            entry.update(sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProductManifestError, match="arm"):
        verify_manifest(manifest_path)


@pytest.mark.asyncio
async def test_rehashed_result_cannot_lie_about_case_count(tmp_path: Path) -> None:
    from app.product_experiments.runner import run_experiment

    root = REPOSITORY_ROOT
    result = await run_experiment(
        root / "benchmarks/product_demo_v1/experiment.json", evalops_sha="e" * 40
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    result_path = tmp_path / "result.json"
    values = json.loads(result_path.read_text(encoding="utf-8"))
    values["case_count"] += 1
    payload = json.dumps(values).encode()
    result_path.write_bytes(payload)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "result.json":
            entry.update(sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProductManifestError, match="case"):
        verify_manifest(manifest_path)


@pytest.mark.parametrize(
    "field,value",
    [("formal_quality_claim_allowed", True), ("schema_version", "evalops.experiment-result/999")],
)
def test_rehashed_result_must_obey_version_and_claim_schema(
    tmp_path: Path, field: str, value: object
) -> None:
    result = ProductExperimentResult(
        experiment_id="blocked",
        status="INPUT_REQUIRED",
        scope="FORMAL",
        dataset_sha256="d" * 64,
        evalops_sha="e" * 40,
        case_count=120,
        source_identities={},
        arms={},
        automated_assessment={"status": "NOT_RUN"},
        case_comparisons=[],
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    path = tmp_path / "result.json"
    values = json.loads(path.read_text(encoding="utf-8"))
    values[field] = value
    payload = json.dumps(values).encode()
    path.write_bytes(payload)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "result.json":
            entry.update(sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProductManifestError, match="schema"):
        verify_manifest(manifest_path)


def test_export_does_not_overwrite_an_existing_evidence_bundle(tmp_path: Path) -> None:
    result = ProductExperimentResult(
        experiment_id="first",
        status="INPUT_REQUIRED",
        scope="FORMAL",
        dataset_sha256="d" * 64,
        evalops_sha="e" * 40,
        case_count=120,
        source_identities={},
        arms={},
        automated_assessment={"status": "NOT_RUN"},
        case_comparisons=[],
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test")
    before = (tmp_path / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_product_artifacts(
            result.model_copy(update={"experiment_id": "second"}),
            output_dir=tmp_path,
            command="test",
        )
    assert (tmp_path / "manifest.json").read_bytes() == before


def test_product_artifacts_have_hash_manifest_and_claim_boundary(tmp_path: Path) -> None:
    result = ProductExperimentResult(
        experiment_id="input-required",
        status="INPUT_REQUIRED",
        scope="FORMAL",
        dataset_sha256="d" * 64,
        evalops_sha="e" * 40,
        case_count=120,
        source_identities={
            "baseline": {
                "repository": "https://example.com/rag",
                "sha": "b" * 40,
                "provider_type": "fixture",
            }
        },
        arms={},
        automated_assessment={"status": "NOT_RUN"},
        case_comparisons=[],
        input_requirements=[
            {
                "arm": "candidate",
                "code": "MISSING_CREDENTIAL_ENV",
                "environment_variable": "CANDIDATE_RAG_TOKEN",
            }
        ],
    )

    manifest = write_product_artifacts(
        result,
        output_dir=tmp_path,
        command="test command",
    )

    persisted = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert {entry["path"] for entry in persisted["files"]} == {"result.json", "report.html"}
    assert manifest["formal_quality_claim_allowed"] is False
    assert persisted["human_review_status"] == "PENDING"
    assert persisted["production_ready"] is False
    assert verify_manifest(tmp_path / "manifest.json")["status"] == "INPUT_REQUIRED"


def test_product_manifest_rejects_tampered_result(tmp_path: Path) -> None:
    result = ProductExperimentResult(
        experiment_id="demo",
        status="INPUT_REQUIRED",
        scope="DEMO",
        dataset_sha256="d" * 64,
        evalops_sha="e" * 40,
        case_count=0,
        source_identities={
            "baseline": {
                "repository": "demo://baseline",
                "sha": "b" * 40,
                "provider_type": "fixture",
            }
        },
        arms={},
        automated_assessment={"status": "NOT_RUN"},
        case_comparisons=[],
    )
    write_product_artifacts(result, output_dir=tmp_path, command="test command")
    (tmp_path / "result.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ProductManifestError, match="size mismatch|digest mismatch"):
        verify_manifest(tmp_path / "manifest.json")
