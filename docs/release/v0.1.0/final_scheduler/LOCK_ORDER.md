# Scheduler and worker lock-order audit

Date: 2026-08-09  
Audited source: `app/jobs/claiming.py`, `results.py`, `failures.py`, `heartbeat.py`, `reaper.py`,
`cancellation.py`, `runs/aggregation.py`, and `events/outbox.py`

## Legend

- `NKU`: `FOR NO KEY UPDATE`
- `KS`: `FOR KEY SHARE`
- `U`: `FOR UPDATE`
- `SL`: `SKIP LOCKED`
- `FK`: implicit key-preserving lock caused by a foreign-key check
- `→`: locks are held in the same transaction in this order
- `| COMMIT |`: previous locks have been released; this is not an overlapping lock edge

## Scheduler claim

```text
Phase A: Tenant NKU+SL → update last_scheduler_turn_at → COMMIT

Phase B: Job U+SL
         → Job fields / Attempt insert
         → conditional Run UPDATE when still queued
         → Audit insert (Tenant FK KS)
         → Outbox insert (Tenant/Run FK key-preserving checks)
         → COMMIT
```

The crucial graph is `Tenant | COMMIT | Job → compatible Tenant FK`, not one long `Tenant → Job` transaction.
Therefore it cannot form an incompatible production cycle with a concurrent `Job → Tenant` Phase-B FK check.

## Result success

```text
Tenant KS → Run U → owned Job U → active Attempt U
          → CaseResult insert (Tenant/Run/Job FK checks)
          → Audit insert
          → aggregate Run while already held
          → Outbox insert
          → COMMIT
```

Tenant KS was introduced before the Run/Job locks to avoid the historical Tenant↔Run FK upgrade deadlock. KS is
compatible with the scheduler's Tenant NKU lock.

## Failure commit

```text
owned Job U → active Attempt U → Job/Attempt flush
            → Run U in aggregation
            → Audit and Outbox inserts with FK checks
            → COMMIT
```

The transaction only operates on the leased Job. Exact owner/version/expiry predicates fence stale workers.

## Reaper

```text
expired Jobs U+SL, ordered by lease expiry and Job id
  → each active Attempt U
  → flush Job/Attempt changes
  → touched Runs U in deterministic string-sorted Run-id order
  → Audit and Outbox inserts
  → COMMIT
```

Multiple Reapers skip already locked Jobs. Deterministic Run ordering and “aggregate before Outbox” were retained from
the earlier real PostgreSQL deadlock fix.

## Cancellation

```text
tenant-scoped Run read (no row lock)
  → Tenant KS
  → Run U
  → all nonterminal Jobs U ordered by Job id
  → Audit/Outbox inserts
  → aggregation while Run already held
  → COMMIT
```

Cancellation's explicit Tenant→Run→Jobs order matches result completion's prefix and uses compatible Tenant KS.

## Heartbeat

```text
single conditional Job UPDATE/RETURNING → COMMIT
```

Owner, expected version, live expiry and running/cancelling status are in one statement. It takes no Tenant, Run,
Attempt, Audit or Outbox lock.

## Outbox dispatcher and cleanup

```text
dispatcher claim: Outbox U+SL → lease fields → COMMIT
ack/reschedule:   single conditional Outbox UPDATE → COMMIT
cleanup:          Outbox U+SL in deterministic order → DELETE → COMMIT
```

Publishing occurs after the claim transaction commits, so network I/O is never performed while a database row lock is
held.

## Entity inventory

| Entity | Explicit row locks | Important implicit/write locks |
|---|---|---|
| Tenant | Phase A NKU+SL; result/cancellation KS | FK checks from Audit, Outbox, CaseResult and other tenant-owned rows |
| Run | result/cancellation/aggregation U | conditional UPDATE during first claim; FK checks from Outbox/Result |
| Job | claim/reaper U+SL; result/failure/cancellation U; heartbeat UPDATE | FK checks from Attempt/Result |
| Attempt | result/failure/reaper U | unique `(job_id, attempt_number)` and Job FK on insert |
| Audit | no pre-existing row lock; INSERT | Tenant FK and resource metadata |
| Outbox | dispatcher/cleanup U+SL; ack/reschedule UPDATE | Tenant and Run FK checks on business-transaction insert |
| CaseResult | no pre-existing row lock; INSERT | Tenant, Run and Job lineage FKs plus uniqueness constraints |

## Cycle audit conclusion

The scheduler-specific forbidden cycle is absent in the candidate:

```text
forbidden: Txn A holds incompatible Tenant lock and waits for Job
           Txn B holds Job and waits for incompatible Tenant lock
```

Production Phase A never waits for or locks a Job before commit. Production Phase B may hold a Job before an implicit
Tenant FK lock, but that lock is compatible with Phase A NKU and with result/cancellation Tenant KS. The deliberate
diagnostic that holds external `Tenant FOR UPDATE` is the only reproduced incompatible edge; it is bounded and expected
to yield `55P03`, not a production scheduler path.

Run/Job ordering differs among older completion paths, but the audited waits do not supply the reverse dependency
needed for the scheduler Tenant↔Job cycle: result/cancellation already hold Run while later locking their target Jobs;
failure/Reaper aggregate Run after their Job locks but do not then acquire another conflicting Job lock. Existing real
concurrency/fault tests remain required; this audit does not replace them.
