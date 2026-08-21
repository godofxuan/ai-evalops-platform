import subprocess
from pathlib import Path

import pytest

from app.external_harness.rag_subprocess import (
    HarnessExecutionError,
    RagHarnessRequestV1,
    RagHarnessSubprocessClient,
)


def test_subprocess_boundary_rejects_non_json_output_without_shell() -> None:
    observed: dict[str, object] = {}

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="not-json", stderr="")

    client = RagHarnessSubprocessClient(
        repo_root=Path("C:/rag"),
        python_executable=Path("C:/python.exe"),
        state_root=Path("C:/state"),
        git_sha="e" * 40,
        runner=runner,
    )

    with pytest.raises(HarnessExecutionError, match="JSON"):
        client.run(RagHarnessRequestV1(case_id="case-1", question="policy?"))

    assert observed["shell"] is False
    assert observed["cwd"] == Path("C:/rag")
    assert observed["timeout"] == 20.0
    assert "--git-sha" in observed["command"]


def test_subprocess_timeout_is_classified() -> None:
    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=20.0)

    client = RagHarnessSubprocessClient(
        repo_root=Path("C:/rag"),
        python_executable=Path("C:/python.exe"),
        state_root=Path("C:/state"),
        git_sha="e" * 40,
        runner=runner,
    )

    with pytest.raises(HarnessExecutionError, match="timed out"):
        client.run(RagHarnessRequestV1(case_id="timeout-case", question="policy?"))
