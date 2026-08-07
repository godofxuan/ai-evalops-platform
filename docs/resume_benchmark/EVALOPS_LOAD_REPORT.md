# AI EvalOps load report

Status: `VERIFIED` for capacity comparison; human adoption decision remains `NOT_RUN`.

## Evidence identity

- Formal run: `gate1-gh-31177702100-1` / GitHub Actions `31177702100`.
- Frozen source: `15e7ac2e28b70430acd0bff88ee6cc78e5b86a86`.
- Evidence commit: `ab97e61ffb46bbbab8d167f8f8f4421fbb26cfa2`.
- Post-Git verification: `complete`; 664 payload files; all SHA-256 values matched.
- Matrix: 2 deterministic workloads × 1/2/4/8 Workers × 4 repetitions = 32 arms.
- Each arm: 50 warm-up cases followed by 500 measured cases.

The source of truth is `docs/results/load/gate1-gh-31177702100-1/final/`. The 32 normalized arm rows
are in `LOAD_RESULTS.csv`; `EVALOPS_SCALING.csv` aggregates every repetition, not the best result.

## Worker scaling result

| Workload | Workers | Throughput median (jobs/s) | Min–max (jobs/s) | Speedup | Efficiency | End-to-end median (ms) |
|---|---:|---:|---:|---:|---:|---:|
| fixed 25 ms I/O | 1 | 21.48 | 21.03–21.89 | 1.00× | 100.0% | 23,277.77 |
| fixed 25 ms I/O | 2 | 38.06 | 37.03–39.21 | 1.77× | 88.6% | 13,136.50 |
| fixed 25 ms I/O | 4 | 56.26 | 56.15–58.65 | 2.62× | 65.5% | 8,886.86 |
| fixed 25 ms I/O | 8 | 66.80 | 63.94–74.44 | 3.11× | 38.9% | 7,496.39 |
| 25 ms I/O + deterministic 5% transient retry | 1 | 19.59 | 19.33–20.27 | 1.00× | 100.0% | 25,528.23 |
| 25 ms I/O + deterministic 5% transient retry | 2 | 34.03 | 32.02–35.38 | 1.74× | 86.9% | 14,700.30 |
| 25 ms I/O + deterministic 5% transient retry | 4 | 50.83 | 48.35–54.58 | 2.59× | 64.9% | 9,842.18 |
| 25 ms I/O + deterministic 5% transient retry | 8 | 60.76 | 56.00–65.86 | 3.10× | 38.8% | 8,239.83 |

Throughput increased monotonically, but scaling was not linear. The 8-Worker arms delivered about
3.1× the 1-Worker throughput at about 39% parallel efficiency. Median p95 queue wait fell from
21.78 s to 6.60 s for fixed I/O and from 22.86 s to 6.49 s for the retry workload. At the same time,
median result-commit transaction latency rose from 11.26 ms to 44.71 ms and from 11.46 ms to
42.51 ms respectively, consistent with growing shared-database contention/coordination overhead.

The per-case p95 target latency was 25 ms in every group because the target is deliberately fixed at
25 ms. It must not be presented as external-model latency. `runs/s` is omitted because each arm
contains only one Run; jobs/s and end-to-end duration are the meaningful measures here.

## Durable correctness during load

- Submitted/unique/completed: `16,000 / 16,000 / 16,000`.
- Failed/lost/orphan nonterminal Jobs: `0 / 0 / 0`.
- Duplicate durable result keys and run/case result keys: `0`.
- Binding mismatches and reconciliation violations: `0`.
- Retries: `400`, all from the deterministic 5% transient workload; all ultimately succeeded.
- Collector missed samples: `0`.

The load run therefore observed no task loss or duplicate durable result. It did **not** deliberately
submit a result or failure from an expired lease, so stale-write acceptance remains `NOT_RUN` and no
fencing claim is admitted from this experiment.

## Decision

The automatic adoption gate intentionally selected no Worker count. Eight Workers gave the highest
throughput in this bounded runner, while four Workers retained substantially better efficiency. A
deployment choice needs cost and latency objectives that were not supplied; fabricating that policy
inside the benchmark would turn measurement into an unreviewed product decision.
