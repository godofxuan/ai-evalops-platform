"""Local-only, single-attempt experiment ledger; no API keys or model downloads."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.strict_json import decode_evidence_json

OLLAMA = "http://127.0.0.1:11434"
MAX_BYTES = 64 * 1024 * 1024
APPROVED_LOCAL_MODELS = ("qwen2.5:3b", "qwen3.5:4b", "qwen3:8b", "gemma4:e2b-it-qat")


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2).encode()


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid_or_oversized_evidence_file")
    return decode_evidence_json(path.read_bytes())


def save_new(path: Path, value: object) -> None:
    """Exclusive create and fsync: an earlier attempt is never overwritten."""
    payload = encoded(value)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def inventory(client: httpx.Client) -> dict[str, Any]:
    version = client.get(OLLAMA + "/api/version").raise_for_status().json()
    models = client.get(OLLAMA + "/api/tags").raise_for_status().json()["models"]
    return {"ollama_version": version["version"], "models": models}


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("schema_version") != "evalops.local-public-pilot/1.0":
        raise ValueError("invalid_plan_schema")
    if plan.get("plan_sha256") != digest({k: v for k, v in plan.items() if k != "plan_sha256"}):
        raise ValueError("plan_hash_mismatch")
    rows = plan["requests"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1500:
        raise ValueError("invalid_request_count")
    seen = set()
    for row in rows:
        identity = row["request_id"]
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("invalid_request_id")
        if identity in seen or identity != digest(
            {k: v for k, v in row.items() if k != "request_id"}
        ):
            raise ValueError("duplicate_or_modified_request")
        seen.add(identity)
        request = row["request"]
        if request["model"] != row["model"] or request.get("stream") is not False:
            raise ValueError("request_identity_mismatch")
        if set(request) - {
            "model",
            "messages",
            "stream",
            "options",
            "format",
            "think",
            "keep_alive",
        }:
            raise ValueError("unsupported_request_fields")
        if request["model"] not in APPROVED_LOCAL_MODELS:
            raise ValueError("unapproved_local_model")
        if not re.fullmatch(r"[0-9a-f]{64}", row["model_digest"]):
            raise ValueError("model_digest_required")
        if type(row["context_byte_budget"]) is not int or row["context_byte_budget"] <= 0:
            raise ValueError("context_budget_required")


def write_plan(output: Path, *, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema_version": "evalops.local-public-pilot/1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "metadata": metadata,
        "requests": [{**row, "request_id": digest(row)} for row in rows],
        "scope": "LOCAL_PUBLIC_SUBSET_NOT_OFFICIAL_LEADERBOARD",
        "formal_quality_claim_allowed": False,
        "production_ready": False,
    }
    plan["plan_sha256"] = digest(plan)
    validate_plan(plan)
    path = output / "plan.json"
    save_new(path, plan)
    return path


def _response_status(raw: dict[str, Any], model: str) -> str:
    if raw.get("model") != model:
        return "MODEL_IDENTITY_MISMATCH"
    if raw.get("done") is not True:
        return "INCOMPLETE_RESPONSE"
    if raw.get("done_reason") == "length":
        return "OUTPUT_LIMIT"
    message = raw.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        return "INVALID_RESPONSE"
    return "RESPONDED"


def execute_plan(
    plan_path: Path,
    output: Path,
    *,
    max_new_calls: int | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Resume only requests with no intent. Unknown/incomplete intents are NOT retried."""
    plan = read_json(plan_path)
    validate_plan(plan)
    if max_new_calls is not None and max_new_calls < 1:
        raise ValueError("positive_max_new_calls_required")
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError("symlink_output_not_allowed")
    lock = output / ".run.lock"
    with lock.open("xb"):
        pass
    owned = client is None
    connection = client or httpx.Client(timeout=120.0, trust_env=False, follow_redirects=False)
    try:
        frozen = output / "plan.json"
        if frozen.exists():
            if read_json(frozen) != plan:
                raise ValueError("different_plan_in_output")
        else:
            if set(output.iterdir()) != {lock}:
                raise ValueError("output_not_empty")
            save_new(frozen, plan)
        attempts = output / "attempts"
        attempts.mkdir(exist_ok=True)
        if attempts.is_symlink():
            raise ValueError("symlink_attempts_not_allowed")
        # Existing bytes must be valid before even read-only inventory requests.
        # Unknown intents remain unknown, but are never reissued below.
        verify_run(output)
        current = inventory(connection)
        available = {row["name"]: row["digest"] for row in current["models"]}
        inventory_rows = {row["name"]: row for row in current["models"]}
        for row in plan["requests"]:
            if available.get(row["model"]) != row["model_digest"]:
                raise ValueError("installed_model_digest_changed")
            model_entry = inventory_rows[row["model"]]
            if model_entry.get("remote_model") or model_entry.get("remote_host"):
                raise ValueError("remote_model_not_allowed")
        calls = 0
        skipped_existing = 0
        for row in plan["requests"]:
            identity = row["request_id"]
            intent_path = attempts / (identity + ".intent.json")
            receipt_path = attempts / (identity + ".result.json")
            if intent_path.exists():
                skipped_existing += 1
                continue
            if receipt_path.exists():
                raise ValueError("result_without_intent")
            if max_new_calls is not None and calls >= max_new_calls:
                break
            request = row["request"]
            # UTF-8 byte bound is conservative relative to tokenizer pieces. Leave
            # separate room for template, generation, and tokenization overhead.
            content_bytes = len(encoded(request["messages"]))
            intent = {
                "plan_sha256": plan["plan_sha256"],
                "request_id": identity,
                "request_sha256": digest(request),
                "started_at": datetime.now(UTC).isoformat(),
                "model_digest_checked": row["model_digest"],
                "ollama_version": current["ollama_version"],
            }
            save_new(intent_path, intent)
            raw: dict[str, Any] | None = None
            error_type: str | None = None
            http_status_code: int | None = None
            started = time.perf_counter()
            status = "CONTEXT_BLOCKED"
            called = False
            if content_bytes <= row["context_byte_budget"]:
                called = True
                calls += 1
                try:
                    with connection.stream("POST", OLLAMA + "/api/chat", json=request) as response:
                        response.raise_for_status()
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body.extend(chunk)
                            if len(body) > 4 * 1024 * 1024:
                                raise ValueError("response_byte_limit")
                        decoded = decode_evidence_json(bytes(body))
                        if not isinstance(decoded, dict):
                            raise ValueError("response_not_object")
                        raw = decoded
                    status = _response_status(raw, row["model"])
                except (httpx.HTTPError, ValueError, KeyError) as error:
                    status = "REQUEST_FAILED"
                    error_type = type(error).__name__
                    if isinstance(error, httpx.HTTPStatusError):
                        # Preserve only the status, not headers, URL or error body.
                        http_status_code = error.response.status_code
            result = {
                **intent,
                "finished_at": datetime.now(UTC).isoformat(),
                "benchmark": row["benchmark"],
                "case_id": row["case_id"],
                "model": row["model"],
                "status": status,
                "called": called,
                "wall_seconds": time.perf_counter() - started,
                "error_type": error_type,
                "http_status_code": http_status_code,
                "response": raw,
            }
            result["result_sha256"] = digest(result)
            save_new(receipt_path, result)
            print(
                json.dumps(
                    {
                        "case": row["case_id"],
                        "model": row["model"],
                        "status": status,
                        "seconds": round(result["wall_seconds"], 2),
                    }
                ),
                flush=True,
            )
        return {
            "new_target_calls": calls,
            "existing_intents_not_retried": skipped_existing,
            **verify_run(output),
        }
    finally:
        if owned:
            connection.close()
        lock.unlink(missing_ok=True)


def verify_run(output: Path) -> dict[str, Any]:
    """Recompute evidence identities and coverage offline, without contacting Ollama."""
    plan = read_json(output / "plan.json")
    validate_plan(plan)
    expected = {row["request_id"]: row for row in plan["requests"]}
    counts: dict[str, int] = {}
    calls = 0
    attempts = output / "attempts"
    allowed = {
        identity + suffix for identity in expected for suffix in (".intent.json", ".result.json")
    }
    if attempts.is_symlink() or not attempts.is_dir():
        raise ValueError("invalid_attempt_directory")
    if {path.name for path in attempts.iterdir()} - allowed:
        raise ValueError("unexpected_attempt_files")
    for identity, row in expected.items():
        intent_path = attempts / (identity + ".intent.json")
        receipt_path = attempts / (identity + ".result.json")
        if not intent_path.exists():
            if receipt_path.exists():
                raise ValueError("result_without_intent")
            status = "NOT_ATTEMPTED"
        else:
            intent = read_json(intent_path)
            if intent["plan_sha256"] != plan["plan_sha256"] or intent["request_id"] != identity:
                raise ValueError("intent_identity_mismatch")
            if intent["request_sha256"] != digest(row["request"]):
                raise ValueError("request_hash_mismatch")
            if intent["model_digest_checked"] != row["model_digest"]:
                raise ValueError("intent_model_mismatch")
            status = "ATTEMPT_OUTCOME_UNKNOWN"
            if receipt_path.exists():
                result = read_json(receipt_path)
                if result["result_sha256"] != digest(
                    {k: v for k, v in result.items() if k != "result_sha256"}
                ):
                    raise ValueError("result_hash_mismatch")
                if any(result.get(key) != value for key, value in intent.items()):
                    raise ValueError("result_intent_mismatch")
                if any(result.get(key) != row[key] for key in ("model", "case_id", "benchmark")):
                    raise ValueError("result_case_mismatch")
                if (
                    type(result["wall_seconds"]) not in (int, float)
                    or not math.isfinite(result["wall_seconds"])
                    or result["wall_seconds"] < 0
                ):
                    raise ValueError("invalid_wall_time")
                status = result["status"]
                http_status_code = result.get("http_status_code")
                if http_status_code is not None and (
                    type(http_status_code) is not int
                    or not 300 <= http_status_code <= 599
                    or status != "REQUEST_FAILED"
                    or result.get("error_type") != "HTTPStatusError"
                    or result["response"] is not None
                ):
                    raise ValueError("http_status_contract_mismatch")
                context_blocked = (
                    len(encoded(row["request"]["messages"])) > row["context_byte_budget"]
                )
                if (status == "CONTEXT_BLOCKED") != context_blocked:
                    raise ValueError("context_status_mismatch")
                if result["response"] is not None and status != _response_status(
                    result["response"], row["model"]
                ):
                    raise ValueError("response_status_mismatch")
                if status == "RESPONDED" and result["response"] is None:
                    raise ValueError("missing_success_response")
                if status not in {
                    "RESPONDED",
                    "MODEL_IDENTITY_MISMATCH",
                    "INCOMPLETE_RESPONSE",
                    "OUTPUT_LIMIT",
                    "INVALID_RESPONSE",
                    "CONTEXT_BLOCKED",
                    "REQUEST_FAILED",
                }:
                    raise ValueError("unknown_status")
                if type(result["called"]) is not bool or result["called"] is not (
                    status != "CONTEXT_BLOCKED"
                ):
                    raise ValueError("called_status_mismatch")
                calls += int(result["called"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "verification": "LOCAL_BYTES_AND_CONTRACT_NOT_PROVENANCE_AUTHENTICATION",
        "planned": len(expected),
        "recorded_target_calls": calls,
        "statuses": counts,
        "complete": not any(
            counts.get(key, 0) for key in ("NOT_ATTEMPTED", "ATTEMPT_OUTCOME_UNKNOWN")
        ),
        "formal_quality_claim_allowed": False,
    }
