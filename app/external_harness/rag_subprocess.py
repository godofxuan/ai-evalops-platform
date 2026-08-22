"""Bounded subprocess client for the versioned Enterprise RAG harness CLI."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_eval.schema import AgentRunArtifact
from app.external_harness.harness_envelope import (
    seal_rag_harness_result,
    verify_and_convert_rag_envelope,
)
from app.external_harness.rag_harness import RagHarnessContractError

_MAX_STDOUT_BYTES = 5 * 1024 * 1024


class HarnessExecutionError(RuntimeError):
    pass


class RagHarnessRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    schema_name: Literal["enterprise.agent-harness-request"] = "enterprise.agent-harness-request"
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)
    timeout_ms: int = Field(default=15_000, ge=100, le=300_000)
    traceparent: str | None = Field(
        default=None,
        pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$",
    )
    mode: Literal["deterministic_mock", "local_real"] = "deterministic_mock"
    attempt_id: str | None = Field(default=None, min_length=1, max_length=100)


Runner = Callable[..., subprocess.CompletedProcess[str]]


class RagHarnessSubprocessClient:
    def __init__(
        self,
        *,
        repo_root: Path,
        python_executable: Path,
        state_root: Path,
        git_sha: str,
        runner: Runner = subprocess.run,
    ) -> None:
        if not _is_sha(git_sha):
            raise ValueError("harness client requires an exact lowercase Git SHA")
        self.repo_root = repo_root
        self.python_executable = python_executable
        self.state_root = state_root
        self.git_sha = git_sha
        self.runner = runner

    def run(self, request: RagHarnessRequestV1) -> AgentRunArtifact:
        command = [
            str(self.python_executable),
            "-m",
            "scripts.run_agent_harness",
            "--state-root",
            str(self.state_root),
            "--git-sha",
            self.git_sha,
        ]
        environment = {
            key: value
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP")
            if (value := os.environ.get(key)) is not None
        }
        try:
            completed = self.runner(
                command,
                input=request.model_dump_json(exclude_none=True),
                text=True,
                capture_output=True,
                check=False,
                shell=False,
                cwd=self.repo_root,
                env=environment,
                timeout=request.timeout_ms / 1000 + 5.0,
            )
        except subprocess.TimeoutExpired as error:
            raise HarnessExecutionError("RAG harness timed out") from error
        if completed.returncode != 0:
            raise HarnessExecutionError(
                f"RAG harness exited with code {completed.returncode}; stderr is withheld"
            )
        if len(completed.stdout.encode("utf-8")) > _MAX_STDOUT_BYTES:
            raise HarnessExecutionError("RAG harness output exceeds the 5 MiB contract limit")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise HarnessExecutionError("RAG harness did not return JSON") from error
        try:
            envelope = seal_rag_harness_result(
                payload,
                producer_source_sha=self.git_sha,
            )
            artifact = verify_and_convert_rag_envelope(envelope)
        except RagHarnessContractError as error:
            raise HarnessExecutionError("RAG harness JSON violates sealed schema 1.1") from error
        if artifact.metadata["producer_git_sha"] != self.git_sha:
            raise HarnessExecutionError("RAG harness result came from an unexpected Git SHA")
        return artifact


def harness_contract_available(repo_root: Path, git_sha: str) -> bool:
    if not _is_sha(git_sha):
        raise ValueError("capability preflight requires an exact lowercase Git SHA")
    command = [
        "git",
        "-c",
        f"safe.directory={repo_root.as_posix()}",
        "-C",
        str(repo_root),
        "cat-file",
        "-e",
        f"{git_sha}:app/agent_runtime/harness_contract.py",
    ]
    return (
        subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        ).returncode
        == 0
    )


def _is_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "HarnessExecutionError",
    "RagHarnessRequestV1",
    "RagHarnessSubprocessClient",
    "harness_contract_available",
]
