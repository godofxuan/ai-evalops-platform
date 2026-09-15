"""Verify the original delivery, extract fresh, and replay with Python networking denied."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ORIGINAL_SHA256 = "3db9535f56a1ff9d3e0539664edb260aa542e3d7d98aeffd8eec8b316300e170"
GUARDED = """
import runpy, sys, socket
def deny(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        raise RuntimeError('offline_audit_denied:' + event)
sys.addaudithook(deny)
try:
    socket.getaddrinfo('example.invalid', 443)
except RuntimeError as e:
    assert str(e).startswith('offline_audit_denied:')
else:
    raise AssertionError('network guard inactive')
sys.argv = ['compare_local_public_benchmarks', *sys.argv[1:]]
runpy.run_module('scripts.compare_local_public_benchmarks', run_name='__main__')
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("fresh replay directory required")
    with args.archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != ORIGINAL_SHA256:
        raise ValueError("not the pinned original Cross Family delivery")
    with zipfile.ZipFile(args.archive) as archive:
        manifest = json.loads(archive.read("DELIVERY_MANIFEST.json"))
        entries = archive.infolist()
        expected = set(manifest["files"]) | {"DELIVERY_MANIFEST.json"}
        if len(entries) != len(expected) or {entry.filename for entry in entries} != expected:
            raise ValueError("duplicate or unexpected archive entries")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or entry.file_size > 64 * 1024 * 1024
            ):
                raise ValueError("unsafe archive member")
            payload = archive.read(entry)
            if entry.filename != "DELIVERY_MANIFEST.json":
                pin = manifest["files"][entry.filename]
                if (
                    len(payload) != pin["bytes"]
                    or hashlib.sha256(payload).hexdigest() != pin["sha256"]
                ):
                    raise ValueError("archive member digest mismatch")
        args.output.mkdir(parents=True)
        archive.extractall(args.output)
    for layout in manifest["evidence_roots"]:
        source = (args.output / layout["archive_prefix"]).resolve()
        destination = (args.output / layout["restore_to"]).resolve()
        if not source.is_relative_to(args.output.resolve()) or not destination.is_relative_to(
            args.output.resolve() / "source" / "artifacts"
        ):
            raise ValueError("unsafe restoration mapping")
        shutil.copytree(source, destination)
    checks = {}
    for benchmark in ("bfcl", "ragbench"):
        old = "artifacts/public-benchmark-20260912"
        new = "artifacts/gemma-cross-family-20260912"
        command = [
            sys.executable,
            "-c",
            GUARDED,
            "verify",
            "--run-dir",
            f"{old}/{benchmark}-local-run",
            "--report-dir",
            f"{old}/{benchmark}-report-final",
            "--run-dir",
            f"{new}/{benchmark}-run",
            "--report-dir",
            f"{new}/{benchmark}-report-final",
            "--output-dir",
            f"{new}/{benchmark}-cross-comparison",
        ]
        if benchmark == "bfcl":
            command += ["--bfcl-source-dir", f"{old}/bfcl/upstream"]
        result = subprocess.run(
            command, cwd=args.output / "source", capture_output=True, timeout=300, check=False
        )
        (args.output / f"{benchmark}-replay.log").write_bytes(result.stdout + result.stderr)
        checks[benchmark] = {"exit_code": result.returncode, "log": f"{benchmark}-replay.log"}
        if result.returncode:
            raise RuntimeError(f"replay_failed:{benchmark}")
    receipt = {
        "archive_sha256": digest,
        "members_verified": len(entries),
        "status": "ORIGINAL_CROSS_FAMILY_RECOMPUTED",
        "checks": checks,
        "model_calls": 0,
        "python_network_and_subprocess_guard": True,
        "os_firewall_changed": False,
        "source": "original ZIP source snapshot",
        "fresh_dependency_install": False,
    }
    (args.output / "REPLAY_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
