# Candidate 3 state machine

Status: `FROZEN_BEFORE_PRODUCTION_CHANGE`

## Durable records

### Scheduler coordination singleton

`scheduler_coordination(id=1)` contains:

- `active_generation >= 0`;
- nullable `active_priority` (`NULL` before the first round);
- `durable_claim_sequence >= 0`;
- timestamps/version for diagnosis.

Only a refill transaction changes generation/priority. A claim transaction locks this row only at its tail to assign a monotonic diagnostic sequence.

### Per-Tenant scheduler state

`tenant_scheduler_states` has one reusable row per participating Tenant:

- `tenant_id` primary key and FK to `tenants.id ON DELETE CASCADE`;
- `generation > 0` plus Tenant form the permit identity;
- `round_priority` and `permit_order` freeze round membership;
- `status in {PENDING, CONSUMED, EMPTY}`;
- `version > 0` increments whenever the row is reused.

The `(generation, tenant_id)` unique constraint prevents duplicate membership. Reuse bounds storage to O(number of Tenants); no history GC is required.

### Job and Worker state

Job transitions remain the existing `QUEUED/RETRY_WAIT -> RUNNING` transition, lease/version/heartbeat fields and Attempt creation. A Worker owns no authoritative scheduler state in memory. `JobAttempt.scheduler_claim_sequence` is nullable for historical Attempts and unique/positive for Candidate 3 claims.

## Normal flow

```text
NO ACTIVE PENDING ROUND
  -> lock scheduler singleton
  -> find highest eligible priority P
  -> generation G := G + 1
  -> upsert one PENDING state per eligible Tenant at P
  -> commit refill

PENDING(T,G,P)
  -> lock state T (SKIP LOCKED fast path; blocking fallback)
  -> lock one eligible Job of T at exact P
  -> existing Job/lease/version/Attempt/Audit/Outbox writes
  -> state PENDING -> CONSUMED
  -> tail-lock singleton; sequence := sequence + 1
  -> attach sequence to Attempt
  -> commit
  -> return committed ClaimedJob receipt
```

When every G state is terminal, a later claimant may refill G+1.

## Races

### Multiple refill attempts

All contenders serialize on the singleton. The first creates the round; later contenders recheck and see a pending member, then leave without incrementing generation.

### Multiple Workers, same Tenant

Only one can lock `(Tenant,G,PENDING)`. Others skip it or wait. No second state for that Tenant exists in G, and G+1 cannot open while any member of G is pending.

### Multiple Workers, different Tenants

They lock different state and Job rows and may construct their claim transactions concurrently. Only the tail diagnostic sequence is globally serialized immediately before commit.

### Pending state but Job vanished

Cancellation or another legal transition may make the seeded Tenant empty. The claimant atomically marks that state `EMPTY` and returns no Job. The caller rechecks global eligibility; if work remains, it participates in the next pending/refill path rather than treating one empty permit as global queue exhaustion.

## Crash matrix

| Crash point | Durable state | Recovery/effect |
|---|---|---|
| before refill commit | old generation only | Whole refill rolls back; another Worker retries. |
| after refill commit, before state lock | PENDING permit | Any Worker can consume it; no owner/lease can leak. |
| after state lock, before Job lock | uncommitted locks | PostgreSQL rollback releases the state; it remains PENDING. |
| during Job/Attempt/Audit/Outbox writes | uncommitted Job and state | Atomic rollback restores both. No lease or partial Outbox survives. |
| after sequence increment, before commit | uncommitted sequence/Attempt | Increment rolls back with the claim; next claim reuses the next durable integer. |
| after commit, before application receipt | CONSUMED + RUNNING Job + Attempt | Claim is durable. Existing lease expiry/reaper recovers a lost Worker; scheduler round may advance. |
| during external Target/Evaluator work | no scheduler lock held | Existing heartbeat/result/failure/reaper state machines apply unchanged. |

## Retry, cancellation and reaper interaction

- `RETRY_WAIT` is eligible only when `next_attempt_at <= eligible_at`; claiming still performs the existing audited transition through `QUEUED`.
- Cancellation before a permit's claim can produce `EMPTY`; cancellation after claim follows current running-Job rules and fencing.
- Reaper only handles durable `RUNNING` Jobs/leases. It never repairs scheduler permits because an uncommitted permit consumption rolls back and a committed one is already terminal.
- A requeued Job becomes eligible for a future generation; no old permit token is reused.

## Empty queue

If no eligible priority exists while the singleton is locked, refill does not increment generation and `claim()` returns the accumulated batch (possibly empty). `NOT_RUN` or empty benchmark arms are never encoded as zero evidence.

## Lock order

```text
refill: scheduler singleton -> read eligible Jobs/Runs -> upsert terminal state rows
claim:  Tenant scheduler state -> EvaluationJob -> existing Run/Audit/Outbox writes
        -> scheduler singleton (tail sequence only) -> COMMIT
```

The apparent opposite singleton/state order cannot form a cycle: refill upserts state rows only after its current-snapshot check found no pending state. An in-flight claim's uncommitted transition remains visibly PENDING, causing refill to exit without touching that state. This claim is still regression-tested under real PostgreSQL timeouts.

## Migration and rollback

Upgrade creates both tables, inserts singleton row 1, adds constraints/indexes/FKs and adds the nullable unique positive Attempt sequence. Existing Attempts remain valid with `NULL`. Downgrade removes the sequence and Candidate 3 tables. The Candidate 2 `Tenant.last_scheduler_turn_at` column remains available, so code rollback does not require reconstructing discarded scheduling timestamps.
