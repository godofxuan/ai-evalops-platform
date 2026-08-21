# Technology decisions

## Inspect is an optional group

Inspect is required to author and execute external evaluation tasks, not to serve the EvalOps API. It lives in the `inspect` dependency group while CI installs all locked groups. This keeps production imports separated without allowing integration drift.

## Convert at the boundary

Inspect and the RAG producer retain their native schemas. EvalOps converts both to `agent-run-artifact/v1` at ingestion. This preserves framework independence and makes content identity/idempotency use one canonical representation.

## Subprocess before HTTP

The completed RAG project publishes a versioned stdin/stdout CLI, not an authenticated HTTP harness endpoint. The adapter therefore uses the stable interface that actually exists. Inventing an HTTP route in EvalOps would not prove cross-service interoperability.

## Paired bootstrap, common set only

Candidate-minus-baseline intervals resample paired deltas on the exact intersection. A-only and B-only IDs remain visible and never silently enter denominators. Formal claims additionally require a preregistered sample size and thresholds.

## Span Link rather than false parenting

RAG and EvalOps can have independent trace roots. A W3C-derived OpenTelemetry Link records correlation without rewriting remote history. Content remains out of span attributes.

## Fail closed on absent baseline contract

The candidate adds harness 1.0 after the frozen baseline. An internal compatibility shim was rejected because it would give A and B different measurement implementations. The correct result is `INPUT_BLOCKED`.
