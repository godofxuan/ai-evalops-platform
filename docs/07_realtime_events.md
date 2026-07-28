# 实时事件与 SSE 合同

## 结论

Redis Pub/Sub 只传递可丢失的实时通知，PostgreSQL 始终是 Run、Job、Attempt 和 Result 的
最终事实来源。客户端连接 `GET /api/v1/runs/{run_id}/events` 时，服务端先执行带 tenant
条件的 Run 查询并发送 `snapshot`，再订阅该 tenant/run 的 Redis 频道。断线重连不尝试从
Pub/Sub 回放，而是重新读取快照。

## 为什么这样设计

Redis Pub/Sub 是 at-most-once：订阅者不在线时消息不会保留。把它当状态总线会造成客户端
永久漏进度，也会让 Redis 故障改变评测正确性。因此采用两层模型：

```text
PostgreSQL transaction commits durable state
                 |
                 v
best-effort Redis PUBLISH
                 |
                 v
SSE live notification
```

发布失败只记录事件类型、tenant/run ID 和异常类型，不记录 Redis URL、密码或业务 payload。
Worker、Reaper 和取消 API 都在数据库提交完成后发布。

## 事件结构

每条 `ProgressEvent` 都有：

- `event_id`：随机 UUID，仅用于本次实时通知标识；
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
不依赖 readiness 或 Redis 发布成功。这是“服务完整可用”和“领域状态仍能正确推进”两个不同
合同。

## 重连与重复

当前不承诺事件回放，也不使用 `Last-Event-ID` 恢复 Pub/Sub 历史。客户端应把每次连接的
首条 snapshot 当作权威基线，后续事件只作为刷新提示。Worker/Reaper 可能发布重复通知，
客户端不能用事件数量推导最终计数。

如果未来需要完整事件历史，应在 PostgreSQL outbox 或 Redis Streams 上另建有持久化和消费
确认的合同，不能假装 Pub/Sub 已具备这些语义。

## 已验证与未验证

单元/API 测试覆盖：

- 模型序列化和受限事件类型；
- tenant/run 精确频道；
- malformed/cross-tenant 丢弃；
- snapshot 先于实时事件；
- Redis 失败转 PostgreSQL polling；
- 关闭流释放 PubSub；
- Redis publish 异常不让已完成 Worker 路径失败；
- SSE 鉴权 Principal 传递和响应 headers。

真实 Redis publish/subscribe 合同已写入 integration 测试。本机没有启用真实 Redis，
因此结果是 skipped，不算通过。
