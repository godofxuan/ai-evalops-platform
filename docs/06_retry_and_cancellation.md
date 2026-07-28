# 重试、崩溃恢复与协作式取消

## 错误分类

Worker 先把异常转换成稳定 `FailureClassification`，再决定是否重试。分类与调度分开，便于
审计、测试和以后调整策略。

默认可重试：

- Target timeout；
- HTTP 408、429、500、502、503、504；
- Target adapter 已明确标记为 transient 的连接错误。

默认不可重试：

- HTTP 400、401、403、404、422；
- 不支持或无效 Target 配置；
- 非预期 Worker 内部错误。

未知异常采用 `worker_internal_error` 和安全通用消息，不把任意异常文本写入数据库或日志。
这是保守策略：自动重试未知编程错误可能制造重试风暴。后续若有证据表明某类数据库/网络错误
是瞬态，应增加显式分类，而不是把全部 Exception 标成 retryable。

## 指数退避与 jitter

第 `attempt_number` 次失败的基础延迟：

```text
exponential = min(max_delay, base_delay × 2^(attempt_number - 1))
```

对称 jitter：

```text
delay = exponential × (1 + jitter_ratio × (2 × random - 1))
```

其中 `random ∈ [0, 1)`。默认 base=1 秒、max=60 秒、jitter ratio=0.2。

是否重试还必须同时满足：

- failure 可重试；
- `attempt_number < max_attempts`；
- 没有取消请求。

Clock 与 RandomSource 都可注入；单元测试使用 fixed random，不调用 sleep。数据库保存
`retryable`、`error_code`、`next_attempt_at`；领取器只在到期后重新领取。

## Worker 失败提交

成功和失败使用相同 fencing 条件：

- Job/Run ID；
- running 或 cancelling；
- lease owner；
- expected version；
- lease 未过期。

失败事务锁定 Job 与 active Attempt 后，根据策略执行：

- transient 且未耗尽：`running → retry_wait`；
- permanent 或耗尽：`running → failed`；
- 已观察取消：`running → cancelling → cancelled` 或
  `cancelling → cancelled`。

事务同步完成 Attempt、错误字段、lease 清理、审计与 Run 聚合。旧 Worker 无权把已由新世代
接管的 Job 改成 retry_wait/failed。

## Heartbeat 与执行期 fencing

Worker 用 `LeaseHeartbeatRunner` 在 Target coroutine 未结束时周期性：

1. 等待 operation 完成或 heartbeat interval；
2. 用当前 version 做条件心跳；
3. 用返回的新 version 替换本地 fencing token；
4. 若数据库返回 cancellation_requested，则设置 cancellation event、取消可取消的 coroutine，
   并以最新 version 提交 cancelled。

配置强制 `heartbeat_interval < lease_duration`。默认 10 秒与 30 秒。

对正在执行的 Job，取消事务改变状态为 cancelling 并写 `cancel_requested_at`，但不递增
lease version。原因是这次更新是给当前 owner 的协作信号，不是所有权换代；如果递增，当前
Worker 的下一次心跳会被错误 fence，无法读取取消。Reaper 回收或重新领取仍会递增 version，
真正隔离旧世代。

## Reaper

候选：

```sql
status IN ('running', 'cancelling')
AND lease_expires_at < now
FOR UPDATE OF evaluation_jobs SKIP LOCKED
```

顺序为 lease expiry、Job ID。每个回收事务：

- 保存 previous worker；
- 将未完成 Attempt 标记为 `lease_expired`；
- 未耗尽且 Run 未取消：进入 retry_wait 并设置 backoff；
- 已耗尽：failed；
- Run/Job 已取消：cancelled；
- 清理 lease；
- 写 `job.lease_expired` 审计；
- 按真实 Job 状态重新聚合 Run。

多个 Reaper 依赖 Job 行锁和 SKIP LOCKED 分工，不依赖 Redis 锁。该语义是幂等回收：第一次
事务离开 running/cancelling 后，后续扫描不再命中。

## Run 聚合

聚合函数只接受全部 Job 状态和是否请求取消：

- 全 queued：queued；
- 任一已开始/等待重试且未取消：running；
- 取消且仍有非终态：cancelling；
- 全 succeeded：succeeded；
- 全 failed：failed；
- 成功/失败混合：partially_succeeded；
- 取消后全部终态且包含 cancelled：cancelled。

数据库聚合在持有 Run 行锁时重新查询分组计数，覆盖缓存计数，而不是只信任 Worker 自增。
这样可以修复并发或历史失败造成的 counter drift。每次终态提交、Reaper 和取消都调用同一
聚合器。

## 取消 API

`POST /api/v1/runs/{run_id}/cancel`：

- tenant 来自 API Key Principal；
- terminal Run 原样返回；
- queued/retry_wait Job 直接 cancelled；
- running Job 进入 cancelling 并保留 lease；
- 已成功 CaseResult 保留；
- 重复调用幂等；
- 没有 running Job 时，Run 可在同一事务直接 cancelled。

取消是协作式的。已经发给上游的请求可能产生费用和副作用；即使本地 coroutine 被取消，也
不能保证远端停止。系统只保证观察到取消后不再自动重试。

## 能证明与不能证明

单元测试能证明分类、backoff、jitter、聚合、状态计划、SQL fencing 和 heartbeat version
传递。真实 PostgreSQL 合同覆盖多 Reaper、不重复回收、旧 Worker 结果拒绝与 queued Run
幂等取消，但本机没有服务，结果为 skip。

当前不能证明负载下 lock wait、真实 crash recovery 时延、远端 HTTP 真正停止或生产长期稳定
性，也不声称 exactly-once。
