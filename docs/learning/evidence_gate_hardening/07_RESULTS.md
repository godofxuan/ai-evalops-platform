# Results and Decision

## Outcome in one sentence

The evidence gates and the locked-Job false-empty bug were closed, but the preregistered
instrumentation overhead gate returned `INSTRUMENTATION_TOO_INTRUSIVE`; formal H1/H2/H3 attribution
was therefore not run, release remains `NOT_READY_TARGETED_NEGATIVE_SCALING`, and the next-stage
decision is `STOP_AFTER_ATTRIBUTION_NO_OPTIMIZATION_YET`.

## Evidence-gate results

| Item | RED | Minimal change | GREEN |
| --- | --- | --- | --- |
| Raw EXPLAIN independence | top-level cardinality could disagree with a recomputed valid manifest and raw plan | schema-v2 assessor independently locates the selector-specific plan node and cross-checks raw, summary and arm contract | 48 focused tests passed after P1-01 |
| Targeted assessor | non-finite/domain-invalid metrics and complete-set metadata spoofing were accepted | full-match arm grammar, arm-derived grouping and finite/domain/exact-four validation | P1-01/P1-02 focused suite reduced to only the planned P1-03 RED cases |
| No false EMPTY gate | nonzero or malformed `empty_while_eligible` did not block schema v2/final targeted assessment | required schema-v2 integer-zero contract and final-gate blocker | all 71 evidence-focused tests passed |
| Locked eligible Job | true PostgreSQL interleaving changed the acquired permit to `EMPTY` when `SKIP LOCKED` temporarily saw no row | scoped nonlocking eligibility probe; retain `PENDING` when eligible work exists; blocking waiting fallback | push `31398322919` and PR `31398332668` passed the durable-fairness job |

The full post-fix local suite before instrumentation passed with `706 passed, 29 skipped` in
438.41 seconds. The skipped local concurrency cases require PostgreSQL; their true-database GREEN is
the exact remote pair above.

## Historical evidence remained immutable

The schema-v1 run `31327388006` still has Git tree
`234347cce8872b75595b2cf312baaf25b74091ce`, status `FAILED`, and its historical cardinality
meaning. The schema-v2 targeted run `31352270523` still has Git tree
`e321f63661645f728481ef11587f94fec9a0547a`; all four rep bundles reassess as `VERIFIED`, while the
top-level repeated assessment remains `NEGATIVE_SCALING`. No historical JSON was repaired in place.

## Preregistered overhead run

- workflow: `31400658653`;
- execution source: `f0cfd8e341bca94586a75cecce74430330ffd12b`;
- instrumentation code lock: `f1ecbf20d8e266eddadd85391d2c782c581ecad2`;
- evidence commit: `4f1fd8bf37d5b440c40684208332116f9d90de0d`;
- representative arm: `fair-q1000-skew_20_to_1-w8-b1`;
- repetitions: exactly three OFF and three ON;
- sealed manifest: 893 listed files, 893 actual files, zero missing, extra, size or SHA-256 mismatches.

### Direct observations

| Mode | Rep | Jobs/s | Claim p95 ms | Worker CPU % | Peak RSS bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| OFF | 1 | 26.819294 | 733.686325 | 92.680504 | 104,681,472 |
| OFF | 2 | 30.125681 | 519.208889 | 95.242913 | 100,638,720 |
| OFF | 3 | 30.601347 | 361.703180 | 94.115362 | 101,019,648 |
| ON | 1 | 30.349410 | 337.029211 | 95.581669 | 101,068,800 |
| ON | 2 | 31.192255 | 473.924356 | 95.152439 | 100,933,632 |
| ON | 3 | 31.748073 | 460.437420 | 96.568313 | 100,675,584 |

### Derived medians and frozen decision

| Metric | OFF median | ON median | Relative change | Gate role |
| --- | ---: | ---: | ---: | --- |
| Jobs/s | 30.125681 | 31.192255 | +3.5404% | no throughput regression |
| Claim p95 | 519.208889 ms | 460.437420 ms | -11.3194% | **absolute change exceeds 10%** |
| Worker CPU | 94.115362% | 95.581669% | +1.5580% | reported, not gating |
| Peak RSS | 101,019,648 | 100,933,632 | -0.0851% | reported, not gating |

The latency change points in a favourable direction, but the preregistration deliberately used an
absolute change. A diagnostic hook that changes transaction timing by more than the budget cannot
be trusted merely because this sample became faster. The correct result is therefore
`INSTRUMENTATION_TOO_INTRUSIVE`, not `VALID`.

## Hypothesis status

Formal four-repetition attribution was skipped automatically at workflow step 13 and assessment at
step 14 was skipped. Consequently:

- H1 SchedulerCoordination singleton contention: `INCONCLUSIVE`;
- H2 Tenant-permit contention: `INCONCLUSIVE`;
- H3 SKIP LOCKED/retry feedback: `INCONCLUSIVE`.

The older targeted counters remain observations that motivated the hypotheses, but they do not
satisfy the preregistered phase-attribution criteria. There is no defensible bottleneck selection and
no authorization for a scheduler candidate.

## What went wrong and what was learned

The instrumentation implementation passed its unit contract, preserved source/workload identity and
recorded the intended phase boundaries. The problem appeared only in paired remote execution: the
ON/OFF claim-p95 medians differed by 11.32%, beyond the frozen 10% budget. This demonstrates why an
overhead gate belongs before formal data collection. Continuing would create a polished but
inadmissible causal story.

The next useful stage, if separately authorized, is to preregister a lower-overhead recorder design
and repeat only the overhead qualification first. It must not alter the existing threshold after
seeing this result, and it must not implement Candidate 4 in the same stage.

## Resume and interview wording

Safe resume wording:

> Hardened a schema-versioned, manifest-bound evaluation evidence pipeline with independent raw-plan
> validation and fail-closed metric contracts; reproduced and fixed a PostgreSQL `SKIP LOCKED`
> false-empty state transition; preregistered a performance attribution experiment whose overhead
> gate correctly stopped an intrusive diagnostic before causal claims were made.

Interview explanation: the most important result is not a speedup. It is that the system rejected
its own measurement apparatus when the apparatus exceeded the declared perturbation budget. That
preserved the distinction between observation, derivation, hypothesis and release claim.
