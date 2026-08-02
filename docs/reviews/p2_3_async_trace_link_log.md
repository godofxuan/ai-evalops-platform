# P2-3 API → Worker/Reaper 异步 Span Link：证据化实施日志

## 1. 阶段身份与边界

- 阶段：P2-3，API → Worker trace context 或 span link。
- 开始日期：2026-08-02（Asia/Shanghai）。
- 分支：`codex/gate1-evidence-hardening`。
- 起始 SHA：`68fffc239e27da7b6c612944e4963a73513edcdb`。
- 起始工作区：clean，本地与远端分支同步。
- P2-2 最终复验：
  [GitHub Actions Run #18](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30730797666)
  两个 job 均 `completed / success`。
- 正式 500-case/32-arm Gate 1、soak、OS 强杀和破坏性故障注入继续 `NOT_RUN`。
- 本阶段不引入通用消息总线、不做 transactional outbox、不向 Prometheus label 添加 trace ID，
  也不创建 PR 或合并分支。

## 2. `zoom-out` 调用链地图

| 领域步骤 | 当前模块 | 当前 trace 行为 | 缺口 |
|---|---|---|---|
| 入站 HTTP | `app/api/middleware.py` | 提取合法 W3C `traceparent`，创建 `api.request` child span | context 只在 API 进程内存中 |
| Run API | `app/api/routes_runs.py` | `run.create` 嵌套在 `api.request` 下 | span context 未交给持久化层 |
| Run/Job transaction | `app/runs/service.py`、`app/runs/repository.py` | 创建 Run 与全部 Job，只有 process-local DB span | Run/Job 行没有异步来源 context |
| Job claim | `app/jobs/claiming.py` | Worker 在 claim 前创建独立 `job.claim` span | claim 前不知道将得到哪个 Job，不能提前建立精确 link |
| Attempt 执行 | `app/workers/worker.py` | 每次 `job.process` 是新的 root trace，子 span 覆盖 target/evaluator/result/event | 只有 tenant/run/job/attempt ID，没有 OTel link |
| Lease recovery | `app/jobs/reaper.py`、`app/workers/runtime.py` | batch recovery 与随后 publish 都创建新 trace | 单个 recovered Job 没有来源 link |
| Attempt 表 | `job_attempts.trace_id` | 保存 Target 返回 payload 中的上游 trace ID | 不是平台 OpenTelemetry span context，不能复用 |

数据库查询已经在 claim/reaper 时 join `evaluation_runs`，所以把一个来源 carrier 放在 Run 上即可
同时服务所有 Job、retry attempt 和 Reaper；复制到每个 Job 会增加写放大与重复事实，没有收益。

## 3. 原始行为、证据与风险判断

现有代码和文档明确写明 Worker/Reaper 创建新 trace，只通过 tenant/run/job/attempt/worker 领域
ID 做日志关联。单元测试也只要求 `job.process` 下存在 target/evaluator/result 子 span，没有
要求任何 `Span.links`。因此问题有直接源码与测试证据，不是推测。

这不是业务一致性、tenant 越权或 Job 丢失缺陷，也不阻断普通功能；它是 P2 可观测性风险：

- 追踪后端不能从一个 Run 创建请求直接跳转到各异步 attempt；
- retry 会产生多个独立 trace，却没有机器可读来源边；
- Reaper 恢复只能靠人工检索领域 ID；
- queue/attempt 故障分析需要跨日志与 trace 手工拼接。

该问题不等于“必须让 API 与所有 Worker span 使用同一个 trace”。长时间异步边界需要先比较
因果表达方式，不能看到 `traceparent` 就机械继续 parent。

## 4. 方案比较与选择

### 4.1 方案 A：Worker 继续 API parent context

优点是追踪 UI 中形成同一 trace。缺点是把已经返回的短 HTTP 请求与排队数分钟/数小时、并且
可能多次 retry/reap 的执行表达成同步 parent-child 树；一个 Run 的大量 Job 会形成超大 trace，
采样和保留策略也被最初请求绑定。技术上 parent span 已结束后仍可创建 child，但语义和运维
成本都不适合本平台的持久化异步任务。因此不选。

### 4.2 方案 B：每次 attempt 新 trace，使用 Span Link

每个 `job.process` 保持独立 root trace，并 link 到首次成功创建该 Run 的平台 `run.create`
span。retry attempt 通过不同 `attempt.id`、`attempt.number` 和不同 root trace 区分，但共享同一
来源 link。Reaper batch 可能包含多个 Run，不强行给 batch span加一个错误 parent；每个
`reaper.job.recovered` span 单独 link。该语义符合异步 fan-out 和 retry，选择此方案。

### 4.3 方案 C：继续只用领域 ID

零 migration，但正是当前缺口，只能人工关联，不能满足 P2-3。领域 ID 仍保留为日志与 span
attribute；Span Link 是补充，不替代 durable identity。

## 5. 冻结的最小合同

1. `evaluation_runs.origin_traceparent VARCHAR(55) NULL` 保存首次创建 Run 时当前平台
   `run.create` span 的 W3C version 00 carrier。
2. 只保存 `traceparent`；不保存或传播 baggage、HTTP header 全集、OTLP header、token、
   `tracestate` 或请求内容。
3. carrier 由 OpenTelemetry propagator 从当前平台 span 注入，不原样保存客户端 header；合法
   入站 trace 的 trace ID 会延续，但 span ID 是平台 `run.create` span。
4. trace context 只用于 observability，绝不能参与 tenant、授权、claim、retry、排序或幂等判断。
5. idempotent replay 不覆盖首次创建的 carrier；并发唯一键 loser 读取 winner，不重写来源。
6. 历史 Run 与 telemetry disabled/no-current-span 场景保存 `NULL`，Worker/Reaper 正常执行但
   没有 link。
7. malformed carrier 必须被忽略并降级为独立 trace，不能让业务 Job/Reaper 失败。
8. 每次 `job.process` 仍是 root span，具有一个有效来源 link，并包含 tenant/run/job/attempt ID、
   `attempt.number`、worker ID；内部 span 继续以它为 parent。
9. `job.claim` 保持独立，因为 span 开始时尚不知道 claim 结果；不能把 batch/空 claim 错绑到
   某个 Run。
10. Reaper 的 batch DB span保持独立；每个结果创建 `reaper.job.recovered` linked root span，
    event publish 在其内部。
11. exporter 或 link 解析不可用不能改变数据库事务与 Job 状态；trace ID 不进入 Prometheus
    label，避免高基数。

## 6. Migration、兼容性与回滚

新增 `20260802_0012_async_trace_link.py`，不修改历史 migration：

- upgrade 只给 `evaluation_runs` 添加 nullable `VARCHAR(55)`；
- 不 backfill 历史 Run，因为历史 API span 已结束且没有可验证 span ID，伪造 context 比 NULL
  更差；
- 不把 Target payload 的 `job_attempts.trace_id` 反向转换为平台 context；两者语义不同；
- downgrade 只删除新列，不删除 Run、Job、Attempt 或结果。

旧应用可忽略数据库中的额外 nullable 列；旧 Run 在新应用上无 link 但继续执行。已经使用新
代码创建的 Run 如果 downgrade，会失去来源 carrier，但业务状态不丢失。部署回滚应先暂停新
实例，用仍含 `0012` 的 release downgrade 到 `0011`，再部署代码 revert。

该阶段修改代码与 migration，因此任何绑定起始 SHA 的旧 Gate 1 prepared bundle 都必须由
现有 preflight 判为 source/hash mismatch；本阶段不修改正式 result/plot schema，也不会覆盖
历史 prepared evidence。

## 7. TDD tracer 计划

1. Telemetry 能捕获当前 version 00 traceparent，并用它创建“新 root trace + Link”；invalid、
   missing、disabled 均安全退化。
2. RunService 把当前 `run.create` carrier放入 `NewRun`，无 context 时为 NULL，idempotent replay
   不写新 carrier。
3. ORM 与 `0012` migration 只新增 nullable 55 字符列，upgrade/downgrade 离线 SQL 可审计。
4. Job claim 和 Reaper 从 joined Run 返回 carrier；真实 PostgreSQL concurrency 合同验证 100
   个 claim 与 expired recovery 都携带同一来源。
5. Worker `job.process` 保持无 parent、拥有一个来源 link；子 span 仍在 attempt trace 内，
   attempt number 明确记录。
6. Reaper 为每个 recovered Job 创建 linked root span；batch span 不错误绑定单个 Run。
7. 定向、并发、migration、非 integration 全量、Ruff、mypy、lock、GitHub PostgreSQL/Redis、
   image 和 Compose 全部回归；正式 Gate 保持 `NOT_RUN`。

## 8. 实施流水

### 8.1 Tracer 1 RED：Telemetry 缺少异步 carrier/Link

新增三组要求：有效当前 span 必须生成精确 version 00 `traceparent`；随后创建的
`job.process` 必须是不同 trace 的 root 且包含一个指向来源 span 的 Link；missing、malformed
和 disabled telemetry 必须安全返回 NULL/空 links。

第一次运行 `tests/unit/core/test_telemetry.py`：`3 failed, 1 passed`。三项失败均为
`AttributeError`：`Telemetry` 不存在 `capture_traceparent` 或 `links_from_traceparent`。现有嵌套
span 测试仍通过，说明 RED 精确命中新能力缺失，没有破坏或误判原有 process-local tracing。

### 8.2 Tracer 1 最小 GREEN

- `start_as_current_span()` 只增加 OpenTelemetry 原生 `links` 参数透传；
- `capture_traceparent()` 用固定版本 propagator 从当前有效 span 注入 carrier，无 span 返回
  NULL；
- `links_from_traceparent()` 对 missing/invalid 返回空 tuple，有效值返回一个 remote
  `SpanContext` Link；解析异常也失败软化，不影响业务；
- 没有加入 baggage/tracestate、全局 provider 或 Prometheus label。

运行结果：`4 passed`，Ruff 通过。首次把该测试文件加入定向 mypy 时，两个历史断言没有先将
Optional `trace_id`/attributes 收窄，得到 2 个测试类型错误；生产代码没有类型错误。补上非空
断言后再次运行：`4 passed`、Ruff 通过、mypy 2 source files 无问题。

### 8.3 Tracer 2 RED：RunService 没有异步来源字段

扩展现有 Run snapshot 测试：无 telemetry/current span 时要求 `origin_traceparent is None`；另用
真实 in-memory Telemetry 在 `run.create` span 内创建 Run，要求传给 repository 的 carrier
精确等于当前平台 span 注入值。

第一次运行：`2 failed, 12 passed`。两项都因 `NewRun` 不存在 `origin_traceparent` 而失败；其余
Run validation/idempotency/Registry 合同通过。这证明缺口位于 Run command 数据，而不是测试
artifact、hash 或现有幂等逻辑。

### 8.4 Tracer 2 最小 GREEN

`NewRun` 在所有必填可复现字段之后新增默认 NULL 的 `origin_traceparent`，保持现有测试 doubles
与非 HTTP 调用兼容。RunService 只在 telemetry 存在时捕获当前 carrier，并显式传给 NewRun；
idempotency 的现有查询仍发生在捕获和创建之前，所以 replay 不写新 context。

Telemetry 与 RunService 合并定向结果：`18 passed`；Ruff 通过；mypy 3 source files 无问题。

### 8.5 Tracer 3 upgrade RED：ORM 与 Alembic 没有 carrier

新增 ORM metadata 合同，要求 Run 字段 nullable、`VARCHAR(55)`、无 Python/server default；新增
离线 upgrade 合同，要求 head 产生 `ALTER TABLE evaluation_runs ADD COLUMN`，且不得生成
`UPDATE evaluation_runs` 伪造历史 context。

第一次运行：`2 failed`。ORM column collection 抛 `AttributeError: origin_traceparent`；离线 SQL
最终 revision 仍为 `0011` 且没有目标 ALTER。两项分别证明运行模型与部署 schema 都缺失。

### 8.6 Tracer 3 upgrade 最小 GREEN

- ORM Run 增加 nullable `String(55)`，不设默认；
- SQLAlchemy repository 在新 Run insert 时写入 command carrier；
- 新 migration `20260802_0012_async_trace_link.py` 只 add column，不 backfill；
- downgrade 暂留空，为独立回滚测试保留 RED。

upgrade/metadata 结果：`2 passed`；Alembic 唯一 head 为 `20260802_0012`。

### 8.7 Tracer 3 downgrade RED

要求 `0012:0011` 生成 `ALTER TABLE evaluation_runs DROP COLUMN origin_traceparent`，且不得出现
`DROP TABLE`。第一次运行 `1 failed`：SQL 只有 Alembic version 更新，没有删除列，证明空
downgrade 尚未满足可回滚合同。

### 8.8 Tracer 3 downgrade 最小 GREEN

`downgrade()` 只执行 `op.drop_column("evaluation_runs", "origin_traceparent")`。upgrade、
downgrade 与 ORM metadata 合并运行：`3 passed`；Ruff 通过。没有删除或更新任何业务行。

### 8.9 Tracer 4 RED 第一层：claim DTO 无法携带 carrier

现有 Worker pipeline 测试先创建已结束的 `run.create` span，再把 carrier 传给 ClaimedJob，并
要求 `job.process` 是 linked root、带 `attempt.number`。第一次运行在进入 Worker 前失败：
`ClaimedJob.__init__() got an unexpected keyword argument 'origin_traceparent'`。这证明 repository
即使保存字段，当前 claim command 也无法把它送入执行层。

给 ClaimedJob 只增加末尾默认 NULL 字段后，同一测试进入 Worker 并继续失败：
`job.process.links` 长度为 0。它同时确认当前 span 已经是无 parent 的新 root、trace ID 与来源
不同，因此后续修复只需增加 Link，不应改成 parent continuation。

### 8.10 Tracer 4 Worker 最小 GREEN

Worker 只在顶层 `job.process` 调用 Telemetry 的容错 carrier→links 转换，并新增整数
`attempt.number` attribute。所有内部 span 继续继承 `job.process`；没有给每个子 span 重复
Link，也没有改变 `job.claim`。完整 Worker 单元结果：`5 passed`；Ruff 通过；mypy 2 source
files 无问题。

### 8.11 Tracer 5 RED：真实 claimer 映射丢失 carrier

用真实 ORM Run/Job 和只模拟 begin/row result 的轻量 session 执行完整
`SQLAlchemyJobClaimer.claim()`。Run 带 carrier，但返回 DTO 的字段是 NULL，断言得到
`None != ORIGIN_TRACEPARENT`。查询本来 select 完整 Run，所以不需要改 SQL 或新增 round-trip；
缺口只在结果映射。

### 8.12 Tracer 5 claimer 最小 GREEN

现有 DTO 构造只增加 `origin_traceparent=run.origin_traceparent`；没有改 select、锁、排序或事务。
Claimer+Worker 合并结果：`10 passed`。Ruff 首次发现新测试的 `app.domain` import 排在
`app.jobs` 之后；手工重排后 Ruff 通过，mypy claimer 无问题。

### 8.13 Tracer 6 RED：Reaper 结果没有来源与 attempt 身份

使用 expired ORM Job、Run、JobAttempt、模拟 transaction 和真实 RetryPolicy 执行完整
`SQLAlchemyJobReaper.reap()`；aggregation 只替换为固定返回，避免把本 tracer 扩大成 Run
聚合测试。事务与 retry 都执行完成，最终断言报 `ReapedJob` 不存在 `origin_traceparent`。这
证明 recovery 输出无法驱动逐 Job linked span，也缺少过期 attempt 的明确属性。

### 8.14 Tracer 6 Reaper 数据最小 GREEN

ReapedJob 增加来源 carrier、nullable expired attempt ID 与 attempt number；reaper 从已锁定的
Run/Attempt 复制，不改 lease transition、retry 或 aggregation。结果：`2 passed`，Ruff 通过，
mypy reaper 无问题。此时 runtime 尚未消费 carrier，下一 tracer 单独锁定 span/event wiring。

### 8.15 Tracer 7 RED：runtime 没有逐 Job linked span 边界

新增 runtime 测试，要求 `handle_reaped_job()` 对一个 failed recovery 创建 linked root，并在其
内部发布 JOB_FAILED 与 RUN_COMPLETED 两个 child `progress.publish` span。第一次运行在 collection
阶段报 ImportError：runtime 不存在该函数。旧逻辑全部内嵌在 process loop，只能创建无来源的
publish span，无法单独验证逐 Job 因果边。

### 8.16 Tracer 7 runtime 最小 GREEN

抽取 `handle_reaped_job()`，外层 batch recovery span 仍只覆盖 DB batch；每个 item 创建独立
`reaper.job.recovered` root，通过 carrier 添加 Link，attributes 包含 tenant/run/job、attempt
ID/number、action 与 previous worker。JOB 与 terminal Run event 各有一个 child
`progress.publish`。运行结果 `2 passed`。Ruff 首次报告测试草稿的 UTC/datetime import 未使用；
删除后 Ruff 通过，mypy runtime 无问题。

### 8.17 Tracer 8 RED：Link 来源 span 缺少 Run identity

API 测试用 in-memory exporter 执行真实路由与 fake RunService，要求成功的 `run.create` span 带
最终 `run.id`。第一次运行请求返回 202，但 attribute 断言得到 `KeyError: run.id`；span 只有
tenant ID。没有修改失败路径，也没有从请求预先猜测 Run ID。

### 8.18 Tracer 8 最小 GREEN 与后置回归

路由接收 service 返回值后给当前 span 设置实际 `run.id` 再返回；失败路径不设置，idempotent
replay 记录既有 Run ID。Run API 结果：`9 passed`，Ruff 通过，mypy route 无问题。

随后补两条实现后回归，不宣称它们曾先失败：入站合法 trace 的 trace ID 可被平台 span 延续，
但 capture 的 span ID 必须是 `run.create` 自己而非客户端 parent；idempotent replay 使用一个
“调用 capture 就失败”的 telemetry double，锁定 replay 在捕获/写入新 context 前返回。

后置回归与 Run 合同合并结果：`23 passed`，Ruff 通过。

### 8.19 定向门禁与 propagator ambient-context 审阅

首次组合格式检查报告 4 个文件会被 Ruff formatter 调整（两个长表达式和两个函数内 class 的
标准空行），所以后续 lint/mypy/tests 当次并未执行。只格式化这 4 个文件后整组重跑：20 files
formatted、Ruff 通过、mypy 91 source files 无问题、`58 passed, 1 skipped`。skip 是本机未启用
真实 PostgreSQL 的 concurrency 合同，不是通过。

随后检查固定 OpenTelemetry 1.44 本地源码，确认 `TraceContextTextMapPropagator.extract()` 在
context 参数为 NULL 时会新建空 `Context()`；invalid carrier 不会回退到当前 ambient span。
生产实现无需修改，但增加“ambient span 内 invalid 仍返回空 links”的回归，防止未来依赖升级
改变该失败语义。

### 8.20 完整回归与 capture 失败软化审阅

完整非 integration：`445 passed, 8 deselected`，232.99s。提交前复审发现 carrier 解析已经
catch 并降级，但 current span 注入若 propagator 自身异常会从 `capture_traceparent()` 冒泡，
理论上可能让 observability 阻断 Run 创建。新增 monkeypatch RED 强制 inject 抛错，要求返回
NULL；这只验证失败软化，不吞掉数据库、artifact 或业务异常。

RED 结果：`1 failed`，`RuntimeError: propagator unavailable` 从 capture 冒泡。最小修复只捕获
propagator inject 异常并返回 NULL；RunService 的其余业务异常边界不变。

GREEN 结果：Telemetry + RunService `19 passed`；2 files formatted；Ruff 通过；mypy telemetry
无问题。由于这发生在第一次完整回归之后，提交前必须重新跑全量，不能沿用 445 项结果。

### 8.21 最终本地重跑

最后一项生产容错落地后，从头重跑 CI 同形门禁与全量：

| 检查 | 最终结果 | 状态 |
|---|---|---|
| P2-3 API/Telemetry/Run/claim/reaper/worker/migration 聚焦 | 59 passed | `VERIFIED` |
| 真实 PostgreSQL 100 claim/99 reap carrier 合同 | 本机 1 skipped | `NOT_RUN_LOCAL` |
| 非 integration 全量 | 446 passed，8 deselected，238.95s | `VERIFIED` |
| Ruff format | 247 files already formatted | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | 116 source files，无问题 | `VERIFIED` |
| uv lock | 70 packages resolved | `VERIFIED` |
| Alembic topology | 唯一 head `20260802_0012` | `VERIFIED` |
| 全部离线 migration tests | 8 passed | `VERIFIED` |
| `git diff --check` / 暂存区检查 | 通过 | `VERIFIED` |
| 本机 Docker/Compose/Collector | 未运行或未配置 | `NOT_RUN` |
| 正式 500-case/32-arm Gate 1 | 未启动 | `NOT_RUN` |

实现提交：`c1cd6074463a6820fa1a7cb8d12f620eb3a4a1a3`。

## 9. 达成效果与仍未证明的边界

达成效果：

- API 成功创建或 replay 的 `run.create` span 记录实际 Run ID；
- 首次新建 Run 持久化平台 span carrier，replay 与并发 loser 不覆盖 winner；
- claim 使用现有 Run join 把 carrier 交给每次 attempt，不增加查询或复制到每个 Job；
- `job.process` 保持新 root trace并建立一个来源 Link，内部 pipeline span 关系不变；
- Reaper batch 不错误绑定单个 Run，每个 recovered Job 单独 linked root；
- missing、historical、disabled、malformed、extract/inject failure 都降级为无 Link，不改变业务；
- trace context 不进入 API response、日志正文、Prometheus label、授权或调度判断；
- `0012` 可独立 upgrade/downgrade，历史 Run 不伪造 backfill。

远端 CI 已进一步证明：

- 绑定文档提交 `5c5d199b1f639826c60406626e8a04223803ffe1` 的
  [GitHub Actions Run #19](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30732220588)
  最终为 `success`；
- `quality-and-integration` 的真实 PostgreSQL claim/reap carrier、`0012` upgrade、P2
  downgrade/re-upgrade、非 integration 测试、Ruff、mypy 与 application image build 均为
  `success`；
- `compose-smoke` 的全拓扑 build、PostgreSQL/Redis 健康等待、Compose migration、
  API/Worker/Reaper 启动与 API readiness 均为 `success`。

仍未证明：

- 本机仍没有 PostgreSQL/Redis/Docker；真实服务与镜像证据来自上述远端 CI，而不是本机；
- 没有 Collector/trace backend，不能证明 OTLP 网络导出、Span Link UI、查询、采样或保留；
- API 与 Worker/Reaper 按设计不是同一个 trace，不应宣传成“端到端单 trace”；
- 不保存 tracestate/baggage，因此不会延续 vendor-specific routing；这是最小数据和安全选择；
- 历史 NULL Run 没有可验证来源 span，永远只能通过领域 ID 关联；
- traceparent 包含调用方可选择的 trace ID，仍只是不可信 observability metadata，绝不能用于
  安全或业务正确性；
- 普通 CI 不能证明容量、生产可靠性、exactly-once、通用 tracing 治理或正式 Gate。

本实现改变 source commit、migration 与 CI，所以所有绑定 P2-3 起始 SHA 或更早 SHA 的旧
prepared Gate 1 bundle 都应被现有 verifier 判为 source/hash mismatch。没有覆盖旧 evidence，
没有升级正式结果/plot schema，也没有启动 500-case 实验。

## 10. 回滚边界

纯仓库回滚入口：

```text
git revert c1cd6074463a6820fa1a7cb8d12f620eb3a4a1a3
```

已升级数据库时，应先暂停 API/Worker/Reaper，用仍含 `0012` 的 release 执行
`alembic downgrade 20260802_0011`，确认只删除 `origin_traceparent`，再部署 revert 后代码。
该 downgrade 会丢失新 Run 的 observability carrier，但不会删除 Run、Job、Attempt、Result 或
评审数据；业务退回领域 ID 关联。旧代码可忽略数据库里暂存的额外 nullable 列，但不能先删除
migration 文件后再尝试 downgrade。

## 11. 提交、推送与远端状态

- 实现提交：`c1cd6074463a6820fa1a7cb8d12f620eb3a4a1a3`；
- 首轮文档提交：`5c5d199b1f639826c60406626e8a04223803ffe1`；
- 两个提交均已推送到 `origin/codex/gate1-evidence-hardening`；
- GitHub Actions 真实 PostgreSQL/Redis/image/Compose：Run #19，`VERIFIED`；
- 当前阶段状态：`REMOTE_CI_VERIFIED / FORMAL_GATE_NOT_RUN`；
- PR/merge：未创建；
- 正式 Gate：`NOT_RUN`。
