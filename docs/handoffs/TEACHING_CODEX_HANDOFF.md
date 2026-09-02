<!-- FINAL-CROSS-REPO-CLOSEOUT:START -->
> Canonical closeout snapshot (2026-09-01): default `main`; evidence baseline `1c2f9d93b488cacf7d5f7c953c8cce906e0f9be6`; exact main CI [33494481676](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33494481676); RAG `2065e571d77439babf76a763ac459a618950f218`; EvalOps Final Pair implementation `4040fa1db7cee6c8380ff8580fa21be17464435b`; Final Pair `FINAL_PAIR_CONTRACT_VERIFIED` (18 cases, 15 converted/source events, 0 dropped, 0 unmapped).
>
> Status: `IMPLEMENTATION_COMPLETE` · `MERGED_TO_DEFAULT_MAIN` · `EXACT_MAIN_SHA_CI_VERIFIED` · `NOT_RELEASED` · `PORTFOLIO_READY` · `FORMAL_AB_NOT_RUN` · `HUMAN_REVIEW_PENDING` · `SHADOW_RELEASE_NOT_PASSED` · `PRODUCTION_NOT_VERIFIED`. Content below this notice that cites earlier branches/SHAs is historical, not the current fact source.
<!-- FINAL-CROSS-REPO-CLOSEOUT:END -->
# 2026-09-02 product and evidence-boundary module

Teach three different evidence classes without allowing substitution:

1. `DEMO_PASS`: 120 deterministic fixture cases prove the EvalOps product workflow only.
2. `AGGREGATE_EVIDENCE_VERIFIED`: the RAG R5 public JSON is real source evidence whose bytes,
   identities, accounting, metric arithmetic and claim boundary can be verified.
3. `FORMAL_CASE_RESULTS=INPUT_REQUIRED`: the public aggregate excludes per-case inputs/results,
   so EvalOps cannot perform its own formal paired run or human-review packet.

Exercise: change one paired count or add a top-level `cases` array to a copied R5 fixture and
show the verifier fail. The learner must explain why a valid aggregate is still not a set of
auditable `CaseResult` rows, and why Hit@5 `88.02%` is not answer accuracy.

# 2026-08-22 teaching update

Teach the integrity remediation through five invariants: database-leased Artifact
deletion with object identity; fair scheduling without diagnostic singleton locking;
producer-digest and event-loss verification; evidence sufficiency before statistics; and
business-success/audit-delivery separation. See docs/integrity_remediation/EXECUTION_LOG.md.
Do not teach the nine-case dataset as a formal A/B result.
# AI EvalOps Platform — Teaching Codex Handoff

## 2026-09-01 scorecard teaching module

Teach the Scorecard before teaching individual metrics:

1. Run `python -m scripts.project_scorecard` and trace the Final Pair, root scheduler
   Manifest, four `arms.csv` files and evaluator registry inputs.
2. Explain why correctness, formal answer quality, scalability and production evidence are
   non-substitutable gates rather than a weighted score.
3. Recompute the 64 arms, 6,400 submitted/unique/terminal Jobs, protected-counter zero sum,
   fairness position 2 versus 953 and all four 4→8 ratios.
4. Use `docs/review/SCALABILITY_DIAGNOSIS.md` to distinguish observation, falsifiable
   hypothesis and causal conclusion.
5. Trace `mcp_audit_delivery_latency_seconds` from durable Outbox creation through fenced
   acknowledgement, then explain how a future p95/p99 SLO would be formed.

Updated: 2026-08-20 on `codex/final-evidence-hardening-v1`. This is the authoritative teaching entry. Demonstrate every
answer with source, transaction boundary, test and evidence rather than memory. The original 2026-08-11 scheduler lessons
below remain a historical deep dive; the current curriculum adds final-hardening Agent Evaluation Infrastructure.

## Required reading order

1. [`PROJECT_STATUS.md`](../../PROJECT_STATUS.md)
2. [`PROJECT_EVIDENCE_MAP.md`](PROJECT_EVIDENCE_MAP.md)
3. Core domain/state-machine sources: `app/persistence/orm_models.py`, `app/jobs/`, `app/workers/`
4. [`EVALOPS_SCHEDULER_PERFORMANCE_TEACHING_HANDOFF.md`](../learning/EVALOPS_SCHEDULER_PERFORMANCE_TEACHING_HANDOFF.md)
5. [`FINAL_HARDENING_REPORT.md`](../final_hardening/FINAL_HARDENING_REPORT.md)
6. [`AGENT_EVALOPS_TUTORIAL.md`](../learning/AGENT_EVALOPS_TUTORIAL.md)
7. [`AGENT_EVAL_RESUME_EVIDENCE.md`](../resume/AGENT_EVAL_RESUME_EVIDENCE.md)
8. [`RESUME_METRIC_LEDGER.md`](RESUME_METRIC_LEDGER.md)
9. [`INTERVIEW_STORY_BANK.md`](INTERVIEW_STORY_BANK.md)

## Required workshop record for every module

Every one of the 21 modules must be taught and recorded in this order: **Concept** → **Real code chain** →
**SQL / transaction boundary** → **Test** → **Failure mode** → **Trade-off** → **Observed result** →
**Interview follow-up** → **Independent answer** → **Small modification exercise**. A learner has not completed a module
by reading the reference answer: they must first predict the failure, trace one transaction, answer unaided, and make or
design the bounded exercise without weakening an invariant.

## Current 21-module curriculum

The compact cards below contain all ten required workshop fields. Paths name the first evidence location; the required
reading above supplies the detailed walkthroughs.

### Curriculum 1 — Why Run, Job and Attempt are separate

- **Concept / Real code chain:** immutable input and desired work are distinct from an execution generation; trace
  `EvaluationRun → EvaluationJob → JobAttempt → CaseResult` in `app/persistence/orm_models.py` and `app/runs/`.
- **SQL / transaction boundary / Test:** Run creation is idempotent; claim creates the Attempt in the same PostgreSQL
  transaction; use Run idempotency and Job-claiming tests.
- **Failure mode / Trade-off / Observed result:** one mutable row loses retry history; more tables cost joins but preserve
  provenance; controlled evidence records unique Jobs/Attempts without claiming production capacity.
- **Interview follow-up / Independent answer / Small modification exercise:** explain why a retry is not a new Job; answer
  without notes; add a test that a second Attempt cannot overwrite the first Attempt's identity.

### Curriculum 2 — At-least-once versus exactly-once

- **Concept / Real code chain:** `lease_runner`, result/failure services and retry policy provide at-least-once execution
  with fenced durable acceptance, not exactly-once external effects.
- **SQL / transaction boundary / Test:** Job/Attempt/result updates are atomic inside PostgreSQL, while Target/tool effects
  are outside it; trace stale-result and retry tests.
- **Failure mode / Trade-off / Observed result:** a crash after an external side effect can repeat it; idempotency/fencing
  protect persisted results but cannot erase that window; the project explicitly retains this limitation.
- **Interview follow-up / Independent answer / Small modification exercise:** describe the crash window; state the guarantee
  unaided; design an idempotency key for one external Target without calling it exactly-once.

### Curriculum 3 — Lease, heartbeat and fencing token

- **Concept / Real code chain:** claim grants temporary owner/version/Attempt authority, heartbeat extends expiry, and each
  write revalidates all of it in `app/jobs/claiming.py`, `heartbeat.py`, `results.py` and `failures.py`.
- **SQL / transaction boundary / Test:** conditional updates lock/check the current Job and active Attempt in one transaction;
  use heartbeat and stale-write unit/concurrency tests.
- **Failure mode / Trade-off / Observed result:** Worker identity alone permits an old generation to write; shorter leases
  recover sooner but false-expire more easily; tested stale writes are rejected.
- **Interview follow-up / Independent answer / Small modification exercise:** explain why expiry must be checked at commit;
  enumerate the fence unaided; write a boundary test for an expired heartbeat.

### Curriculum 4 — How a stale Worker can overwrite a new result

- **Concept / Real code chain:** a paused Worker can resume after Reaper/retry assigned the Job to a new Attempt; compare
  old and current owner/version/Attempt in result and failure commits.
- **SQL / transaction boundary / Test:** serialization is at the locked Job/Attempt rows, not the Python process; run stale
  success and stale failure tests.
- **Failure mode / Trade-off / Observed result:** last-write-wins corrupts the accepted generation; strict fences reject late
  valid-looking work at the cost of discarding its computation; protected counters were zero in frozen scope.
- **Interview follow-up / Independent answer / Small modification exercise:** draw the two-Worker timeline; name every fence
  unaided; mutate one fence out of a test double and predict the failing assertion.

### Curriculum 5 — Reaper, retry and Attempt generation

- **Concept / Real code chain:** Reaper closes expired Attempts and chooses retry/fail/cancel before a replacement claim;
  trace `app/jobs/reaper.py`, retry policy and cancellation.
- **SQL / transaction boundary / Test:** `FOR UPDATE SKIP LOCKED` partitions expired Jobs among Reapers and closes the old
  Attempt atomically; use competing-Reaper and crash-recovery tests.
- **Failure mode / Trade-off / Observed result:** duplicate recovery can create conflicting generations; row locks constrain
  concurrency but do not prove universal liveness; tested recovery remains bounded.
- **Interview follow-up / Independent answer / Small modification exercise:** explain why Reaper owns no Target work; trace
  retry_count unaided; add a permanent-failure classification case.

### Curriculum 6 — PostgreSQL row locks and `SKIP LOCKED`

- **Concept / Real code chain:** row locks serialize mutations while `SKIP LOCKED` lets claimers make progress on other
  eligible rows; trace the ordered candidate query in `app/jobs/claiming.py`.
- **SQL / transaction boundary / Test:** the candidate selection and state transition share a transaction; inspect real
  PostgreSQL claim and parallelism tests.
- **Failure mode / Trade-off / Observed result:** locked first candidates can be invisible, and inconsistent lock order can
  deadlock; non-blocking progress trades complete visibility for throughput; bounded CI passes.
- **Interview follow-up / Independent answer / Small modification exercise:** contrast blocking and skip-locked selection;
  explain the visibility gap unaided; alter a test fixture to lock the first eligible Job.

### Curriculum 7 — Deterministic false-empty race

- **Concept / Real code chain:** the selected tenant can still have an eligible but locked Job, so an empty skip-locked query
  must not consume its durable permit; trace the independent eligibility probe in `claiming.py`.
- **SQL / transaction boundary / Test:** one transaction holds the Job lock while another claims; Barrier/Event-controlled
  real-PostgreSQL tests reproduce RED then GREEN.
- **Failure mode / Trade-off / Observed result:** consuming on false-empty overtakes the tenant; a second probe adds query
  cost but preserves `PENDING`; one RED and two GREEN workflows document the repair.
- **Interview follow-up / Independent answer / Small modification exercise:** narrate the exact interleaving; distinguish
  “no visible row” from “no eligible row”; add a second locked eligible Job to the fixture.

### Curriculum 8 — Durable fair-turn scope

- **Concept / Real code chain:** reusable per-tenant round state controls durable receipt order; it is not a proof of universal
  fairness; trace fair-turn state and permit consumption in `claiming.py`.
- **SQL / transaction boundary / Test:** round membership/turn and claim mutate transactionally; use deterministic fairness
  tests and frozen targeted evidence.
- **Failure mode / Trade-off / Observed result:** reservation order can differ from durable receipt order; state adds lock
  contention; exact frozen 20:1 observations moved secondary receipt position from 953 to 2.
- **Interview follow-up / Independent answer / Small modification exercise:** state what the experiment cannot prove; answer
  its exact workload unaided; propose a new test without changing the frozen benchmark.

### Curriculum 9 — Trajectory artifact schema

- **Concept / Real code chain:** a framework-neutral envelope records steps, tool calls, handoffs and context events in
  `app/agent_eval/schemas.py` and artifact models.
- **SQL / transaction boundary / Test:** metadata and tenant reference persist in PostgreSQL while content uses the artifact
  storage path; schema and Agent workflow tests validate shape/ownership.
- **Failure mode / Trade-off / Observed result:** framework-specific traces cannot be compared consistently; a neutral schema
  loses some native detail but enables deterministic fixtures; eight fixed adapters are fixture replay only.
- **Interview follow-up / Independent answer / Small modification exercise:** identify required versus optional identity;
  explain why this is not “all frameworks supported”; add one invalid-step schema case.

### Curriculum 10 — canonical JSON and SHA-256

- **Concept / Real code chain:** canonical serialization makes semantically identical normalized artifacts produce stable
  bytes and SHA-256 identity; trace canonical helpers and artifact ingestion.
- **SQL / transaction boundary / Test:** digest identity is computed before immutable metadata/reference persistence; canonical
  ordering and hash tests cover determinism.
- **Failure mode / Trade-off / Observed result:** ordinary JSON key/number differences create unstable hashes; normalization
  constrains accepted forms; current artifacts have reproducible content identity, not signatures.
- **Interview follow-up / Independent answer / Small modification exercise:** distinguish hash identity from authenticity;
  derive the stable-byte rule unaided; add a key-order equivalence test.

### Curriculum 11 — immutable Agent artifact ingestion

- **Concept / Real code chain:** accepted trajectory content and provenance are append-only evidence; trace Agent ingestion
  service, ArtifactBlob/Reference and migration `20260820_0019`.
- **SQL / transaction boundary / Test:** database identity/metadata commit is atomic only within PostgreSQL; object bytes are
  a separate store; API/workflow tests reject conflicting reuse.
- **Failure mode / Trade-off / Observed result:** mutation invalidates past comparisons; immutability creates versions and
  storage growth; integration evidence confirms stable replay.
- **Interview follow-up / Independent answer / Small modification exercise:** explain why update-in-place is unsafe; list the
  immutable fields unaided; add a conflicting digest/metadata test.

### Curriculum 12 — seven deterministic trajectory metric extractors

- **Concept / Real code chain:** exactly seven deterministic extractor kinds map a stored trajectory to reproducible metric
  records; trace `app/agent_eval/evaluators.py` and schemas.
- **SQL / transaction boundary / Test:** extraction runs from persisted evidence and result rows commit with identity/provenance;
  unit and Agent workflow tests cover every kind.
- **Failure mode / Trade-off / Observed result:** calling them “verified evaluators” overstates authority; deterministic rules
  are reproducible but bounded; all seven kinds pass current CI as extractors.
- **Interview follow-up / Independent answer / Small modification exercise:** name the distinction between deterministic and
  verified; classify one extractor unaided; add an invalid-input test without adding an eighth public kind.

### Curriculum 13 — reported versus derived provenance

- **Concept / Real code chain:** `reported` values come from the producer; `derived` values are computed from stored trajectory;
  neither is authority-verified; trace metric provenance fields and migration `20260820_0025`.
- **SQL / transaction boundary / Test:** provenance is persisted with the metric record in its transaction; schema/evaluator
  and migration tests enforce the enum/shape.
- **Failure mode / Trade-off / Observed result:** merging sources makes trust invisible; explicit provenance adds query/policy
  work; current records keep the distinction.
- **Interview follow-up / Independent answer / Small modification exercise:** say what evidence would justify `verified`;
  classify task-success unaided; test explicit opt-in for reported task success.

### Curriculum 14 — common-case-only regression

- **Concept / Real code chain:** a comparison evaluates only the explicit common case set unless a named policy permits
  difference; trace `app/agent_eval/regression.py` and `regression_service.py`.
- **SQL / transaction boundary / Test:** immutable manifest pins baseline/candidate artifact and result IDs before verdict
  persistence; unit/API/workflow tests cover exact/intersection/allow-diff.
- **Failure mode / Trade-off / Observed result:** comparing aggregate runs with different cases creates false conclusions;
  common cases improve comparability but reduce coverage; verdict includes scope.
- **Interview follow-up / Independent answer / Small modification exercise:** explain intersection bias; choose a policy
  unaided for a missing case; add a manifest-replay assertion.

### Curriculum 15 — case-set, coverage and sufficiency fail-closed

- **Concept / Real code chain:** verdicts require explicit case policy, minimum common samples and coverage; insufficient
  evidence cannot become PASS.
- **SQL / transaction boundary / Test:** evidence counts/manifest and verdict persist together; regression tests cover missing,
  low-coverage and low-sample branches.
- **Failure mode / Trade-off / Observed result:** a one-case overlap can look excellent; fail-closed gates reduce false PASS
  at the cost of more inconclusive results; current tests exercise insufficiency.
- **Interview follow-up / Independent answer / Small modification exercise:** distinguish failure from insufficient evidence;
  calculate coverage unaided; raise a threshold in a test and predict the verdict.

### Curriculum 16 — source-bound double review and adjudication

- **Concept / Real code chain:** review packets bind source/result/artifact hashes and stage evaluator visibility before
  adjudication; trace human-review service and migration `20260820_0022`.
- **SQL / transaction boundary / Test:** task creation and immutable source identity commit in PostgreSQL; API/workflow tests
  cover reviewer visibility and packet SHA.
- **Failure mode / Trade-off / Observed result:** showing prior judgments anchors reviewers; staged visibility costs workflow
  complexity; current evidence makes packet identity auditable, not objectively true.
- **Interview follow-up / Independent answer / Small modification exercise:** explain double-review independence; describe the
  hash chain unaided; test that a packet hash changes when source identity changes.

### Curriculum 17 — MCP per-call authentication

- **Concept / Real code chain:** authentication/authorization is revalidated for every MCP stdio tool/resource call, including
  after credential revocation; trace MCP server/auth code and audit resource identity.
- **SQL / transaction boundary / Test:** each call obtains tenant context for its database work; a real stdio subprocess test
  revokes credentials between calls and expects denial.
- **Failure mode / Trade-off / Observed result:** session-only auth leaves revoked credentials active; per-call checks add
  latency but close that window; current local-stdio CI passes.
- **Interview follow-up / Independent answer / Small modification exercise:** explain why connection auth is insufficient;
  state the transport boundary unaided; add a resource-read revocation case.

### Curriculum 18 — Agent evidence RLS and composite foreign keys

- **Concept / Real code chain:** tenant ownership is repeated in Agent rows and composite references so cross-tenant links
  cannot rely only on service filtering; RLS consumes transaction tenant context.
- **SQL / transaction boundary / Test:** `SET LOCAL`-style context/policies and composite foreign keys live within a database
  transaction; RLS and tenant-consistency integrations exercise them.
- **Failure mode / Trade-off / Observed result:** global-ID-only FKs permit ownership mismatch and owner roles may bypass RLS;
  redundancy improves defense but complicates migrations; current CI covers the configured topology.
- **Interview follow-up / Independent answer / Small modification exercise:** explain why composite ownership matters; state
  the shared-role limitation unaided; design a cross-tenant insert rejection.

### Curriculum 19 — orphan-object reconciliation

- **Concept / Real code chain:** a dry-run-first reconciler finds unreferenced object-store blobs after grace, rechecks before
  deletion, retries failures and records durable audit events.
- **SQL / transaction boundary / Test:** PostgreSQL reference scan/audit and object deletion are separate operations; real
  PostgreSQL/MinIO tests cover dry-run, grace, recheck and retry.
- **Failure mode / Trade-off / Observed result:** deleting immediately can race an in-flight database commit; grace/recheck
  retain garbage longer but reduce false deletion; reconciliation integration passes current CI.
- **Interview follow-up / Independent answer / Small modification exercise:** narrate an upload-before-commit crash; explain
  recheck unaided; add a newly referenced object between scan and delete.

### Curriculum 20 — PostgreSQL and object storage are not one atomic transaction

- **Concept / Real code chain:** database commit and S3/MinIO object mutation have no shared transaction manager; artifact
  service and reconciler implement compensation, not two-phase commit.
- **SQL / transaction boundary / Test:** only database rows share ACID; HTTP object calls sit outside; artifact and reconciliation
  tests cover known failure windows.
- **Failure mode / Trade-off / Observed result:** either side may succeed alone; compensation is simpler and eventually repairs
  known orphans but cannot promise atomicity; limitation remains explicit.
- **Interview follow-up / Independent answer / Small modification exercise:** enumerate both half-commit states; reject the
  atomicity claim unaided; design an outbox-based cleanup trigger without claiming 2PC.

### Curriculum 21 — portfolio-ready is not release-ready

- **Concept / Real code chain:** engineering depth and honest evidence make a portfolio useful while frozen release gates can
  still fail; trace release decision, final report and current status.
- **SQL / transaction boundary / Test:** no single SQL transaction changes an evidence verdict; fail-closed assessors and
  cross-document tests preserve boundaries.
- **Failure mode / Trade-off / Observed result:** hiding negative scaling creates a misleading resume; layering it as historical
  protects candor while current Agent capabilities lead; v0.1.0 remains `NOT_READY_TARGETED_NEGATIVE_SCALING`.
- **Interview follow-up / Independent answer / Small modification exercise:** defend the stop decision; state
  `portfolio-ready != release-ready != production-ready` unaided; classify a new claim into resume/interview/forbidden tiers.

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
# 2026-09-02 required product-workflow module

Add [`PRODUCT_EXPERIMENT_WORKFLOW.md`](../learning/PRODUCT_EXPERIMENT_WORKFLOW.md) to the required
teaching path. The module explains why the existing control plane needed a thin product entry,
how exact-case pairing and paired bootstrap prevent misleading averages, how provider secrets
and SSRF are bounded, why deterministic demo success is not formal quality evidence, and how
`INPUT_REQUIRED`/`HUMAN_REVIEW_PENDING` preserve honest state. The implementation/evidence SHA
is `41de043f40c02c0d1349332c6bd19e9116202838`; exact implementation CI `33589528112` succeeded
and the same SHA was non-force fast-forwarded to default `main`.
