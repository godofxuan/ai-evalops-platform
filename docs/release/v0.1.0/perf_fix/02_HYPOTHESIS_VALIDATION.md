# H1 PostgreSQL 并发假设验证

## 1. 验证边界

本阶段只验证 H1，不改 production scheduler。测试运行在 GitHub Actions 的真实 PostgreSQL
18.4 服务上，本机因没有 Docker 明确 skip，未把 SQLite、SQL 编译或本地 mock 当作行锁证据。

优先级保持为：H1 排名截断 + Tenant 热点锁；只有 H1 rejected 才进入 H2 retry/probe 放大，
再不足才进入 H3 connection/transaction lock wait。结果显示 H1 confirmed，因此未扩展到 H2/H3。

## 2. RED-1：production-shaped locked head

- commit：`8567738f2f413868086ba98d55eaa1a09a392404`
- push run：`31295464313`
- PR run：`31295467932`
- fixture：同一 Tenant、同一 running Run、J1–J4，`limit=1`。
- 同步方式：Worker A 在显式未提交事务中执行 production candidate selector，确认选中 J1；
  保持 Job/Tenant 锁期间，Worker B 调用公开 `SQLAlchemyJobClaimer.claim()`。
- 稳定性：每次使用全新 fixture，重复 20 次，不使用随机 sleep。

两个独立 runner 的 Checks annotation 都显示 20/20 为 expected J2、observed empty tuple。其他
integration steps 与 image build 成功，排除迁移、fixture 和通用 CI 故障。

结论：`LOCKED_HEAD_CONCURRENCY_RED` confirmed。

## 3. RED-2：只锁 J1，隔离 rank pruning

- commit：`06f8e5e2e9697a89b0585007be2e03eef3808903`
- push run：`31295691145`
- Worker A 只执行 `SELECT evaluation_jobs.id ... FOR UPDATE` 锁 J1；没有读取或锁 Tenant。
- Worker B 仍走 current fair selector，`limit=1`。
- Checks annotation 标签：`RANK_PRUNING_CONCURRENCY_RED`。

20/20 为 expected J2、observed empty。由于 Tenant 完全未锁，结果隔离证明：每 Tenant 的
`row_number()` 候选在锁前被 `tenant_candidate_rank <= 1` 裁成 J1；J1 被 `SKIP LOCKED`
跳过后，J2 没有进入可回填候选集合。

结论：rank-before-lock/pruning 子假设 confirmed。

## 4. RED-3：只锁 Tenant，所有 Job 均未锁

- commit：`869b8649321091c59d0cec9de197ee08bd095929`
- push run：`31295918494`
- Worker A 只执行 `SELECT tenants.id ... FOR UPDATE`；J1–J4 均未锁。
- Worker B 走 production claim，理想结果为 J1。
- Checks annotation 标签：`TENANT_HOT_ROW_RED`。

20/20 为 expected J1、observed empty。结果隔离证明：`FOR UPDATE OF evaluation_jobs, tenants
SKIP LOCKED` 使一个 Tenant 行成为该 Tenant 所有 Job claim 的共享热点，即使任务行完全可用，
也会整体跳过该 Tenant。

结论：Tenant hot-row 子假设 confirmed。

## 5. RED-4：8 Worker 诊断基线

- commit：`95f64eab9084a472232e7a7bec99b0b5ec54e2bf`
- push run：`31296185080`
- fixture：100 个同 Tenant queued jobs；8 Worker；`limit=1`；`asyncio.Barrier(9)` 同步启动。
- 不使用固定耗时断言；延迟只作为观测值。

原始 annotation 指标：

| Metric | RED value |
|---|---:|
| claim requests | 8 |
| claim attempts | 23 |
| successful requests | 8 |
| final empty requests | 0 |
| claimed / unique jobs | 8 / 8 |
| empty attempts | 15 |
| eligible probes | 15 |
| empty while eligible | 15 |
| contention retries | 15 |
| retry / success | 1.875 |
| claim latency p50 | 173.664705 ms |
| claim latency max | 217.405732 ms |

最终 correctness 是 8/8 unique success，但它由 15 次有任务时空尝试与固定 retry/probe 掩盖。
这解释了为什么旧 correctness suite 可以全绿，而 4/8 Worker formal throughput 仍显著回退。

## 6. H1 决策

H1 状态：`CONFIRMED`。

两个子预测均在独立显式锁实验中 20/20 成立，组合实验也在 push/PR 两个 runner 成立；因此
允许进入 production fix。H2/H3 没有被声明为不存在，只是当前证据已经足以解释 blocker，按
三假设上限和最小修复原则不继续扩散诊断范围。

## 7. 验证过程问题

1. 第一次轮询在新增 step 已失败、后续 Build 正在运行时，状态选择表达式返回了最后一个
   in-progress step，曾误读为 RED-1 通过。最终 run conclusion 与逐 step API 明确显示新增 step
   failure；随后从 Checks annotation 取得断言详情并更正。
2. 原始 job log 下载 API 对公开仓库仍返回 403 `Must have admin rights`。没有提高权限，改用公开
   Checks annotations；push 与 PR 两份 annotation 提供了独立复现。
3. 每个测试第一次提交前都先在本机跑 format/lint/mypy；本机 integration 只允许明确 skip，
   production behavior 结论全部来自 PostgreSQL runner。
