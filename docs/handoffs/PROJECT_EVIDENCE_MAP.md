# AI EvalOps Platform — Project Evidence Map

Revalidated: 2026-08-20 on `codex/final-evidence-hardening-v1`. Current implementation baseline:
`22fda896a1b24b0cf41cd1402ead521f74758ac6`; migration head: `20260820_0025`; successful final-hardening workflow:
[`32282462281`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32282462281).

This is the claim-to-proof index for recruiters, interviewers, Teaching Codex and Resume Codex. A claim is usable only
inside its Scope. [`PROJECT_STATUS.md`](../../PROJECT_STATUS.md) is the current cross-layer state authority; the historical
v0.1.0 scheduler release decision remains authoritative for its frozen gate.

## Current final-hardening evidence

| Claim | Code / migration | Tests / remote evidence | Safe scope | Forbidden expansion |
| --- | --- | --- | --- | --- |
| Framework-neutral trajectory artifact with canonical JSON/SHA-256 and immutable ingestion | `app/agent_eval/schemas.py`, service/storage paths, migration `0019` | schema/service/API plus authenticated PostgreSQL/MinIO workflow; run `32282462281` | stable content identity and immutable project evidence | signature/authenticity or support for every Agent framework |
| Seven deterministic trajectory metric extractors with `reported`/`derived` provenance | `app/agent_eval/evaluators.py`, result records, migrations `0020`/`0025` | evaluator/schema and workflow tests | deterministic stored-evidence extraction | “seven verified evaluators” or authority-verified truth |
| Common-case-only regression with explicit case-set, coverage and sufficiency fail-closed policy | `app/agent_eval/regression.py`, `regression_service.py`, migration `0021` | unit/API/workflow replay tests | immutable selected IDs and bounded caller policy | universal model-quality standard |
| Source/result/artifact/packet-bound review with staged visibility | review service/schema, migration `0022` | review unit/API/workflow tests | auditable packet identity and controlled evaluator visibility | objective ground truth or proof reviewers are unbiased |
| Per-call MCP stdio credential revalidation | `mcp_server.py`, `mcp_stdio.py`, service adapter | in-memory protocol plus real stdio revoke integration; run `32282462281` | local authenticated stdio | Streamable HTTP, OAuth resource server or remote rate limit |
| Agent evidence tenant constraints | RLS/context repositories, migration `0023` | real PostgreSQL RLS/composite-FK integrations | configured CI topology | complete production role isolation |
| Dry-run-first orphan reconciliation | reconciliation service/repository, migration `0024` | PostgreSQL/MinIO dry-run/grace/recheck/retry/audit integration | compensating cleanup | atomic PostgreSQL/S3 commit or two-phase commit |
| Fixed eight-family adapter evidence | `app/agent_eval/benchmark.py`, `benchmarks/agent_eval_v1/` | canonical checked-in fixture replay | deterministic Custom/LangGraph-style mapping | live LangGraph runtime or performance benchmark |

## Historical scheduler/archive evidence — revalidated 2026-08-11

The sections below preserve archive baseline `39f381e8369e044392fbad39c3fbc75d5bdeb942`. Their dates, SHAs, 64-arm/6,400-Job
counts, negative scaling and invalid measurement results are historical and remain binding for the blocked v0.1.0 release;
they are not current production-capacity evidence.

## 1. Multi-tenant immutable evaluation inputs

- **Claim:** tenant-derived identity scopes Dataset and immutable Dataset Version operations.
- **Code path:** `app/auth/dependencies.py`, `app/datasets/service.py`, `app/persistence/orm_models.py`.
- **Test:** `tests/integration/test_identity_and_datasets.py`, `tests/integration/test_tenant_consistency_constraints.py`, `tests/integration/test_tenant_rls.py`.
- **Experiment / Metric:** integration contracts; no production traffic metric.
- **Scope:** application predicates and database consistency constraints; RLS is a spike because the shared owner role can bypass policy.
- **Evidence path:** `docs/08_security_boundaries.md`, `docs/resume_benchmark/EVALOPS_RLS_SPIKE.md`.
- **SHA:** archive baseline `39f381e`; individual evidence records retain their source SHAs.
- **Allowed wording:** “implemented tenant-scoped identity, immutable dataset versions and database consistency constraints.”
- **Forbidden wording:** “proved complete tenant isolation” or “production-secure multi-tenancy.”
- **Interview explanation:** API filtering alone is insufficient; identity is server-derived and tenant consistency is repeated in persistence constraints.

## 2. Asynchronous Run / Job / Attempt state machine

- **Claim:** a Run expands immutable cases into durable Jobs; each claim opens an Attempt and transitions explicit state.
- **Code path:** `app/runs/`, `app/jobs/claiming.py`, `app/domain/enums.py`, `app/persistence/orm_models.py`.
- **Test:** `tests/integration/test_run_idempotency.py`, `tests/concurrency/test_job_claiming.py`.
- **Experiment / Metric:** targeted run contains 6,400/6,400 submitted/unique/terminal Jobs.
- **Scope:** frozen CI experiment; at-least-once execution, not exactly-once.
- **Evidence path:** `docs/results/release/v0.1.0/targeted-gh-31352270523-1/assessment.json`.
- **SHA:** source `91acdba9f5b5f1a84fb03640382c9e4871364afe`.
- **Allowed wording:** “built durable asynchronous evaluation orchestration with explicit Job and Attempt state.”
- **Forbidden wording:** “exactly-once execution” or “zero loss under every failure.”
- **Interview explanation:** Job is desired work; Attempt is one lease-bound execution identity, so retries do not overwrite history.

## 3. Lease, heartbeat and fenced commits

- **Claim:** owner, lease version, live expiry and active Attempt identity reject stale heartbeat/result/failure writes.
- **Code path:** `app/jobs/lease.py`, `app/jobs/heartbeat.py`, `app/jobs/results.py`, `app/jobs/failures.py`.
- **Test:** `tests/concurrency/test_job_claiming.py`, `tests/unit/jobs/test_results.py`, `tests/failure_injection/test_fault_matrix.py`.
- **Experiment / Metric:** targeted protected stale-success and stale-failure accepted counts are both 0; historical fault matrix also records 0 accepted stale commits.
- **Scope:** tested races and fault scenarios only.
- **Evidence path:** targeted `arms.csv`; `docs/resume_benchmark/FAULT_RESULTS.csv`.
- **SHA:** current source `91acdba`; historical fault sources are recorded per CSV row.
- **Allowed wording:** “fenced stale workers by owner/version/expiry/Attempt checks in tested races.”
- **Forbidden wording:** “linearizable exactly-once result delivery.”
- **Interview explanation:** `worker_id` can be reused and does not identify a lease generation; version plus Attempt identity does.

## 4. Reaper-based crash recovery

- **Claim:** competing Reapers lock expired Jobs with `FOR UPDATE SKIP LOCKED`, close the expired Attempt, then retry/fail/cancel according to policy.
- **Code path:** `app/jobs/reaper.py`, `app/jobs/retry_policy.py`, `app/jobs/cancellation.py`.
- **Test:** `tests/unit/jobs/test_reaper.py`, `tests/concurrency/test_job_claiming.py`, `tests/failure_injection/test_fault_matrix.py`.
- **Experiment / Metric:** historical A–I before/after summary: 54/54 successful repetitions, 0 recorded correctness violations.
- **Scope:** historical controlled fault matrix, not an availability SLO.
- **Evidence path:** `docs/resume_benchmark/EVALOPS_FAULT_INJECTION.csv`.
- **SHA:** CSV carries source commit and raw evidence for every phase.
- **Allowed wording:** “implemented lease-expiry recovery and validated selected crash/race scenarios.”
- **Forbidden wording:** “deadlock-free,” “zero downtime,” or “self-heals every failure.”
- **Interview explanation:** row locking divides expired work across Reapers; transaction rollback preserves recoverability if a Reaper dies.

## 5. Durable fair scheduler and false-empty repair

- **Claim:** a durable fair round prevents the heavy tenant from hiding the secondary tenant in the frozen 20:1 workload; a real PostgreSQL race fixed false `EMPTY` consumption.
- **Code path:** `app/jobs/claiming.py`, scheduler models in `app/persistence/orm_models.py`.
- **Test:** `tests/concurrency/test_tenant_durable_fairness.py`, especially `test_locked_eligible_job_does_not_mark_scheduler_permit_empty`; `tests/concurrency/test_tenant_claim_parallelism.py`.
- **Experiment / Metric:** fair secondary durable receipt position `2/2/2/2` for w1/w2/w4/w8 across four repetitions; legacy position 953.
- **Scope:** exact queue=1000, sample_jobs=100, 20:1, batch=1 contract; remaining TOCTOU/liveness boundaries are not universal proofs.
- **Evidence path:** `docs/release/v0.1.0/fairness_redesign/`, targeted rep `arms.csv` files.
- **SHA:** source `91acdba`; RED `31397416017`; GREEN `31398322919` and `31398332668`.
- **Allowed wording:** “met the frozen 20:1 fairness receipt-position contract and repaired a deterministic `SKIP LOCKED` false-empty race.”
- **Forbidden wording:** “universal fairness,” “strong fairness,” “starvation-free,” or “deadlock-free.”
- **Interview explanation:** `SKIP LOCKED` empty means “nothing visible now,” not “nothing eligible exists”; the separate probe prevents irreversible permit consumption.

## 6. Fail-closed evidence contract v2

- **Claim:** the assessor rejects source/workload/arm drift and independently derives candidate cardinality from raw PostgreSQL EXPLAIN.
- **Code path:** `scripts/release_evidence.py`, `scripts/targeted_scheduler_evidence.py`.
- **Test:** `tests/unit/scripts/test_release_evidence.py`, `tests/unit/scripts/test_targeted_scheduler_evidence.py`.
- **Experiment / Metric:** 598/598 manifest entries rehashed with zero mismatch; 512 EXPLAIN summaries are covered by the four targeted bundles.
- **Scope:** schema-v2 contract artifacts; it does not prove the software outside recorded arms.
- **Evidence path:** `docs/release/v0.1.0/evidence_contract_v2/`, targeted root `manifest.json`.
- **SHA:** assessor and producer identities are recorded in each bundle.
- **Allowed wording:** “designed a source-bound, independently assessed, fail-closed release evidence contract.”
- **Forbidden wording:** “cryptographically proves all benchmark claims” or “tamper-proof system.”
- **Interview explanation:** producer summaries are inputs, not proof; raw plan, independent parsing and manifest identity reduce self-attestation risk.

## 7. Frozen performance release gate

- **Claim:** the preregistered scaling rule correctly blocked v0.1.0.
- **Code path:** `scripts/release_evidence.py`, workflow evidence scripts.
- **Test:** scaling, numeric-domain and missing-arm fail-closed tests in `tests/unit/scripts/test_release_evidence.py`.
- **Experiment / Metric:** 4→8 ratio: single 0.782511, balanced 0.772797, 20:1 0.796214, many-small 1.014063; 3/4 below 0.95.
- **Scope:** frozen targeted experiment on GitHub-hosted CI; not production capacity.
- **Evidence path:** targeted `assessment.json`, `docs/release/v0.1.0/RELEASE_DECISION.md`.
- **SHA:** source `91acdba`; workflow `31352270523`.
- **Allowed wording:** “built a preregistered performance gate that blocked release when 3/4 workloads missed the frozen threshold.”
- **Forbidden wording:** “highly scalable,” “linear scaling,” or “production capacity validated.”
- **Interview explanation:** correctness passed but release readiness required both correctness and scaling; one cannot substitute for the other.

## 8. Measurement-system qualification

- **Claim:** three measurement designs were rejected before causal attribution because they failed the frozen perturbation/validity contract.
- **Code path:** `scripts/performance_attribution_evidence.py`, `scripts/measurement_system_evidence.py`, `scripts/postgres_wait_telemetry.py`.
- **Test:** `tests/unit/scripts/test_measurement_system_evidence.py`, `tests/unit/scripts/test_postgres_wait_telemetry.py`, `tests/integration/test_postgres_wait_telemetry.py`.
- **Experiment / Metric:** observer v1 absolute claim-p95 change 11.3194%; v2 13.4906%; passive telemetry throughput -0.4292% but claim-p95 -28.0396%, all against 10% claim-p95 budget.
- **Scope:** qualification detects association with the measurement mode; it does not identify the scheduler bottleneck or prove why ON was faster.
- **Evidence path:** `docs/release/v0.1.0/performance_attribution/`, `docs/release/v0.1.0/measurement_system_v2/04_RESULTS.md`.
- **SHA:** passive workflow `31421039618`, source `aa8b29c`, measurement code `0915c10d`.
- **Allowed wording:** “qualified and rejected intrusive/invalid measurement systems, leaving causal hypotheses inconclusive.”
- **Forbidden wording:** “proved the root cause,” “observer improved latency,” or “PostgreSQL locks caused scaling failure.”
- **Interview explanation:** absolute thresholds treat suspicious speedups and slowdowns symmetrically; either can invalidate causal inference.

## 9. Evidence-based stop decision

- **Claim:** candidate budgets and preregistered stop rules prevented further tuning after measurement validity failed.
- **Code path:** decision is procedural, enforced in release/handoff documents rather than a runtime feature.
- **Test / Experiment / Metric:** scheduler candidate budget 0; measurement candidate budget 0; H1/H2/H3 formal repetitions `NOT_RUN`.
- **Scope:** this v0.1 archive decision.
- **Evidence path:** `PROJECT_STATUS.md`, `docs/release/v0.1.0/RELEASE_DECISION.md`.
- **SHA:** archive baseline `39f381e` plus subsequent documentation commits.
- **Allowed wording:** “stopped causal claims and release work when evidence prerequisites failed.”
- **Forbidden wording:** “solved the scaling root cause” or “ready for Candidate 4.”
- **Interview explanation:** continuing creates researcher degrees of freedom and risks tuning to the benchmark or observer instead of learning.
