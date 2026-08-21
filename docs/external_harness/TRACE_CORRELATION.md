# Cross-system trace correlation

The RAG harness accepts W3C `traceparent` and returns the propagated trace ID plus its actual root span ID. EvalOps validates all identities before ingesting the artifact. When EvalOps creates an independently rooted evaluation span, `build_remote_parent_link()` creates an OpenTelemetry `Link` to the remote producer context rather than pretending the spans have an invalid parent/child relationship.

Allowed correlation attributes are `eval.run_id`, `eval.case_id`, `eval.attempt_id`, and `producer.git.sha`. Prompts, answers, retrieved text, tokens, credentials, tenant identity, and policy arguments are forbidden span attributes. Exporter exceptions return a telemetry failure signal but do not change evaluation control flow.

Mechanism result: `PASS` via `test_trace_correlation.py`. Candidate smoke also demonstrated that an input trace ID survives through the harness output and trajectory artifact. This is not an end-to-end collector/backend availability claim.

References: https://opentelemetry.io/docs/specs/semconv/ and https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
