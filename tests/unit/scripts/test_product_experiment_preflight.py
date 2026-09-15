from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts.run_product_experiment import _run, main
from scripts.verify_product_experiment import verify_manifest
from tests.product_http_support import LoopbackTargetService, LoopbackTargetTransport

ROOT = Path(__file__).resolve().parents[3]


def _file_snapshot(directory: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(directory): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _child_names(directory: Path) -> list[str]:
    return [path.name for path in directory.iterdir()]


def _args(tmp_path: Path, output: Path) -> argparse.Namespace:
    demo = ROOT / "benchmarks/product_demo_v1"
    spec = json.loads((demo / "experiment.json").read_bytes())
    cases = json.loads((demo / "cases.json").read_bytes())[:2]
    raw = json.dumps(cases).encode()
    (tmp_path / "cases.json").write_bytes(raw)
    spec["dataset"]["sha256"] = hashlib.sha256(raw).hexdigest()
    spec["policy_path"] = str(ROOT / "benchmarks/formal_agent_quality_v1/policy.json")
    for arm in spec["arms"]:
        arm["provider"] = dict(
            type="http",
            target_id=arm["label"],
            base_url="https://rag.example.com",
            endpoint="/query",
        )
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return argparse.Namespace(
        spec=path,
        output_dir=output,
        evalops_sha="e" * 40,
        validate_only=False,
        export_mode="public",
        gate="automated",
    )


def _network_boundary(monkeypatch: pytest.MonkeyPatch, server: LoopbackTargetService) -> None:
    original_dns = socket.getaddrinfo
    original_client = httpx.AsyncClient

    def dns(host: Any, *args: Any, **kwargs: Any) -> Any:
        # Public identity is a fixture; requests still travel over real loopback sockets.
        if host in ("rag.example.com", b"rag.example.com"):
            host = "93.184.216.34"
        return original_dns(host, *args, **kwargs)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return original_client(transport=LoopbackTargetTransport(server.port), **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(httpx, "AsyncClient", client)


async def test_nonempty_output_fails_before_any_target_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("user content", encoding="utf-8")
    args = _args(tmp_path, output)
    async with LoopbackTargetService() as server:
        _network_boundary(monkeypatch, server)
        with pytest.raises(FileExistsError):
            await _run(args)
        assert server.requests == []
    assert marker.read_text(encoding="utf-8") == "user content"


async def test_existing_export_lock_is_preserved_without_target_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reserved"
    lock = tmp_path / ".reserved.export.lock"
    lock.write_text("other writer", encoding="utf-8")
    args = _args(tmp_path, output)
    async with LoopbackTargetService() as server:
        _network_boundary(monkeypatch, server)
        with pytest.raises(FileExistsError):
            await _run(args)
        assert server.requests == []
    assert lock.read_text(encoding="utf-8") == "other writer"
    assert not output.exists()


async def test_output_write_failure_happens_before_target_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _args(tmp_path, tmp_path / "unwritable")

    def denied_write(path: Path, payload: bytes) -> int:
        raise PermissionError("filesystem write denied")

    monkeypatch.setattr(Path, "write_bytes", denied_write)
    async with LoopbackTargetService() as server:
        _network_boundary(monkeypatch, server)
        with pytest.raises(PermissionError):
            await _run(args)
        assert server.requests == []
    assert not (tmp_path / ".unwritable.export.lock").exists()


@pytest.mark.parametrize("placement", ["output", "ancestor"])
@pytest.mark.parametrize("kind", ["symlink", "junction"])
async def test_linked_output_or_ancestor_is_rejected_before_target_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placement: str, kind: str
) -> None:
    target = tmp_path / "real-directory"
    target.mkdir()
    linked = tmp_path / "linked-directory"
    if kind == "junction":
        if os.name != "nt":
            pytest.skip("Windows junction")
        await asyncio.to_thread(
            subprocess.run,
            ["cmd", "/c", "mklink", "/J", str(linked), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        try:
            linked.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlink privileges unavailable")
    output = linked if placement == "output" else linked / "new-output"
    args = _args(tmp_path, output)
    async with LoopbackTargetService() as server:
        _network_boundary(monkeypatch, server)
        with pytest.raises(FileExistsError):
            await _run(args)
        assert server.requests == []
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("sha", ["short", "E" * 40, "", "g" * 40])
@pytest.mark.parametrize("validate_only", [False, True])
async def test_invalid_evalops_sha_is_rejected_before_calls_or_output_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sha: str, validate_only: bool
) -> None:
    output = tmp_path / "new-parent" / "output"
    args = _args(tmp_path, output)
    args.evalops_sha = sha
    args.validate_only = validate_only
    async with LoopbackTargetService() as server:
        _network_boundary(monkeypatch, server)
        with pytest.raises(ValueError):
            await _run(args)
        assert server.requests == []
    assert not output.parent.exists()


@pytest.mark.parametrize("existing_empty", [False, True])
async def test_valid_new_or_empty_output_still_exports_after_real_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_empty: bool
) -> None:
    output = tmp_path / "valid-output"
    if existing_empty:
        output.mkdir()
    args = _args(tmp_path, output)
    async with LoopbackTargetService() as server:
        _network_boundary(monkeypatch, server)
        assert await _run(args) == 2  # Two cases cannot satisfy the unchanged evidence policy.
        assert len(server.requests) == 4
    verify_manifest(output / "manifest.json")
    assert (output / "report.html").is_file()
    assert not (tmp_path / ".valid-output.export.lock").exists()
    assert not any(name.startswith(".evalops-preflight-") for name in _child_names(tmp_path))


async def test_validate_only_does_not_touch_output_or_take_an_export_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "existing-output"
    output.mkdir()
    (output / "keep.txt").write_text("user content", encoding="utf-8")
    lock = tmp_path / ".existing-output.export.lock"
    lock.write_text("other writer", encoding="utf-8")
    args = _args(tmp_path, output)
    args.validate_only = True
    args.evalops_sha = None
    before = _file_snapshot(tmp_path)
    async with LoopbackTargetService() as server:
        _network_boundary(monkeypatch, server)
        assert await _run(args) == 0
        assert server.requests == []
    after = _file_snapshot(tmp_path)
    assert after == before


def test_cli_invalid_sha_has_safe_input_error_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "new-parent" / "output"
    args = _args(tmp_path, output)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_product_experiment",
            "--spec",
            str(args.spec),
            "--output-dir",
            str(output),
            "--evalops-sha",
            "PRIVATE-SHA",
        ],
    )
    assert main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"error_code": "experiment_input_invalid"}
    assert "PRIVATE-SHA" not in captured.out + captured.err
    assert not output.parent.exists()
