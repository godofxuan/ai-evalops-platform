# Low-overhead instrumentation requalification preregistration

## Authorization and immutable prior result

- Registered: 2026-08-11 (Asia/Shanghai)
- Starting source: `63f47001cdb2cc72b39e61e7f9b5bb540224e2ec`
- Prior diagnostic workflow: `31400658653`
- Prior evidence commit: `4f1fd8bf37d5b440c40684208332116f9d90de0d`
- Prior verdict: `INSTRUMENTATION_TOO_INTRUSIVE`
- Scheduler-behaviour candidate budget: **0**

The prior result is immutable. Its claim-p95 median absolute change was 11.3194%, above the
registered 10% budget. This new stage does not reinterpret, overwrite or retry that run. It creates
a new source lock and a separately identified requalification run.

## Diagnosis before modification

The previous OFF observations had a 12.96% throughput range and a 69.12% claim-p95 range. All three
OFF repetitions ran before all three ON repetitions, so temporal database/runner drift was perfectly
confounded with instrumentation mode.

A local 1.4-million-event microbenchmark measured approximately 4.93 microseconds of incremental
recorder work per representative claim sequence. Each remote ON repetition retained only
1,100–1,152 timing samples in a 24–25 KiB raw JSON file. These observations make string dispatch and
sample storage real but quantitatively insufficient, by themselves, to explain the remote 11.3194%
shift.

Ranked falsifiable hypotheses:

1. **Order confounding**: if sequential OFF-then-ON execution is the dominant issue, a frozen
   counterbalanced order will reduce the apparent mode shift without changing the scheduler.
2. **Unnecessary clock reads**: if counter-only and ignored markers contribute material observer
   work, avoiding monotonic-clock calls for those markers will reduce the recorder microbenchmark.
3. **Raw observation growth**: if list allocation is material, cost will grow with retained timing
   samples. The observed sample/byte counts currently make this unlikely; raw observations remain
   required and will not be removed in this iteration.
4. **Intrinsic lock-contention variance**: if run-to-run database variance dominates even after
   counterbalancing, the unchanged overhead gate may still fail. That is a valid stop result, not
   permission to relax the threshold or add repetitions after seeing data.

## Allowed implementation delta

Only the following changes are permitted before the new source lock:

1. `ClaimPhaseRecorder.observe()` may avoid calling its monotonic clock for events that neither start
   nor finish a registered timing interval. Counter semantics and all raw timing observations must
   remain unchanged.
2. The benchmark CLI may select an exact preregistered arm from the existing plan. Selection must be
   full-match/exact, fail closed when absent, and must not synthesize or alter an arm.
3. The dedicated requalification workflow may execute only the registered representative arm and
   use the frozen counterbalanced order below.
4. Tests, assessment validation, source locks, manifests, evidence preservation and documentation
   may be added.

Forbidden changes include scheduler SQL/state/policy, queue size, distribution, Worker count, claim
batch, sample size, connection pool, retry/backoff, lease, fairness threshold, performance threshold,
repetition count, percentile calculation or historical evidence.

## Frozen overhead contract

- Arm: `fair-q1000-skew_20_to_1-w8-b1`
- Queue size: 1,000
- Distribution: `skew_20_to_1`
- Workers: 8
- Claim batch: 1
- Measured Jobs: 100
- Instrumentation OFF repetitions: exactly 3
- Instrumentation ON repetitions: exactly 3
- Execution order: `OFF-1, ON-1, ON-2, OFF-2, OFF-3, ON-3`
- Same exact commit, GitHub runner job, PostgreSQL/Redis containers and migration state
- Throughput statistic: median of the three observations for each mode
- Claim-p95 statistic: median of the three observations for each mode

The order is fixed before execution. It distributes both modes across the beginning, middle and end
of the six-run sequence. A result may not be excluded because it is inconvenient.

## Unchanged pass/fail rule

Instrumentation is `VALID` only when both are true:

- absolute median throughput regression is at most 5%; and
- absolute median claim-p95 change is at most 10%.

CPU and RSS changes remain reporting-only. Any source, arm, sample-size, order, repetition, manifest
or correctness drift fails closed. Exceeding either overhead threshold yields
`INSTRUMENTATION_TOO_INTRUSIVE` and stops formal attribution.

## Formal attribution boundary

Only a `VALID` overhead result on this exact contract may unlock the existing four-repetition formal
q1000/b1, Workers 1/2/4/8, four-distribution attribution matrix and the already registered H1/H2/H3
criteria. The formal run still cannot change release readiness, authorize Candidate 4, merge PR #1,
create a tag/release or run downstream release qualification.

If overhead remains invalid, this stage stops after sealing and documenting the new negative
evidence. It does not perform another automatic instrumentation redesign.
