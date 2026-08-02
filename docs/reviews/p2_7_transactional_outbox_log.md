# P2-7 事务型 Outbox 改进记录

## 1. 基本信息与结论

- 项目：AI EvalOps Platform（多租户异步 AI 评测与任务编排平台）。
- 阶段：P2-7，PostgreSQL transactional outbox 与 Redis 通知 relay。
- 起始提交：`e14a1af91043fb94e8913bcd80a83080ecf6339c`。
- 数据库 migration：`20260802_0013_transactional_outbox`，父版本
  `20260802_0012_async_trace_link`。
- 正式 500-case/32-arm Gate：`NOT_RUN`；本阶段没有启动、修改或伪造正式 Gate 结果。
- 结论：Run/Job 状态和“需要发送通知”现在在同一个 PostgreSQL 事务中提交；API
  进程中的 relay 用有界租约认领、在事务外发布 Redis、再用 owner fencing 确认。通知交付语义
  是 **at-least-once**，不是 exactly-once；Redis Pub/Sub 仍然不是历史事实库，SSE 仍以首次
  PostgreSQL snapshot 为权威基线。

本阶段提交链：

| 提交 | 目的 |
|---|---|
| `3490bbb` | RED：要求 Outbox ORM、migration、认领、退避和分发合同 |
| `db9dc01` | RED：禁止 Worker、Reaper、取消路由在状态提交后直接发布 |
| `f27bac6` | RED：要求成功、失败、重试、取消状态提交器在原事务写 Outbox |
| `1382da4` | RED：要求有界 relay 循环与安全配置 |
| `51739c1` | RED：要求 API lifespan 启停 relay |
| `9c0820a` | GREEN：实现 migration、Outbox、状态写入、relay 与移除直发 |
| `88cb18f` | 真实 PostgreSQL/Redis、并发认领、重试、重放集成合同 |
| `45d3354` | RED：禁止 Reaper 在取得 Run 更新锁前插入 Outbox |
| `2174324` | 修复 CI 暴露的双 Reaper 外键锁升级死锁 |
| `4eba918` | RED：要求 `progress.publish` span 迁移到 relay |
| `63644f8` | GREEN：API relay 对真实 Redis publish 建 span |
| `5092f49` | 文档：记录完整 P2-7 设计、问题、证据和残余风险 |

## 2. 为什么 P2-7 合适，为什么此时做

P2-6 结束后，状态正确性和实时通知之间仍有一个明确故障窗口：

```text
Worker / Reaper / cancel API
    1. COMMIT PostgreSQL state
    2. PUBLISH Redis
```

如果进程在 1 成功后、2 执行前退出，数据库状态已经推进，但通知永久丢失。原有
snapshot-first SSE 保证客户端重连后能恢复最终状态，所以这不是“领域事实丢失”；但在线客户端
可能长时间不知道状态已变化，且平台没有可恢复的通知意图。这个问题不能靠在内存中多重试几次
解决，因为进程退出会同时丢失重试状态。

这一阶段适合实现 Outbox，原因是：

1. 状态变更已经集中在 Claim、Result、Failure、Reaper、Cancellation 的 PostgreSQL 事务；
2. Redis 明确只承担低延迟通知，不需要把它升级为第二事实源；
3. API 已经是 Redis/SSE 边界，可拥有 relay，不必为本阶段增加第七个 Compose 服务；
4. P2-3 已处理异步 trace link，P2-4 已处理进程隔离，P2-5/P2-6 已收紧 Gate 证据，
   因此当前剩余的高价值正确性缺口正是状态与通知意图的原子性。

本阶段没有把 Outbox 误述为“Redis 消息不丢”。Outbox 保证的是：只要业务状态事务提交，对应
通知意图也持久化；只要 API relay 和 Redis 后续恢复，意图可以再次尝试。它不保证离线 Pub/Sub
订阅者收到历史消息。

## 3. 修改前审计结果

修改前有三类直发路径：

- `EvaluationWorker` 在 claim、成功、失败和 Run terminal 后调用 `EventPublisher`；
- Reaper runtime 在 `SQLAlchemyJobReaper.reap()` 事务返回后发布 recovery/terminal 事件；
- `POST /runs/{run_id}/cancel` 在 CancellationService 返回后 best-effort 发布。

共同问题：

- 发布发生在数据库事务外；
- `suppress(Exception)` 或内部 catch 会保护业务状态不回滚，但也会让失败通知没有持久重试入口；
- Worker/Reaper 每个进程都需要 Redis client，扩大了不必要依赖；
- 进程崩溃点位于 DB commit 与 publish 之间时，没有任何行能说明“还欠一条通知”；
- 发布成功后若进程在确认前退出，未来引入重试时会产生重复，因此不能承诺 exactly-once；
- 旧 `event_id` 是发布时临时创建，失败重试没有稳定身份。

## 4. 方案比较与采用判断

### 4.1 方案 A：保持提交后直发，增加内存重试

优点是改动小。缺点是进程退出仍丢失待重试数据，多个 Worker 各自维护重试也难以观察和接管。
拒绝。

### 4.2 方案 B：把 Redis Streams 变成持久队列/事实源

Streams 可以保留消息并提供 consumer group，但会引入 PostgreSQL 状态与 Redis 消息两个提交点；
如果没有额外分布式事务，仍然存在“只提交一边”的问题。它也改变了当前 snapshot-first/PubSub
架构，超出本阶段。拒绝。

### 4.3 方案 C：新增独立 Outbox 服务

独立服务有清晰的进程隔离，但本阶段会增加镜像角色、Compose 拓扑、health、metrics、部署和
容量问题。API 已经必须连接 PostgreSQL 与 Redis，且可通过 `SKIP LOCKED` 支持未来多 API
副本并发 relay。因此当前不增加服务。保留为规模化后的部署选项。

### 4.4 方案 D：PostgreSQL Outbox + API relay

采用。业务事务只新增 Outbox 行；relay 的数据库租约事务保持短小，网络发布在事务外；成功后
用 dispatcher owner 和有效 lease 做 fenced acknowledgement。这个方案把不可恢复窗口改为
可恢复状态：

```text
state transaction:
    durable state + outbox intent -> COMMIT

relay:
    claim/lease -> COMMIT
    Redis PUBLISH (no DB transaction held)
    fenced mark_published -> COMMIT
```

## 5. 冻结后的数据合同

### 5.1 `progress_event_outbox`

核心字段：

| 字段 | 语义 |
|---|---|
| `id` | 稳定 `event_id`；重试和重放保持不变 |
| `tenant_id`, `run_id` | tenant/run 路由及复合 FK 隔离 |
| `event_type`, `payload_json`, `occurred_at` | 原始通知内容与发生时间 |
| `available_at` | 下一次允许认领的时间 |
| `attempt_count` | 每次成功取得租约时加一 |
| `lease_owner`, `lease_expires_at` | relay 短租约和 owner fencing |
| `published_at` | Redis publish 成功且 fenced ack 成功的持久标记 |
| `last_error_code` | 仅保存有界异常类型/安全错误码，不保存异常正文或 payload |
| `created_at` | 数据库创建时间，用于稳定候选排序和诊断 |

数据库约束：

- `(run_id, tenant_id)` 复合 FK 指向 `evaluation_runs(id, tenant_id)`，`ON DELETE CASCADE`；
- `attempt_count >= 0`；
- lease owner 与 expiry 必须同时为空或同时非空；
- 已发布行不能仍带租约；
- event type 只允许 `run_started`、`job_progress`、`job_failed`、`job_retried`、
  `run_completed`；
- pending partial index 覆盖 `available_at, created_at, id`；
- tenant/run/created index支持范围诊断。

`snapshot` 和 `heartbeat` 不写 Outbox：它们是每次 SSE 连接即时生成的传输事件，不是业务状态
转换通知。

### 5.2 同事务写入点

- Claim：第一个成功把 Run 从 queued 改为 running 的 claimant 写 `run_started`；每个 claim 写
  running `job_progress`。
- Result：成功结果、Job terminal、Run aggregate 与 succeeded `job_progress` 同事务；只有 Run
  status 本次真正进入 terminal 才写一次 `run_completed`。
- Failure：retry_wait 写 `job_retried`，永久/耗尽/取消结束写 `job_failed`；Run 本次进入 terminal
  才写 `run_completed`。
- Reaper：Job lease recovery 与 recovery event 同事务；Run terminal event 同样只在真实 status
  transition 时写。
- Cancellation：第一次有效取消写 cancelling `job_progress`；若同一事务聚合为 terminal，改写
  `run_completed`；已经 terminal 的幂等调用直接返回，不新增事件。

`RunAggregation.status_changed` 是本阶段新增的显式信号。只检查最终 status 是否 terminal 不够，
否则同一个 Run 的每个 Job 完成都可能重复产生 `run_completed`。

## 6. Relay、租约、退避与关闭合同

### 6.1 认领

`SQLAlchemyOutboxStore.claim_batch()`：

1. 只选择 `published_at IS NULL`；
2. 只选择 `available_at <= now`；
3. 只选择无租约或租约已过期的行；
4. 按 `available_at, created_at, id` 排序；
5. 批量上限 1–1000；
6. 使用 `FOR UPDATE SKIP LOCKED`，让多个 API relay 不重复持有同一行；
7. 在短事务内写 owner、expiry、`attempt_count += 1` 后提交。

### 6.2 发布与确认

- Redis publish 在认领事务外执行，不让网络延迟占用 PostgreSQL 行锁；
- publish 有独立 timeout，并且配置验证要求 timeout 严格短于 lease；
- publish 返回 false、抛异常或超时会释放当前 owner 的租约，按有界指数退避更新
  `available_at`；
- 错误只保存 `publish_returned_false` 或异常类型，截断到 100 字符；
- 成功后 `mark_published()` 要求相同 owner、未发布、lease 尚未过期；
- ack fencing 失败返回 `lease_lost`，不能把别的 relay 已接管的行标记完成。

退避公式为：

```text
min(base_seconds * 2 ** (attempt_count - 1), max_seconds)
```

指数被限制在 62，避免无意义的巨大中间值；base/max 和配置上下界均在启动前校验。

### 6.3 API 生命周期

API 启动时：

- 复用已有 PostgreSQL session factory 与 Redis client；
- 为本进程生成不含凭据的唯一 dispatcher ID；
- 创建 relay task；
- Worker/Reaper 不再为了通知创建 Redis client。

API 停止时：

1. 设置 stop event；
2. 等待 relay 当前 iteration 正常退出；
3. 再关闭 Redis；
4. 再 dispose database engine；
5. 最后 shutdown telemetry。

这避免了“先关连接、后台任务再使用已关闭资源”。循环每次失败只记录异常类型，并等待下一轮，
不会因一次 PostgreSQL/Redis 故障永久退出。

默认配置：

```text
EVALOPS_OUTBOX_POLL_SECONDS=0.5
EVALOPS_OUTBOX_BATCH_SIZE=50
EVALOPS_OUTBOX_LEASE_SECONDS=30
EVALOPS_OUTBOX_PUBLISH_TIMEOUT_SECONDS=5
EVALOPS_OUTBOX_RETRY_BASE_SECONDS=1
EVALOPS_OUTBOX_RETRY_MAX_SECONDS=60
```

这些是有界安全默认值，不是生产容量结论。

### 6.4 Trace 所有权

Worker/Reaper 不再拥有 `progress.publish` span，因为它们不再执行 Redis publish。API relay 对
真实发布建立该 span，并写低基数之外的 trace attributes：tenant ID、run ID、event type。
这些 ID 只进入 trace，不进入 Prometheus label。publisher 的失败 counter 也随真实 publisher
迁移到 API 进程 registry。

## 7. 明确的交付语义

本设计是 at-least-once：

```text
Redis accepted event
        |
        | process crashes before mark_published
        v
lease expires -> another relay republishes same event_id
```

因此客户端可能看到同一个 SSE `id` 两次。稳定 event ID 允许客户端做去重，但服务端当前不承诺
为每个客户端保存消费 offset，也不承诺 Last-Event-ID 回放。连接断开期间的通知仍可能错过；重连
后第一帧 PostgreSQL snapshot 才是恢复机制。

不能使用以下表述：

- “Redis 现在 exactly-once”；
- “Pub/Sub 可以回放离线历史”；
- “每个业务转换只会被客户端看到一次”；
- “Outbox 替代 PostgreSQL 成为事实源”；
- “CI 成功证明生产容量或正式 Gate 已通过”。

## 8. TDD 过程与证据

### 8.1 RED：基础 Outbox 合同

`3490bbb` 先加入 ORM/migration/claim/dispatcher 测试。初次结果为 4 个 collection error：
`app.events.outbox` 和 `ProgressEventOutbox` 均不存在；migration 检查另外证明 head 没有 0013。

### 8.2 RED：禁止提交后直发

`db9dc01` 给 Worker、Reaper 和 cancel route 注入 forbidden publisher，并禁止执行进程产生
`progress.publish` span。旧实现得到 `4 failed, 12 passed`：Worker 直发两次、Reaper 直发两条、
cancel route 直发一次，且 Worker span 仍存在。

### 8.3 RED：全部状态提交器必须写 Outbox

`f27bac6` 新增 5 个状态事务测试：

- success：`job_progress + run_completed`；
- retry：`job_retried`；
- exhausted failure：`job_failed + run_completed`；
- terminal cancellation：`run_completed`；
- nonterminal cancellation：cancelling `job_progress`。

首次运行 `5 failed`，共同原因是 session 中 Outbox 行为空，而不是 fixture 或无关异常。

### 8.4 RED：有界循环、配置和 lifespan

- `1382da4` 首先因 `run_outbox_dispatch_loop` 不存在而 collection error；配置单独执行得到
  `3 failed, 12 passed`，分别证明字段缺失和两个跨字段约束未实现；
- `51739c1` 用一个记录型 relay task 要求 lifespan 启动并在 shutdown 等待；旧应用在 1 秒后
  `TimeoutError`，证明没有启动 relay。

### 8.5 GREEN：核心实现

核心 GREEN 后：

- 状态/Claim/Reaper 聚焦：21 passed；
- Worker/Reaper/API 移除直发聚焦：28 passed；
- relay/config/lifespan：24 passed；
- events/jobs/workers/ORM/migration/API 聚焦：105 passed；
- Ruff lint 通过；strict mypy 对 app 91 个源文件通过。

### 8.6 RED/GREEN：发布 span 迁移

`4eba918` 给 OutboxDispatcher 传 telemetry，旧构造器得到：

```text
TypeError: OutboxDispatcher.__init__() got an unexpected keyword argument 'telemetry'
1 failed, 7 passed
```

`63644f8` 让 relay 对真正 publish 建 `progress.publish` span；events/app/Worker/Reaper 聚焦
`16 passed`，Ruff 与 strict mypy 通过。

## 9. 真实服务测试覆盖

`tests/integration/test_transactional_outbox.py` 在真实 PostgreSQL/Redis 下验证：

1. Outbox insert 后同事务抛异常，最终查询不到该行；
2. 用其他 tenant 给 Run 写 Outbox，被复合 FK 精确拒绝；
3. 两个 dispatcher 并发认领同一行，合计只有一个 claim/publish；
4. Redis subscriber 收到原始 event ID，数据库随后写 `published_at` 并清租约；
5. 首次 publisher 返回 false，行保持 pending、写安全错误码、按 2 秒退避；
6. 时钟推进后第二次发布成功，event ID 不变、attempt 从 1 变 2；
7. 模拟 Redis 已接受但 ack 丢失，第一次结果为 lease_lost；
8. lease 过期后另一 dispatcher 重放相同 event ID 并成功确认，明确证明 at-least-once。

本机无 Docker/PostgreSQL/Redis，所以该测试为 `1 skipped`，没有写成通过。GitHub Actions
#27、#28 与最终 #29 中该独立步骤均实际通过。

## 10. 实际遇到的问题、判断和处理

### 10.1 Ruff import/format 与 mypy 指数类型

- 两处链式调用和条件表达式不符合 formatter；只做机械格式化；
- 测试中的 SQLAlchemy import 分组错误；按第三方/项目内顺序调整；
- mypy 把 `2 ** exponent` 的返回路径视为 `Any`；改为 `2.0 ** exponent`，保持数值语义并让
  返回值可证明为 float；
- 没有添加 `noqa`、扩大 `type: ignore` 或关闭 strict。

### 10.2 把 YAML 误传给 Python linter

一次检查命令把 `.github/workflows/ci.yml` 作为 Ruff 输入，产生 473 条 Python syntax error。
这是工具调用范围错误，不是 YAML 或项目失败。处理方式是：

- 只对 `.py` 运行 Ruff；
- 用 diff 和缩进检查核对 workflow；
- 最终由 GitHub Actions 实际解析并运行新增 step。

不能把这 473 条伪错误写成产品 RED。

### 10.3 本地非集成测试外层超时

锁、format、lint、mypy 与 pytest 五项并行时，pytest 在 124 秒达到工具上限，没有断言失败输出。
该结果记为 UNKNOWN/TIMEOUT，不记成功也不记失败。随后单独给 5 分钟，得到：

```text
488 passed, 9 deselected in 284.35s
```

9 个 deselected 是需要真实服务的 integration marker，不是本地通过。

### 10.4 GitHub Actions #27：真实双 Reaper 死锁

Run #27 的新增 Outbox 集成步骤成功，Compose smoke 成功，但原有 job claiming/lease recovery
integration 失败。PostgreSQL 报：

```text
deadlock detected
CONTEXT: while locking tuple in relation "evaluation_runs"
SELECT ... FROM evaluation_runs ... FOR UPDATE
```

根因不是 `SKIP LOCKED` 失效，而是新外键造成锁升级顺序：

```text
Reaper A: lock Job A -> insert Outbox(FK Run) -> KEY SHARE Run -> wants UPDATE Run
Reaper B: lock Job B -> insert Outbox(FK Run) -> KEY SHARE Run -> wants UPDATE Run
```

两边持有可共存的 key-share，又都要升级为互斥 update，形成环。只给整个 Reaper 添加数据库
deadlock retry会降低出现概率，但会保留错误锁顺序，因此未采用。

修复过程：

1. `45d3354` 在 aggregate stub 中断言聚合前没有 Outbox 行；旧代码稳定 RED；
2. Job recovery 事件先保存在内存中的 `ReapedJob`；
3. 先 flush Job/Attempt，按字符串排序的 Run ID 顺序聚合并取得 Run `FOR UPDATE`；
4. 在已经持有 Run 更新锁后，统一插入 Job 和 Run completion Outbox；
5. 聚焦 9 passed；GitHub Actions #28 的双 Reaper 并发场景和全部后续步骤成功。

这个问题说明：transactional outbox 不只是“加一张表”。外键插入本身参与 PostgreSQL 锁图，
必须把父行锁顺序纳入设计。

## 11. 验证结果

| 检查 | 结果 | 状态 |
|---|---|---|
| 基础 RED | 缺模块/ORM，4 collection errors；migration 2 failed | `VERIFIED_RED` |
| 禁止直发 RED | 4 failed, 12 passed | `VERIFIED_RED` |
| 状态写入 RED | 5 failed | `VERIFIED_RED` |
| relay/config RED | collection error；配置 3 failed | `VERIFIED_RED` |
| lifespan RED | 等待 relay 启动超时 | `VERIFIED_RED` |
| Reaper 锁顺序 RED | 聚合前已存在 Outbox，1 failed | `VERIFIED_RED` |
| 状态/执行/relay 聚焦 | 105 passed | `VERIFIED` |
| 锁顺序修复聚焦 | 9 passed | `VERIFIED` |
| relay span 聚焦 | 16 passed | `VERIFIED` |
| 最终本地非 integration 全量 | 488 passed, 9 deselected in 269.13s | `VERIFIED` |
| `uv lock --check` | 70 packages | `VERIFIED` |
| Ruff format | 259 files | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | app/scripts/integration/concurrency 119 source files | `VERIFIED` |
| 本地真实 Outbox integration | 1 skipped；无本地服务 | `NOT_RUN_LOCAL` |
| GitHub Actions #27 | Outbox/Compose 成功；双 Reaper deadlock，整体 failure | `VALUABLE_FAILURE` |
| GitHub Actions #28 | 两个 job success；并发/Outbox/migration/image/Compose success | `VERIFIED_REMOTE` |
| GitHub Actions #29 | head `5092f49` 两个 job success；最终 tracing/文档也在验证范围 | `VERIFIED_REMOTE_FINAL` |
| 正式 500-case/32-arm/soak | 未授权、未运行 | `NOT_RUN` |

Run #27：
[GitHub Actions #27](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30738559010)。

Run #28（绑定 head `21743246d3c0a57b3686c3c47aa75a839da9b672`）：
[GitHub Actions #28](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30738964791)。

Run #29（绑定 head `5092f49eccc504b3d13a960e872305eb08c010b9`）：
[GitHub Actions #29](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30739846288)。两个 job
均 success；步骤级确认非集成回归、全部 PostgreSQL/Redis integration、P2 migration
downgrade/re-upgrade、application image 与完整 Compose smoke 均实际执行。

## 12. Migration、部署与回滚

### 12.1 Upgrade

推荐顺序：

1. 先应用 migration 0013；
2. 再部署新 API/Worker/Reaper；
3. 确认 relay 能认领、发布和确认；
4. 观察 pending 行、错误码、Redis failure counter 和 readiness。

旧应用看到多出的表不会受影响，所以“先 migration 后应用”兼容。新应用若在 0013 前启动，首次
状态事务或 relay 查询会遇到表不存在，因此不能反向部署。

### 12.2 Downgrade

1. 先停止所有新版本 Worker/Reaper/API，避免它们继续依赖 Outbox；
2. 部署回旧的提交后直发版本；
3. 明确接受 pending/delivered notification intent 将丢失；
4. 再 downgrade 到 0012，删除索引与 Outbox 表。

Downgrade 不回滚 EvaluationRun/Job/Result 业务状态，但会删除所有通知意图与交付诊断。不能在
仍有新版本进程运行时先 drop 表。

## 13. 残余风险与后续工作

1. **已发布行尚无 retention/GC**：表会增长；需要独立、受界、可审计的 delivered-row cleanup，
   不能顺手删除 pending 行。
2. **没有 backlog/oldest-age 指标**：当前有 batch 日志和 Redis failure counter，但生产运维还应
   观测 pending count、oldest available age、retry/lease-lost。
3. **API down 会增加通知延迟**：业务状态仍能由 Worker/Reaper推进，pending 行会保留；但没有
   API relay 时不会发布。
4. **无 dead-letter/max attempts**：退避有上限但会无限重试；这是避免静默丢通知的选择，未来需
   配套运维策略。
5. **消费者去重由客户端负责**：稳定 event ID 支持去重，但 SSE 服务不保存客户端 offset。
6. **Pub/Sub 仍无离线历史**：断线恢复依靠 snapshot，不是回放。
7. **数据库查询无本阶段新增 statement timeout**：极端数据库卡顿可能拖慢 relay shutdown；应与
   全局数据库 timeout 策略一起设计。
8. **没有多区域、网络分区或长时间 soak**：CI 只证明受控 PostgreSQL/Redis/Compose 合同。
9. **正式 Gate 未运行**：没有吞吐、p95/p99、资源曲线、容量 knee 或 Worker adoption 结论。

## 14. 达成效果

修改前：

```text
state committed -> process crash -> no durable notification intent
```

修改后：

```text
state + intent committed
        -> relay/Redis unavailable: pending row remains and retries
        -> publish succeeds: fenced ack records completion
        -> publish succeeds but ack lost: same event_id may replay
```

因此本阶段真正达成的是“数据库事实与通知意图原子提交 + 可接管重试 + 明确重复语义”，而不是
“Redis 永不丢消息”或“exactly-once”。

## 15. 学习与面试表述

推荐表述：

> 我审计到 Worker、Reaper 和取消 API 都在数据库提交后 best-effort publish，进程在两步之间
> 崩溃会永久丢失通知意图。我用 RED 先固定所有状态提交器必须在原事务写 PostgreSQL Outbox，
> 再让 API relay 用 `FOR UPDATE SKIP LOCKED` 认领、事务外 Redis publish、owner/lease fencing
> 确认和有界指数退避。真实 CI 首轮暴露了外键 key-share 到 Run `FOR UPDATE` 的锁升级死锁，
> 我没有用重试掩盖，而是统一为先按固定顺序锁 Run、后插 Outbox；第二轮真实双 Reaper 并发和
> Outbox 重放测试通过。交付明确是 at-least-once，同一 event ID 可重复，SSE 仍 snapshot-first。

值得记住的工程点：

- Outbox 解决的是双写原子性，不自动解决消费历史、去重、GC、告警和容量；
- 网络 I/O 不应放在持有数据库认领锁的事务中；
- claim、publish、ack 三阶段必须有 lease owner fencing；
- 外键插入会取得父行锁，新增表也可能改变原有并发锁图；
- “CI 新测试通过但旧并发测试失败”说明必须跑完整回归，而不是只跑新功能；
- skipped integration 只能写 `NOT_RUN_LOCAL`，最终结论必须绑定真实服务 CI 的 head 和 run。
