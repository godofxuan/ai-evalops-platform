# 实时事件与 SSE 合同

## 结论

Redis Pub/Sub 只传递可丢失的实时通知，PostgreSQL 始终是 Run、Job、Attempt 和 Result 的
最终事实来源。客户端连接 `GET /api/v1/runs/{run_id}/events` 时，服务端先执行带 tenant
条件的 Run 查询并发送 `snapshot`，再订阅该 tenant/run 的 Redis 频道。断线重连不尝试从
Pub/Sub 回放，而是重新读取快照。Run/Job 状态和通知意图通过 PostgreSQL transactional
outbox 原子提交；API relay 负责后续 Redis 发布。

## 为什么这样设计

Redis Pub/Sub 是 at-most-once：订阅者不在线时消息不会保留。把它当状态总线会造成客户端
永久漏进度，也会让 Redis 故障改变评测正确性。直接在数据库 commit 后 publish 还会留下
进程崩溃窗口，因此采用三层模型：

```text
PostgreSQL transaction commits durable state + outbox intent
                 |
                 v
API relay leases pending row -> Redis PUBLISH -> fenced acknowledgement
                 |
                 v
SSE live notification; reconnect always starts from PostgreSQL snapshot
```

发布失败只记录安全错误码/异常类型，不记录 Redis URL、密码或业务 payload。失败行释放租约并按
有界指数退避重试。Worker、Reaper 和取消 API 不再直接连接 publisher；它们只在原状态事务中
写 Outbox。

## 事件结构

每条 `ProgressEvent` 都有：

- `event_id`：由状态事务创建的稳定 UUID；重试和崩溃接管时保持不变；
- `event_type`：受限枚举；
- `run_id`、`tenant_id`：服务端路由和二次隔离检查；
- `timestamp`：带时区时间；
- `payload`：小型 JSON，不承载最终事实。

支持的事件类型：

- `snapshot`；
- `run_started`；
- `job_progress`；
- `job_failed`；
- `job_retried`；
- `run_completed`；
- `heartbeat`。

频道名为：

```text
evalops:{tenant_id}:run:{run_id}
```

即使消息进入了正确频道，subscriber 仍重新验证 payload 内的 tenant/run；格式错误或不匹配
的消息会被丢弃。

## SSE 连接顺序

1. Bearer API Key 派生服务端 `Principal`。
2. `RunEventStream.open()` 用 `principal.tenant_id + run_id` 查询 PostgreSQL。不存在与
   跨 tenant 均沿用统一 404。
3. 在 HTTP headers 开始发送前完成上述授权查询。
4. 第一条 SSE 必须是完整 `snapshot`。
5. 为这个客户端创建独立 Redis PubSub 连接并订阅精确频道。
6. 有实时消息时原样转为 SSE；订阅轮询超时发送 `heartbeat`。
7. 客户端断开或生成器关闭时 unsubscribe 并 `aclose()`。

SSE 帧包含 `id`、`event` 和单行 JSON `data`。响应使用 `Cache-Control: no-cache` 和
`X-Accel-Buffering: no`。

## Redis 故障降级

订阅阶段发生连接、协议或超时异常时：

- 记录安全 warning；
- 不结束 Run、不改 Job；
- 转为按 `EVALOPS_SSE_FALLBACK_POLL_SECONDS` 查询 PostgreSQL；
- 快照发生变化时再发送 `snapshot`；
- 没变化时发送来源为 `postgresql_fallback` 的 heartbeat。

readiness 仍把 Redis 不可用报告为 503，因为完整实时能力不可用；但 Worker 的持久化正确性
不依赖 readiness 或 Redis 发布成功。发布失败时 Outbox row 保持 pending；API relay/Redis
恢复后重新尝试。这是“服务完整可用”和“领域状态仍能正确推进”两个不同合同。

## 保留策略与运维观测

API 内独立 cleanup task 默认每 60 秒删除一批最多 500 条“已确认发布且 `published_at` 早于
7 天 cutoff”的行。候选查询按 `published_at,id` 排序并使用 `FOR UPDATE SKIP LOCKED`；pending、
retry 和尚未 fenced acknowledgement 的行不会进入删除集合。多个 API 副本可以并发维护。

`/metrics` 从 PostgreSQL 刷新 `outbox_pending` 和 `outbox_oldest_pending_age_seconds`；后者从
最早 pending 的 `created_at` 计算，使长期 retry 不会被未来 `available_at` 隐藏。retry、lease
loss 和实际 cleanup 删除量分别有全局 Counter。每次完整成功 snapshot 还写
`outbox_metrics_last_success_timestamp_seconds`；失败时保留上次时间、增加
`outbox_metrics_refresh_failures_total` 并让 `/metrics` 继续返回 200。告警模板覆盖 backlog、lease
loss 与持续五分钟没有成功刷新；不代表真实 Prometheus/Alertmanager 已部署或验证。

## 重连与重复

当前不承诺客户端历史回放，也不使用 `Last-Event-ID` 恢复 Pub/Sub 历史。客户端应把每次连接
的首条 snapshot 当作权威基线，后续事件只作为刷新提示。

Outbox relay 是 at-least-once：Redis 已接受事件但进程在 `mark_published` 前退出时，租约过期后
另一 relay 会用同一个 `event_id` 重放。客户端可以按 SSE `id` 去重，但不能用事件数量推导
最终计数，也不能假定只会看到一次。

当前 Outbox 保存的是平台待发布/已发布意图，不是每个 SSE 客户端的消费日志。如果未来需要
完整客户端历史，应另建消费 offset、保留和回放合同，不能假装 Pub/Sub 或现有 Outbox 已具备
这些语义。

## 已验证与未验证

单元/API 测试覆盖：

- 模型序列化和受限事件类型；
- tenant/run 精确频道；
- malformed/cross-tenant 丢弃；
- snapshot 先于实时事件；
- Redis 失败转 PostgreSQL polling；
- 关闭流释放 PubSub；
- 成功、失败、重试、Claim、Reaper 和取消在状态事务内写通知意图；
- 多 relay `SKIP LOCKED` 认领、owner fencing、超时和有界退避；
- Redis publish 异常不让已完成 Worker 路径失败，并保留 pending row；
- publish 成功但 ack 丢失时以相同 event ID 重放；
- 两个 maintenance 并发、每轮一条时只删除两条过期 delivered 行；近期 delivered 和旧 pending
  保留；
- durable pending=1 与 oldest age=8 天的真实 PostgreSQL Gauge 快照；
- durable snapshot 成功时间精确等于观察时钟；失败保留旧时间并增加失败 Counter；
- SSE 鉴权 Principal 传递和响应 headers。

真实 PostgreSQL/Redis integration 覆盖事务回滚、跨 tenant FK、双 relay 认领、失败重试和
ack 丢失重放；P2-8 覆盖并发 retention 与 durable Gauge，P2-9 又验证 snapshot 成功时间。本机
没有启用真实服务，因此结果是 skipped；GitHub Actions #28、#29、#31 和 #34 已实际通过对应合同。
完整过程和残余风险见
[`reviews/p2_7_transactional_outbox_log.md`](reviews/p2_7_transactional_outbox_log.md)、
[`reviews/p2_8_outbox_operations_log.md`](reviews/p2_8_outbox_operations_log.md) 与
[`reviews/p2_9_outbox_metrics_freshness_log.md`](reviews/p2_9_outbox_metrics_freshness_log.md)。
