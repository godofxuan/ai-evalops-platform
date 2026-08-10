# Low-overhead Requalification

## Why a second stage was allowed

Workflow `31400658653` stopped before formal attribution because instrumentation changed median
claim p95 by 11.3194% in absolute terms. The next user instruction authorized a new stage, but not a
scheduler candidate. The stage was therefore limited to diagnosing the observer, reducing its local
work, and running one separately preregistered overhead requalification.

The old evidence was not retried or reinterpreted. A new preregistration was committed before code,
and explicitly prohibited a third automatic redesign if requalification failed.

## Feedback loop and ranked hypotheses

The remote failure was first decomposed without editing code:

- OFF throughput range: 12.96%;
- OFF claim-p95 range: 69.12%;
- execution order: all three OFF runs before all three ON runs;
- recorder microbenchmark: about 4.93 microseconds of incremental work per representative claim
  sequence;
- each ON raw file: only 1,100–1,152 timing samples and about 24–25 KiB.

This ranked order confounding and intrinsic PostgreSQL contention variance above raw-list growth or
the direct CPU cost of the recorder. The predictions were documented before the new experiment:
counterbalancing should remove simple early/late drift; unnecessary clock elimination should improve
the deterministic microbenchmark; if neither makes the remote absolute shift admissible, the
instrument remains unqualified.

## RED 1: unnecessary monotonic-clock reads

The first regression test sent nine counter-only or ignored markers to `ClaimPhaseRecorder`. Before
the fix it reported `1 failed, 2 passed`: the injected clock was called nine times, while the frozen
contract expected zero.

The minimal fix moved counters into one event map and returned before reading the clock unless the
event starts or finishes a registered timing interval. The first GREEN attempt double-counted
`tenant_permit_acquired`, producing `permit_pending_count=3` instead of 2. Existing semantic tests
caught this. Removing the old duplicate increment produced `3 passed`.

The same local microbenchmark fell from approximately 4.93 to 3.38 microseconds per claim sequence,
about a 31% reduction. This is a recorder result, not evidence that remote contention perturbation
was solved.

## RED 2: exact representative-arm execution

The original overhead workflow assessed only `fair-q1000-skew_20_to_1-w8-b1` but each repetition ran
all 16 targeted arms. New tests first produced `2 failed`: the CLI rejected `--arm-id`, and no
fail-closed selector existed.

The runner now selects one arm only from the already built frozen plan. An unknown arm raises
`ExperimentError`; it cannot synthesize a new workload. Existing callers without `--arm-id` still run
the complete plan. The configuration records `selected_arm_id`.

## RED 3: overhead and formal evidence scopes

Pre-push review found that the attribution assessor still required a 16-arm set for every overhead
CSV. An exact-arm runner would therefore fail with `arm_set_mismatch`. Three tests first failed with
an unsupported `overhead_arm_only` contract.

The minimal assessor change makes the scope explicit:

- old calls retain the full-matrix overhead contract for historical replay;
- requalification passes `overhead_arm_only=True` and requires exactly the registered overhead arm;
- formal repetitions always require the complete 16-arm set.

The five attribution tests then passed. This separation prevents a one-arm formal result or a
16-arm requalification from being accepted accidentally.

## Counterbalanced remote run

Workflow `31407782154` used source
`f2f20b797b65d1d49d62cbadbc5b858d6420595f`, code lock
`0fd5376300155ee4fdfa3cfd248d636bdeca3100`, and exact order:

`OFF-1, ON-1, ON-2, OFF-2, OFF-3, ON-3`.

Every exact-arm run and bundle assessment succeeded. The overhead observations were:

| Mode | Rep | Jobs/s | Claim p95 ms | CPU % | Peak RSS bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| OFF | 1 | 27.705688 | 627.587034 | 94.051317 | 101,490,688 |
| OFF | 2 | 26.606419 | 556.897573 | 94.775746 | 96,194,560 |
| OFF | 3 | 27.153355 | 863.906619 | 93.155489 | 96,219,136 |
| ON | 1 | 28.883211 | 542.922064 | 95.716869 | 96,321,536 |
| ON | 2 | 27.169103 | 375.767745 | 95.812165 | 96,284,672 |
| ON | 3 | 27.301233 | 586.177144 | 94.251684 | 96,223,232 |

Medians changed as follows:

- throughput: 27.153355 to 27.301233 Jobs/s, +0.5446%;
- claim p95: 627.587034 to 542.922064 ms, -13.4906%;
- CPU: +1.7709%;
- RSS: +0.0681%.

All three order-paired claim-p95 changes were negative: -13.4906%, -32.5248% and -32.1481%. Simple
OFF-first/ON-later drift therefore does not explain the second result. The observer appears to alter
the high-contention timing distribution in a favourable direction. That is still perturbation; a
faster measured result is not automatically a more truthful result.

The unchanged absolute 10% claim-p95 rule failed. Formal repetitions and H1/H2/H3 assessment were
skipped. The top manifest independently verified 84 listed and actual files with zero missing,
extra, size or SHA-256 mismatches. Evidence commit:
`b9aee04d10aeafa088876a68b9895d5a8d0ab180`.

## Final judgment and trade-off

The local optimization is technically correct and preserved because it removes unnecessary work
without changing metrics. It did not qualify the instrument. A third automatic attempt would turn a
bounded diagnosis into threshold-seeking, so the stage stops.

H1, H2 and H3 remain `INCONCLUSIVE`. The project still has a useful finding: phase timing through
this synchronous per-event observer is not sufficiently non-perturbing under the registered
skew20:1/w8 workload. A future, separately designed measurement approach would need a different seam
such as database-native wait telemetry or an asynchronous trace buffer, plus its own preregistration.
That is a future design question, not permission to implement Candidate 4.

## Interview explanation

The strongest explanation is that the team did not keep rerunning until the gate turned green. It
reduced a measured local cost, corrected an order-confounded workflow, and still accepted the second
negative result. This demonstrates experimental discipline: implementation improvement, measurement
validity, causal attribution and release readiness are four separate claims.
