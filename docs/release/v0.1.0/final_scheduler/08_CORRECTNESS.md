# Final scheduler correctness evidence

Date: 2026-08-09  
Initial real-PostgreSQL qualification source: `9ac70886c03c2d3a21ae667f47c5b5971c90ed4d`

## Outcome first

All initial production-shaped scheduler contracts passed push CI `31315634340` and PR CI `31315639504`. No lease,
version, Attempt, Audit, Outbox, result or stale-worker fence was weakened. Final correctness remains `PENDING` only
because the 10W/100J `limit=1` contract was subsequently strengthened from one full drain to 20 full drains and must
be run at the next source SHA.

## Contract matrix

| Contract | Result at `9ac7088` | Evidence meaning |
|---|---|---|
| selector under external Tenant lock | PASS | explicit Phase-B candidate selection is Job-only |
| external Tenant `FOR UPDATE` diagnostic | PASS, expected `55P03` | full writes still honor FK lock semantics |
| external Tenant `FOR NO KEY UPDATE` control | PASS | minimum lock is compatible with durable FK writes |
| short reservation/durable-claim overlap | PASS | production-shaped transactions complete in bounded time |
| same-Tenant reservation exclusion | PASS | two fair-turn writers cannot own the row together |
| cross-Tenant `SKIP LOCKED` progress | PASS | Tenant B progresses while Tenant A is held |
| reservation-only crash | PASS | queued Job has no lease/Attempt and is recoverable |
| priority before fairness | PASS | high-priority Job remains first across Tenants |
| 10W/100J, `limit=1` | PASS for one full drain | 100 unique claims and 100 Attempts; 20 repetitions pending |
| 8W/100J first wave, `limit=1` | PASS | eight successful requests, eight unique Jobs |

The existing real claim-path 20:1 test also remains unchanged: legacy FIFO first serves the secondary Tenant at
position 21, while the fair selector serves it within the first two claims. This contract must be re-observed in the
capacity evidence before final promotion.

## Same-Tenant 8-worker diagnostic

| Source/run | attempts | retries | retry/success | claim p50 | claim p95 | max | unique |
|---|---:|---:|---:|---:|---:|---:|---:|
| `1b6a2f8` / push `31314066767` | 17 | 9 | 1.125 | 151.639 ms | not emitted | 171.872 ms | 8/8 |
| `86767e7` / push `31314586983` | 13 | 5 | 0.625 | 128.250 ms | not emitted | 157.404 ms | 8/8 |
| `18fb876` / PR `31315029030` | 14 | 6 | 0.750 | 99.560 ms | not emitted | 131.190 ms | 8/8 |
| `9ac7088` / push `31315634340` | 12 | 4 | 0.500 | 117.400 ms | 157.049 ms | 164.373 ms | 8/8 |

These are individual CI diagnostics, not throughput claims. They show correctness and expose contention; they cannot
substitute for four repeated 1/2/4/8-worker targeted arms.

## Preserved durable invariants

- Job claims stay unique under `FOR UPDATE OF evaluation_jobs SKIP LOCKED` and status rechecks.
- Job Attempt number and Job version advance atomically with the lease.
- Result and failure commits still require the expected owner, live lease and exact version.
- stale success and stale failure acceptance remain zero by contract.
- CaseResult and Attempt uniqueness constraints remain unchanged.
- Run transition, Job transition, Audit and Outbox remain in the Phase-B transaction.
- Phase-A crash cannot create an orphan running Job because Phase A creates no Job lease or Attempt.

No timing threshold is used to decide these correctness properties.
