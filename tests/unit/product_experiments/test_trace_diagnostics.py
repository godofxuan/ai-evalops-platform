import base64
import hashlib
import json
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from google.protobuf.json_format import MessageToDict
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from app.product_experiments.trace_diagnostics import (
    TraceBundle,
    parse_otlp_traces,
    summarize_trace,
)

TRACE = "a" * 32
ROOT = "b" * 16
CHILD = "c" * 16


def span(span_id: str = ROOT, **updates: object) -> dict[str, object]:
    return {
        "traceId": TRACE,
        "spanId": span_id,
        "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": "1002000000",
        "attributes": [{"key": "openinference.span.kind", "value": {"stringValue": "LLM"}}],
        "status": {"code": 1},
        **updates,
    }


def payload(*spans: dict[str, object]) -> bytes:
    return json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}).encode()


def test_structural_summary_reports_child_error_without_claiming_task_success() -> None:
    source = payload(span(), span(CHILD, parentSpanId=ROOT, status={"code": 2}))
    bundle = parse_otlp_traces(source)
    summary = summarize_trace(bundle, TRACE)
    assert bundle.source_sha256 == hashlib.sha256(source).hexdigest()
    assert summary["trust_level"] == "REPORTED_TRACE_ONLY"
    assert summary["evidence_status"] == "OBSERVED"
    assert summary["completeness"] == "UNPROVEN"
    assert summary["topology_status"] == "NO_MISSING_PARENTS"
    assert summary["span_count"] == 2
    assert summary["observed_error_span_ids"] == [CHILD]
    assert summary["spans"][0]["child_error_span_ids"] == [CHILD]
    assert summary["spans"][0]["duration_ns"] == 2_000_000
    assert summary["spans"][0]["span_kind"] == "LLM"
    assert "task_success" not in summary


def test_real_locked_sdk_exporter_shape_is_projected_without_sensitive_content() -> None:
    lock = tomllib.loads((Path(__file__).parents[3] / "uv.lock").read_text(encoding="utf-8"))
    for dependency in ("opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-http", "protobuf"):
        locked = next(item["version"] for item in lock["package"] if item["name"] == dependency)
        assert version(dependency) == locked
    secret = "sensitive-content-sentinel"
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource({"service.name": secret}), shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(secret)
    with tracer.start_as_current_span(secret) as root:
        root.set_attribute("openinference.span.kind", "CHAIN")
        with tracer.start_as_current_span(secret) as child:
            child.set_attribute("gen_ai.operation.name", "execute_tool")
            child.set_attribute("input.value", secret)
            child.set_attribute("output.value", secret)
            child.set_attribute("http.request.header.authorization", secret)
            child.set_attribute("tool_call.function.arguments", secret)
            child.add_event(secret, {"exception.message": secret})
            child.set_status(Status(StatusCode.ERROR, secret))
    message = encode_spans(exporter.get_finished_spans())
    document = MessageToDict(message, use_integers_for_enums=True)
    # Protobuf JSON differs from OTLP JSON only in these ID byte encodings.
    for resource in document["resourceSpans"]:
        for scope in resource["scopeSpans"]:
            for exported in scope["spans"]:
                for field in ("traceId", "spanId", "parentSpanId"):
                    if field in exported:
                        exported[field] = base64.b64decode(exported[field]).hex()
    source = json.dumps(document).encode()
    assert secret in source.decode()
    bundle = parse_otlp_traces(source)
    summary = summarize_trace(bundle, f"{root.get_span_context().trace_id:032x}")
    provider.shutdown()
    assert summary["span_count"] == 2
    assert len(summary["observed_error_span_ids"]) == 1
    assert {item["span_kind"] for item in summary["spans"]} == {"CHAIN", "TOOL"}
    assert secret not in bundle.model_dump_json()
    assert secret not in json.dumps(summary)


@pytest.mark.parametrize(
    "updates",
    [
        {"traceId": "0" * 32},
        {"traceId": "not-a-trace"},
        {"traceId": 123},
        {"spanId": "0" * 16},
        {"spanId": "g" * 16},
        {"spanId": "a" * 32},
        {"parentSpanId": "0" * 16},
        {"parentSpanId": False},
        {"startTimeUnixNano": "-1"},
        {"startTimeUnixNano": 1.5},
        {"startTimeUnixNano": True},
        {"startTimeUnixNano": "1e9"},
        {"endTimeUnixNano": str(2**64)},
        {"endTimeUnixNano": "1"},
        {"status": {"code": "STATUS_CODE_ERROR"}},
        {"status": {"code": True}},
        {"status": {"code": 3}},
        {"status": []},
        {"kind": "SPAN_KIND_INTERNAL"},
        {"kind": True},
        {"kind": 6},
        {"attributes": {}},
        {"attributes": [{"key": "x", "value": "bad"}]},
        {"attributes": [{"key": "x", "value": {}}, {"key": "x", "value": {}}]},
    ],
)
def test_malformed_span_structure_is_rejected_without_echoing_input(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValueError) as error:
        parse_otlp_traces(payload(span(**updates)))
    assert "not-a-trace" not in str(error.value)


def test_uppercase_ids_integer_timestamps_empty_parent_and_unset_status_are_supported() -> None:
    record = span(
        traceId=TRACE.upper(),
        spanId=ROOT.upper(),
        parentSpanId="",
        startTimeUnixNano=1_000_000_000,
        endTimeUnixNano=1_002_000_000,
    )
    del record["status"]
    bundle = parse_otlp_traces(payload(record))
    assert bundle.spans[0].parent_span_id is None
    assert bundle.spans[0].status == "UNSET"
    assert bundle.spans[0].trace_id == TRACE


@pytest.mark.parametrize(
    "records",
    [
        [span(), span()],
        [span(), span(spanId=ROOT.upper())],
        [span(parentSpanId=ROOT)],
        [span(parentSpanId=CHILD), span(CHILD, parentSpanId=ROOT)],
    ],
)
def test_duplicate_ids_and_parent_cycles_are_rejected(records: list[dict[str, object]]) -> None:
    with pytest.raises(ValueError, match="duplicate|cycle"):
        parse_otlp_traces(payload(*records))


def test_missing_parent_is_partial_and_never_binds_to_another_trace() -> None:
    bundle = parse_otlp_traces(
        payload(
            span(CHILD, parentSpanId=ROOT, attributes=[]),
            span(traceId="d" * 32, status={"code": 2}),
        )
    )
    summary = summarize_trace(bundle, TRACE)
    assert summary["topology_status"] == "PARTIAL"
    assert summary["missing_parent_ids"] == [ROOT]
    assert summary["observed_error_span_ids"] == []
    assert summary["root_span_ids"] == []
    assert "missing_parent_spans" in summary["unknowns"]
    assert "unrecognized_span_kind" in summary["unknowns"]


def test_absent_trace_remains_missing_even_when_another_trace_has_ok_spans() -> None:
    bundle = parse_otlp_traces(payload(span()))
    summary = summarize_trace(bundle, "d" * 32)
    assert summary["evidence_status"] == "MISSING"
    assert summary["topology_status"] == "MISSING"
    assert summary["span_count"] == 0
    assert summary["spans"] == []
    assert "trace_not_in_export" in summary["unknowns"]
    with pytest.raises(ValueError, match="identifier"):
        summarize_trace(bundle, "unsafe-sensitive-identifier")


@pytest.mark.parametrize(
    "source",
    [
        b" " * (2 * 1024 * 1024 + 1),
        payload(*(span(f"{index + 1:016x}") for index in range(2001))),
        payload(span(attributes=[{"key": f"k{index}", "value": {}} for index in range(129)])),
        json.dumps(
            {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": [
                                {"key": f"k{index}", "value": {}} for index in range(129)
                            ]
                        }
                    }
                ]
            }
        ).encode(),
        payload(
            *(
                span(f"{index + 1:016x}", parentSpanId=f"{index:016x}" if index else "")
                for index in range(65)
            )
        ),
    ],
    ids=["bytes", "spans", "span-attributes", "resource-attributes", "ancestry-depth"],
)
def test_oversized_trace_evidence_is_rejected(source: bytes) -> None:
    with pytest.raises(ValueError, match="limit"):
        parse_otlp_traces(source)


@pytest.mark.parametrize(
    "updates",
    [
        {"trace_id": "0" * 32},
        {"span_id": "not-an-id"},
        {"parent_span_id": "0" * 16},
        {"duration_ns": -1},
        {"duration_ns": 2**64},
        {"span_kind": "sensitive-arbitrary-text"},
        {"status": "SUCCESS"},
        {"parent_span_id": ROOT},
        {"trace_id": TRACE.upper()},
    ],
)
def test_reloaded_projection_revalidates_span_contract(updates: dict[str, object]) -> None:
    document = parse_otlp_traces(payload(span())).model_dump(mode="json")
    document["spans"][0].update(updates)
    with pytest.raises(ValueError):
        TraceBundle.model_validate_json(json.dumps(document))


@pytest.mark.parametrize(
    "source",
    [
        b'{"resourceSpans": [], "resourceSpans": []}',
        b'{"futureField": NaN}',
        b'{"futureField": Infinity}',
        b'{"futureField": 1e999}',
        b"\xff",
        b"[]",
        b'{"futureField":' + b"[" * 65 + b"0" + b"]" * 65 + b"}",
        b'{"resourceSpans": {}}',
        b'{"resourceSpans": [null]}',
        b'{"resourceSpans": [{"scopeSpans": null}]}',
        b'{"resourceSpans": [{"scopeSpans": [{"spans": null}]}]}',
    ],
)
def test_strict_json_and_envelope_validation_are_applied(source: bytes) -> None:
    with pytest.raises(ValueError):
        parse_otlp_traces(source)


def test_empty_and_future_export_fields_remain_missing_not_successful() -> None:
    for source in (b"{}", b'{"resourceSpans": []}', b'{"futureField": {"nested": [1]}}'):
        summary = summarize_trace(parse_otlp_traces(source), TRACE)
        assert summary["evidence_status"] == "MISSING"
        assert summary["completeness"] == "UNPROVEN"


def test_unknown_semantic_kind_is_not_echoed_and_root_cause_stays_unproven() -> None:
    secret = "arbitrary-sensitive-kind"
    bundle = parse_otlp_traces(
        payload(
            span(
                attributes=[
                    {"key": "openinference.span.kind", "value": {"stringValue": secret}},
                ]
            )
        )
    )
    summary = summarize_trace(bundle, TRACE)
    assert summary["spans"][0]["span_kind"] == "UNKNOWN"
    assert "root_cause_unproven" in summary["unknowns"]
    assert secret not in bundle.model_dump_json()
    assert secret not in json.dumps(summary)


def test_reloaded_projection_revalidates_hash_graph_bounds_and_preserves_safe_roundtrip() -> None:
    bundle = parse_otlp_traces(payload(span()))
    assert TraceBundle.model_validate_json(bundle.model_dump_json()) == bundle
    document = bundle.model_dump(mode="json")
    document["source_sha256"] = "not-a-hash"
    with pytest.raises(ValueError):
        TraceBundle.model_validate_json(json.dumps(document))
    document = bundle.model_dump(mode="json")
    document["spans"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        TraceBundle.model_validate_json(json.dumps(document))
    document["spans"] = [
        {**document["spans"][0], "span_id": f"{index + 1:016x}"} for index in range(2001)
    ]
    with pytest.raises(ValueError):
        TraceBundle.model_validate_json(json.dumps(document))
