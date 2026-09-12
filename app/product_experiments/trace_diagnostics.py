"""Bounded offline OTLP projections; reported spans never prove task success."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.strict_json import decode_evidence_json

MAX_TRACE_BYTES = 2 * 1024 * 1024
MAX_TRACE_SPANS = 2000
MAX_TRACE_ATTRIBUTES = 128
MAX_TRACE_DEPTH = 64

OPENINFERENCE_KINDS = {
    "LLM",
    "EMBEDDING",
    "CHAIN",
    "RETRIEVER",
    "RERANKER",
    "TOOL",
    "AGENT",
    "GUARDRAIL",
    "EVALUATOR",
    "PROMPT",
}
GEN_AI_KINDS = {
    "chat": "LLM",
    "text_completion": "LLM",
    "generate_content": "LLM",
    "embeddings": "EMBEDDING",
    "execute_tool": "TOOL",
    "retrieval": "RETRIEVER",
    "create_agent": "AGENT",
    "invoke_agent": "AGENT",
    "invoke_workflow": "CHAIN",
}


def _span_kind(attributes: dict[str, Any]) -> str:
    value = attributes.get("openinference.span.kind")
    if isinstance(value, str) and value in OPENINFERENCE_KINDS:
        return value
    operation = attributes.get("gen_ai.operation.name")
    return GEN_AI_KINDS.get(operation, "UNKNOWN") if isinstance(operation, str) else "UNKNOWN"


class TraceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    span_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    parent_span_id: str | None = Field(pattern=r"^[0-9a-f]{16}$")
    span_kind: str = Field(pattern="^(" + "|".join(sorted(OPENINFERENCE_KINDS)) + "|UNKNOWN)$")
    duration_ns: int = Field(ge=0, lt=2**64)
    status: Literal["UNSET", "OK", "ERROR"]

    @field_validator("trace_id", "span_id", "parent_span_id")
    @classmethod
    def nonzero_identifier(cls, value: str | None) -> str | None:
        if value is not None and int(value, 16) == 0:
            raise ValueError("invalid OTLP identifier")
        return value


class TraceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    spans: tuple[TraceSpan, ...] = Field(max_length=MAX_TRACE_SPANS)
    trust_level: Literal["REPORTED_TRACE_ONLY"] = "REPORTED_TRACE_ONLY"

    @model_validator(mode="after")
    def consistent_graph(self) -> TraceBundle:
        _validate_graph(list(self.spans))
        return self


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("OTLP message must be an object")
    return value


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("OTLP repeated field must be an array")
    return value


def _identity(value: Any, length: int) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value) is None
        or int(value, 16) == 0
    ):
        raise ValueError("invalid OTLP identifier")
    return value.lower()


def _timestamp(value: Any) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
        value = int(value)
    if type(value) is not int or not 0 <= value < 2**64:
        raise ValueError("invalid OTLP nanosecond timestamp")
    return value


def _enum(value: Any, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid OTLP numeric enum")
    return value


def _attributes(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    keys: set[str] = set()
    for raw in _array(value):
        item = _object(raw)
        key = item.get("key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("invalid or duplicate OTLP attribute key")
        keys.add(key)
        content = _object(item.get("value", {}))
        if key in {"openinference.span.kind", "gen_ai.operation.name"}:
            result[key] = content.get("stringValue")
    return result


def _project_span(value: Any) -> TraceSpan:
    raw = _object(value)
    start = _timestamp(raw.get("startTimeUnixNano"))
    end = _timestamp(raw.get("endTimeUnixNano"))
    if end < start:
        raise ValueError("OTLP span ends before it starts")
    parent = raw.get("parentSpanId", "")
    _enum(raw.get("kind", 0), 5)
    code = _enum(_object(raw.get("status", {})).get("code", 0), 2)
    return TraceSpan(
        trace_id=_identity(raw.get("traceId"), 32),
        span_id=_identity(raw.get("spanId"), 16),
        parent_span_id=None if parent == "" else _identity(parent, 16),
        span_kind=_span_kind(_attributes(raw.get("attributes", []))),
        duration_ns=end - start,
        status=("UNSET", "OK", "ERROR")[code],
    )


def _validate_graph(spans: list[TraceSpan]) -> None:
    identities = {(span.trace_id, span.span_id): span for span in spans}
    if len(identities) != len(spans):
        raise ValueError("duplicate OTLP span identifier in trace")
    for span in spans:
        seen: set[str] = set()
        current: TraceSpan | None = span
        while current is not None:
            if current.span_id in seen:
                raise ValueError("OTLP parent cycle")
            seen.add(current.span_id)
            if len(seen) > MAX_TRACE_DEPTH:
                raise ValueError("OTLP ancestry depth limit exceeded")
            current = (
                identities.get((span.trace_id, current.parent_span_id))
                if current.parent_span_id is not None
                else None
            )


def _check_attribute_bounds(document: dict[str, Any]) -> None:
    pending: list[Any] = [document]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "attributes" and len(_array(child)) > MAX_TRACE_ATTRIBUTES:
                    raise ValueError("OTLP attribute count limit exceeded")
                pending.append(child)
        elif isinstance(value, list):
            pending.extend(value)


def parse_otlp_traces(payload: bytes) -> TraceBundle:
    """Read one ExportTraceServiceRequest JSON document, retaining no content fields."""
    if not isinstance(payload, bytes):
        raise ValueError("OTLP input must be bytes")
    if len(payload) > MAX_TRACE_BYTES:
        raise ValueError("OTLP byte limit exceeded")
    document = _object(decode_evidence_json(payload))
    _check_attribute_bounds(document)
    spans: list[TraceSpan] = []
    for resource in _array(document.get("resourceSpans", [])):
        for scope in _array(_object(resource).get("scopeSpans", [])):
            for raw in _array(_object(scope).get("spans", [])):
                if len(spans) >= MAX_TRACE_SPANS:
                    raise ValueError("OTLP span count limit exceeded")
                spans.append(_project_span(raw))
    return TraceBundle(source_sha256=hashlib.sha256(payload).hexdigest(), spans=tuple(spans))


def summarize_trace(bundle: TraceBundle, trace_id: str) -> dict[str, Any]:
    """Describe the selected reported trace without inferring causes or completeness."""
    trace_id = _identity(trace_id, 32)
    spans = sorted(
        (span for span in bundle.spans if span.trace_id == trace_id), key=lambda span: span.span_id
    )
    identities = {span.span_id for span in spans}
    missing = sorted(
        {
            span.parent_span_id
            for span in spans
            if span.parent_span_id is not None and span.parent_span_id not in identities
        }
    )
    roots = [span.span_id for span in spans if span.parent_span_id is None]
    unknowns = ["trace_completeness_unproven", "task_success_not_inferred", "root_cause_unproven"]
    if not spans:
        unknowns.append("trace_not_in_export")
    if missing:
        unknowns.append("missing_parent_spans")
    if len(roots) > 1:
        unknowns.append("multiple_reported_roots")
    if any(span.span_kind == "UNKNOWN" for span in spans):
        unknowns.append("unrecognized_span_kind")
    if any(span.status == "UNSET" for span in spans):
        unknowns.append("unset_span_status")
    child_errors: dict[str, list[str]] = {}
    for span in spans:
        if span.status == "ERROR" and span.parent_span_id is not None:
            child_errors.setdefault(span.parent_span_id, []).append(span.span_id)
    return {
        "trace_id": trace_id,
        "source_sha256": bundle.source_sha256,
        "trust_level": bundle.trust_level,
        "evidence_status": "OBSERVED" if spans else "MISSING",
        "topology_status": "MISSING"
        if not spans
        else "PARTIAL"
        if missing
        else "NO_MISSING_PARENTS",
        "completeness": "UNPROVEN",
        "span_count": len(spans),
        "root_span_ids": roots,
        "missing_parent_ids": missing,
        "observed_error_span_ids": [span.span_id for span in spans if span.status == "ERROR"],
        "unknowns": unknowns,
        "spans": [
            {
                **span.model_dump(),
                "child_error_span_ids": child_errors.get(span.span_id, []),
            }
            for span in spans
        ],
    }
