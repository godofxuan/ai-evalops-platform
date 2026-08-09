# v0.1.0 release decision

## Decision: NOT_READY

截至 2026-08-09，本分支不应创建或发布 `v0.1.0` Release。

审阅入口：[Draft PR #1](https://github.com/godofxuan/ai-evalops-platform/pull/1)。Draft 状态表示证据可供
审阅，不表示满足 release gate。

当前 scheduler candidate（HEAD `2879b4c`）已把 historical Job/Tenant 联合 claim 拆成两个提交
边界：短 Tenant fair-turn reservation，以及 tenant-scoped、只显式锁 Job 的 durable claim。
Phase B 仍可能因 tenant-referencing writes 产生 PostgreSQL foreign-key lock semantics，不能描述成
“transaction 完全不涉及 Tenant lock”。该 candidate 的 push/PR CI `31297535370` / `31297538171`
均在 same-tenant integration step 达到 GitHub 6 小时上限后被取消，所以以下旧 source gate 不能
自动 promotion 为当前 candidate 的 release 结论。

| Gate | Historical verified source | Current candidate `2879b4c` |
|---|---|---|
| correctness | A–I ×3 27/27，stale accepted 0 | UNKNOWN；CI 未完成 |
| fairness | 20:1 secondary tenant position ≤2 | UNKNOWN；需重跑 durable-claim contract |
| capacity | 1k/10k/100k 32+16 arms VERIFIED | NOT_RUN |
| CI | `31274490725`、`31275450358` success | FAIL；两个 run 均在 6h 上限取消 |
| evidence manifest | historical capacity/formal/fault PASS | INCOMPLETE |
| README/evidence consistency | historical source 边界已核验 | 当前架构事实已校正，最终数字待验证 |
| performance release gate | **FAIL**；8 组中 5 组回退 >15% | NOT_RUN；历史 FAIL 尚未被替代 |

当前首要 blocker：same-tenant PostgreSQL integration 无限等待，导致 current candidate 的 CI、
correctness 与后续 performance qualification 均未完成。解决该测试/锁问题后，仍必须重跑 targeted、
capacity、fault 与 formal gate；历史上 tenant-fair claim path 在 4/8 workers 的 performance FAIL
继续有效，直到新的 source-bound evidence 取代它。没有 LLM judge、UI、SDK、Kafka、Temporal、
production tracing backend 均不是 blocker。

## What is ready

代码与证据适合作为 Draft PR 供审阅：多租户公平 correctness、resume-safe lease/fencing、短暂依赖
中断恢复、1k/10k/100k source-bound 容量与完整证据链都已建立。它可以称为
“evidence-backed experimental release candidate”，不能称为 production-ready、production-grade、
exactly-once、linear scaling 或 strong fairness SLO。

## Required next release action

先为所有锁敏感测试加入 PostgreSQL/Python/CI fail-fast，再用 `pg_stat_activity`、`pg_locks` 与
`pg_blocking_pids` 证明 6 小时等待的真实原因，并校正 production-shaped test contract。只有普通 CI
GREEN 后才允许按顺序运行 targeted、capacity、fault 与 formal gate；全部通过后才能把本文件改为
`READY_FOR_V0_1_0_RELEASE`。历史 FAILED/negative bundles 必须继续保留。
