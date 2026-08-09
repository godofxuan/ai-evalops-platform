# Final Scheduler PostgreSQL lock diagnostic

Date: 2026-08-09  
Diagnostic source commit: `86767e71d4d50a760db27f91fa5d42e998ec9e38`  
Push CI: [31314586983](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31314586983)  
PR CI: [31314589931](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31314589931)

## Outcome first

H2 is confirmed. A durable claim can select and lock an `evaluation_jobs` row while another transaction holds
`Tenant FOR UPDATE`, but it cannot finish its mandatory `audit_events` insert because PostgreSQL's Tenant foreign-key
check needs a compatible key-preserving lock. The strong external Tenant lock blocks that check. The resulting wait is
not in the Job selector and is not a lease/fencing failure.

The control experiment also passed: holding `Tenant FOR NO KEY UPDATE` allows the same complete durable claim to
finish. This is the direct evidence supporting the H3 candidate: retain Tenant mutual exclusion and `SKIP LOCKED`, but
use the weakest lock mode compatible with updating only `last_scheduler_turn_at`.

## Why the old six-hour run was not evidence

The old test allowed the database wait and Python await to remain unbounded. CI runs `31297535370` and
`31297538171` were cancelled only after approximately six hours. A cancellation at the workflow ceiling did not say
which statement waited, which PID blocked it, or whether PostgreSQL would eventually make progress.

Commit `1b6a2f8` added three independent bounds:

| Layer | Bound | Purpose |
|---|---:|---|
| PostgreSQL transaction | `lock_timeout=1500ms` | Turn an incompatible lock wait into SQLSTATE `55P03` |
| PostgreSQL transaction | `statement_timeout=8000ms` | Bound non-lock SQL stalls as a separate last resort |
| Python await | 15 seconds | Prevent a lost/cancelled task from hanging pytest |
| CI step | 10 minutes | Bound the entire same-tenant suite and its cleanup |

The next push CI `31314066767` failed in `3m49s`, not six hours. Its annotation located the failure in
`INSERT INTO audit_events`: PostgreSQL reported the Tenant FK check's `FOR KEY SHARE` and SQLSTATE `55P03`.

## H2 experiment matrix

Commit `86767e7` split the misleading combined test into three explicit experiments. CI #100 reported only the
deliberately still-red 8-worker contention assertion, so all three experiments below passed before the artifact upload:

| Experiment | External lock | Operation under test | Expected | Observed |
|---|---|---|---|---|
| Selector-only | `Tenant FOR UPDATE` | Job-only selector | Returns the first eligible Job | PASS |
| Durable diagnostic | `Tenant FOR UPDATE` | Job + Attempt + lease/version + Audit + Outbox commit | Captures lock graph, then `55P03` | PASS |
| Compatibility control | `Tenant FOR NO KEY UPDATE` | Same complete durable claim | Returns and commits the first Job | PASS |

This distinction matters: the selector is independent of the Tenant row, while the durable write set intentionally is
not independent because Audit and Outbox rows carry Tenant foreign keys.

## Raw PostgreSQL evidence

Artifact metadata:

- name: `final-scheduler-lock-diagnostics-31314586983-1`
- artifact id: `9038393415`
- size reported by GitHub: 1,192 bytes compressed
- expanded JSONL size: 14,339 bytes
- GitHub digest: `sha256:71dd44d0bbc4b1b4589b419154246e84d8b2719a21a21038c056fbfc6f926df4`
- independently downloaded ZIP SHA-256: the same digest
- created: `2026-08-09T13:01:10Z`
- expires: `2026-11-07T12:57:44Z`

The JSONL record contains the complete relevant rows from `pg_stat_activity`, `pg_blocking_pids(pid)` and
`pg_locks`. Its decisive fields are:

A source-controlled focused projection is preserved at
`raw/h2-lock-projection-31314586983.json`. It explicitly identifies itself as a projection; the complete raw record is
the digest-bound GitHub artifact above.

| Evidence | Value |
|---|---|
| Blocker PID | `397` |
| Blocker SQL | `SELECT tenants.id ... FOR UPDATE` |
| Blocker state | `idle in transaction` |
| Blocker transaction | `1191`, `ExclusiveLock`, granted |
| Target PID/application | `399` / `final-scheduler-durable-for-update` |
| `pg_blocking_pids(399)` | `[397]` |
| Target wait | `wait_event_type=Lock`, `wait_event=transactionid` |
| Target requested transaction lock | transaction `1191`, `ShareLock`, `granted=false` |
| Target write evidence | `RowExclusiveLock` on `audit_events` and both relevant indexes |
| Target Tenant evidence | tuple lock on relation `tenants`, page `0`, tuple `88` |

One nuance is preserved rather than hidden: at the snapshot instant, `pg_stat_activity.query` for PID 399 displayed
the test begin-hook's latest `SET LOCAL statement_timeout` text even though its wait and acquired relation locks already
showed the durable write path. The CI exception independently names the blocked `INSERT INTO audit_events` and the FK
trigger's `FOR KEY SHARE`. The conclusion therefore relies on the complete cross-source lock evidence, not on that one
query-text column.

## Lock relationship

```text
PID 397: Tenant FOR UPDATE
  owns transaction 1191 ExclusiveLock
                    |
                    | pg_blocking_pids(399) = [397]
                    v
PID 399: durable claim
  selected/locked Job
  began audit_events write
  needs Tenant FK key-preserving lock
  waits for ShareLock on transaction 1191 (not granted)
```

## Decision

H2: `CONFIRMED`.  
H3 may proceed as one minimal production iteration: compile and use
`FOR NO KEY UPDATE OF tenants SKIP LOCKED` in Phase A only. Phase B's Job lock, atomic durable write set, lease,
version, audit, Outbox and fencing behavior must remain unchanged and must be requalified in real PostgreSQL CI.
