# v0.1.0 release decision

## Decision: NOT_READY

截至 2026-08-10，PR #1 必须保持 Draft；不得 merge，不得创建 `v0.1.0` tag 或 GitHub Release。

Candidate 3 的普通 CI 和预注册 scheduler correctness 已通过，但 source-bound targeted workflow
`31327388006` 失败。第 1 次 repetition 的 16/16 workload/worker arms 均完成并各自通过 correctness，
20:1 的 application receipt 与数据库 claim sequence 均观察到 secondary position `2/2/2/2`；然而
release-bundle 校验发现 64/128 个 `fair` EXPLAIN 摘要的 `candidate_cardinality` 与冻结的 queue-size
合同不一致，正式 blocker 为 `postgres_explain_candidate_cardinality_mismatch`。因此 4 次 repetitions
没有完成，不能宣称 targeted fairness 或 performance 正式通过。

| Gate | Current result | Evidence |
|---|---|---|
| ordinary CI | PASS | source `02f5e68`; push `31327012832`; PR `31327016117` |
| scheduler correctness | PASS | priority、20×10W/100J、uniqueness、full drain、permit crash、cross-Tenant progress、fencing、deadlock regressions |
| frozen 20:1 fairness | INCOMPLETE | rep1 observed `2/2/2/2`, but required four-repetition targeted bundle did not verify |
| targeted qualification | **FAILED** | `31327388006`; blocker `postgres_explain_candidate_cardinality_mismatch` |
| targeted performance | INCOMPLETE / NOT_ESTABLISHED | only rep1 exists; 4→8 ratios are diagnostic only |
| current 1k/10k/100k capacity | NOT_RUN | stopped after targeted failure |
| current same-runner A/B/C | NOT_RUN | stopped after targeted failure |
| current A–I ×3 fault | NOT_RUN | stopped after targeted failure |
| current formal 32-arm | NOT_RUN | stopped after targeted failure |
| release manifest | INCOMPLETE FOR RELEASE | targeted failed; downstream bundles do not exist |

## Candidate 3 achieved scope

- Replaced Candidate 2's separable reservation/Phase-B ordering with durable fair rounds backed by a singleton
  coordination row and reusable per-Tenant scheduler state.
- A round cannot advance while an equal-priority Tenant permit remains pending; Job/Attempt/Audit/Outbox writes and
  permit consumption commit in one short PostgreSQL transaction.
- `JobAttempt.scheduler_claim_sequence` adds a database-linearized diagnostic without redefining the frozen
  application-visible receipt gate.
- The deterministic Candidate 2 RED (secondary receipt position `8`) becomes GREEN for Candidate 3, and ordinary
  PostgreSQL CI preserves priority, uniqueness, liveness, crash rollback/recovery and fencing.
- No Worker execution, evaluator, result, reaper, API, lease duration, retry budget, workload, Worker count or
  fairness threshold was changed to obtain the result.

## Why qualification still stops

The targeted assessor was preregistered to fail closed. Candidate 3 changed the fair EXPLAIN query from a Job-ranked
candidate set to scheduler-round membership; the saved fair summaries therefore report active Tenant cardinality
(`1`, `2`, `4` or `100`) while the old release contract still requires queue cardinality `1000`. All 64 fair
summaries mismatch; all 64 legacy summaries retain `1000`. This is a real evidence-contract incompatibility, not a
license to discard the gate or reinterpret an incomplete run as PASS.

Section 58/62 of the frozen execution protocol requires `targeted fail -> STOP`. No Candidate 4, threshold change,
workload change, parameter tuning or immediate retry is permitted. Historical capacity/fault/formal bundles remain
`VERIFIED_HISTORICAL` only.
