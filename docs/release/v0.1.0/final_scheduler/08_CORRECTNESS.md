# Final scheduler correctness evidence

Date: 2026-08-09  
Initial real-PostgreSQL qualification source: `9ac70886c03c2d3a21ae667f47c5b5971c90ed4d`

## Outcome first

All initial production-shaped scheduler contracts passed push CI `31315634340` and PR CI `31315639504`. No lease,
version, Attempt, Audit, Outbox, result or stale-worker fence was weakened. The strengthened 20-drain 10W/100J
`limit=1` contract then found a 9/10 first-wave failure in PR CI `31317179594`; current final correctness is therefore
`VERIFIED_CANDIDATE_2_CI` at source `ed095cc`, after push run `31318294569` and PR run `31318298660` both passed.

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
| 10W/100J, `limit=1` | PASS | 20 isolated drains, 2,000 unique claims and 2,000 Attempts |
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

### Strengthened 10W result

At source `5261e56`, push run `31317175140` passed all 20 drains, but PR run `31317179594` observed 9 successful
requests in one first wave. Because the fixture began with 100 eligible Jobs, that empty request cannot be interpreted
as queue exhaustion. Candidate 2 replaces fixed-budget polling with a single waiting short-turn fallback after an
eligibility probe. The test now emits per-repetition attempts, probes, empty-while-eligible and waiting-fallback counts
before asserting, so any next failure remains diagnostic.

Candidate 2 then passed all 20 isolated repetitions: 200/200 first-wave requests returned 200 unique Jobs, zero
first-wave requests were empty, and all 20 queues drained to 100 unique Jobs and 100 Attempts. The aggregate complete
drain is therefore 2,000 unique claims and 2,000 Attempts. This is a correctness count, not a throughput result.

The corrected same-Tenant 8-worker diagnostic at PR run `31318298660` recorded 11 attempts, 3 contention fallbacks,
`retry/success=0.375`, zero empty requests, p50 `129.754ms`, p95 `137.596ms`, max `139.828ms`, and 8/8 unique Jobs.

Targeted attempt 1 exposed a separate Run/Job lock-order deadlock. Commit `3350c23` changed the result-completion Run
guard from `FOR UPDATE` to `FOR NO KEY UPDATE`, retaining writer mutual exclusion while admitting the claim Outbox
foreign-key `KEY SHARE`. Push CI `31319292162` and PR CI `31319295583` both passed the new real-PostgreSQL regression.
Attempt 2 completed 12 production-worker arms with 1,200/1,200 unique terminal Jobs and zero lost, duplicate durable
result, orphan or empty-while-eligible counts. The release still fails the separate 20:1 fairness contract at w8.

## Preserved durable invariants

- Job claims stay unique under `FOR UPDATE OF evaluation_jobs SKIP LOCKED` and status rechecks.
- Job Attempt number and Job version advance atomically with the lease.
- Result and failure commits still require the expected owner, live lease and exact version.
- stale success and stale failure acceptance remain zero by contract.
- CaseResult and Attempt uniqueness constraints remain unchanged.
- Run transition, Job transition, Audit and Outbox remain in the Phase-B transaction.
- Phase-A crash cannot create an orphan running Job because Phase A creates no Job lease or Attempt.

No timing threshold is used to decide these correctness properties.
