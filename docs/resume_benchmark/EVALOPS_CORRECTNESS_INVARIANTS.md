# AI EvalOps correctness invariants

Status: load invariants `VERIFIED`; deliberately induced fencing matrix `PENDING`.

## Verified by the formal 500-case matrix

Across 32 real-service arms and 16,000 measured Jobs:

| Invariant | Observed | Status |
|---|---:|---|
| submitted Jobs | 16,000 | `VERIFIED` |
| unique Jobs | 16,000 | `VERIFIED` |
| terminal Jobs | 16,000 | `VERIFIED` |
| failed Jobs | 0 | `VERIFIED_ZERO` |
| lost Jobs | 0 | `VERIFIED_ZERO` |
| orphan nonterminal Jobs | 0 | `VERIFIED_ZERO` |
| duplicate durable results | 0 | `VERIFIED_ZERO` |
| tenant/config binding mismatches | 0 | `VERIFIED_ZERO` |
| reconciliation violations | 0 | `VERIFIED_ZERO` |
| retries | 400 | `VERIFIED` |

Every retry attempt sequence was contiguous, and all 400 retry events ultimately reached success.

## Still requiring deliberate fault injection

The load harness records `stale_submission_rejection.evidence=NOT_RUN`. Consequently, it cannot
answer whether an expired Worker can overwrite a reclaimed Job. Scenarios C and D must deliberately
submit late success and late failure from Worker A after Reaper recovery and Worker B reclaim. Both
accepted counts must be exactly zero before the full correctness gate can pass.

Current answer to the central question: no task loss occurred in the formal load experiment; old
Worker overwrite has not yet been established by this experiment and remains withheld.
