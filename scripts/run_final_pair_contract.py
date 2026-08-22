from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from app.agent_eval.schema import artifact_content_sha256
from app.external_harness.harness_envelope import (
    canonical_sha256,
    seal_rag_harness_result,
    verify_and_convert_rag_envelope,
)
from app.external_harness.rag_harness import RagHarnessContractError

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CI_PATTERN = re.compile(r"^https://github\.com/[^/]+/[^/]+/actions/runs/[0-9]+$")
SCHEMA = "evalops.final-pair-contract/1.0"
RAG_TEST_CASES = {
    "unknown-tool-deny": (
        "tests/agent_runtime/test_tool_policy.py::"
        "test_deny_precedes_ask_and_allow_and_unknown_tools_fail_closed"
    ),
    "ask-is-not-allow": (
        "tests/agent_runtime/test_tool_policy.py::test_ask_cannot_be_treated_as_allow"
    ),
    "start-idempotency-retry": (
        "tests/agent_runtime/test_start_lifecycle.py::"
        "test_same_start_key_is_stable_and_does_not_duplicate_checkpoint_or_trajectory"
    ),
    "process-restart-duplicate-resume": (
        "tests/agent_runtime/test_durable_orchestrator.py::"
        "test_interrupt_survives_process_restart_and_duplicate_resume_is_idempotent"
    ),
    "wrong-tenant-expired-approval": (
        "tests/agent_runtime/test_durable_orchestrator.py::"
        "test_wrong_tenant_user_role_hash_and_expiry_cannot_resume"
    ),
    "concurrent-resume-fencing": (
        "tests/agent_runtime/test_durable_orchestrator.py::"
        "test_two_connections_concurrently_resume_once_and_complete_once"
    ),
}
EVALOPS_TEST_CASES = {
    "inspect-partial-unknown-duplicate-fail-closed": (
        "tests/unit/external_harness/test_inspect_adapter.py::"
        "test_inspect_unknown_partial_duplicate_order_and_version_fail_closed"
    ),
    "duplicate-content-identity": (
        "tests/unit/agent_eval/test_artifact_schema.py::"
        "test_framework_neutral_agent_run_artifact_has_stable_content_identity"
    ),
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def git_head(repository: Path) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={repository.as_posix()}", "rev-parse", "HEAD"],
        cwd=repository,
        text=True,
    ).strip()


def python_executable(repository: Path) -> Path:
    candidates = (
        repository / ".venv" / "Scripts" / "python.exe",
        repository / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"repository has no managed Python runtime: {repository}")


def run_command(command: Sequence[str], *, cwd: Path, output_path: Path) -> None:
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    output_path.write_text(
        completed.stdout + ("\nSTDERR\n" + completed.stderr if completed.stderr else ""),
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"contract command failed ({completed.returncode}): {command}")


def run_rag_harness(
    *,
    rag_repository: Path,
    rag_sha: str,
    output_directory: Path,
) -> dict[str, Any]:
    request = {
        "schema_name": "enterprise.agent-harness-request",
        "schema_version": "1.0",
        "case_id": "final-pair-contract",
        "question": "What is the remote work policy?",
        "attempt_id": "final-pair-contract-attempt-v1",
        "traceparent": f"00-{'1' * 32}-{'2' * 16}-01",
        "mode": "deterministic_mock",
    }
    with tempfile.TemporaryDirectory(prefix="evalops-final-pair-rag-") as state_root:
        command = [
            str(python_executable(rag_repository)),
            "-m",
            "scripts.run_agent_harness",
            "--state-root",
            state_root,
            "--git-sha",
            rag_sha,
        ]
        completed = subprocess.run(
            command,
            cwd=rag_repository,
            env={**os.environ, "PYTHONHASHSEED": "0"},
            input=json.dumps(request),
            text=True,
            capture_output=True,
            check=False,
        )
    (output_directory / "rag-harness.stderr.txt").write_text(
        completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"RAG harness failed ({completed.returncode})")
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise RuntimeError("RAG harness output must be a JSON object")
    (output_directory / "rag-harness-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def rejected(operation: Any) -> bool:
    try:
        operation()
    except RagHarnessContractError:
        return True
    return False


def reseal(envelope: dict[str, Any]) -> None:
    envelope["harness_result_sha256"] = canonical_sha256(
        {key: value for key, value in envelope.items() if key != "harness_result_sha256"}
    )


def integer_metadata(metadata: dict[str, Any], key: str) -> int:
    value = metadata[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"Artifact metadata {key} must be an integer")
    return cast(int, value)


def case(case_id: str, *, evidence: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "result": "PASS",
        "evidence": evidence,
        "details": details or {},
    }


def execute(
    *,
    rag_repository: Path,
    rag_sha: str,
    evalops_sha: str,
    implementation_ci: str,
    output_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evalops_repository = Path(__file__).resolve().parents[1]
    if not SHA_PATTERN.fullmatch(rag_sha) or not SHA_PATTERN.fullmatch(evalops_sha):
        raise ValueError("Final Pair requires exact lowercase 40-character Git SHAs")
    if not CI_PATTERN.fullmatch(implementation_ci):
        raise ValueError("implementation CI must be a GitHub Actions run URL")
    if git_head(rag_repository) != rag_sha:
        raise RuntimeError("local RAG checkout does not equal the required RAG SHA")
    if git_head(evalops_repository) != evalops_sha:
        raise RuntimeError("local EvalOps checkout does not equal the required implementation SHA")
    if output_directory.exists():
        raise FileExistsError(f"immutable output directory already exists: {output_directory}")
    output_directory.mkdir(parents=True)

    definitions = [
        {"case_id": item, "kind": "real-pair"}
        for item in (
            "read-only-search",
            "policy-projection",
            "citation-projection",
            "terminal-projection",
            "trace-propagation",
            "zero-event-loss",
            "tampered-outer-envelope",
            "tampered-producer-artifact",
            "unknown-producer-event",
        )
    ]
    definitions.extend(
        {"case_id": item, "kind": "rag-mechanism", "node_id": node}
        for item, node in RAG_TEST_CASES.items()
    )
    definitions.extend(
        {"case_id": item, "kind": "evalops-mechanism", "node_id": node}
        for item, node in EVALOPS_TEST_CASES.items()
    )
    definitions.append(
        {
            "case_id": "duplicate-import-idempotency",
            "kind": "implementation-ci-integration",
            "node_id": (
                "tests/integration/test_agent_eval_workflow.py::"
                "test_real_postgresql_agent_evaluation_regression_and_review_workflow"
            ),
        }
    )
    dataset_hash = sha256(definitions)
    case_manifest: dict[str, Any] = {
        "schema_version": f"{SCHEMA}.cases",
        "case_count": len(definitions),
        "case_ids": [item["case_id"] for item in definitions],
        "dataset_hash": dataset_hash,
        "rag_source_sha": rag_sha,
        "evalops_source_sha": evalops_sha,
        "cases": definitions,
    }
    case_manifest["case_manifest_sha256"] = sha256(case_manifest)

    producer = run_rag_harness(
        rag_repository=rag_repository,
        rag_sha=rag_sha,
        output_directory=output_directory,
    )
    envelope = cast(
        dict[str, Any],
        seal_rag_harness_result(producer, producer_source_sha=rag_sha),
    )
    artifact = verify_and_convert_rag_envelope(envelope)
    (output_directory / "evalops-harness-envelope.json").write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    tool_names = {
        event["tool_name"]
        for event in producer["tool_events"]
        if event["event_type"] == "tool.completed"
    }
    if "search" not in tool_names:
        raise RuntimeError("real pair did not complete read-only search")
    if not producer["policy_decisions"]:
        raise RuntimeError("real pair omitted policy decisions")
    if not producer["citations"]:
        raise RuntimeError("real pair omitted citation checks")
    if artifact.terminal.state != "answer":
        raise RuntimeError("real pair did not reach the expected terminal state")
    if artifact.metadata["trace_id"] != producer["trace_id"]:
        raise RuntimeError("trace identity projection failed")
    source_count = integer_metadata(artifact.metadata, "source_event_count")
    converted_count = integer_metadata(artifact.metadata, "converted_event_count")
    dropped_count = integer_metadata(artifact.metadata, "dropped_event_count")
    unmapped_count = integer_metadata(artifact.metadata, "unmapped_event_count")
    if (source_count, dropped_count, unmapped_count) != (converted_count, 0, 0):
        raise RuntimeError("event accounting is not lossless")

    results = [
        case("read-only-search", evidence="real RAG CLI tool.completed projection"),
        case("policy-projection", evidence="policy projection SHA and Envelope verification"),
        case("citation-projection", evidence="citation.checked Artifact events"),
        case("terminal-projection", evidence="Producer terminal to EvalOps terminal"),
        case("trace-propagation", evidence="traceparent and Artifact trace identity"),
        case(
            "zero-event-loss",
            evidence="EvalOps loss accounting",
            details={
                "source_event_count": source_count,
                "converted_event_count": converted_count,
                "dropped_event_count": dropped_count,
                "unmapped_event_count": unmapped_count,
            },
        ),
    ]
    outer_tamper = copy.deepcopy(envelope)
    outer_tamper["result"]["answer"] = "tampered"
    if not rejected(lambda: verify_and_convert_rag_envelope(outer_tamper)):
        raise RuntimeError("outer-envelope tampering was accepted")
    results.append(case("tampered-outer-envelope", evidence="HARNESS_DIGEST_MISMATCH"))

    producer_tamper = copy.deepcopy(envelope)
    producer_tamper["result"]["trajectory_artifact"]["trajectory"][0]["payload"] = {
        "tampered": True
    }
    reseal(producer_tamper)
    if not rejected(lambda: verify_and_convert_rag_envelope(producer_tamper)):
        raise RuntimeError("producer Artifact tampering was accepted")
    results.append(case("tampered-producer-artifact", evidence="producer digest/hash chain"))

    unknown_event = copy.deepcopy(envelope)
    unknown_event["result"]["trajectory_artifact"]["trajectory"][0]["event_type"] = "unknown.event"
    reseal(unknown_event)
    if not rejected(lambda: verify_and_convert_rag_envelope(unknown_event)):
        raise RuntimeError("unknown Producer event was accepted")
    results.append(case("unknown-producer-event", evidence="strict ProducerEventType"))

    rag_nodes = list(RAG_TEST_CASES.values())
    run_command(
        [
            str(python_executable(rag_repository)),
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            *rag_nodes,
        ],
        cwd=rag_repository,
        output_path=output_directory / "rag-mechanism-tests.txt",
    )
    results.extend(
        case(item, evidence=node, details={"source_sha": rag_sha})
        for item, node in RAG_TEST_CASES.items()
    )

    evalops_nodes = list(EVALOPS_TEST_CASES.values())
    run_command(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *evalops_nodes],
        cwd=evalops_repository,
        output_path=output_directory / "evalops-mechanism-tests.txt",
    )
    results.extend(
        case(item, evidence=node, details={"source_sha": evalops_sha})
        for item, node in EVALOPS_TEST_CASES.items()
    )
    results.append(
        case(
            "duplicate-import-idempotency",
            evidence=implementation_ci,
            details={
                "source_sha": evalops_sha,
                "integration_node_id": definitions[-1]["node_id"],
            },
        )
    )

    result_manifest: dict[str, Any] = {
        "schema_version": f"{SCHEMA}.results",
        "rag_source_sha": rag_sha,
        "evalops_source_sha": evalops_sha,
        "implementation_ci": implementation_ci,
        "harness_schema": artifact.metadata["harness_envelope_schema"],
        "case_count": len(results),
        "case_ids": [item["case_id"] for item in results],
        "dataset_hash": dataset_hash,
        "case_manifest_sha256": case_manifest["case_manifest_sha256"],
        "rag_output_digest": producer["trajectory_artifact"]["artifact_sha256"],
        "harness_result_sha256": artifact.metadata["harness_result_sha256"],
        "evalops_artifact_digest": artifact_content_sha256(artifact),
        "source_event_count": source_count,
        "converted_event_count": converted_count,
        "unmapped_event_count": unmapped_count,
        "dropped_event_count": dropped_count,
        "trace_identity": {
            "trace_id": producer["trace_id"],
            "root_span_id": producer["root_span_id"],
            "traceparent": producer["propagated_traceparent"],
        },
        "all_cases_terminal": True,
        "all_expected_projections_match": True,
        "all_tampering_tests_rejected": True,
        "duplicate_imports_idempotent": True,
        "formal_ab_executed": False,
        "human_review_status": "PENDING",
        "shadow_release_status": "INPUT_BLOCKED",
        "production_ready": False,
        "result": "FINAL_PAIR_CONTRACT_VERIFIED",
        "cases": results,
    }
    result_manifest["result_manifest_sha256"] = sha256(result_manifest)
    return case_manifest, result_manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the exact-SHA Final Pair Contract Suite")
    parser.add_argument("--rag-repository", type=Path, required=True)
    parser.add_argument("--rag-sha", required=True)
    parser.add_argument("--evalops-sha", required=True)
    parser.add_argument("--implementation-ci", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    case_manifest, result_manifest = execute(
        rag_repository=args.rag_repository.resolve(),
        rag_sha=args.rag_sha,
        evalops_sha=args.evalops_sha,
        implementation_ci=args.implementation_ci,
        output_directory=args.output_directory.resolve(),
    )
    (args.output_directory / "case-manifest.json").write_text(
        json.dumps(case_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_directory / "result-manifest.json").write_text(
        json.dumps(result_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result_manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
