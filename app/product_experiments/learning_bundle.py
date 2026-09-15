"""Immutable private workflow packages, independently reconstructable offline."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.core.strict_json import decode_evidence_json
from app.product_experiments.learning_analysis import (
    build_analysis,
    regression_focus,
    render_analysis_html,
    review_packet_for_analysis,
)
from app.product_experiments.learning_workflow import (
    WorkflowEvidence,
    json_bytes,
    load_evidence,
    plain_path,
    read_file,
)
from app.product_experiments.reliability_client import _lock as directory_lock
from app.product_experiments.trace_diagnostics import TraceBundle


def require_new_output(directory: Path) -> None:
    plain_path(directory)
    if directory.exists():
        raise ValueError("output_already_exists")


def analysis_contents(
    evidence: WorkflowEvidence,
    *,
    profile: str,
    traces: TraceBundle | None,
) -> dict[str, bytes]:
    report = build_analysis(evidence, profile=profile, traces=traces)
    packet = review_packet_for_analysis(report)
    template = [
        {
            "packet_hash": packet["packet_hash"],
            "item_id": item["item_id"],
            "reviewer_id": "REPLACE_WITH_REVIEWER_ID",
            "evidence_kind": "HUMAN_DECLARED",
            "label": None,
        }
        for item in packet["items"]
    ]
    return {
        "analysis.json": json_bytes(report),
        "report.html": render_analysis_html(report).encode("utf-8"),
        "review-packet.json": json_bytes(packet),
        "reviews-template.json": json_bytes(template),
        "regression-focus.json": json_bytes(regression_focus(report)),
    }


def write_learning_bundle(
    evidence: WorkflowEvidence,
    *,
    output_dir: Path,
    profile: str = "normalized_exact_v1",
    traces: TraceBundle | None = None,
) -> dict[str, Any]:
    allowed_source_names = {
        "manifest.json",
        "result.json",
        "report.json",
        "report.html",
        "baseline.json",
        "candidate.json",
        "dataset.json",
    }
    if (
        not isinstance(evidence.source_files, dict)
        or not set(evidence.source_files) <= allowed_source_names
    ):
        raise ValueError("workflow_unsafe_source_file_name")
    with directory_lock(output_dir):
        require_new_output(output_dir)
        contents = {f"source/{name}": payload for name, payload in evidence.source_files.items()}
        contents["config.json"] = json_bytes(
            {
                "schema_version": "evalops.learning-config/1.0",
                "profile": profile,
            }
        )
        contents.update(analysis_contents(evidence, profile=profile, traces=traces))
        if traces is not None:
            contents["traces.json"] = json_bytes(traces.model_dump(mode="json"))
        manifest = {
            "schema_version": "evalops.learning-bundle/1.0",
            "visibility": "PRIVATE",
            "formal_quality_claim_allowed": False,
            "production_ready": False,
            "files": {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
                for name, data in contents.items()
            },
        }
        contents["manifest.json"] = json_bytes(manifest)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".evalops-workflow-", dir=output_dir.parent) as root:
            staged = Path(root) / "bundle"
            for name, data in contents.items():
                path = staged / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            verified = verify_learning_bundle(staged)
            require_new_output(output_dir)
            staged.rename(output_dir)
        return verified


def verify_learning_bundle(directory: Path) -> dict[str, Any]:
    plain_path(directory)
    manifest = decode_evidence_json(read_file(directory / "manifest.json", 1024 * 1024))
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "visibility",
            "files",
            "formal_quality_claim_allowed",
            "production_ready",
        }
        or (
            manifest["schema_version"],
            manifest["visibility"],
            manifest["formal_quality_claim_allowed"],
            manifest["production_ready"],
        )
        != ("evalops.learning-bundle/1.0", "PRIVATE", False, False)
        or manifest["formal_quality_claim_allowed"] is not False
        or manifest["production_ready"] is not False
    ):
        raise ValueError("workflow_manifest_invalid")
    pins = manifest["files"]
    if not isinstance(pins, dict) or not 8 <= len(pins) <= 15:
        raise ValueError("workflow_file_set_invalid")
    actual: set[str] = set()
    for path in directory.iterdir():
        plain_path(path)
        if path.is_dir():
            if path.name != "source":
                raise ValueError("workflow_unknown_directory")
            for child in path.iterdir():
                plain_path(child)
                if not child.is_file() or len(actual) >= 16:
                    raise ValueError("workflow_file_set_invalid")
                actual.add(f"source/{child.name}")
        else:
            actual.add(path.name)
        if len(actual) > 16:
            raise ValueError("workflow_file_set_invalid")
    if actual != set(pins) | {"manifest.json"}:
        raise ValueError("workflow_file_set_mismatch")
    contents: dict[str, bytes] = {}
    total = 0
    for name, pin in pins.items():
        if "\\" in name or ".." in name or name.startswith("/") or ":" in name:
            raise ValueError("workflow_unsafe_file_name")
        data = read_file(directory / name)
        total += len(data)
        if total > 512 * 1024 * 1024:
            raise ValueError("workflow_bundle_size_limit")
        if pin != {"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}:
            raise ValueError("workflow_file_hash_mismatch")
        contents[name] = data
    required = {
        "config.json",
        "analysis.json",
        "report.html",
        "review-packet.json",
        "reviews-template.json",
        "regression-focus.json",
        "source/manifest.json",
        "source/dataset.json",
    }
    if not required <= set(contents):
        raise ValueError("workflow_file_set_mismatch")
    config = decode_evidence_json(contents["config.json"])
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "profile"}
        or (config["schema_version"] != "evalops.learning-config/1.0")
        or not isinstance(config["profile"], str)
    ):
        raise ValueError("workflow_config_invalid")
    evidence = load_evidence(directory / "source")
    traces = None
    if "traces.json" in contents:
        decode_evidence_json(contents["traces.json"])
        traces = TraceBundle.model_validate_json(contents["traces.json"])
    expected = analysis_contents(evidence, profile=config["profile"], traces=traces)
    permitted = (
        set(expected) | {"config.json"} | {f"source/{name}" for name in evidence.source_files}
    )
    if traces is not None:
        permitted.add("traces.json")
    if set(contents) != permitted:
        raise ValueError("workflow_file_set_mismatch")
    if any(contents[name] != data for name, data in expected.items()):
        raise ValueError("workflow_diagnostic_recomputation_mismatch")
    return {
        "status": "VERIFIED",
        "verification_scope": evidence.verification_scope,
        "diagnostics": "RECOMPUTED",
        "quality_status": evidence.result.status,
        "source_provenance_verified": False,
        "trace_provenance_verified": False,
        "human_review_status": "PENDING",
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
