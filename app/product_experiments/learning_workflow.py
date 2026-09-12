"""Explain existing experiments without changing their frozen quality gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.strict_json import decode_evidence_json
from app.external_harness.formal_quality import FormalQualityPolicy
from app.product_experiments.aggregation import (
    ProductAggregationContext,
    aggregate_product_observations,
)
from app.product_experiments.durable_bundle import verify_durable_bundle
from app.product_experiments.input_snapshot import ExperimentInputSnapshot
from app.product_experiments.report import render_experiment_html
from app.product_experiments.runner import (
    ExperimentCase,
    ProductExperimentResult,
    parse_product_dataset,
)
from app.product_experiments.spec import ExperimentSpec


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def plain_path(path: Path) -> None:
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise ValueError("workflow_link_not_allowed")


def read_file(path: Path, limit: int = 256 * 1024 * 1024) -> bytes:
    plain_path(path)
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("workflow_input_size_limit")
    return payload


@dataclass(frozen=True)
class WorkflowEvidence:
    result: ProductExperimentResult
    cases: list[ExperimentCase]
    raw_dataset: bytes
    verification_scope: str
    source_files: dict[str, bytes]


def load_evidence(directory: Path, *, dataset_path: Path | None = None) -> WorkflowEvidence:
    """Verify and recompute a local or durable private bundle; never execute a target."""
    from scripts.verify_product_experiment import verify_manifest

    plain_path(directory)
    manifest_payload = read_file(directory / "manifest.json", 1024 * 1024)
    manifest = decode_evidence_json(manifest_payload)
    if not isinstance(manifest, dict):
        raise ValueError("workflow_manifest_invalid")
    if manifest.get("schema_version") == "evalops.durable-bundle/1.0":
        verification = verify_durable_bundle(directory)
        if verification.verification_scope != "PRIVATE_RECOMPUTED":
            raise ValueError("private_source_required")
        source_files = {
            name: read_file(directory / name)
            for name in ("manifest.json", "report.json", "report.html", "dataset.json")
        }
        raw = source_files["dataset.json"]
        if dataset_path is not None and read_file(dataset_path, 10 * 1024 * 1024) != raw:
            raise ValueError("workflow_dataset_mismatch")
        report = decode_evidence_json(source_files["report.json"])
        result = ProductExperimentResult.model_validate_json(json_bytes(report["result"]))
        scope = "PRIVATE_RECOMPUTED"
    else:
        verify_manifest(directory / "manifest.json")
        if manifest.get("schema_version") not in {
            "evalops.product-experiment-manifest/2.0",
        }:
            raise ValueError("private_source_required")
        source_files = {
            entry["path"]: read_file(directory / entry["path"]) for entry in manifest["files"]
        }
        source_files["manifest.json"] = manifest_payload
        raw = read_file(dataset_path or directory / "dataset.json", 10 * 1024 * 1024)
        source_files["dataset.json"] = raw
        result = ProductExperimentResult.model_validate_json(source_files["result.json"])
        if source_files["report.html"] != render_experiment_html(
            result.model_dump(mode="json")
        ).encode("utf-8"):
            raise ValueError("workflow_source_html_mismatch")
        scope = "LOCAL_RECOMPUTED_NOT_PROVENANCE"
    cases = parse_product_dataset(raw, expected_sha256=result.dataset_sha256)
    if scope.startswith("LOCAL_"):
        _recompute_local(result, cases)
    return WorkflowEvidence(result, cases, raw, scope, source_files)


def _recompute_local(result: ProductExperimentResult, cases: list[ExperimentCase]) -> None:
    snapshot = ExperimentInputSnapshot.model_validate(result.input_snapshot)
    snapshot.validate_result_binding(result.model_dump(mode="json"))
    if result.status == "INPUT_REQUIRED":
        raise ValueError("workflow_execution_required")
    config = {
        **snapshot.configuration,
        "experiment_id": result.experiment_id,
        "policy_path": "not-read",
        "dataset": {"path": "not-read", "sha256": result.dataset_sha256},
    }
    spec = ExperimentSpec.model_validate_json(json_bytes(config))
    context = ProductAggregationContext(
        experiment_id=result.experiment_id,
        execution_id=result.execution_id,
        scope=result.scope,
        task_type=result.task_type,
        dataset_sha256=result.dataset_sha256,
        evalops_sha=result.evalops_sha,
        source_identities=result.source_identities,
        input_snapshot=result.input_snapshot,
        policy=FormalQualityPolicy.model_validate_json(json_bytes(snapshot.policy)),
        agent_comparison_policy=spec.agent_comparison_policy,
        citation_precision_min=spec.citation_precision_min,
        evaluator_names=spec.evaluators,
    )
    rebuilt = aggregate_product_observations(
        context=context,
        cases=cases,
        observations=result.observations,
        execution_errors=result.execution_errors,
        execution_schedule=result.execution_schedule,
        execution_events=result.execution_events,
    )
    if json_bytes(rebuilt.model_dump(mode="json")) != json_bytes(result.model_dump(mode="json")):
        raise ValueError("workflow_source_recomputation_mismatch")


def source_digest(evidence: WorkflowEvidence) -> str:
    return hashlib.sha256(
        json_bytes(
            {
                name: hashlib.sha256(payload).hexdigest()
                for name, payload in evidence.source_files.items()
            }
        )
    ).hexdigest()
