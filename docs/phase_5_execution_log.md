# Phase 5 逐步执行日志

## P5-001：问题、合同与文件计划

- 日期：2026-07-29
- 起始 SHA：`e328933`
- 目标：错误分类、指数退避+jitter、失败落库、执行期 heartbeat、Reaper、Run 聚合、
  cooperative cancellation 和可运行 Worker/Reaper CLI。
- 当前缺口：Phase 4 只处理成功；任何 Target 异常都会让 Job 保持 running，CLI 仍是生命周期
  占位。
- 设计判断：
  - PostgreSQL 继续是唯一事实源；
  - 成功/失败必须用相同 fencing；
  - Reaper 与 Worker 共用 RetryPolicy；
  - Run counters 由全量 Job 聚合修正；
  - 时间和随机数均注入；
  - 取消不承诺撤销远端副作用。
- 计划文件：random source、retry policy、failures、reaper、cancellation、aggregation、
  lease runner、runtime、API/集成/并发测试和本文档。

## P5-002：核心策略 RED

先写五组测试：

1. transient/permanent 分类与 jitter；
2. Run 聚合；
3. expired lease `SKIP LOCKED` SQL；
4. Job cancellation plan；
5. heartbeat runner version/cancel。

收集得到 5 个 `ModuleNotFoundError`，分别对应上述五个尚不存在的模块。

## P5-003：RetryPolicy GREEN

- HTTP 408/429/500/502/503/504 和 timeout 可重试；
- HTTP 400/401/403/404/422 与无效配置不可重试；
- unknown error 使用安全 `worker_internal_error` 且默认永久；
- exponential backoff 封顶；
- 对称 jitter 使用注入 RandomSource；
- max attempts 与 cancel 是独立停止条件。

固定 random=0.75、base=2、attempt=3、ratio=0.25 的期望延迟为 9 秒，测试无需 sleep。

## P5-004：聚合、Reaper SQL 与取消计划 GREEN

- 纯聚合函数覆盖 queued/running/succeeded/failed/partial/cancelling/cancelled。
- 空 Run 被拒绝，避免除零或模糊状态。
- Reaper SQL 明确 running/cancelling、expired、固定顺序和 `SKIP LOCKED`。
- queued/retry_wait 直接 cancel，running 进入 cancelling，terminal 不变。
- 首轮结合旧 heartbeat 测试得到 `35 passed, 1 failed`：旧测试仍断言 status 必须严格等于
  running。
- 判断：Phase 5 需要 cancelling Worker 继续一次 heartbeat 来读取取消信号，所以 SQL 合同
  改为 running/cancelling，并返回 cancel_requested_at。
- 更新过期合同后 `36 passed`。

## P5-005：第二组 RED 与失败落库

- 新测试要求 failure commit 使用 owner/version/live-expiry fencing。
- RED：`app.jobs.failures` 不存在。
- 新 Worker 测试要求 429 不再丢失 claim，而是调用 failure committer。
- 新 Run API 测试要求 cancel 使用服务端 Principal 并返回当前 snapshot。
- 实现后目标集合 `22 passed`。

失败事务：

- 锁 owned Job 与 active Attempt；
- 分类异常；
- 决定 retry_wait/failed/cancelled；
- 完成 Attempt；
- 清理 lease；
- 保存安全错误字段；
- 审计；
- 调用统一 Run 聚合。

## P5-006：执行期 heartbeat 与取消竞态

- `LeaseHeartbeatRunner` 维护最新 version。
- operation 异常包装为带 `lease_version` 的 `LeaseOperationError`，使失败落库不会使用过期
  token。
- 心跳观察取消后设置 event、取消 coroutine，并携带最新 version 进入 failure committer。
- 一个关键竞态判断：running → cancelling 不递增 lease version；否则当前 owner 的下次
  heartbeat 会在读取取消前被 fence。直接 cancelled、Reaper 和重新领取仍递增 version。
- `cancelling → succeeded` 保留，表示完成事务先获得 Job 锁或 Worker 在安全提交点完成。

## P5-007：Reaper 与聚合持久化

- Reaper 每批短事务使用 Job `SKIP LOCKED`。
- active Attempt outcome=`lease_expired`。
- previous worker、action、next attempt、reason 全部写审计。
- 多 Run 以排序后的 Run ID 聚合，降低批次间 Run lock 顺序死锁风险。
- 聚合持有 Run lock、重新 group-by Job statuses 并覆盖 counters。
- Result committer 从“只增加 succeeded counter”重构为同一统一聚合器。

## P5-008：Cancellation service 与 API

- 先 tenant-scoped 读取 Run；
- 按 Job ID 锁所有非终态 Job，再锁 Run，保持与 Worker/Reaper 的 Job→Run 锁顺序一致；
- terminal Run 幂等返回；
- queued/retry_wait 直接终止；
- running 写 cooperative signal；
- 聚合决定 cancelling 或 cancelled；
- `POST /api/v1/runs/{id}/cancel` 返回 202 snapshot。

真实 PostgreSQL Run 集成合同增加 queued cancel 与重复 cancel，均应返回 cancelled 且计数为 2。

## P5-009：Worker/Reaper runtime

- CLI `--check` capability 从 `lifecycle_only` 更新为 `operational`。
- Worker loop 构造 claimer、heartbeat runner、Target/Evaluator pipeline、成功/失败 committer。
- Reaper loop 周期扫描并支持 `--once`。
- 空队列/周期等待使用可被 stop event 提前唤醒的 asyncio wait。
- 日志只记录稳定 event、worker/reaper ID 与 error type，不记录异常文本或 case 内容。
- 配置验证 heartbeat < lease、retry base <= max。

## P5-010：并发合同扩展

真实 PostgreSQL 并发测试现在还要求：

- 19 个已过期 Job 由两个 Reaper 合计恰好回收 19 次；
- Job ID 不重复；
- 全部进入 retry_wait；
- 19 条 Attempt 标为 lease_expired。

本机两个真实合同结果均为 skip，原因是缺少 migrated PostgreSQL。未改用 SQLite。

## P5-011：静态与回归

- 中途目标：`52 passed`，随后 runtime 集合 `56 passed`。
- mypy 首轮唯一失败：backoff 表达式被推断含 Any。
- 修正：使用 `math.pow(2.0, exponent)` 固定 float 类型，公式不变。
- Ruff 唯一失败：等待函数的 try/except/pass 可用 suppress；机械修改。
- 最终：
  - Ruff All checks passed；
  - mypy 65 source files，0 issues；
  - 非集成回归 `181 passed, 4 deselected in 4.19s`；
  - 指定两个真实合同 `2 skipped`。
- Docker/Compose 仍未运行，本机没有 docker 命令。

## P5-012：提交

- `b7f3de5 feat(worker): add retry recovery and cancellation`
- 提交前 `git diff --cached --check` 通过。
- 未 push。

## 为什么没有采用其他方案

- tenacity 全包：会隐藏 retry classification、Attempt 和 backoff 审计。
- 真实 sleep 测试：慢且不稳定；使用 Clock/RandomSource。
- Redis delayed queue：Redis 不是最终事实源；next_attempt_at 留在 PostgreSQL。
- Reaper 先查后逐个无锁更新：多 Reaper 会重复回收；使用行锁与 SKIP LOCKED。
- 取消时强杀线程：Python/远端 HTTP 不保证安全；采用 cooperative cancellation。
- 每个 Worker 自己写 Run 终态：局部视图会错；使用统一数据库聚合。

## 当前能证明

- 明确的可重试/永久错误表；
- backoff+jitter 可复现且不超 max attempts；
- 旧 lease 对成功和失败都无提交权；
- Run 状态规则与 counter 重算集中；
- Worker/Reaper 进程入口已接真实组件；
- API 取消与重复取消合同存在。

## 当前不能证明

- 本机真实多 Reaper 和取消/完成竞争；
- Worker 进程在 Docker 中真实长时运行；
- 上游请求收到 task cancellation 后真正停止；
- PostgreSQL 故障期间连接恢复策略；
- exactly-once、零重复费用或生产级可靠性。

## 建议亲自理解

1. `app/jobs/retry_policy.py`：分类、次数边界和 jitter。
2. `app/jobs/failures.py`：异常如何变成数据库状态。
3. `app/jobs/reaper.py`：expired lease 的幂等回收。
4. `app/runs/aggregation.py`：为什么重新聚合比 counter 自增更可靠。
5. `app/jobs/cancellation.py`：Job→Run 锁顺序与运行中 Job version 取舍。
6. `app/workers/lease_runner.py`：最新 fencing token 如何穿过异常路径。

## 面试官可能追问

- jitter 为什么需要注入 RandomSource？
- unknown error 为什么默认不重试？
- 多个 Reaper 如何避免重复回收？
- 取消为何不保证上游零副作用？
- running→cancelling 为什么不更换 lease generation？
- counters 与全量聚合冲突时谁是事实？
- Worker 在 heartbeat 后异常，失败提交应使用哪个 version？
- PostgreSQL 故障时当前 loop 有哪些不足？
