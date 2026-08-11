# AI EvalOps Platform — Teaching Codex Handoff

Updated: 2026-08-11. This is the authoritative teaching entry. Read `PROJECT_STATUS.md` and
`docs/handoffs/PROJECT_EVIDENCE_MAP.md` first; demonstrate each answer with source, test and evidence rather than memory.

## Teaching contract

Teaching Codex must teach from first principles, ask the learner to explain the mechanism before showing the answer, and
keep every claim inside its measured scope. Execution is **at-least-once**, frozen 20:1 evidence is not universal fairness,
v0.1.0 is `NOT_READY`, PR #1 is Draft, H1/H2/H3 are inconclusive, and production readiness is not verified.

Session loop: concept check → trace code → predict failure → inspect test → inspect artifact → explain trade-off → answer
interview question → challenge the evidence boundary.

## Module 1 — Platform architecture and entity separation

### Concept

An evaluation control plane separates immutable inputs, orchestration state, execution history and output. One mutable
“evaluation row” cannot safely represent revisions, retries and case-level results.

### Project implementation

`Dataset` owns a collection; `DatasetVersion` freezes cases; `EvaluationRun` binds target/evaluator/version identities;
`EvaluationJob` is desired case work; `JobAttempt` is one lease generation; `CaseResult` is the accepted outcome;
`ArtifactBlob`/`ArtifactReference` separate physical content from ownership.

```text
request -> Run -> Job -> Attempt -> Worker -> Target/Evaluator -> CaseResult -> Artifact
```

### Source code

`app/persistence/orm_models.py`, `app/runs/`, `app/workers/`, `app/evaluators/`, `app/artifacts/`.

### Failure mode

Collapsing Job and Attempt lets retries overwrite execution identity and defeats stale-generation checks. Collapsing Dataset
and DatasetVersion lets a Run’s input change after creation.

### Test

`tests/integration/test_run_idempotency.py`, `tests/integration/test_identity_and_datasets.py`,
`tests/concurrency/test_job_claiming.py`.

### Evidence

Targeted workflow `31352270523` records 6,400 submitted/unique/terminal Jobs. This is frozen-experiment evidence only.

### Trade-off

More entities and constraints complicate queries/migrations, but preserve immutable provenance and retry history.

### Interview question

Why are Job and Attempt separate, and why is CaseResult not simply a mutable Job column?

### Reference answer

Job is durable intent; Attempt is one lease-bound execution. Recovery can create several Attempts, while the active fenced
Attempt alone may commit the accepted CaseResult. This preserves history without pretending execution happened once.

### Follow-up question

Which identities must a Run freeze to make later results reproducible?

### Common wrong answer

“Separate tables are only normalization” or “one Job always has one Attempt.”

## Module 2 — Multi-tenancy as an end-to-end invariant

### Concept

Tenant isolation is not an API filter. Trusted identity, service queries, foreign keys, artifact ownership and database
roles must agree on tenant identity.

### Project implementation

Bearer API Keys map server-side to a Principal; clients do not choose `tenant_id`. Repository predicates and consistency
constraints repeat the boundary. RLS is explicitly a spike because the shared owner runtime role can bypass policy.

### Source code

`app/auth/dependencies.py`, `app/auth/service.py`, `app/datasets/service.py`, `app/artifacts/repository.py`, tenant models and
migrations under `app/persistence/` and `alembic/`.

### Failure mode

An endpoint authorizes tenant A but loads a referenced object by global ID, causing cross-tenant binding. Owner-role RLS
bypass can make an enabled policy provide no runtime barrier.

### Test

`tests/integration/test_identity_and_datasets.py`, `tests/integration/test_tenant_consistency_constraints.py`,
`tests/integration/test_tenant_rls.py`.

### Evidence

Integration contracts cover cross-tenant behavior; `docs/resume_benchmark/EVALOPS_RLS_SPIKE.md` records the role limitation.

### Trade-off

Repeated tenant keys/predicates are verbose but safer. Full RLS needs distinct migration/runtime roles and transaction-level
tenant context, which is not complete here.

### Interview question

Why is filtering by `tenant_id` in FastAPI insufficient?

### Reference answer

Background workers, other repositories and incorrect joins can bypass one endpoint. Identity must be server-derived and
validated at every persistence boundary; database constraints add defense. RLS helps only when runtime roles cannot bypass it.

### Follow-up question

How would you roll out RLS without breaking Worker and Reaper access?

### Common wrong answer

“Authentication automatically isolates every database query.”

## Module 3 — Job state machine, lease and heartbeat

### Concept

A state machine makes legal transitions explicit. A lease grants temporary authority; heartbeat extends it; Attempt records
the execution generation; retry policy decides whether failure creates another Attempt.

### Project implementation

Jobs transition through queued/running/retry/cancelling/terminal states. Claim atomically writes owner, expiry, version and
Attempt. Heartbeat requires current live owner/version. Transient failures receive bounded backoff; permanent failures end.

### Source code

`app/domain/enums.py`, `app/jobs/claiming.py`, `app/jobs/heartbeat.py`, `app/jobs/retry_policy.py`,
`app/jobs/cancellation.py`, `app/workers/lease_runner.py`.

### Failure mode

A dead Worker leaves RUNNING forever without expiry; an overly short lease reaps healthy work; an unguarded late writer can
move terminal state backward.

### Test

`tests/concurrency/test_job_claiming.py`, `tests/unit/workers/test_lease_runner.py`, job failure/cancellation unit tests.

### Evidence

Frozen targeted orphan-nonterminal and illegal-transition counters are zero. Historical scenario A kills a Worker after claim.

### Trade-off

Short leases recover faster but risk false expiry; long leases delay recovery. Production values need operating evidence not
claimed by this project.

### Interview question

What happens if a Worker hangs after claiming a Job?

### Reference answer

Heartbeat stops; after expiry a Reaper closes the Attempt and chooses retry/failure/cancellation. A replacement gets a new
version/Attempt, and the old Worker is fenced from durable commit.

### Follow-up question

How would you choose lease duration and heartbeat interval in production?

### Common wrong answer

“The queue guarantees the Job runs exactly once.”

## Module 4 — Fencing stale workers

### Concept

Fencing prevents an old owner writing after authority moved. Process identity is not enough; a write must prove current
generation, active Attempt and live lease.

### Project implementation

Heartbeat/result/failure compare `worker_id`, lease version, `lease_expires_at > now`, Job state and Attempt. Result commit
locks relevant Tenant/Run/Job/Attempt state and relies on unique CaseResult persistence.

### Source code

`app/jobs/heartbeat.py`, `app/jobs/results.py`, `app/jobs/failures.py`, `app/persistence/orm_models.py`.

### Failure mode

Worker A pauses; B reclaims and finishes; A resumes. Checking only `worker_id` or RUNNING can accept A’s stale write.

### Test

`tests/concurrency/test_job_claiming.py`, `tests/unit/jobs/test_results.py`, historical fault scenarios C and D.

### Evidence

Current targeted stale-success and stale-failure accepted counters are zero; fault evidence is historical supporting scope.

### Trade-off

Database fencing adds conditional writes/locks but cannot undo an external side effect already performed by a Target.

### Interview question

Why is `worker_id` alone not a fencing token?

### Reference answer

It labels a process, not the order of ownership. Reuse or delayed messages may belong to an older lease; monotonically changed
version plus active Attempt distinguishes generations.

### Follow-up question

Design a stale-result race test without sleeps.

### Common wrong answer

“Use a UUID Worker ID, so stale writes become impossible.”

## Module 5 — Reaper, retries and execution semantics

### Concept

At-least-once permits repeated execution Attempts. Exactly-once business effect requires idempotent/fenced persistence and,
for external effects, an additional idempotency/transaction contract.

### Project implementation

Reapers select expired Jobs ordered by expiry with `FOR UPDATE SKIP LOCKED`, close the Attempt, then retry/fail/cancel in one
transaction. Competing Reapers cannot own the same locked row.

### Source code

`app/jobs/reaper.py`, `app/jobs/retry_policy.py`, `app/jobs/cancellation.py`, `app/jobs/results.py`.

### Failure mode

Two Reapers race, a Reaper dies mid-recovery, or an old Worker commits after recovery.

### Test

`tests/unit/jobs/test_reaper.py`, dual-Reaper paths in `tests/concurrency/test_job_claiming.py`, historical scenario H.

### Evidence

Historical A–I before/after summaries contain 54/54 successful controlled repetitions and zero recorded violations. This is
not an availability SLO.

### Trade-off

`SKIP LOCKED` improves concurrent progress but is not inherently fair. Retry improves recovery but can repeat Target calls.

### Interview question

Did this project implement exactly-once execution?

### Reference answer

No. It implements at-least-once execution and fenced/idempotent durable result persistence for tested paths. Target execution
may repeat, and arbitrary external effects are not transactionally coupled to PostgreSQL.

### Follow-up question

What would a payment-like Target need to make retries safe?

### Common wrong answer

“A unique result row makes the whole distributed execution exactly once.”

## Module 6 — Durable fair scheduling and false-empty

### Concept

Fairness under concurrency needs shared durable order. `SKIP LOCKED` reports visible rows, not whether eligible rows exist.

### Project implementation

Coordination generation/sequence and reusable tenant permits (`PENDING`, `CONSUMED`, `EMPTY`) form a fair round. Claim locks
permit and exact-priority Job atomically. If `SKIP LOCKED` sees none, an independent exists probe preserves `PENDING` when
eligible work remains.

### Source code

`app/jobs/claiming.py`; `SchedulerCoordination` and `TenantSchedulerState` in `app/persistence/orm_models.py`.

### Failure mode

Tx1 locks the only eligible Job. Tx2 owns its tenant permit; `SKIP LOCKED` returns empty. Old code marked `EMPTY`, losing a
valid turn.

### Test

`tests/concurrency/test_tenant_durable_fairness.py::test_locked_eligible_job_does_not_mark_scheduler_permit_empty`, plus
overtaking, rollback and cross-tenant progress tests.

### Evidence

RED `31397416017`; GREEN `31398322919`/`31398332668`. Frozen targeted fair secondary position is 2 at every worker count and
repetition; legacy is 953.

### Trade-off

The probe adds a query and fixes one known false-empty transition, but does not prove global starvation freedom.

### Interview question

Why can’t zero rows from `SKIP LOCKED` mean “tenant has no work”?

### Reference answer

A qualifying row can be hidden behind another transaction’s lock. Persisting `EMPTY` from temporary visibility loses state;
the separate eligibility probe keeps the permit pending.

### Follow-up question

What liveness property remains unproved?

### Common wrong answer

“Nonblocking selection guarantees fairness and starvation freedom.”

## Module 7 — Evidence contract v1 to v2

### Concept

Evidence is a producer/independent-assessor contract. Producer summaries cannot prove their own identity, completeness or
interpretation; missing/ambiguous data must fail closed.

### Project implementation

Schema v2 binds source SHA, arm IDs, workload metadata, candidate unit, numeric domains and protected counters. It preserves
raw EXPLAIN, independently locates selector candidate nodes, requires coverage and verifies a SHA-256 manifest.

### Source code

`scripts/release_evidence.py`, `scripts/targeted_scheduler_evidence.py`, `.github/workflows/` evidence workflows.

### Failure mode

Stale bundles can be labeled current; arms can spoof workload; top-level EXPLAIN totals can be mistaken for selector
cardinality; missing counters can be treated as zero.

### Test

`tests/unit/scripts/test_release_evidence.py` covers source, arm, raw-plan, metadata, counter and manifest failures.

### Evidence

598/598 targeted manifest entries rehash with zero mismatch; four repetitions cover 64 arms and 512 EXPLAIN summaries.
Historical schema-v1 workflow `31327388006` remains FAILED.

### Trade-off

More storage and assessor code buys reproducible rejection. Hashes verify integrity, not signer authenticity.

### Interview question

Why is a producer CSV insufficient release evidence?

### Reference answer

The producer can mislabel identity, omit arms, calculate the wrong node or default missing failures. The assessor must bind
identity, inspect raw data and fail closed; the manifest detects later artifact drift.

### Follow-up question

What threat does a SHA-256 manifest not solve?

### Common wrong answer

“A hash proves the experiment was correct and independent.”

## Module 8 — Formal scaling and negative results

### Concept

Scaling uses a preregistered workload, aggregation rule and threshold. Correctness and performance are separate release gates.

### Project implementation

Four repetitions yield median Jobs/s for w4/w8. Ratio is `median(w8) / median(w4)`; every workload must reach 0.95. Nothing
was changed after seeing results.

### Source code

`scripts/release_evidence.py`, `scripts/targeted_scheduler_evidence.py`.

### Failure mode

Selecting the best repetition, moving the threshold or hiding failed workloads converts a gate into post-hoc storytelling.

### Test

Release-assessor tests enforce complete arms, finite numbers, protected counters and source-bound scaling.

### Evidence

Ratios: single 0.782511, balanced 0.772797, 20:1 0.796214, many-small 1.014063. Three of four fail 0.95; v0.1.0 is NOT_READY.

### Trade-off

A strict gate blocks a useful prototype, but prevents redefining success. Portfolio usability is not release readiness.

### Interview question

Does negative scaling mean the scheduler is incorrect?

### Reference answer

No. Bounded correctness/fairness passed; the 4→8 performance contract failed. It says this candidate missed this release
target on frozen CI workloads, not why or what production capacity is.

### Follow-up question

Why not lower the threshold to 0.75 afterward?

### Common wrong answer

“One workload scaled above 1.0, so the release broadly scales.”

## Module 9 — Measurement-system validity

### Concept

Causal experiments first qualify the instrument. Observer effect includes slowdown and speedup, so absolute change matters;
association with measurement mode is not root cause.

### Project implementation

Synchronous observer v1, lower-overhead v2 and external 5 Hz PostgreSQL sampling each faced frozen 5% throughput/10%
claim-p95 budgets before formal H1/H2/H3 attribution.

### Source code

`scripts/performance_attribution_evidence.py`, `scripts/measurement_system_evidence.py`,
`scripts/postgres_wait_telemetry.py`.

### Failure mode

In-transaction callbacks alter scheduling/locking; passive polling can still perturb or correlate with drift. “ON faster” is
not automatically improvement.

### Test

`tests/unit/scripts/test_measurement_system_evidence.py`, `tests/unit/scripts/test_postgres_wait_telemetry.py`,
`tests/integration/test_postgres_wait_telemetry.py`.

### Evidence

Observer claim-p95 absolute changes: 11.3194%, 13.4906%, 28.0396%. Passive run recorded 69 successful/65 wait-observing
samples, 5,393 rows and zero errors/drops/overflow, but still failed validity.

### Trade-off

Rejecting the instrument loses a convenient explanation but protects causal validity. Four ON/four OFF is qualification,
not a large-sample proof.

### Interview question

Why did lower ON latency invalidate rather than validate the observer?

### Reference answer

The frozen question was whether ON changed metrics, not whether it worsened them. Absolute 28.04% exceeded the 10% budget,
so OFF/ON were not comparable enough for attribution; direction has no supported causal story.

### Follow-up question

What can `pg_stat_activity`/`pg_locks` sampling show, and what can it not prove?

### Common wrong answer

“Passive means zero overhead” or “faster ON proves telemetry optimized PostgreSQL.”

## Module 10 — Engineering stop decisions

### Concept

Preregistration, candidate budgets and stop rules limit researcher degrees of freedom. Negative evidence is an outcome.

### Project implementation

After Candidate 3 scaling and three measurement qualification failures, scheduler candidate budget = 0 and measurement
candidate budget = 0. No Candidate 4, observer v4, threshold/workload change or extra repetitions were authorized.

### Source code

Procedural governance in `PROJECT_STATUS.md`, `docs/release/v0.1.0/RELEASE_DECISION.md` and measurement reports.

### Failure mode

Post-hoc tuning of Worker/batch/pool/lease/threshold or repeated observer invention overfits benchmark and narrative.

### Test

Cross-surface consistency checks preserve NOT_READY, Draft, inconclusive hypotheses and zero candidate budgets; CI keeps
evidence assessors fail-closed.

### Evidence

Preserved states: `NEGATIVE_SCALING`, two `INSTRUMENTATION_TOO_INTRUSIVE`, `MEASUREMENT_SYSTEM_INVALID`, and
`PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY`.

### Trade-off

Stopping leaves the bottleneck unexplained, but avoids unsupported causality. Future work needs new authorization and
preregistration rather than continuation disguised as closure.

### Interview question

Why stop instead of Candidate 4 or 20 more repetitions?

### Reference answer

Correctness passed, scaling failed, and no observer qualified. More post-result tuning/repetition expands researcher freedom
without repairing the invalid prerequisite. The honest decision was to preserve evidence and keep v0.1.0 NOT_READY.

### Follow-up question

What evidence would justify reopening the project?

### Common wrong answer

“We ran out of time” or “it was probably noisy CI.”

## Graduation checklist

The learner may use a resume bullet only if they can draw the entity flow, distinguish at-least-once from exactly-once,
trace every fence, explain the false-empty interleaving, recalculate the scaling verdict, explain all three rejected
measurement designs without inventing a cause, and state every forbidden claim.
