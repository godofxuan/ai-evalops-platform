# Interview Evidence Map

## Run / Job / Attempt; lease / heartbeat / fencing; Reaper

- Design background: separate durable work from each execution generation under at-least-once semantics.
- Code: `app/runs`, `app/jobs`, `app/workers`, `app/reaper`.
- Tests: `tests/concurrency/test_job_claiming.py`, `test_stale_worker.py`, `test_reaper_concurrency.py`.
- Failure scenario: a stalled worker finishes after its lease was recovered; owner/version/expiry/Attempt checks reject it.
- Why: transactionally fenced database state is achievable without claiming exactly-once external side effects.
- Limitation: an external tool call can repeat; 4→8 Worker evidence shows negative scaling.

## Tenant fairness

- Design background: prevent a high-volume tenant from monopolizing claim order.
- Code: fair candidate/round state in `app/jobs/claiming.py` and scheduler models/migrations.
- Tests: `tests/concurrency/test_tenant_fair_claiming.py`, `test_tenant_durable_fairness.py`.
- Failure scenario: false-empty `SKIP LOCKED` observations and durable turn races.
- Why: short phase-separated transactions bound coordination and make state auditable.
- Limitation: fairness correctness is not a performance or universal fairness theorem.

## Transactional outbox

- Design background: database state and Redis publication cannot be one atomic transaction.
- Code: `app/events/outbox.py`, `app/events/publisher.py`.
- Tests: `tests/integration/test_transactional_outbox.py`.
- Failure scenario: commit succeeds and publisher crashes before Redis send; durable rows replay.
- Why: at-least-once notification with idempotent consumers is explicit and observable.
- Limitation: Redis messages can repeat and realtime delivery is not the state authority.

## Agent artifact; canonical JSON / SHA-256

- Design background: compare immutable semantic trajectories across runtime adapters.
- Code: `app/agent_eval/schema.py`, `service.py`, migration 0019/0023.
- Tests: artifact schema/API tests and `test_agent_http_minio_e2e.py`.
- Failure scenario: tenant/run/case mismatch, duplicate concurrent upload, object tampering.
- Why: canonical bytes define content identity while PostgreSQL owns tenant/query metadata.
- Limitation: an object put can survive DB rollback and requires reconciliation.

## Evaluator identity

- Design background: the same artifact can have multiple implementation/config evaluation identities.
- Code: `app/agent_eval/evaluators.py`, `service.py`, migrations 0020/0025.
- Tests: evaluator unit tests and Agent workflow integration.
- Failure scenario: accepting unused config would create distinct SHA identities with identical behavior.
- Why: reject unsupported config and bind implementation version/config SHA/provenance.
- Limitation: current evidence is reported or derived; no authoritative verified extractor exists.

## Regression manifest

- Design background: a release decision must be replayable after new evidence arrives.
- Code: `regression.py`, `regression_service.py`, migration 0021.
- Tests: `test_failure_and_regression.py`, `test_agent_eval_workflow.py`.
- Failure scenario: `{A,B}` vs `{A,C}` polluted A's metrics; latest artifact later changed an old comparison.
- Why: one common set plus immutable selected IDs and stored decision/report.
- Limitation: thresholds and minimum sample rules remain explicit caller policy.

## MCP authentication

- Design background: a long-lived stdio process must not retain a revoked startup Principal.
- Code: `mcp_server.py`, `mcp_stdio.py`, `mcp_service_adapter.py`.
- Tests: official MCP client unit and real subprocess/PostgreSQL integration.
- Failure scenario: revoke/expire/disable during process lifetime or race revocation with a call.
- Why: per-call scrypt/state check and shared row locks define ordering; audit avoids arguments/plaintext.
- Limitation: local stdio only; environment variable and same-user host processes remain in the threat model.

## Human review

- Design background: ordinary CaseResult and multiple Agent artifacts can share one Run/case.
- Code: `app/reviews/service.py`, `schemas.py`, `agent_eval/review_packet.py`, migration 0022.
- Tests: review packet unit and three-reviewer PostgreSQL workflow.
- Failure scenario: conflict-ignore returns the wrong source; machine score anchors first judgment; packet tampering.
- Why: immutable source/packet hashes and service-layer staged visibility.
- Limitation: allowlisting selected identifiers does not produce anonymity.

## RLS

- Design background: application predicates need database depth defense.
- Code: migration 0023 and composite ORM constraints.
- Tests: restricted `NOBYPASSRLS` role section in Agent workflow and existing tenant RLS suite.
- Failure scenario: missing tenant context, cross-tenant direct SQL or mismatched reference/tenant/Run/SHA.
- Why: fail-closed policy plus composite lineage makes bypass harder.
- Limitation: Compose has not yet separated long-lived runtime and migration-owner credentials.

## Object reconciliation

- Design background: S3 and PostgreSQL do not share an atomic commit.
- Code: `app/artifacts/reconciliation.py`, storage listing, migration 0024.
- Tests: `test_artifact_reconciliation.py`.
- Failure scenario: put succeeds/DB rolls back; reference appears after scan; delete fails once; shared SHA.
- Why: dry-run/grace/new-transaction recheck/audit/retry minimizes destructive risk.
- Limitation: periodic operation and monitoring are still required; no 2PC claim.

## CI / Compose

- Design background: external-service behavior must run outside mocks.
- Code: `.github/workflows/ci.yml`, `deploy/compose.yaml`, `Dockerfile`.
- Tests: dedicated PostgreSQL, MinIO, stdio MCP, RLS, concurrency and Compose smoke steps.
- Failure scenario: migrations pass offline but fail on PostgreSQL; auth/storage ordering differs from a recording service.
- Why: separate focused JUnit-producing steps make evidence attributable.
- Evidence: final-hardening run `32282462281` passed quality/integration and Compose smoke at source `22fda89`.
- Limitation: one CI topology is correctness evidence, not production-scale or SLO evidence.
