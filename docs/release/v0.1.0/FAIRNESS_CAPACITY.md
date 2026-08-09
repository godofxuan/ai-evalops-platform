# v0.1.0 RC fairness and capacity

Current conclusion: targeted qualification `FAILED`; complete Candidate 3 fairness is `INCOMPLETE`; current
1k/10k/100k capacity is `NOT_RUN`.

Targeted run `31327388006` executed source `02f5e68` with the frozen 1k queue, four distributions, Workers
1/2/4/8, batch 1 and four planned repetitions. Repetition 1 completed all 16 arms. In 20:1, secondary Tenant first
application-visible durable receipts were `2/2/2/2`; database-linearized claim sequence also reported `2/2/2/2`.
All 16 raw arm assessments were `VERIFIED` and reconciled 1,600/1,600 Jobs.

That observation is not a formal PASS. The repetition-level release bundle failed
`postgres_explain_candidate_cardinality_mismatch`: the Candidate 3 round-membership EXPLAIN reports active Tenant
cardinality (`1`, `2`, `4` or `100`), while the frozen evidence assessor still requires Job queue cardinality
`1000`. Exactly 64/128 EXPLAIN records—all `fair` records and no legacy records—mismatched. The top level therefore
records zero verified repetitions and fails the required count of four.

Observed rep1 metrics are diagnostic only:

| Distribution | w4 Jobs/s | w8 Jobs/s | 4→8 | w8 claim p95 ms | w8 retries | w8 waiting fallbacks |
|---|---:|---:|---:|---:|---:|---:|
| single Tenant | 29.785233 | 20.197495 | 0.678104 | 835.514 | 559 | 318 |
| balanced | 51.446398 | 40.408899 | 0.785456 | 304.065 | 98 | 60 |
| 20:1 | 36.767757 | 27.574409 | 0.749962 | 671.042 | 272 | 155 |
| many-small | 47.575351 | 45.425358 | 0.954809 | 422.767 | 0 | 0 |

Historical `31272789199` still contains complete 1k/10k/100k capacity evidence. Its 100k single-Tenant/w8
approximately `0.628 Jobs/s`, `504` retries and `41s` claim p95 remain negative engineering history, not Candidate 3
measurements. No current capacity or strong-fairness SLO is supported.
