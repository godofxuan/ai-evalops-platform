# Offline trace diagnostics adapter

## Public interface and scope

- `parse_otlp_traces(payload: bytes) -> TraceBundle`: frozen structural projection,
  `source_sha256`, `spans`, and `trust_level = REPORTED_TRACE_ONLY`.
- `summarize_trace(bundle, trace_id: str) -> dict`: exact normalized trace-ID selection;
  `evidence_status`, `topology_status`, `completeness = UNPROVEN`, counts,
  observed error IDs, missing parents, unknowns, and allowlisted span records.
  Each span additionally lists direct `child_error_span_ids`; errors are not
  propagated into parent status. Output spans are ordered by span ID, not time.
- `TraceSpan`: trace/span/parent ID, normalized `span_kind`, `duration_ns`, status.
- Malformed or over-budget inputs raise `ValueError` without copying payload data
  into the error message. Raw names, prompts, answers, tool arguments, resource
  metadata, events, headers, and status messages are never retained in the models.

## Standards checked

[OTLP JSON encoding](https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding)
requires lowerCamelCase fields, hex IDs instead of generic protobuf base64 IDs,
and numeric enums. Timestamps are emitted as decimal strings; decoders accept
integer numbers too. Unknown fields are ignored, within local resource budgets.
[OpenInference semantic conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)
specify `openinference.span.kind` and an enumerated set of operation kinds.

The SDK compatibility test will create real in-memory SDK spans, invoke the
installed OTLP protobuf encoder, and serialize with protobuf `MessageToDict`.
Generic protobuf JSON's base64 IDs require explicit hex conversion to satisfy
the OTLP JSON deviation. This is an offline file adapter, not an OTLP receiver.

[OpenTelemetry GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md)
confirm `gen_ai.operation.name`. The local allowlist maps chat, text completion,
and content generation to LLM; embeddings to EMBEDDING; execute_tool to TOOL;
retrieval to RETRIEVER; create_agent/invoke_agent to AGENT; invoke_workflow to
CHAIN. An allowlisted OpenInference kind takes precedence. Other values become
UNKNOWN and their raw strings are discarded.

## Accepted bounded profile

- One UTF-8 JSON ExportTraceServiceRequest with `resourceSpans` /
  `scopeSpans` / `spans`, up to 2 MiB and 2,000 spans. Empty envelopes are valid
  but supply no trace evidence.
- Maximum 128 entries in each attributes array (including ignored resource,
  scope, and event attributes); JSON nesting and span ancestry are each bounded
  at 64. Ignored fields still count against input budgets.
- Nonzero 32-hex trace IDs and 16-hex span IDs; optional parent IDs are empty
  or nonzero 16-hex. IDs normalize to lowercase. Both start/end timestamps must
  be present, unsigned 64-bit integer numbers or decimal strings, end >= start.
- Numeric OTLP kind 0-5 and status 0-2 only; omitted status means UNSET.
  Duplicate attribute keys, duplicate per-trace span IDs, parent cycles, invalid
  envelope shapes, duplicate JSON keys, nonfinite JSON, and over-budget input
  are rejected. Missing parents are not rejected: topology is PARTIAL.
- This deliberately bounded projection is not a general OTLP schema validator
  or collector. Binary protobuf, gzip, JSONL, raw SDK JSON, and arbitrary vendor
  trace shapes are not accepted; ignored payload content is not interpreted.

## Evidence boundary

Reported span errors are observations, not root-cause findings or task success.
Even a root with all its reported parents present cannot prove trace completeness.
Missing parents are visible as partial topology; absent trace IDs stay missing.
Metrics do not cause inferred retrieval/tool faults.

The source hash links the original imported bytes; it is not a signature or
authenticated provenance. When only the sanitized projection is saved, the
original source hash cannot be independently recomputed without the raw file.
Frozen projection models revalidate hashes, normalized IDs, kinds, statuses,
durations, span limits, duplicate identities, cycles, and ancestry on reload.
Callers must still apply `decode_evidence_json` and a byte limit before loading
untrusted saved JSON: Pydantic's JSON parser alone allows duplicate keys.

## Validation log

Witnessed vertical red/green iterations covered the initial structural summary,
real SDK GenAI mapping, core span field validation, duplicate/cyclic graphs,
missing trace/parent evidence, resource budgets, and saved-projection validation.
Regression coverage additionally exercises strict JSON/envelope failures,
unsupported semantic strings, empty/future envelopes, and sensitive exporter
content exclusion.

The compatibility test checks installed versions against `uv.lock`:
opentelemetry-sdk 1.44.0, opentelemetry-exporter-otlp-proto-http 1.44.0,
protobuf 7.35.1. SDK spans are collected in memory and encoded using
`encode_spans`, then `MessageToDict(use_integers_for_enums=True)` with the
required hex-ID conversion. No network calls or new dependencies are involved.

Validation on 2026-09-12: 61 focused pytest cases pass; focused Ruff and strict
Mypy checks pass. This is adapter-level evidence, not collector interoperability
certification, full-trace completeness, authenticated execution, or model quality.

## Independent workflow review follow-up: post-execution recovery

Confirmed an export-lifecycle data-loss bug with real Agent fixture executions:
raising at the first private source exporter or final output rename deleted all
accepted evidence with the temporary directory. The root agent authorized a
bounded fix confined to `run_workflow` and a separate recovery test module.

The execution staging directory is now allocated before execution with explicit
cleanup. It persists after every exception once a result has been returned.
Immediately after execution, before any normal exporter, it captures:

- PRIVATE opt-in: `captured-result.json` (ProductExperimentResult) and
  `captured-dataset.json` (original dataset bytes).
- PUBLIC default: `captured-public-result.json` (the existing allowlisted
  PublicExperimentSummary) only. Public runs never stage raw observations or
  dataset bytes on disk, even when their public exporter fails.
- `capture-status.json`: schema `evalops.workflow-capture/1.0`, status
  `CAPTURED_NOT_EXPORTED`, visibility, original quality status, per-file SHA-256
  and byte sizes, `verification_scope = CAPTURE_ONLY_NOT_VERIFIED`, and false
  provenance/formal-quality/production flags. This completion marker is written
  last. It is not a verified learning bundle or authenticated execution proof.

Failures return code 3 and safe structured status `EXECUTED_EXPORT_BLOCKED`,
schema `evalops.workflow-export-status/1.0`, capture status COMPLETE or FAILED,
`output_published`, absolute `recovery_path`, and an offline-only/no-target-rerun
instruction. The same data is attempted in `export-status.json`. Failed storage
may prevent any capture or status marker; stdout then explicitly reports FAILED
instead of promising saved evidence. A completed capture is checked again before
claiming it survived a late failure. No exception messages are copied to output.

The existing natural diagnostic-size error path still returns
`EXECUTED_ANALYSIS_BLOCKED` with a valid `output/source` bundle for offline analysis.
Successful output publication cleans the extra staging capture. A process kill
or power loss during capture can still leave incomplete files; these captures
must be hash-checked and recomputed before use, not treated as verified artifacts.

Recovery validation: six new real-fixture tests cover first source-export
failure, final rename failure in both visibility modes, public-only export
failure, storage exhaustion, and partial cleanup failure. The fixture runner is
real; only export/file boundaries are fault-injected. All twelve recovery and
existing workflow CLI tests, including natural oversized-diagnostics recovery,
passed together in 51.56 seconds. Final focused Ruff and strict Mypy checks pass.
