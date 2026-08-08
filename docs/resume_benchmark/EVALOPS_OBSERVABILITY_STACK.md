# Prometheus and OpenTelemetry runtime stack

Status: configuration, verification contracts, and focused tests `VERIFIED`; real Compose execution
`PENDING` on the next GitHub Actions run.

## Decision

Compose now includes Prometheus `v3.13.2-distroless` and OpenTelemetry Collector contrib `0.158.0`,
both selected from the current official stable releases and run under their image-declared non-root
UIDs. Grafana is intentionally omitted: Prometheus's query API and Collector evidence can prove the
data paths without adding a dashboard whose presence would not prove instrumentation correctness.

Prometheus scrapes API `/metrics`, Worker `:9101`, and Reaper `:9102` every two seconds and loads the
existing Outbox alert rules. The Collector accepts OTLP/HTTP on 4318, batches for one second, and uses
the detailed debug exporter for inspectable CI evidence. The Python exporter is configured with the
complete `http://otel-collector:4318/v1/traces` endpoint because this application setting is passed
directly to the trace-specific OTLP/HTTP exporter.

## Correlation model

API request and `run.create` spans share the incoming API trace. The persisted W3C `traceparent`
captures that Run origin. Worker `job.process` and Reaper recovery deliberately start new traces with
a Span Link to the origin rather than continuing one parent-child trace across queue delay, retries,
and lease recovery. Run/Job/Attempt IDs are trace/log attributes, not Prometheus labels, preventing
unbounded time-series cardinality.

This is a semantic choice, not a missing cross-process parent. Operators correlate by `run.id` and
`job.id`, then follow the Span Link back to the originating API trace. Existing unit and real
PostgreSQL claiming tests prove carrier persistence and link construction; the Compose proof confirms
that spans from API, Worker, and Reaper reach one Collector.

## Verification contract

`scripts/verify_observability_stack.py` fails closed unless all three Prometheus scrape pools are
`up`, and queries non-empty series for API traffic, database operation latency, queue depth, retry,
and lease expiration. It then requires detailed Collector output to contain `process.role` values for
API, Worker, and Reaper. All waits are bounded.

This proof does not claim production retention, alert delivery, log aggregation, or a trace search
backend. Collector debug output is for development/CI evidence. A production deployment should route
OTLP to a durable backend and protect Prometheus/Collector endpoints with network policy or an
authenticated gateway.

## Local RED/GREEN

Deployment RED produced five failures because neither service nor either config existed. The first
GREEN attempt then exposed a brittle test that expected `otel-collector` literally in the workflow
command even though the verifier owns that detail; the test was corrected to inspect the verifier.
Manual image-config comparison found `config.yml` would not match the Collector's default
`config.yaml` before any remote run, so the filename and contract were corrected.

Focused result: 21 tests passed; Ruff and strict MyPy passed. Local Docker is unavailable, so actual
scrape/export behavior remains pending remote Compose evidence.
