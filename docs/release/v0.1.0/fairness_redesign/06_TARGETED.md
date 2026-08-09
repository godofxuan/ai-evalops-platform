# Candidate 3 targeted qualification

Status: `FAILED`; stop condition reached

## Source and artifact identity

| Field | Value |
|---|---|
| Candidate 3 source | `02f5e680e71d05c76c145da6895122a2cf04ba14` |
| workflow run | `31327388006` |
| workflow result | Failure, 1m31s |
| evidence bot commit | `90a4e03ae75d0ae391f16f32934c144430de196d` |
| artifact | `targeted-gh-31327388006-1`, 404 KB |
| artifact digest | `sha256:b9db8fc934b3e736c5a30868833218cc470ab011fcfa24f12dc4892cdfe47a1a` |
| queue/distributions | 1000; single, balanced, 20:1, many-small |
| Workers/batch/repetitions | 1/2/4/8; batch 1; 4 planned |

## What actually completed

Repetition 1 completed 16/16 expected arms. Every raw arm assessment was `VERIFIED`; aggregate correctness was
1,600 submitted, 1,600 unique terminal, zero lost, duplicate durable result, orphan, attempt mismatch,
empty-while-eligible, stale success/failure accepted and illegal transition.

For 20:1, frozen application receipt positions at w1/w2/w4/w8 were `2/2/2/2`. The new database-linearized sequence
was complete and reported the same positions. This is useful diagnostic evidence that Candidate 3 addressed the
Candidate 2 overtaking schedule in the one executed repetition.

## Why the gate failed

The repetition assessor returned only:

`postgres_explain_candidate_cardinality_mismatch`

All 64 Candidate 3 `fair` EXPLAIN summaries report scheduler-round membership cardinality: single `1`, balanced
`4`, 20:1 `2`, many-small `100`. The frozen evidence checker still compares every selector's candidate cardinality
with Job queue size `1000`. The 64 legacy FIFO summaries remain `1000`, so exactly 64/128 summaries mismatch.

This is not evidence that the Job state machine failed, and it is not permission to alter the assessor after seeing
RED and continue the same release attempt. The preregistered protocol says `targeted fail -> STOP`. Top-level
assessment consequently records `status=FAILED`, `repetition_count=0`, `repetition_count_must_equal_4`.

## Limited performance observations

Rep1 4→8 ratios: single `0.678104`, balanced `0.785456`, 20:1 `0.749962`, many-small `0.954809`. Only many-small
meets the configured 0.95 floor in this one observation. Because the repetition bundle failed and repetitions 2–4
did not run, none is a formal targeted-performance result.

## Decision

- Frozen gate was not redefined.
- No failed arm or EXPLAIN was deleted.
- No threshold, workload, Worker, batch, seed, retry, pool, sleep or lease parameter changed.
- No Candidate 4 or targeted retry was started.
- Capacity, same-runner, fault and formal stages are `NOT_RUN` by stop rule.
