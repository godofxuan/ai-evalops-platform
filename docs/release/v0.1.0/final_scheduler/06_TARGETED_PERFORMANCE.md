# Final scheduler targeted performance

Date: 2026-08-09
Status: `TRIGGER_READY`

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

Candidate 2 correctness is qualified by push CI `31318294569` and PR CI `31318298660`. The dedicated trigger file is
included in the next commit; the workflow's `GITHUB_SHA` becomes the exact benchmark source. Results will be appended
without overwriting any historical negative bundle.
