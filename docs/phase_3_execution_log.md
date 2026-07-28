# Phase 3 逐步执行日志

## P3-001：范围判断与仓库复核

- 日期：2026-07-29
- 起始 SHA：`ffff1e4`
- 用户指令：继续执行并全部完成。
- 判断：该新指令覆盖原附件“每阶段停止”和“五个学习模块第一轮仅写 RED tests”的流程限制；
  仍保留逐阶段 TDD、详细日志、小提交、不自动 push、失败与 skip 不得美化等约束。
- 当前问题：数据库已有 Job lease 字段，但没有状态机、Attempt 表、领取实现、心跳条件更新和
  审计事实。
- 文件计划：新增两个状态机、clock、`app/jobs`、Phase 3 migration、单元/并发测试及两份
  合同文档；修改 enum、ORM 和 Worker 配置。

## P3-002：Job 状态机 RED → GREEN

- 首个测试要求 `queued → running` 返回 previous/current/reason/actor。
- RED：`ModuleNotFoundError: app.domain.job_state_machine`。
- 最小实现：显式邻接表、固定领域异常和不可变 transition 对象。
- 扩展表驱动测试第一次运行产生 10 个失败，因为其余合法边尚未加入。
- 修正：只加入需求列出的合法边，不增加便利捷径。
- GREEN：Job 合法边、非法边和空审计上下文全部通过。
- 效果：各 service 不再需要复制状态判断。
- 风险：纯函数只能判转换是否合法，不能证明数据库状态没有在别处被直接写入。

## P3-003：Run 状态机 RED → GREEN

- RED：`ModuleNotFoundError: app.domain.run_state_machine`。
- 实现：queued/running/cancelling 与四类终态的显式图。
- 表驱动扩展测试第一次产生 9 个失败；加入需求允许边后通过。
- 额外回归：成功 Run 不能重新打开；reason/actor 不得为空。
- 判断：首个 Job 领取可以启动 Run，但最终状态只能由全局聚合器决定。

## P3-004：Attempt 与 Audit ORM RED → GREEN

- 测试先导入 `JobAttempt`、`AuditEvent`，并检查表、外键、唯一约束及字段。
- RED：`ImportError: cannot import name AuditEvent`。
- 实现：
  - `AttemptOutcome`；
  - `(job_id, attempt_number)` 唯一；
  - attempt、latency 检查约束；
  - tenant-owned `audit_events` 和资源索引。
- GREEN：ORM 元数据测试 `6 passed`。
- 效果：每次真实执行有独立记录，状态原因/操作人有数据库落点。

## P3-005：Clock、领取 SQL 与心跳 SQL RED → GREEN

- 新测试同时要求：
  - UTC aware system clock；
  - PostgreSQL `FOR UPDATE OF evaluation_jobs SKIP LOCKED`；
  - 确定性领取顺序；
  - Run 状态过滤；
  - 心跳 owner/version/status/live-expiry 全条件；
  - `UPDATE ... RETURNING`；
  - Worker ID、batch、duration 边界。
- RED：三个模块在收集时失败：
  - `app.core.clock` 不存在；
  - `app.jobs` 不存在；
  - heartbeat 模块不存在。
- 最小实现后 GREEN：目标集合 `39 passed`。
- 设计判断：
  - 使用 PostgreSQL 行锁，不用 Redis 锁；
  - `retry_wait` 到期时在一个事务内走两条合法边；
  - Target 调用不得进入领取事务；
  - 心跳每次递增 version，调用方必须更新自己的 fencing token。

## P3-006：并发合同与迁移

- 新增 migration `20260729_0004_worker_leases.py`。
- `alembic heads`：`20260729_0004 (head)`。
- `alembic upgrade head --sql`：成功生成完整 PostgreSQL DDL。
- 并发测试合同：
  - 10 个 Worker 同时领取 20 个 Job；
  - 每个 Job 仅有一个 claim；
  - 20 条 Attempt；
  - 合法心跳得到新版本；
  - 旧版本和错误 owner 均被拒绝。
- 本机结果：`1 skipped`，原因是未设置带迁移真实 PostgreSQL 的
  `EVALOPS_RUN_INTEGRATION=1`。没有使用 SQLite 替代。
- 未验证：真实调度时的锁等待、吞吐和事务隔离细节。

## P3-007：静态检查问题与修正

- 首轮目标测试：`45 passed, 1 skipped`。
- Ruff 首轮失败 4 项，均为未使用 import：
  `timedelta`、`UUID`、`LocalArtifactStore`、`datetime`。
- 修正：删除导入，不改变行为。
- mypy：45 个 app source files，0 issues。
- Ruff：All checks passed。
- 非集成全量回归：`127 passed, 4 deselected in 5.70s`。
- 临时 pytest 目录在验证其父路径为仓库根后用 PowerShell `Remove-Item -LiteralPath`
  精确清理。

## P3-008：提交

- 实现提交：`e712f8a feat(worker): add skip-locked leases and heartbeat`
- 提交前：`git diff --cached --check` 通过。
- 未 push。

## 为什么没有采用其他方案

- Celery：会隐藏本阶段要学习的领取、行锁、lease 和 crash recovery。
- Redis 分布式锁：Redis 不是最终事实源，也不能替代 Job 行的事务更新。
- `SELECT` 后在另一个事务更新：锁在提交时释放，会重新打开重复领取窗口。
- 只比较 `lease_owner`：同名 Worker/同一进程重启时无法隔离旧执行；必须加入 version。
- 长事务包住模型调用：会长期持锁和连接，故障放大明显。
- SQLite 集成测试：不支持本合同依赖的 PostgreSQL 锁语义。

## 当前实现能证明什么

- 状态图允许与禁止的边；
- reason/actor 强制存在；
- PostgreSQL 方言 SQL 含 `SKIP LOCKED`、候选过滤、固定顺序和 fencing 条件；
- ORM/migration 存在 Attempt 唯一约束及审计表；
- 领取和心跳 API 通过类型、lint 与非集成回归。

## 当前实现不能证明什么

- 本机真实 PostgreSQL 下 10 Worker 无重复领取；
- Worker 已执行 Target 或提交结果；
- lease 到期后已经由 Reaper 回收；
- exactly-once 执行或零重复上游调用；
- 生产负载、长时稳定性或安全认证。

## 建议亲自理解的代码

1. `app/jobs/claiming.py`：锁范围、事务边界、retry_wait 两步转换和 Run 条件启动。
2. `app/jobs/heartbeat.py`：为什么五个 WHERE 条件缺一不可。
3. `app/domain/job_state_machine.py`：显式图与领域错误。
4. `app/persistence/orm_models.py`：Attempt 唯一约束与审计事实。
5. `tests/concurrency/test_job_claiming.py`：真实 PostgreSQL 证据和 skip 的区别。

## 面试官可能追问

- `SKIP LOCKED` 为什么只适合队列消费者，不适合普通列表？
- 锁定多条 Job 时如何避免饥饿？
- lease owner 与 version 分别防什么问题？
- Worker 心跳成功后为什么必须替换本地 version？
- 领取后崩溃和 Target 成功后崩溃的语义有什么不同？
- 为什么这仍是 at-least-once，而不是 exactly-once？
- 两个 Worker 同时启动同一 Run 时为何只有一个 Run 审计事件？
