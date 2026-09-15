"""Atomic, non-overwriting portable bundles for public projections or private recomputation."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.strict_json import decode_evidence_json
from app.product_experiments.durable_verification import (
    DurableReportVerification,
    verify_durable_report,
)
from app.product_experiments.export_service import MAX_REPORT_BYTES, encode_report
from app.product_experiments.report import render_experiment_html


class _FilePin(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0, le=MAX_REPORT_BYTES)


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["evalops.durable-bundle/1.0"] = "evalops.durable-bundle/1.0"
    visibility: Literal["public", "private"]
    files: dict[str, _FilePin]
    formal_quality_claim_allowed: Literal[False] = False
    production_ready: Literal[False] = False


def _plain_path(path: Path) -> None:
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise ValueError("bundle_link_not_allowed")


def _read(path: Path, limit: int) -> bytes:
    _plain_path(path)
    if not path.is_file():
        raise ValueError("bundle_file_missing")
    with path.open("rb") as source:
        payload = source.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("bundle_file_limit")
    return payload


def _html(payload: bytes) -> bytes:
    report = decode_evidence_json(payload)
    inner = report["summary"] if "summary" in report else report["result"]
    return render_experiment_html(inner).encode("utf-8")


def verify_durable_bundle(
    directory: Path, *, expected_report_sha256: str | None = None
) -> DurableReportVerification:
    _plain_path(directory)
    manifest_bytes = _read(directory / "manifest.json", 64 * 1024)
    decode_evidence_json(manifest_bytes)
    manifest = _Manifest.model_validate_json(manifest_bytes)
    expected = {"report.json", "report.html"}
    if manifest.visibility == "private":
        expected.add("dataset.json")
    if set(manifest.files) != expected or {
        item.name for item in directory.iterdir()
    } != expected | {"manifest.json"}:
        raise ValueError("bundle_file_set_mismatch")
    contents: dict[str, bytes] = {}
    for name in sorted(expected):
        payload = _read(
            directory / name, 10 * 1024 * 1024 if name == "dataset.json" else MAX_REPORT_BYTES
        )
        pin = manifest.files[name]
        if pin.byte_size != len(payload) or pin.sha256 != hashlib.sha256(payload).hexdigest():
            raise ValueError("bundle_file_hash_mismatch")
        contents[name] = payload
    verification = verify_durable_report(
        contents["report.json"],
        raw_dataset=contents.get("dataset.json"),
        expected_sha256=expected_report_sha256,
    )
    expected_scope = (
        "PRIVATE_RECOMPUTED" if manifest.visibility == "private" else "PUBLIC_PROJECTION_ONLY"
    )
    if verification.verification_scope != expected_scope:
        raise ValueError("bundle_visibility_mismatch")
    if contents["report.html"] != _html(contents["report.json"]):
        raise ValueError("bundle_html_mismatch")
    return verification


def write_durable_bundle(
    payload: bytes,
    *,
    output_dir: Path,
    raw_dataset: bytes | None = None,
    expected_report_sha256: str | None = None,
) -> DurableReportVerification:
    _plain_path(output_dir)
    if output_dir.exists():
        raise ValueError("output_already_exists")
    verification = verify_durable_report(
        payload, raw_dataset=raw_dataset, expected_sha256=expected_report_sha256
    )
    if verification.verification_scope == "PRIVATE_SOURCE_REQUIRED":
        raise ValueError("private_source_required")
    public = verification.verification_scope == "PUBLIC_PROJECTION_ONLY"
    if public and raw_dataset is not None:
        raise ValueError("public_bundle_must_not_include_source")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.export.lock"
    _plain_path(lock_path)
    # Exclusive sibling lock; never remove a lock created by another writer.
    lock = lock_path.open("x", encoding="utf-8")
    try:
        with TemporaryDirectory(
            prefix=".evalops-durable-export-", dir=output_dir.parent
        ) as temporary:
            staged = Path(temporary) / "bundle"
            staged.mkdir()
            contents = {"report.json": payload, "report.html": _html(payload)}
            if raw_dataset is not None:
                contents["dataset.json"] = raw_dataset
            manifest = _Manifest(
                visibility="public" if public else "private",
                files={
                    name: _FilePin(sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data))
                    for name, data in contents.items()
                },
            )
            for name, data in contents.items():
                (staged / name).write_bytes(data)
            (staged / "manifest.json").write_bytes(encode_report(manifest.model_dump(mode="json")))
            verify_durable_bundle(staged, expected_report_sha256=verification.report_sha256)
            _plain_path(output_dir)
            if output_dir.exists():
                raise ValueError("output_already_exists")
            staged.rename(output_dir)
    finally:
        lock.close()
        lock_path.unlink()
    return verification
