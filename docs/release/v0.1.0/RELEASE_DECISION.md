# v0.1.0 release decision

## Decision: NOT_READY

截至 2026-08-09，不得 merge PR #1，不得创建 `v0.1.0` tag 或 GitHub Release。PR 保持 Draft。

当前唯一 blocker：最终 Candidate 2 在 source `246252e30e63f046a4a1fb5d684a35449aaef9e3` 的 targeted run
`31319556885` 中未通过冻结的并发 20:1 公平门禁。8 Worker 时 secondary Tenant 的首个 durable
claim 完成位置为 4；合同要求 `<= 2`。

| Gate | Current result | Evidence |
|---|---|---|
| CI | PASS | Candidate 2: `31318294569`/`31318298660`; Run guard: `31319292162`/`31319295583` |
| state/fencing correctness | PASS | 20×10W drains; targeted attempt 2 已完成 1,200/1,200 unique terminal Jobs |
| concurrent 20:1 fairness | **FAIL** | `skew_20_to_1/w8`, secondary durable claim position 4 > 2 |
| targeted four-repetition scaling | INCOMPLETE | repetition 1 在第 12 arm fail-closed |
| current 1k/10k/100k capacity | NOT_RUN | targeted PASS 前置条件未满足 |
| current A-I ×3 fault | NOT_RUN | capacity PASS 前置条件未满足 |
| current formal 32-arm | NOT_RUN | correctness/fault/performance chain 未完成 |
| same-runner A/B/C | NOT_RUN | targeted gate 未通过 |
| release manifest | INCOMPLETE FOR RELEASE | 两次 targeted 失败 artifact 完整；下游 current bundles 不存在 |

## 已解决的问题

- 6 小时 CI hang 的真实原因是测试长期持有外部 `Tenant FOR UPDATE`，完整 durable claim 的 Tenant FK
  write 请求 `KEY SHARE` 并被阻塞，而测试 scope 又等待 claim 返回。它是错误测试等待环，不是 Job
  selector 隐式锁 Tenant。
- selector-only、外部 `FOR UPDATE`、外部 `FOR NO KEY UPDATE` 和 bounded production overlap 已在真实
  PostgreSQL 中分开验证；所有 lock-sensitive tests 都有 PostgreSQL/Python/CI fail-fast。
- fair-turn Tenant guard 使用最小充分的 `FOR NO KEY UPDATE`；Job durable claim 仍使用
  `FOR UPDATE OF evaluation_jobs SKIP LOCKED`。
- Candidate 2 用一次有界等待 fallback 消除 20 次 10W/100J 中的 false-empty；2,000 unique Jobs 与
  2,000 Attempts 通过双入口 CI。
- targeted attempt 1 暴露 Result Run-first 与 Claim Job-first 的锁环。`3350c23` 把 Run guard 降为
  `FOR NO KEY UPDATE`，保留 writer 互斥并允许 Outbox FK `KEY SHARE`；双入口 CI 通过，attempt 2 的
  1,200 Jobs 未再发生 deadlock。

## 为什么现在停止

任务最多允许两个基于新证据的 scheduler production iterations；Candidate 2 已是最后一个。不得通过
放宽 secondary position `<= 2`、增加 retry/sleep/pool/batch/lease 或删除失败 arm 来取得绿色。

历史 capacity、fault 和 formal bundles 继续作为 `VERIFIED_HISTORICAL` 保存，但不得代表当前 Candidate
2。下一阶段只允许一个目标：先形成带可证明并发公平不变量的 scheduler redesign proposal，再决定是否
开启新的实现周期。
