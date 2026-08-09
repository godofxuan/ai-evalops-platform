# Final scheduler production design

Date: 2026-08-09

## Outcome first

The accepted candidate remains a PostgreSQL two-phase scheduler. It does not add a queue coordinator or move durable
truth outside PostgreSQL. Phase A records a fair Tenant turn in a short transaction. Phase B independently claims one
Job and atomically establishes the execution lease and all durable side effects.

## Transaction boundaries

### Phase A — fair-turn reservation

One short transaction:

1. materialize eligible Job ranks per Tenant;
2. select the priority-first/fair Tenant candidate;
3. acquire `FOR NO KEY UPDATE OF tenants SKIP LOCKED`;
4. recheck Job and Run eligibility in the outer locking query;
5. update only `Tenant.last_scheduler_turn_at`;
6. commit and release the Tenant lock.

Phase A creates no Attempt, no Job lease, no Audit event and no Outbox event. If the worker exits after commit, no Job
is lost because no Job changed state.

### Phase B — durable Job claim

A separate transaction:

1. select one eligible Job inside the reserved Tenant using
   `FOR UPDATE OF evaluation_jobs SKIP LOCKED`;
2. revalidate Job/Run eligibility;
3. transition the Job to `running` and establish owner, expiry, heartbeat and incremented version;
4. create one unique `JobAttempt`;
5. conditionally transition a queued Run to running;
6. add Audit rows and transactional Outbox rows;
7. commit before returning `ClaimedJob` to the Worker.

Phase B does not explicitly acquire the Tenant scheduler row lock. Its Tenant-referencing durable inserts still cause
PostgreSQL foreign-key checks and compatible key-preserving locks. Saying “Phase B does not lock Tenant” without that
qualification is inaccurate.

## Concurrency properties

- Two Phase-A writers for the same Tenant remain mutually exclusive because `FOR NO KEY UPDATE` conflicts with another
  same-row `FOR NO KEY UPDATE` writer.
- `SKIP LOCKED` lets a scheduler choose Tenant B instead of waiting behind Tenant A.
- Phase-B FK key-preserving locks are compatible with the Phase-A non-key update lock, so the durable write does not
  wait behind an unnecessarily strong `FOR UPDATE` reservation.
- Job uniqueness remains enforced by `FOR UPDATE SKIP LOCKED`, Job status predicates and unique Attempt/Result
  constraints.
- Result/failure/heartbeat fencing remains based on lease owner, live expiry and exact version.

## Reservation miss semantics and observability

Two-phase scheduling can reserve a Tenant and then find no Job in Phase B because another worker claimed the last
eligible row. This is an efficiency signal, not automatically a correctness error.

Each worker process now exports:

- `tenant_turn_reserved_total` after Phase A commits a Tenant reservation;
- `tenant_turn_without_job_total` only when that reservation reaches Phase B and finds no Job;
- `reservation_miss_rate` as process-local misses divided by reservations.

No Tenant/Run/Job identifiers are metric labels. Cross-process analysis sums the counters; PostgreSQL remains the
durable source of truth. The formal capacity runner also records reservation latency, Job-claim latency and the same
reserved/miss/rate values per arm.

## Crash behavior

| Crash point | Durable state | Recovery |
|---|---|---|
| Before Phase-A commit | No reservation change | Another worker selects normally |
| After Phase-A commit, before Phase B | Fair timestamp advanced; Job still queued/retry-wait; no lease | Another worker eventually reserves and claims |
| During Phase-B transaction | Transaction rollback; no partial Attempt/lease/Audit/Outbox | Job remains eligible according to committed state |
| After Phase-B commit, before execution | Job has a fenced lease and Attempt | Heartbeat/Reaper contract recovers expiry |

## Scope deliberately unchanged

- no third scheduler phase;
- no new queue infrastructure;
- no relaxed fencing, idempotency or tenant isolation;
- no retry/sleep/pool/lease parameter tuning;
- no claim batch-size change;
- no change to result commit, failure commit, heartbeat or Reaper algorithms.

The detailed explicit and implicit lock inventory is in `LOCK_ORDER.md`.

## Qualification state

The production algorithm in commit `18fb876` and the production-shaped PostgreSQL contracts in commit `9ac7088`
passed both push CI `31315634340` and PR CI `31315639504`. This establishes the transaction and correctness design; it
does not establish the release performance claim. Repeated targeted scaling, capacity, current fault injection and
formal 32-arm evidence remain separate gates.
