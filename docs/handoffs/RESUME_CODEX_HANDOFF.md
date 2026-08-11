# AI EvalOps Platform — Resume Codex Handoff

Updated: 2026-08-11. This is the authoritative entry for resume writing. Read `PROJECT_STATUS.md`,
`RESUME_METRIC_LEDGER.md`, `JD_RESEARCH_2026-08-11.md`, `resume_package/`, then `RESUME_INTERVIEW_CONSISTENCY.md`.

## Position the project correctly

This is not “an AI website” or a middleware inventory. It demonstrates AI Evaluation Infrastructure, asynchronous Python
backend systems, distributed state machines/concurrency correctness, reliability/evidence engineering and performance-
measurement discipline. It is portfolio-ready and release-not-ready. PR #1 is Draft; there is no v0.1.0 tag/Release.

Use `strong action + system/problem + measured constraint + result`. Keep one primary claim per one-to-two-line bullet.

## A. AI Evaluation / EvalOps

### Primary bullets

**A1.** Built a multi-tenant asynchronous AI evaluation backend that binds immutable Dataset Versions, targets and evaluator
identities into auditable Run→Job→Attempt→CaseResult workflows with artifact-backed outputs.

**A2.** Designed a source-bound, fail-closed release evidence contract that independently assessed raw PostgreSQL plans and
SHA-256 manifests across a frozen 64-arm/6,400-Job experiment, with all protected correctness counters at zero.

**A3.** Established a preregistered performance gate that blocked v0.1.0 when 3 of 4 frozen 4→8 Worker workloads missed the
0.95 scaling threshold, preserving the failed result instead of redefining release success.

### Backup bullets

**A-B1.** Qualified three generations of performance instrumentation and stopped causal attribution when absolute claim-p95
perturbation exceeded the frozen 10% budget, leaving H1/H2/H3 explicitly inconclusive.

**A-B2.** Implemented versioned evaluator/target bindings, deterministic targets, result metrics, comparisons and human
review workflows so evaluations remain reproducible and auditable across runs.

## B. AI Platform / Python Backend

### Primary bullets

**B1.** Engineered a Python 3.12/FastAPI/PostgreSQL backend that expands tenant-scoped evaluation requests into durable Jobs,
lease-bound Attempts and fenced result/artifact transactions, with PostgreSQL authoritative and Redis a lossy notification path.

**B2.** Fenced stale Workers with owner/version/live-expiry/Attempt checks across heartbeat, result and failure commits; the
frozen 6,400-Job experiment accepted zero stale success or stale failure writes.

**B3.** Implemented lease-expiry recovery with competing `FOR UPDATE SKIP LOCKED` Reapers, bounded retry classification and
transactional Attempt closure; historical A–I before/after fault matrices recorded 54/54 successful controlled repetitions.

### Backup bullets

**B-B1.** Built tenant-derived API identity, immutable Dataset Versions, idempotent Run creation and database consistency
constraints; explicitly documented that the shared-owner RLS spike is not complete production isolation.

**B-B2.** Separated SHA-256 artifact blobs from tenant references and validated local/S3-compatible persistence paths, while
documenting that object storage and PostgreSQL do not form one atomic transaction.

## C. Distributed Systems

### Primary bullets

**C1.** Modeled at-least-once execution as durable Job/Attempt generations and used lease-version fencing to reject stale
heartbeat/result/failure writes without claiming exactly-once external effects.

**C2.** Deterministically reproduced a real PostgreSQL `SKIP LOCKED` false-empty race, then preserved the tenant permit as
`PENDING` via an independent eligibility probe; one RED and two GREEN workflows record the fix.

**C3.** Built a durable fair-round scheduler whose frozen 20:1 experiment placed the secondary tenant at durable receipt
position 2 for w1/w2/w4/w8 in all four repetitions, versus 953 under legacy FIFO.

### Backup bullets

**C-B1.** Coordinated concurrent Reapers and Workers through row locks, transaction rollback and explicit state transitions,
with zero lost/orphan/Attempt-sequence violations in the frozen 64-arm evidence.

**C-B2.** Hardened benchmark integrity by making the assessor derive selector-specific candidate cardinality from raw
EXPLAIN rather than trusting producer summaries, with 598/598 manifest files independently rehashed.

## D. Reliability / Infrastructure

### Primary bullets

**D1.** Automated fail-closed CI evidence gates for source identity, workload/arm completeness, PostgreSQL plan semantics,
correctness counters and artifact manifests, preventing stale or malformed bundles from becoming release evidence.

**D2.** Enforced a release stop rule that retained `NEGATIVE_SCALING`, kept PR #1 Draft and left v0.1.0 untagged when the
candidate passed bounded correctness but failed its frozen scaling contract.

**D3.** Rejected two intrusive synchronous observers and one invalid passive PostgreSQL telemetry design after 11.3194%,
13.4906% and 28.0396% absolute claim-p95 changes exceeded the 10% qualification budget.

### Backup bullets

**D-B1.** Exercised nine controlled failure scenarios before/after scheduler work for 54/54 historical successful
repetitions with zero recorded correctness violations; retained the metric as historical instead of presenting a current SLO.

**D-B2.** Added structured/redacted logs, Prometheus metrics, OpenTelemetry tracing, readiness and evidence integrity checks,
while excluding unsupported production on-call, incident-response and capacity claims.

## Selection guidance

- Submit exactly three bullets; keep the two backups only for JD-specific replacement.
- Lead with A for EvalOps, B for Python/backend, C for distributed systems, D for reliability/release engineering.
- “6,400 Jobs” must retain “frozen/controlled experiment.” Scaling failure is release discipline, not performance success.
- Measurement invalidity is normally an interview story or backup bullet.

## Forbidden words

Unless future evidence changes: `production-ready`, `production-scale`, `exactly-once`, `universal fairness`, `strong
fairness`, `starvation-free`, `deadlock-free`, `linear scaling`, `highly scalable`, `proven root cause`, `production
capacity`, `zero data loss universally`.

## Separation from the RAG project

AI EvalOps carries distributed backend/orchestration/fencing/release-evidence claims. The RAG project carries retrieval,
grounding, citation, Agent/Guard and multi-document attribution claims. Never describe both as generic enterprise AI.
