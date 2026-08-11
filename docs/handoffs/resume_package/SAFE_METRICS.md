# Safe Metrics

Use only with scope:

| Metric | Safe shorthand | Required qualifier |
| --- | --- | --- |
| 64 arms / 6,400 Jobs | all protected counters zero | frozen controlled schema-v2 experiment |
| fair position 2 vs legacy 953 | all 16 skew observations | exact q1000/sample100/batch1/20:1 workload only |
| 598/598 target manifest | zero missing/size/hash mismatch | artifact integrity, not signed proof |
| 4→8 ratios | 0.782511 / 0.772797 / 0.796214 / 1.014063 | 3/4 failed frozen 0.95 gate |
| false-empty | 1 RED / 2 GREEN workflows | deterministic real PostgreSQL test |
| fault matrix | 54/54 successful, zero recorded violations | historical A–I before/after controlled scope |
| observer perturbation | 11.3194%, 13.4906%, 28.0396% absolute claim-p95 | instruments rejected; no root cause |
| local tests | 783 passed / 33 skipped | `.venv` Python 3.12; external services not enabled locally |

Full authority: [`RESUME_METRIC_LEDGER.md`](../RESUME_METRIC_LEDGER.md).
