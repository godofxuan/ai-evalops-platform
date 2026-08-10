# Passive PostgreSQL measurement-system qualification preregistration

## Authorization and immutable release state

- Registered: 2026-08-11 (Asia/Shanghai)
- Starting audit SHA: `8a093a735333fe3e54bc6238e0a8d4949b73ccf6`
- Measurement code lock: `7dca9715fbb5f2a46f648161f8a67d086de9d485`
- Measurement candidate budget: **1**, consumed by this passive PostgreSQL design
- Production scheduler candidate budget: **0**
- Production behavior changes in this stage: **0**

The release state is not an outcome of this experiment and cannot be changed by it. Candidate 3
bounded correctness and frozen 20:1 fairness remain PASS; formal targeted 4-to-8 scaling remains
`NEGATIVE_SCALING`; v0.1.0 remains `NOT_READY`; PR #1 remains Draft; H1/H2/H3 remain
`INCONCLUSIVE`; current capacity, same-runner, fault and formal attribution stages remain
`NOT_RUN_STOPPED`.

The two synchronous callback qualifications remain immutable failures. Independently recalculated
absolute claim-p95 changes were 11.3194% and 13.4906%, both above the unchanged 10% limit, even
though ON was faster. The synchronous observer is therefore
`RETIRED_FOR_FORMAL_ATTRIBUTION` and is not used here.

## Question and candidate

The only question is whether an external process polling PostgreSQL core views is sufficiently
non-perturbing to qualify for a future, separately preregistered H1/H2/H3 attribution stage. The
candidate uses a separate process and connection, static read-only SQL over `pg_stat_activity` and
`pg_locks`, and bounded streaming output. It never calls the claim callback and never enters a Job
claim transaction.

This stage does not test H1, H2 or H3, does not choose a bottleneck, and does not authorize a
scheduler change. No fourth measurement candidate is allowed if this candidate fails.

## Local frequency engineering study

The committed `local_frequency_study.json` compared 1, 5, 10 and 20 Hz for three seconds each using
the exact public projection and JSONL streaming path with 16 bounded rows/sample. This Windows host
has no local PostgreSQL, Docker or `psql`; real query overhead and database query latency are
therefore `NOT_RUN_NO_LOCAL_POSTGRESQL`, not silently estimated.

| Hz | Successful samples | JSONL bytes/s | Modeled opportunities in historical 100-Job period |
| ---: | ---: | ---: | ---: |
| 1 | 3 | 5,534.60 | 3.68 |
| 5 | 15 | 27,648.22 | 18.41 |
| 10 | 30 | 55,297.44 | 36.83 |
| 20 | 60 | 110,396.56 | 73.66 |

The frozen selection is **5 Hz**. It offers about 18 opportunities in the historical 3.68-second
representative period while issuing half as many queries as 10 Hz and one quarter as many as 20 Hz.
One hertz provides fewer than four opportunities and has excessive information-loss risk. These
local figures are parameter-selection evidence only and make no measurement-validity claim.

## Frozen workload and exactly-eight-run order

- Arm: `fair-q1000-skew_20_to_1-w8-b1`
- Queue size: 1,000
- Distribution: `skew_20_to_1`
- Worker concurrency: 8
- Claim batch: 1
- Measured Jobs: 100
- OFF repetitions: exactly 4
- ON repetitions: exactly 4
- Additional repetitions after seeing data: forbidden

| Global position | Block | Mode | Mode repetition |
| ---: | :---: | :---: | ---: |
| 1 | A | OFF | 1 |
| 2 | A | ON | 1 |
| 3 | A | ON | 2 |
| 4 | A | OFF | 2 |
| 5 | B | ON | 3 |
| 6 | B | OFF | 3 |
| 7 | B | OFF | 4 |
| 8 | B | ON | 4 |

Every repetition creates a fresh fixture after recording database size and Tenant, Run, Job and
Attempt counts. Existing EXPLAIN collection occurs equally before the measured period. There is no
workload-claim warm-up. The measured period is exactly the bounded 100-Job Worker sample. The
fixture is deleted afterward and post-cleanup counts are recorded. OFF and ON differ only in whether
the external telemetry process is enabled.

## Frozen calculation and reporting

The gate uses the median of four OFF and four ON observations:

```text
throughput_relative_change = (ON throughput median - OFF throughput median) / OFF median
claim_p95_relative_change = (ON claim-p95 median - OFF claim-p95 median) / OFF median
```

Both are direction-independent absolute gates:

- `abs(throughput_relative_change) <= 0.05`
- `abs(claim_p95_relative_change) <= 0.10`

For each mode and each gated metric the report also includes min, max, mean, median, range,
range/mean and MAD, plus four adjacent counterbalanced pair observations. These stability
descriptors do not change the frozen gate and are not statistical-significance claims.

## Fail-closed validity contract

`MEASUREMENT_SYSTEM_VALID` requires all of the following:

1. both absolute perturbation limits pass;
2. all correctness counters and `empty_while_eligible` are zero;
3. ON successful sample count is positive;
4. telemetry error, dropped-sample and buffer-overflow counts are zero;
5. source, measurement-code, workflow, arm, workload, sample-size, mode, frequency and order
   identities are exact;
6. every sealed run manifest has zero missing, extra, size-mismatched or hash-mismatched files.

Any failure yields `MEASUREMENT_SYSTEM_INVALID`. A valid result yields only
`QUALIFIED_FOR_FUTURE_FORMAL_ATTRIBUTION`. An invalid result yields
`PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY`. In both cases H1/H2/H3 are `NOT_RUN` and
the workflow contains no formal-attribution job.

## Stop rules

The experiment stops after exactly eight runs. A correctness failure is preserved as
`CORRECTNESS_BLOCKER_DISCOVERED`; it is not patched and rerun under the same identity. Source,
workload, order, telemetry-integrity or manifest drift fails closed. Thresholds, workload, sampling
frequency and repetition count cannot be adjusted after observing remote results.

