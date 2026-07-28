# Phase 6 逐步执行日志

日期：2026-07-29

起始提交：`a130779`

实现提交：`1293836`

## 1. 开始前判断

原阶段要求实时进度和 SSE，但项目的最终状态必须留在 PostgreSQL。开始前先判断：

- Redis Pub/Sub 适合低延迟通知，不适合回放或最终状态；
- 每个 SSE 客户端需要独立 PubSub 生命周期；
- 必须先完成 tenant-scoped PostgreSQL 查询再开始响应，否则 404 可能在 headers 已发出后
  才出现；
- 发布必须在数据库事务提交后，且失败不能倒灌到 Job；
- 重连只能靠新 snapshot，不能声称 `Last-Event-ID` 可恢复丢失消息。

随后核对 Redis 官方 async 文档：异步命令需要 await，PubSub 可用 `listen()`/`get_message`
并需要 `aclose()`；官方同时明确 Pub/Sub 是 at-most-once。FastAPI 官方文档确认
`StreamingResponse` 会逐块发送生成器内容。

## 2. RED：先写合同测试

新增五组测试：

1. ProgressEvent 与频道命名；
2. Redis publisher 成功/故障；
3. subscriber 丢弃 malformed 和跨 tenant 消息并清理资源；
4. snapshot-first、heartbeat 和 PostgreSQL fallback；
5. 认证后的 SSE API。

另新增真实 Redis integration 合同，以及 Worker 最新 heartbeat version 回归测试。

第一次命令：

```text
pytest tests/unit/events tests/api/test_events.py tests/unit/workers/test_worker.py
```

结果：4 个 collection errors，全部为 `ModuleNotFoundError: app.events`。这是预期 RED，
证明测试不是对已有行为的重复断言。

## 3. 实现事件模型和 best-effort publisher

修改：

- `app/events/models.py`：EventType、ProgressEvent、tenant/run channel；
- `app/events/publisher.py`：序列化并 PUBLISH；
- `app/events/subscriber.py`：独立 PubSub、解析、二次隔离和 finally 清理。

原因：

- schema 限定事件类型和字段；
- 精确频道降低误投范围，payload 复核形成第二道边界；
- publisher 捕获异常，保证 Redis 不成为 durable path 的依赖；
- finally 中 unsubscribe/aclose，避免客户端断开造成连接泄漏。

## 4. 实现 snapshot-first SSE 和降级

`RunEventStream.open()` 首先调用现有 RunService。只有授权查询成功，route 才创建
StreamingResponse。生成器首帧是 snapshot，之后订阅 Redis。

Redis listener 抛错时进入 PostgreSQL polling。快照变化发送新 snapshot，不变发送
heartbeat。没有增加数据库事件表，因为这个阶段明确选择可丢失实时通知；持久事件历史若需要
应单独设计 outbox。

## 5. 第一次 GREEN 问题

第一次实现后结果：

```text
10 passed, 1 failed
```

失败原因：测试辅助函数每次构造事件都生成不同 UUID，比较的是不同 `event_id`。固定测试
event ID 后通过。这不是删断言或放宽实现，而是让测试只改变它想验证的 tenant 维度。

## 6. 发现并修复 heartbeat fencing 缺陷

新增测试要求 LeaseRunner 返回 version 5 时成功提交也必须使用 5。现有 Worker 却传
`claim.version`（例如 2）。

影响：Target 执行中发生任何成功 heartbeat 后，数据库 version 已更新；仍传初始 version 会
被结果 committer 当作 stale lease 拒绝。

修正：成功路径改传 LeaseRunner 返回的 `lease_version`。失败路径此前已经传最新 version。
回归测试保持独立，防止以后再次把初始 claim 当作当前 generation。

## 7. 接入 Worker、Reaper 和取消

- ClaimReceipt 增加 `run_started`，只在数据库成功把 Run 从 queued 改为 running 时发布
  `run_started`；
- Worker 在 claim 后发布 running、成功后发布 succeeded；
- FailureReceipt/ResultReceipt 带聚合后的 RunStatus，用于 terminal `run_completed`；
- Reaper receipt 带 tenant/run/status，发布 retried/failed 和 terminal 通知；
- cancel API 在取消事务返回后发布当前状态；
- API、Worker、Reaper 各自创建/复用适合进程生命周期的 Redis client，并在退出关闭。

额外保护：Worker 对 publisher 再包一层异常隔离。因此即便替换成不遵守 best-effort 合同的
第三方 publisher，也不会把 Redis 异常变成 Job 失败。

## 8. 静态检查发现的问题

- Ruff：main import 顺序、模拟 redis-py 的 `timeout` 参数、空 except 风格；
- mypy：成功/失败分支复用 `receipt`，被推断为冲突类型；
- redis-py 的 `PubSub.aclose` stub 是 untyped。

处理：

- 重排 import；
- 对测试替身的兼容参数做单行、单规则 noqa；
- 用 `contextlib.suppress`；
- 变量拆成 `failure_receipt` / `result_receipt`；
- 只在实际 untyped 调用行做 `type: ignore[no-untyped-call]`，没有全局关闭 strict mypy。

## 9. 最终验证结果

| 检查 | 结果 |
|---|---|
| `uv lock --check` | 通过；仍为 48 packages |
| Ruff format/check | 通过 |
| mypy app | 71 source files，无问题 |
| 非集成 pytest | 191 passed，5 deselected |
| 真实 Redis Pub/Sub | 1 skipped；未设置真实服务开关 |
| Alembic | Phase 6 无 schema 变更，head 保持 `20260729_0005` |

## 10. 达成效果与剩余边界

达成：

- 认证、tenant-scoped、snapshot-first SSE；
- Worker/Reaper/cancel 的提交后通知；
- Redis 故障不改变 PostgreSQL 最终状态；
- SSE 实时故障自动退化为数据库轮询；
- 连接关闭释放订阅资源；
- 修复执行期 heartbeat 后成功结果误用旧 version 的缺陷。

仍不声称：

- Pub/Sub 历史回放；
- 无重复事件；
- Redis 故障时仍有相同实时延迟；
- 本机真实 Redis 并发通过；
- 多 API 节点下的容量和反压已验证。
