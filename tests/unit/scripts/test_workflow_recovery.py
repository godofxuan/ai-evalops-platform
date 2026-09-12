import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.product_experiments.runner import ProductExperimentResult
from scripts import evaluation_workflow as workflow

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "benchmarks/agent_tool_demo_v1/experiment.json"


def arguments(output: Path, *, private: bool = True) -> argparse.Namespace:
    return argparse.Namespace(
        output_dir=output,
        profile="normalized_exact_v1",
        traces=None,
        evalops_sha="e" * 40,
        include_private=private,
    )


def recovery_files(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


async def test_first_source_export_failure_preserves_real_execution_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executions = 0
    run = workflow.run_experiment

    async def counted(*args: Any, **kwargs: Any) -> ProductExperimentResult:
        nonlocal executions
        executions += 1
        return await run(*args, **kwargs)

    def fail_export(*args: Any, **kwargs: Any) -> None:
        raise OSError("PRIVATE_EXCEPTION_SENTINEL")

    monkeypatch.setattr(workflow, "run_experiment", counted)
    monkeypatch.setattr(workflow, "write_product_artifacts", fail_export)
    output = tmp_path / "output"
    assert await workflow.run_workflow(arguments(output), SPEC) == 3
    captured = capsys.readouterr()
    assert "PRIVATE_EXCEPTION_SENTINEL" not in captured.out + captured.err
    status = json.loads(captured.out)
    assert status["status"] == "EXECUTED_EXPORT_BLOCKED"
    assert status["capture_status"] == "COMPLETE"
    recovery = Path(status["recovery_path"])
    result = ProductExperimentResult.model_validate_json(
        (recovery / "captured-result.json").read_bytes()
    )
    raw = (recovery / "captured-dataset.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result.dataset_sha256
    assert len(result.observations["candidate"]) == 120
    assert executions == 1
    assert not output.exists()
    assert json.loads((recovery / "capture-status.json").read_bytes())["visibility"] == "PRIVATE"
    restored = tmp_path / "offline-restored"
    completed = await asyncio.to_thread(
        subprocess.run,
        [
            sys.executable,
            "-m",
            "scripts.evaluation_workflow",
            "recover",
            "--bundle",
            str(recovery),
            "--output-dir",
            str(restored),
            "--include-private",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["targets_called"] == 0
    assert (restored / "dataset.json").read_bytes() == raw


@pytest.mark.parametrize("private", [True, False])
async def test_final_publish_failure_preserves_capture_without_public_raw_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    private: bool,
) -> None:
    output = tmp_path / "output"
    rename = Path.rename

    def reject_final(path: Path, target: Path) -> Path:
        if Path(target) == output:
            raise OSError("PRIVATE_PUBLISH_EXCEPTION")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", reject_final)
    assert await workflow.run_workflow(arguments(output, private=private), SPEC) == 3
    emitted = capsys.readouterr()
    assert "PRIVATE_PUBLISH_EXCEPTION" not in emitted.out + emitted.err
    status = json.loads(emitted.out)
    assert status["status"] == "EXECUTED_EXPORT_BLOCKED"
    assert status["capture_status"] == "COMPLETE"
    recovery = Path(status["recovery_path"])
    assert not output.exists()
    if private:
        assert (recovery / "captured-result.json").is_file()
        assert (recovery / "captured-dataset.json").read_bytes() == (
            SPEC.parent / "cases.json"
        ).read_bytes()
    else:
        from app.product_experiments.public_summary import PublicExperimentSummary

        public = PublicExperimentSummary.model_validate_json(
            (recovery / "captured-public-result.json").read_bytes()
        )
        assert public.observed_case_arm_count == 240
        assert not (recovery / "source").exists()
        assert not (recovery / "captured-result.json").exists()
        assert not (recovery / "captured-dataset.json").exists()
        for data in recovery_files(recovery).values():
            assert b'"observations"' not in data
            assert b'"fixture_profiles"' not in data


async def test_public_export_failure_retains_only_public_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_publication(*args: Any, **kwargs: Any) -> None:
        raise OSError("PRIVATE_EXCEPTION_SENTINEL")

    monkeypatch.setattr(workflow, "_publish_files", fail_publication)
    assert await workflow.run_workflow(arguments(tmp_path / "out", private=False), SPEC) == 3
    emitted = capsys.readouterr()
    status = json.loads(emitted.out)
    recovery = Path(status["recovery_path"])
    assert status["capture_status"] == "COMPLETE"
    assert status["visibility"] == "PUBLIC"
    assert set(recovery_files(recovery)) == {
        "captured-public-result.json",
        "capture-status.json",
        "export-status.json",
    }
    assert "PRIVATE_EXCEPTION_SENTINEL" not in emitted.out + emitted.err


async def test_failed_capture_writes_are_reported_honestly_without_claiming_saved_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def storage_full(path: Path, data: bytes) -> int:
        raise OSError("PRIVATE_STORAGE_EXCEPTION")

    monkeypatch.setattr(Path, "write_bytes", storage_full)
    assert await workflow.run_workflow(arguments(tmp_path / "out"), SPEC) == 3
    emitted = capsys.readouterr()
    status = json.loads(emitted.out)
    assert status["status"] == "EXECUTED_EXPORT_BLOCKED"
    assert status["capture_status"] == "FAILED"
    assert status["recovery_status_write"] == "FAILED"
    assert recovery_files(Path(status["recovery_path"])) == {}
    assert "PRIVATE_STORAGE_EXCEPTION" not in emitted.out + emitted.err


async def test_partial_cleanup_failure_does_not_claim_capture_is_still_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    temporary_directory = workflow.TemporaryDirectory

    def interrupted_cleanup(*args: Any, **kwargs: Any) -> Any:
        temporary = temporary_directory(*args, **kwargs)
        if kwargs.get("delete") is False:

            def fail_cleanup() -> None:
                (Path(temporary.name) / "captured-result.json").unlink()
                raise OSError("PRIVATE_CLEANUP_EXCEPTION")

            temporary.cleanup = fail_cleanup
        return temporary

    monkeypatch.setattr(workflow, "TemporaryDirectory", interrupted_cleanup)
    output = tmp_path / "output"
    assert await workflow.run_workflow(arguments(output), SPEC) == 3
    emitted = capsys.readouterr()
    status = json.loads(emitted.out)
    assert status["capture_status"] == "FAILED"
    assert (output / "manifest.json").exists()
    assert "PRIVATE_CLEANUP_EXCEPTION" not in emitted.out + emitted.err
