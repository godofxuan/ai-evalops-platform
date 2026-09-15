"""Recoverable private local ledger, never a trusted server preregistration."""

import hashlib
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from typing import Any
from uuid import UUID

from app.core.strict_json import decode_evidence_json
from app.product_experiments.client import ProductAPIClient
from app.product_experiments.durable_bundle import verify_durable_bundle, write_durable_bundle
from app.product_experiments.export_service import encode_report
from app.product_experiments.reliability import (
    MAX_PANEL_REPORT_BYTES,
    ReliabilityPlan,
    build_reliability_report,
    render_reliability_html,
    verify_reliability_report,
)
from app.product_experiments.service import ExperimentSubmissionAccepted


def plain_path(path: Path) -> None:
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("ledger_link_not_allowed")


def read_bounded(path: Path, limit: int) -> bytes:
    plain_path(path)
    if not path.is_file():
        raise ValueError("ledger_file_missing")
    with path.open("rb") as source:
        payload = source.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("ledger_file_limit")
    return payload


def _names(directory: Path, limit: int) -> set[str]:
    plain_path(directory)
    names = set()
    for item in directory.iterdir():
        plain_path(item)
        names.add(item.name)
        if len(names) > limit:
            raise ValueError("ledger_entry_limit")
    return names


@contextmanager
def _lock(directory: Path) -> Iterator[None]:
    plain_path(directory)
    namespace = Path(gettempdir()) / "evalops-reliability-locks"
    plain_path(namespace)
    namespace.mkdir(exist_ok=True)
    key = hashlib.sha256(os.path.normcase(os.path.abspath(directory)).encode()).hexdigest()
    lock_path = namespace / f"{key}.lock"
    plain_path(lock_path)
    lock = lock_path.open("a+b")
    try:
        if lock.seek(0, 2) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        lock.close()  # OS releases even on process death. Never unlink another process's inode.


def _publish(
    directory: Path, contents: dict[str, bytes], *, stage_parent: Path | None = None
) -> None:
    with _lock(directory):
        if directory.exists():
            raise ValueError("output_already_exists")
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(
            prefix=".reliability-stage-", dir=stage_parent or directory.parent
        ) as temporary:
            staged = Path(temporary) / "bundle"
            staged.mkdir()
            for name, payload in contents.items():
                (staged / name).write_bytes(payload)
            plain_path(directory)
            if directory.exists():
                raise ValueError("output_already_exists")
            staged.rename(directory)


def create_reliability_ledger(directory: Path, plan: ReliabilityPlan, raw_dataset: bytes) -> None:
    plan = ReliabilityPlan.model_validate_json(plan.model_dump_json())
    plan.validate_dataset(raw_dataset)
    _publish(
        directory,
        {"plan.json": plan.model_dump_json(indent=2).encode(), "dataset.json": raw_dataset},
    )


def _load(
    directory: Path,
) -> tuple[ReliabilityPlan, bytes, dict[int, ExperimentSubmissionAccepted]]:
    names = _names(directory, 22)
    payload = read_bounded(directory / "plan.json", 2 * 1024 * 1024)
    decode_evidence_json(payload)
    plan = ReliabilityPlan.model_validate_json(payload)
    raw = read_bounded(directory / "dataset.json", 10 * 1024 * 1024)
    plan.validate_dataset(raw)
    allowed = {"plan.json", "dataset.json"} | {
        f"{prefix}-{trial:02d}"
        for prefix in ("receipt", "trial")
        for trial in range(1, plan.trial_count + 1)
    }
    if not names <= allowed:
        raise ValueError("ledger_file_set_mismatch")
    receipts = {}
    identities: set[UUID] = set()
    for trial in range(1, plan.trial_count + 1):
        receipt_dir = directory / f"receipt-{trial:02d}"
        if receipt_dir.name not in names:
            if f"trial-{trial:02d}" in names:
                raise ValueError("ledger_bundle_without_receipt")
            continue
        if _names(receipt_dir, 1) != {"receipt.json"}:
            raise ValueError("ledger_receipt_file_set")
        receipt = decode_evidence_json(read_bounded(receipt_dir / "receipt.json", 16 * 1024))
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"plan_sha256", "trial", "idempotency_key", "accepted"}
            or receipt["plan_sha256"] != plan.plan_sha256
            or type(receipt["trial"]) is not int
            or receipt["trial"] != trial
            or receipt["idempotency_key"] != plan.idempotency_key(trial)
        ):
            raise ValueError("ledger_receipt_binding")
        accepted = ExperimentSubmissionAccepted.model_validate_json(
            encode_report(receipt["accepted"])
        )
        ids = {accepted.id, accepted.baseline_run_id, accepted.candidate_run_id}
        if (
            len(ids) != 3
            or ids & identities
            or accepted.status_url != f"/api/v1/experiments/{accepted.id}"
        ):
            raise ValueError("ledger_duplicate_or_invalid_identity")
        identities.update(ids)
        receipts[trial] = accepted
    return plan, raw, receipts


async def submit_reliability_ledger(directory: Path, client: ProductAPIClient) -> dict[str, Any]:
    with _lock(directory):
        plan, raw, receipts = _load(directory)
        for trial in range(1, plan.trial_count + 1):
            accepted = await client.submit(
                request=plan.trial_request(trial),
                dataset_payload=raw,
                idempotency_key=plan.idempotency_key(trial),
            )
            if trial in receipts:
                if accepted != receipts[trial]:
                    raise ValueError("ledger_replay_identity_mismatch")
                continue
            ids = {accepted.id, accepted.baseline_run_id, accepted.candidate_run_id}
            if len(ids) != 3 or any(
                ids & {r.id, r.baseline_run_id, r.candidate_run_id} for r in receipts.values()
            ):
                raise ValueError("ledger_duplicate_or_invalid_identity")
            _publish(
                directory / f"receipt-{trial:02d}",
                {
                    "receipt.json": encode_report(
                        {
                            "plan_sha256": plan.plan_sha256,
                            "trial": trial,
                            "idempotency_key": plan.idempotency_key(trial),
                            "accepted": accepted.model_dump(mode="json"),
                        }
                    )
                },
                stage_parent=directory.parent,
            )
            receipts[trial] = accepted
        return {
            "submitted_trials": len(receipts),
            "plan_sha256": plan.plan_sha256,
            "formal_quality_claim_allowed": False,
        }


def _reports(
    directory: Path, raw: bytes, receipts: dict[int, ExperimentSubmissionAccepted]
) -> list[tuple[int, bytes]]:
    reports = []
    total_bytes = 0
    for trial, receipt in receipts.items():
        bundle = directory / f"trial-{trial:02d}"
        if not bundle.exists():
            continue
        if _names(bundle, 4) != {"report.json", "report.html", "dataset.json", "manifest.json"}:
            raise ValueError("ledger_bundle_file_set")
        payload = read_bounded(bundle / "report.json", MAX_PANEL_REPORT_BYTES)
        read_bounded(bundle / "report.html", MAX_PANEL_REPORT_BYTES)
        total_bytes += len(payload)
        if total_bytes > 128 * 1024 * 1024:
            raise ValueError("ledger_total_evidence_limit")
        verified = verify_durable_bundle(bundle)
        if (
            verified.verification_scope != "PRIVATE_RECOMPUTED"
            or verified.execution_id != receipt.id
            or read_bounded(bundle / "dataset.json", 10 * 1024 * 1024) != raw
        ):
            raise ValueError("ledger_bundle_identity")
        _match_receipt(payload, receipt)
        reports.append((trial, payload))
    return reports


def _match_receipt(payload: bytes, receipt: ExperimentSubmissionAccepted) -> None:
    snapshot = decode_evidence_json(payload)["result_snapshot"]
    if (
        snapshot["experiment_id"] != str(receipt.id)
        or snapshot["arms"]["baseline"]["run_id"] != str(receipt.baseline_run_id)
        or snapshot["arms"]["candidate"]["run_id"] != str(receipt.candidate_run_id)
    ):
        raise ValueError("ledger_bundle_run_identity")


async def collect_reliability_ledger(directory: Path, client: ProductAPIClient) -> dict[str, Any]:
    with _lock(directory):
        plan, raw, receipts = _load(directory)
        reports = _reports(directory, raw, receipts)
        build_reliability_report(plan=plan, raw_dataset=raw, reports=reports)
        collected = {trial for trial, _ in reports}
        states = {}
        for trial, receipt in receipts.items():
            if trial in collected:
                states[str(trial)] = "PRIVATE_RECOMPUTED"
                continue
            status = await client.get(receipt.id)
            if (
                status.id != receipt.id
                or status.baseline.id != receipt.baseline_run_id
                or status.candidate.id != receipt.candidate_run_id
            ):
                raise ValueError("ledger_status_identity")
            states[str(trial)] = status.state
            if status.state not in {"READY_FOR_ASSESSMENT", "EXECUTION_FAILED", "CANCELLED"}:
                continue
            payload = await client.export(receipt.id, include_private=True)
            build_reliability_report(
                plan=plan, raw_dataset=raw, reports=[*reports, (trial, payload)]
            )
            _match_receipt(payload, receipt)
            output = directory / f"trial-{trial:02d}"
            with (
                _lock(output),
                TemporaryDirectory(prefix=".reliability-stage-", dir=directory.parent) as temporary,
            ):
                staged = Path(temporary) / "bundle"
                write_durable_bundle(payload, output_dir=staged, raw_dataset=raw)
                plain_path(output)
                if output.exists():
                    raise ValueError("output_already_exists")
                staged.rename(output)
            reports = _reports(directory, raw, receipts)
        return {
            "collected_trials": len(reports),
            "expected_trials": plan.trial_count,
            "states": states,
            "formal_quality_claim_allowed": False,
        }


def report_reliability_ledger(directory: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.absolute().is_relative_to(directory.absolute()):
        raise ValueError("report_must_be_outside_ledger")
    with _lock(directory):
        plan, raw, receipts = _load(directory)
        report = build_reliability_report(
            plan=plan, raw_dataset=raw, reports=_reports(directory, raw, receipts)
        )
        _publish(
            output_dir,
            {
                "report.json": encode_report(report),
                "report.html": render_reliability_html(report).encode(),
            },
        )
        return {
            "report_created": True,
            "status": report["status"],
            "plan_sha256": plan.plan_sha256,
            "expected_trials": plan.trial_count,
            "collected_trials": len(report["trial_reports"]),
            "formal_quality_claim_allowed": False,
        }


def verify_reliability_ledger(directory: Path, output_dir: Path) -> dict[str, Any]:
    with _lock(directory):
        plan, raw, receipts = _load(directory)
        if _names(output_dir, 2) != {"report.json", "report.html"}:
            raise ValueError("panel_report_file_set")
        payload = read_bounded(output_dir / "report.json", MAX_PANEL_REPORT_BYTES)
        verify_reliability_report(
            payload, plan=plan, raw_dataset=raw, reports=_reports(directory, raw, receipts)
        )
        report = decode_evidence_json(payload)
        if read_bounded(output_dir / "report.html", MAX_PANEL_REPORT_BYTES) != (
            render_reliability_html(report).encode()
        ):
            raise ValueError("panel_html_mismatch")
        return {
            "verification_scope": "PRIVATE_RECOMPUTED_PANEL",
            "status": report["status"],
            "plan_sha256": plan.plan_sha256,
            "expected_trials": plan.trial_count,
            "collected_trials": len(report["trial_reports"]),
            "server_provenance_verified": False,
            "formal_quality_claim_allowed": False,
        }
