# Final scheduler formal scaling disposition

Date: 2026-08-09

Status: `NOT_RUN_TARGETED_FAIRNESS_FAILED`

The frozen 32-arm formal experiment (2 workloads × 1/2/4/8 workers × 4 repetitions × 500 measured Jobs = 16,000
Jobs) was not triggered. The current A/B/C same-runner paired benchmark was also not run. Both require the preceding
targeted, capacity, correctness and current fault gates to pass.

## Limited targeted diagnostic

Only repetition 1 reached 12 arms before the fairness fail-closed stop:

| Distribution | 4W Jobs/s | 8W Jobs/s | 8W / 4W | Change |
|---|---:|---:|---:|---:|
| single Tenant | 58.417 | 52.297 | 0.8952 | -10.48% |
| balanced four Tenants | 60.977 | 55.386 | 0.9083 | -9.17% |
| 20:1 | 58.963 | 52.517 | 0.8907 | -10.93% |

These values are `LIMITED`, not a targeted or formal performance verdict, because repetitions 2–4 and the
many-small-Tenants arms did not run. They cannot be used in a resume throughput claim.

## Comparison status

| Comparison | Status | Boundary |
|---|---|---|
| historical cross-runner | `VERIFIED_HISTORICAL_NEGATIVE` | different CPU runners; not causal proof |
| A/B/C same-runner paired | `NOT_RUN` | blocked by targeted fairness failure |
| current formal 32-arm | `NOT_RUN` | blocked by targeted fairness failure |

The historical pre-fair and broken-fair formal bundles remain preserved. Neither is promoted as the current
Candidate 2 result.
