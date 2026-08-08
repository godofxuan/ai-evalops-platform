# AI EvalOps correctness invariants

Status: formal load invariants and deliberately induced A–I fencing matrix `VERIFIED`.

## Formal 500-case load matrix

Across 32 real-service arms and 16,000 measured Jobs:

| Invariant | Observed | Status |
|---|---:|---|
| submitted / unique / terminal Jobs | 16,000 / 16,000 / 16,000 | `VERIFIED` |
| failed / lost / orphan nonterminal Jobs | 0 / 0 / 0 | `VERIFIED_ZERO` |
| duplicate durable results | 0 | `VERIFIED_ZERO` |
| tenant/config binding mismatches | 0 | `VERIFIED_ZERO` |
| reconciliation violations | 0 | `VERIFIED_ZERO` |
| retries that ultimately succeeded | 400 | `VERIFIED` |

The load harness did not induce expired-lease writes and correctly labeled that field `NOT_RUN`.
Those claims come from the separate fault matrix below, not from an invented load-test zero.

## Deliberately induced A–I matrix after reconnect changes

Source `03d6987`; evidence `fault-gh-31247720668-1`; 9 scenarios × 3 repetitions:

| Invariant | Observed | Status |
|---|---:|---|
| logical Jobs submitted / unique / terminal / succeeded | 84 / 84 / 84 / 84 | `VERIFIED` |
| failed / lost / orphan Jobs | 0 / 0 / 0 | `VERIFIED_ZERO` |
| duplicate CaseResults / terminal commits | 0 / 0 | `VERIFIED_ZERO` |
| deliberate retries | 72 | `VERIFIED` |
| stale successes attempted / accepted | 3 / 0 | `VERIFIED_ZERO_ACCEPTED` |
| stale failures attempted / accepted | 3 / 0 | `VERIFIED_ZERO_ACCEPTED` |
| concurrent duplicate-key HTTP requests succeeded | 60 / 60 | `VERIFIED` |
| unique Runs produced by those requests | 3 (one per repetition) | `VERIFIED` |

Scenarios C and D used the real PostgreSQL state machine and deliberately submitted late success and
late failure from Worker A after recovery and Worker B commit. Both were rejected by lease fencing.
Scenario H ran two Reapers against 20 eligible Jobs per repetition; all 60 were reaped once without
overlap. Scenario I sent 20 concurrent identical idempotency requests per repetition and produced
one Run each time.

Central answer: the retained experiments observed no task loss, and the deliberately expired Worker
could not overwrite the reclaimed Job with either a late success or a late failure.

## Multi-tenant fair claiming

Source `6d29925`; GitHub Actions `31253695011`; real PostgreSQL:

| Invariant | Observed | Status |
|---|---:|---|
| Tenant A older / Tenant B later equal-priority Jobs | 20 / 1 | `VERIFIED` |
| legacy FIFO position of Tenant B | 21 | `VERIFIED` |
| fair maximum claim position of Tenant B | 2 | `VERIFIED` |
| unique / duplicate Jobs in first two claims | 2 / 0 | `VERIFIED_ZERO_DUPLICATES` |
| existing concurrent single-tenant unique-claim/fencing suite | passed | `VERIFIED` |

This proves the controlled first-wave fairness contract, not a universal latency SLO or a submission
rate/concurrency quota.
