# AI EvalOps Platform — resume bullet pool

Status binding: Candidate 3 source `02f5e68`; ordinary CI PASS; targeted `31327388006` FAILED; release `NOT_READY`.

Select two or three bullets per role. Do not combine them with fairness/scaling/capacity claims.

## AI / RAG / Agent role

- 设计多租户异步 AI 评测任务的 Run/Job/Attempt/CaseResult 状态机，以 lease、heartbeat、retry、reaper 与
  owner/version/live-expiry fencing 阻止 stale Worker 覆盖合法结果；真实 PostgreSQL CI 覆盖崩溃恢复、
  stale success/failure 与非法状态迁移。
- 建立 Git SHA、协议、raw result、manifest、artifact digest 绑定的评测证据链；对失败实验 fail-closed，
  明确区分 current、historical、limited、failed 与 not-run，避免用历史容量替代当前候选方案。

## Python backend role

- 基于 FastAPI、SQLAlchemy、PostgreSQL 与 Redis 实现多租户异步任务编排；在 20 轮 10 Worker/100 Job、
  `limit=1` 并发合同中完成 2,000 个 unique Job claims/Attempts，保持 priority、full drain 与零首波空返回。
- 使用 `pg_stat_activity`、`pg_locks`、`pg_blocking_pids` 和 fail-fast timeout 复现 Run→Job / Job→Run 锁环，
  以最小 `FOR NO KEY UPDATE` lock mode 修复 FK 相关 deadlock，并在 push/PR 真实 PostgreSQL CI 中回归。
- 为 Job claim 保留 lease owner/expiry、heartbeat、attempt/version fencing 与原子 Attempt/Audit/Outbox 写入，
  防止重复 durable result 和过期 Worker 写回。

## Bank / SOE IT role

- 采用 PostgreSQL 状态机和可审计事件链实现多租户评测任务处理，结合租约、心跳、重试、回收与版本
  fencing，降低重复处理和过期节点覆盖结果的风险。
- 以固定并发协议和 source-bound manifest 验证任务领取正确性：20×10 Worker/100 Job 共 2,000 个
  unique claims/Attempts；失败门禁和未执行项均保留，不将实验结果表述为生产 SLO。

## Interview-only engineering story

The following is strong interview material but must not be a positive resume metric:

- Candidate 2 reservation order did not imply durable receipt order; deterministic RED reached secondary position 8.
- Candidate 3 durable rounds made the same test GREEN and rep1 observed positions `2/2/2/2`.
- The overall targeted bundle still failed because the EXPLAIN candidate unit changed from Jobs to Tenant round
  members while the assessor contract remained queue-cardinality based.
- The team stopped before Candidate 4 or downstream gates, preserving the failed evidence.

## Forbidden phrases

- “实现强公平/线性扩展/生产级容量/Exactly Once”。
- “20:1/8W 公平性已正式通过”。
- “v0.1.0 ready/production ready”。
- Any current capacity/fault/formal number for Candidate 3.
