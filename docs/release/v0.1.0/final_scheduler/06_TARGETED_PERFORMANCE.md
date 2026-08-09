# Final scheduler targeted performance

Date: 2026-08-09
Status: `FAILED_FAIRNESS_GATE`

## Attempt 1: correctness RED, no performance decision

Workflow run [31318923861](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31318923861) executed at
source `0e19f645e30338e68b6bfc060dd848927ed9d6c1` and failed after 48 seconds. The benchmark did not reach the repeated
4-to-8 comparison, so this is neither `NEGATIVE_SCALING` nor `PERFORMANCE_PASS`.

The first single-Tenant/1-worker arm completed 100/100 unique Jobs at `12.398905 Jobs/s`, with zero lost Jobs,
duplicates, empty-while-eligible returns or reservation misses. The following 2-worker arm exposed a PostgreSQL
deadlock between a result transaction holding the Run row before requesting a Job row and a concurrent claim holding
a Job row before its transactional Outbox insert requested the Run foreign-key `KEY SHARE` lock. The source-bound
failure, PostgreSQL log, environment and fail-closed assessment are preserved under
`docs/results/release/v0.1.0/targeted-gh-31318923861-1/`; artifact digest is
`78506cf95177e9f883c47f58be1253974da52a695ff5fc620e0aa970ab581b97`.

RED-driven commit `3350c2315a8a7e92e97a73218de321582294fdc8` changes only the result-completion Run guard from `FOR UPDATE` to
`FOR NO KEY UPDATE`. It still serializes Run writers but is compatible with claim/Outbox FK readers. A compile-level
RED/GREEN and a real-PostgreSQL FK compatibility regression were added. Push CI
[31319292162](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31319292162) passed in 4m27s and PR CI
[31319295583](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31319295583) passed in 4m21s. Both complete
quality/integration and Compose jobs are green, so attempt 2 may now run at the next trigger commit's exact SHA.

## Frozen protocol

- queue size: 1,000;
- distributions: single Tenant, balanced four Tenants, 20:1 skew, many small Tenants;
- workers: 1, 2, 4, 8;
- claim batch: 1;
- measured Jobs per arm: 100, leaving 900 background eligible Jobs;
- repetitions: 4 complete executions;
- real `EvaluationWorker`, PostgreSQL and Compose environment;
- source-bound per-repetition manifests plus one aggregate manifest.

Every arm records Jobs/s, claim p50/p95/p99, reservation p50/p95/p99, Job-claim p50/p95/p99, reservation counts and
misses, contention retry/success, waiting fallbacks, empty while eligible, PostgreSQL waiting sessions, Worker CPU/RSS
and correctness reconciliation.

## Gate

For every distribution, compare the median 4-worker and 8-worker throughput across the four repetitions. If
`throughput_8 < throughput_4 * 0.95`, the result is `NEGATIVE_SCALING`; capacity and formal experiments must not run.
This targeted investigation boundary does not replace or relax the frozen release regression gate.

Candidate 2 scheduler correctness was qualified by push CI `31318294569` and PR CI `31318298660`. Attempt 1 then
exposed the independent Run/Job lock-order RED above. Any retry must use a new source-bound trigger; results must be
appended without overwriting attempt 1 or any historical negative bundle.

## Attempt 2: frozen fairness gate FAILED

Workflow run [31319556885](https://github.com/godofxuan/ai-evalops-platform/actions/runs/31319556885) executed at exact
source `246252e30e63f046a4a1fb5d684a35449aaef9e3`. It failed in 1m11s after completing 12 arms in repetition 1.
Artifact `targeted-gh-31319556885-1` is 280 KB with SHA-256
`ed75825c310e52d31e8c0bb54432411bd31f57f520a244462c9aefdf06f68d58`; bot commit `f1a276f` preserves 117
manifest-bound files under `docs/results/release/v0.1.0/targeted-gh-31319556885-1/`.

All 12 completed arms reconciled 100/100 unique terminal Jobs with zero lost Jobs, duplicate durable results,
orphans and empty-while-eligible claims. The Run-lock deadlock from attempt 1 did not recur. The
`skew_20_to_1/w8` arm nevertheless recorded the secondary Tenant's first durable claim at position 4. The frozen
contract requires position `<= 2`, so `assess_arm_runtime` returned
`skew_secondary_tenant_first_claim_position_exceeds_2` and the protocol stopped before repetition 2.

The position is ordered by a global monotonic timestamp taken only after `SQLAlchemyJobClaimer.claim()` returns from
its committed transaction. It is not result-completion or collector order. The failure is therefore a current
scheduler fairness RED, not a harness ordering artifact. The gate is not relaxed.

The one available repetition also showed 4-to-8 throughput ratios of `0.8952` for single Tenant, `0.9083` for
balanced Tenants and `0.8907` for 20:1. These are `LIMITED` diagnostics only: the formal targeted scaling decision
requires four repetitions and is therefore `NOT_COMPLETED`. The independent fairness failure is sufficient to reject
the release.

Candidate 2 is the second and final allowed scheduler production iteration. No Candidate 3, capacity run,
same-runner paired run, fault rerun or formal scaling run is permitted in this sprint.
