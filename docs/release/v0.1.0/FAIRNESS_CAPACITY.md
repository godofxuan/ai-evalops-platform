# v0.1.0 RC fairness and capacity

Current conclusion: Candidate 3 passes the frozen four-repetition targeted correctness/fairness workload, but
targeted self-scaling is `NEGATIVE_SCALING`; current 1k/10k/100k capacity remains `NOT_RUN_STOPPED`.

Targeted run `31352270523` executed source `91acdba` with queue 1000, four distributions, Workers 1/2/4/8, batch 1
and four repetitions. All 64 arms completed. Each rep bundle independently verified under schema v2; aggregate
correctness is 6,400/6,400 unique terminal Jobs with every protected failure counter zero. In every repetition,
20:1 secondary Tenant application receipt positions at w1/w2/w4/w8 were `2/2/2/2`.

The repeated performance result is:

| Distribution | w4 median Jobs/s | w8 median Jobs/s | w8/w4 | Required | Result |
|---|---:|---:|---:|---:|---|
| single Tenant | 24.190086 | 18.929004 | 0.782511 | 0.95 | NEGATIVE_SCALING |
| balanced | 44.752825 | 34.584871 | 0.772797 | 0.95 | NEGATIVE_SCALING |
| 20:1 | 32.700255 | 26.036396 | 0.796214 | 0.95 | NEGATIVE_SCALING |
| many-small | 42.245796 | 42.839905 | 1.014063 | 0.95 | VERIFIED |

Every w8 observation is below every w4 observation in the three failing distributions, so the verdict is not caused
by a single median outlier. At w8, contention retries and claim p95 also rise materially in those distributions.
That supports a contention hypothesis but is not sufficient to authorize or select a production fix.

Historical run `31272789199` still contains complete 1k/10k/100k capacity evidence. Its 100k single-Tenant/w8
approximately `0.628 Jobs/s`, `504` retries and `41s` claim p95 remain historical engineering evidence, not current
Candidate 3 measurements. No current capacity or production performance SLO is supported.
