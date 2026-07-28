# Worker 领取、租约与心跳合同

## 正确性语义

第一版语义是：

```text
at-least-once execution
+ idempotent result persistence
+ lease-based crash recovery
```

租约不会带来 exactly-once。旧 Worker 可能在网络分区后继续执行外部请求，因此后续结果提交
必须再次核对 `job_id + lease_owner + version + live lease`，并依赖唯一结果约束阻止重复最终
结果。

## 候选领取

`build_claim_candidates_statement()` 生成 PostgreSQL 查询，候选包括：

- `queued`；
- `retry_wait` 且 `next_attempt_at <= now`；
- 所属 Run 只能为 `queued` 或 `running`。

顺序固定为：

1. `priority DESC`；
2. `created_at ASC`；
3. `id ASC`。

最后使用：

```sql
FOR UPDATE OF evaluation_jobs SKIP LOCKED
```

锁只覆盖 Job 行。`SKIP LOCKED` 的目标是让多个队列消费者跳过别的事务已锁定的 Job；
它会给出不一致视图，所以不用于普通业务列表查询。依据可参阅
[PostgreSQL SELECT 文档](https://www.postgresql.org/docs/current/sql-select.html) 和
[SQLAlchemy with_for_update 文档](https://docs.sqlalchemy.org/en/20/core/selectable.html)。

## 领取事务边界

一个领取批次在短事务中完成选取、状态转换、租约字段、版本递增、Attempt 和审计写入。
事务提交后才执行 Target/Evaluator。网络调用、模型调用、artifact 写入等慢操作不能持有领取
行锁，否则吞吐和故障隔离都会恶化。

同一个 Run 的多个 Job 可能由不同 Worker 同时领取。Run 的 `queued → running` 使用带状态
条件的单条 `UPDATE ... RETURNING`；只有真正更新成功的事务写对应审计事件。

## 心跳保护

心跳是单条条件更新，必须同时满足：

- Job ID 相同；
- 状态仍为 `running`；
- `lease_owner` 等于 Worker；
- `version` 等于 Worker 持有的期望版本；
- `lease_expires_at > now`。

成功后更新时间、延长租约、版本加一，并用 `RETURNING` 把新版本交给 Worker。任一条件失败都
返回 `LeaseLostError`。旧 owner、旧 version、终态 Job 和已过期租约都不能被续期。

使用版本条件的原因是 owner 字符串可能在后续重新领取中复用；仅比较 owner 不能区分同一
Worker 进程的旧执行世代。SQLAlchemy 的乐观版本概念见
[官方版本控制文档](https://docs.sqlalchemy.org/en/20/orm/versioning.html)。

## 参数边界

- Worker ID 不得为空；
- 单次领取 1–100 条；
- 默认租约 30 秒，允许 5–3600 秒；
- 默认心跳间隔 10 秒；
- 租约策略对象拒绝非正值和超过 1 小时的时长。

运行时还应保证心跳间隔明显小于租约时长。配置字段分别为
`EVALOPS_WORKER_LEASE_SECONDS`、`EVALOPS_WORKER_HEARTBEAT_SECONDS` 和
`EVALOPS_WORKER_CLAIM_BATCH_SIZE`。

## 故障窗口

- 领取事务提交前崩溃：事务回滚，Job 可被其他 Worker 领取。
- 提交后、调用 Target 前崩溃：Job 保持 running，等待租约到期和 Reaper。
- Target 已产生副作用后崩溃：可能发生重复调用；上游若支持幂等键，应传递稳定的
  `job_id/attempt`。
- 心跳发布失败：不得假定租约仍归自己；执行者应停止提交并让 Reaper 回收。
- Redis 失败：不影响 PostgreSQL 租约事实。

## 验证边界

本地测试已验证状态机、SQL 结构、输入边界、迁移链和静态类型。真实 PostgreSQL 并发测试
合同会并发启动 10 个 Worker，断言 20 个 Job 无重复领取、Attempt 数量正确，并检查旧版本和
错误 owner 的心跳被拒绝。本机没有 PostgreSQL，测试被明确 skip，因此当前不能声称实际行锁
行为已在本机通过。
