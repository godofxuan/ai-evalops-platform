# AI EvalOps Platform — Resume Metric Ledger

Revalidated: 2026-08-11 from checked-in artifacts. Every value requires its Scope.

| Metric | Value | Scope | Evidence | Allowed | Forbidden |
| --- | ---: | --- | --- | --- | --- |
| Targeted arms | 64 | 4 distributions × w1/w2/w4/w8 × 4 repetitions; q1000, sample_jobs=100, batch=1 | targeted rep `arms.csv` files | “frozen 64-arm experiment” | “64 production workloads” |
| Submitted / unique / terminal Jobs | 6,400 / 6,400 / 6,400 | same frozen targeted run | `docs/results/release/v0.1.0/targeted-gh-31352270523-1/rep*/bundle/arms.csv` | “6,400 submitted/unique/terminal Jobs” | production volume or universal zero loss |
| Protected counters | all 0 | lost, duplicate durable result, stale success/failure accepted, illegal transition, orphan nonterminal, Attempt mismatch across 64 arms | same CSVs | list exact tested counters | “zero data loss universally” |
| Fair secondary receipt position | 2 in all 16 skew observations | exact frozen 20:1 contract; w1/w2/w4/w8 × four repetitions | skew rows in rep CSVs | “position 2 in every frozen observation” | universal/strong fairness, starvation-free |
| Legacy secondary receipt position | 953 in all 16 matching observations | same exact workload | same | “versus 953 under legacy FIFO” | generic latency improvement |
| EXPLAIN summaries | 512 | 64 arms × fair/legacy × 4 plan repetitions | rep bundle `explain/` trees | “512 raw-plan summaries covered” | production query plans |
| Target manifest | 598/598, 0 missing/size/hash mismatch | independently rehashed 2026-08-11 | targeted root `manifest.json` | artifact integrity | signed/tamper-proof evidence |
| Single 4→8 ratio | 0.782511 | median Jobs/s, four repetitions, threshold 0.95 | targeted `assessment.json` | negative gate fact | scalable/high performance |
| Balanced 4→8 ratio | 0.772797 | same | same | negative gate fact | scalable/high performance |
| 20:1 4→8 ratio | 0.796214 | same | same | negative gate fact | scalable/high performance |
| Many-small 4→8 ratio | 1.014063 | same | same | one workload passed | claim all workloads scale |
| Scaling gate | 3/4 failed 0.95 | all workloads had to pass | targeted `assessment.json` | “gate blocked release” | “near-ready release” |
| False-empty workflows | 1 RED, 2 GREEN | deterministic real PostgreSQL race | `31397416017`; `31398322919`; `31398332668` | RED→GREEN story | universal liveness proof |
| Historical fault matrix | 54/54 successful, 0 recorded violations | A–I ×3 before and after; historical SHAs | `docs/resume_benchmark/EVALOPS_FAULT_INJECTION.csv` | “historical controlled matrix” | current Candidate 3 capacity/SLO |
| Observer v1 claim-p95 | 11.3194% absolute change | 3 OFF/3 ON; 10% max | run `31400658653` | instrument rejected | scheduler root cause |
| Observer v2 claim-p95 | 13.4906% absolute change | low-overhead 3 OFF/3 ON; 10% max | run `31407782154` | instrument rejected | improvement/root cause |
| Passive throughput | OFF 29.918848; ON 29.790450; -0.4292% | 4 OFF/4 ON qualification | run `31421039618` | within 5% throughput budget | zero-overhead telemetry |
| Passive claim-p95 | OFF 708.689593 ms; ON 509.975702 ms; -28.0396% | same; absolute change exceeds 10% | measurement `assessment.json` | measurement invalid | ON improved scheduler |
| Passive telemetry integrity | 69 successful; 65 wait-observing; 5,393 rows; 0 errors/drops/overflow | 5 Hz qualification | eight telemetry summaries | collector ran cleanly | causal bottleneck evidence |
| Passive manifest | 151/151, 0 missing/size/hash mismatch | independently rehashed 2026-08-11 | measurement root `manifest.json` | artifact integrity | signed evidence |
| Local project test suite | 783 passed, 33 skipped | `.venv` Python 3.12; skips require external PostgreSQL/Redis/MinIO flags | 2026-08-11 rerun | exact local result | “816 tests passed” |
| System-Python attempt | exit 4, 55 collection errors | Python 3.13 missing project dependencies/plugin | 2026-08-11 rerun | environment diagnosis | code regression |
| Compileall | exit 0 | system Python, `app scripts tests` | 2026-08-11 rerun | syntax compilation | full-test substitute |
| Pre-archive CI | `31422948234`, `31422955446` success | baseline `39f381e`; branch and PR CI | GitHub Actions | historical baseline CI | final archive CI until rerun passes |

## Calculation notes

- All four `arms.csv` files were imported and every numeric Job/correctness field was independently summed.
- Receipt positions were grouped independently by worker count; each has four fair values of 2 and legacy values of 953.
- Scaling ratios were read from assessor `self_scaling`, whose w4/w8 throughput values are four-repetition medians.
- Both root manifests were rehashed by relative path and checked for missing file, size and SHA-256 mismatch.
- Fault total is 18 summary rows × 3 repetitions = 54, split 27 before/27 after; it remains historical.
