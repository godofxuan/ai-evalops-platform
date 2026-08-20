# Final Hardening Report

## Identity

- Base SHA: `8fb89bd383433d9e1b00b0b84df4522639e208c9`
- Branch: `codex/final-evidence-hardening-v1`
- Final implementation SHA: `22fda896a1b24b0cf41cd1402ead521f74758ac6`
- Migration head: `20260820_0025`
- Local Docker: unavailable
- Remote CI: [run `32282462281`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32282462281),
  quality/integration and Compose smoke both successful

## Scope and root causes

| Area | Root cause | Repair | Trade-off |
| --- | --- | --- | --- |
| Regression | Intersection count existed, but metrics used complete Runs; latest evidence was re-resolved on every request | Common-set-only metrics, explicit case policy, sufficiency stats, frozen comparison/manifest tables | More persisted rows and a deliberate secure-default migration for callers |
| Human Review | `run+case` conflated ordinary and Agent evidence; machine results anchored first review | Source/artifact/packet hashes, source-specific uniqueness, staged evaluator visibility, packet digest verification | Multiple tasks can now exist for one case and consumers must display source |
| Review packet | Top-level deletion did not cover nested runtime identity | Bounded allowlists for input/citations/sources/trajectory | Useful tool-name/metadata detail is intentionally omitted |
| MCP | Principal was authenticated only at process startup | Per-call scrypt/status/tenant revalidation, shared locks through service call, bounded audit | Each call pays scrypt/database cost; stdio remains local only |
| Public evidence | Agent workflow test called services directly and used local storage | Real lifespan/HTTP/auth/PostgreSQL/MinIO/two-tenant/concurrency test | Runs only where PostgreSQL, Redis and MinIO are available |
| Database defense | Agent evidence tables lacked RLS and artifact reference was linked only by ID | RLS policies and reference+tenant+Run+SHA composite FK | Compose role separation is still incomplete |
| Orphan objects | Object put can outlive a rolled-back database transaction | Dry-run/grace/recheck/delete/audit reconciliation | No false cross-system atomicity; periodic operation still required |
| Metric claims | Producer fields were presented beside derived counts without provenance | Persisted reported/derived provenance, strict config rejection, numeric validation | No current metric is independently verified |

## Closed in code and executed tests

- All gated rates/counts use the same common-case set.
- Exact case-set mismatch and insufficient evidence do not execute a passing gate.
- Comparison creation pins artifact and evaluator-result IDs and idempotently replays the stored result.
- Review tasks have explicit immutable source and packet identities; evaluator evidence is withheld from an unsubmitted
  reviewer by the service, not only by a UI.
- MCP authenticates every call and records bounded outcome metadata without plaintext keys.
- Artifact metadata/reference lineage is enforced by a composite foreign key.
- Reconciliation is dry-run-first and performs a new-transaction reference recheck.
- Unsupported evaluator configs and invalid negative/non-finite numeric evidence are rejected.

## Qualification outcome

- Final CI at exact source `22fda896a1b24b0cf41cd1402ead521f74758ac6` passed formatting, Ruff, mypy, 826
  non-integration tests, every dedicated PostgreSQL/Redis/MinIO/MCP/concurrency step, both migration downgrade/upgrade
  paths, image build and Compose smoke.
- The first remote run exposed evidence-graph cleanup ordering and an invalid zero-case test fixture. The second run
  passed those repaired paths and exposed a missing non-null MCP audit `resource_id`. The third run passed after binding
  that resource identity to the call trace UUID. These failures and repairs are retained as evidence, not hidden.

## Not yet closed

- The desktop has no Docker CLI; external-service qualification therefore comes from the linked remote run, not a
  claimed local execution.
- Compose still uses one database credential for migration and long-lived app processes. Restricted-role RLS behavior is
  tested, but deployment role separation is not complete.
- There is no verified evaluator backed by an authoritative server-side permission/tool audit source.
- Reconciliation is not a two-phase commit and cannot promise that orphan objects never occur.
- No Streamable HTTP MCP endpoint, OAuth resource-server boundary or remote MCP rate limiting exists.
- No live LangGraph runtime/performance experiment was performed.

## Claims that remain unsafe

- production-ready;
- exactly-once execution;
- fully anonymous or bias-free review;
- seven verified evaluators;
- support for every Agent framework;
- live LangGraph benchmark or performance leadership;
- proven production-scale or linear Worker scaling;
- atomic PostgreSQL/S3 writes;
- complete production RLS role separation.

## Production-readiness gaps

Split migration/runtime DB roles, set tenant context on every runtime transaction under the restricted role, add
authoritative verified evaluator inputs, schedule/monitor reconciliation, define retention/SLOs, perform threat
modeling and load/failure testing, and establish remote MCP security before opening a network listener.

Historical scheduler evidence is unchanged: the frozen 4→8 Worker runs contain negative scaling and measurement
limitations. This hardening work does not turn them into Agent performance evidence.
