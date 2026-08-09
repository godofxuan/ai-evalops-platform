# Frozen concurrent fairness invariant

Status: `FROZEN_BEFORE_PRODUCTION_CHANGE`

## What is being made fair?

Five different orders exist in the current scheduler. Treating them as interchangeable caused Candidate 2's design error.

| Label | Observable order | Is it the release gate? |
|---|---|---|
| A | Tenant reservation order: Phase A locks a Tenant fair-turn row, updates `last_scheduler_turn_at`, and commits. | No. It is an internal scheduling decision. |
| B | Job lock acquisition order: Phase B obtains `FOR UPDATE OF evaluation_jobs SKIP LOCKED`. | No. A lock may be held before its transaction commits. |
| C | durable Job transaction commit order: Job, lease, version, Attempt, Audit and Outbox changes become visible together. | A required database diagnostic, but the frozen harness does not directly timestamp the PostgreSQL commit. |
| D | committed receipt order: `SQLAlchemyJobClaimer.claim()` has exited its transaction and returned a `ClaimedJob`; the harness immediately records a monotonic application timestamp. | **Yes. This is the existing frozen `position <= 2` observation point.** |
| E | result completion order: Target and Evaluator work later produce or fail a result. | No. Execution duration is unrelated to scheduler admission fairness. |

The Candidate 3 gate remains D. A database-linearized sequence may be added to distinguish C from D, but it supplements rather than replaces the frozen application-visible receipt.

## Workload preconditions

The strict two-Tenant invariant applies when:

- both Tenants already have equal-priority eligible Jobs at first-wave start;
- the queue distribution is the frozen 20:1 skew;
- worker concurrency is 8 and claim limit is 1;
- the secondary Tenant is not introduced after the wave starts;
- every repetition is judged separately, not by an average that hides a failure.

## Invariants

### F1 — Priority preservation

If an eligible Job has higher priority than another eligible Job, Tenant fairness alone must not admit the lower-priority Job first. Fairness is applied within the current highest eligible priority class.

### F2 — Equal-priority Tenant fairness

Under the workload preconditions above, the secondary Tenant's first durable committed `claim()` receipt must have global position `<= 2` in every frozen-protocol repetition.

### F3 — No starvation

A Tenant that continuously has eligible work at the active priority cannot be bypassed by other same-priority Tenants without bound. The implementation must identify a finite scheduler boundary at which that Tenant is admitted.

### F4 — Job uniqueness

Exactly one Worker can durably transition a Job into the claimed/running state for a given Attempt. First-wave and full-drain reconciliation must find no duplicated Job claims or Attempts.

### F5 — No false empty

While claimable unlocked work exists, scheduler coordination must not make Workers return empty indefinitely. A transient nonblocking miss must either wait on bounded database coordination or retry through an explicit liveness path.

### F6 — Fencing preservation

Candidate 3 must preserve Attempt identity and sequence, Job version, lease owner, lease expiry, heartbeat and stale success/failure rejection. Scheduler fairness is not permission to weaken result fencing.

### F7 — Crash safety

A crash at any scheduler/claim boundary must not lose a Job, create a permanent permit leak, starve a Tenant permanently, or publish a lease without the atomic Job/Attempt/Audit/Outbox transaction. Recovery must follow from committed database state; no in-memory owner is authoritative.

### F8 — Bounded coordination

Scheduler/global coordination locks may exist only in short database transactions. They must never cross Target execution, Evaluator execution, result processing, or general Worker work. If a global linearization row is used, it must not be held while constructing the full claim transaction.

## Linearization obligations

A valid Candidate 3 proposal must state all of the following before code changes:

1. which durable state decides membership in the next fair admission unit;
2. which lock prevents a hot Tenant from accumulating overtaking admissions;
3. what event permits the scheduler to advance to the next admission unit;
4. where database claim order is linearized, if a diagnostic sequence is introduced;
5. what happens when a Worker rolls back or disappears at each boundary.

## Non-negotiable test oracle

The implementation may add stronger diagnostics, but it may not modify the 20:1 distribution, 8 Workers, limit 1, seed, case count, receipt timestamp, per-repetition decision, or `<= 2` threshold. Candidate 2's position 4 remains a failure. Candidate 3 must pass the same oracle or the redesign stops.
