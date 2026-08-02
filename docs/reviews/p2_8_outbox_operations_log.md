# P2-8 Outbox 保留策略与运维可观测性记录

## 1. 基本信息与最终结论

- 项目：AI EvalOps Platform（多租户异步 AI 评测与任务编排平台）。
- 阶段：P2-8，transactional Outbox delivered-row retention、backlog metrics 与告警合同。
- 起始分支：`codex/gate1-evidence-hardening`。
- 起始提交：`762bcf9aa61d4859b5564da022b264ece782c6a1`。
- 首轮实现/真实服务验证提交：`69cba416ed7c8254e4bc0eb4247568652c0f78e4`。
- 代码与首版证据文档验证提交：`5b374d22fd9fdc48d93b14103b405b31dd0dd3bb`。
- 数据库 migration：`20260803_0014_outbox_retention_index`，父版本
  `20260802_0013_transactional_outbox`。
- GitHub Actions：
  [Run #31](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759184986)，
  绑定实现 head；
  [Run #32](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759680786)，
  绑定代码与首版证据文档 head。两次运行的两个 job 均为 `success`。
- 正式 500-case/32-arm Gate：`NOT_RUN`。本阶段没有生成或修改正式实验结果、吞吐、p95/p99、
  容量拐点或 Worker adoption 结论。
- 最终结论：已发布且超过保留期的 Outbox 行现在可由 API 内独立 maintenance task 以有界
  `SKIP LOCKED` 批次删除；pending 行不会进入删除候选。API `/metrics` 从 PostgreSQL 刷新全局
  pending 数与 oldest pending age，并暴露 retry、lease-lost、cleanup Counter。仓库提供两条
  Prometheus alert rule 模板，但没有声称这些规则已经部署或在 Alertmanager 中触发。

本阶段没有改变以下语义：

- PostgreSQL 仍是 Run/Job/Result 和通知意图的持久边界；
- Redis Pub/Sub 仍是在线通知层，不提供历史回放；
- Outbox 仍是 at-least-once，同一 event ID 可能重放；
- SSE 仍以 PostgreSQL snapshot-first 恢复；
- cleanup 删除的是已经 fenced acknowledgement 的通知意图，不删除 pending，也不删除业务状态。

## 2. 为什么继续做 P2-8，为什么不直接运行正式 Gate

P2-7 的详细记录明确留下两个最先需要收口的运行风险：

1. `published_at IS NOT NULL` 的行永不删除，表会随通知量持续增长；
2. 运维只能看 batch 日志和 Redis failure Counter，无法直接看到 durable pending 数和最老积压年龄。

README 和面试问题也把 delivered-row retention、pending backlog/oldest-age 指标列为下一步。
所以 P2-8 是对已实现 Outbox 的运维闭环，不是继续增加业务 API。

没有先做 dead-letter/max-attempts，原因是该决定包含产品策略：

- 达到多少次后停止重试；
- 停止后是否允许人工 replay；
- 是否把通知静默丢弃、转存还是升级事件；
- 谁拥有确认和删除 dead-letter 的权限。

这些选择会改变“只要恢复就继续尝试”的现有交付合同，不能由实现者擅自决定。

没有把普通“继续”解释为运行正式 500-case/32-arm Gate。原始协议要求用户定义或确认性能/
adoption gate，并禁止自动运行正式矩阵、破坏性故障、强杀和 soak。因此本阶段继续保持
`FORMAL_GATE_NOT_RUN`。

## 3. 修改前审计结果

| 审计项 | 修改前行为 | 风险 |
|---|---|---|
| delivered retention | `published_at` 只写不删 | 表、索引和备份持续增长 |
| cleanup 查询 | 不存在 | 无法说明哪些行可以安全删除 |
| cleanup 并发 | 不存在 | 多 API 副本若自行删除，可能互相等待或重复抢同一批 |
| retention index | 只有 pending 与 tenant/run 索引 | 按 `published_at` 清理会扫描不匹配结构 |
| pending Gauge | 不存在 | 无法区分“实时安静”和“通知持续积压” |
| oldest age | 不存在 | 单个长期失败事件可能隐藏在总数中 |
| retry/lease-lost Counter | dispatcher 只返回 batch result、写日志 | 无法稳定做趋势与告警 |
| cleanup Counter | 不存在 | 无法知道 maintenance 是否实际删除过数据 |
| 告警规则 | 仓库没有 rule 文件 | “需要告警”只有文字，没有机器可读合同 |
| API lifespan | 只有 dispatcher task | maintenance 不会自动运行 |
| Compose 转发 | `.env.example` 有 relay 参数，Compose 未转发 | 容器只能使用代码默认值，宿主覆盖无效 |
| migration head | `20260802_0013` | 没有 retention 查询索引 |

审计还确认无需新增列：`published_at`、`id`、`created_at` 已足以表达 eligibility、稳定排序和
oldest pending age。新增表或把 Redis 改成历史日志都不是本阶段所需。

## 4. 冻结后的合同

### 4.1 删除资格

一行只有同时满足以下条件才可进入 cleanup 候选：

```text
published_at IS NOT NULL
AND published_at < now - retention_seconds
```

使用严格小于号。恰好等于 cutoff 的行要等下一轮，避免时钟边界含糊。

以下行永远不能由该 cleanup 删除：

- `published_at IS NULL` 的首次待发布行；
- 正在退避、未来 `available_at` 才到期的 retry；
- publish 已被 Redis 接受但 fenced acknowledgement 尚未提交的 leased 行；
- 任何 Run/Job/Result 业务事实。

数据库原有检查约束要求已发布行不能仍带 lease，所以 cleanup 不需要绕开租约或修改 owner。

### 4.2 有界并发 SQL

候选 CTE：

```text
SELECT id
FROM progress_event_outbox
WHERE published_at IS NOT NULL
  AND published_at < :published_before
ORDER BY published_at, id
LIMIT :batch_size
FOR UPDATE OF progress_event_outbox SKIP LOCKED
```

随后在同一个短事务内：

```text
DELETE FROM progress_event_outbox
WHERE id IN (SELECT id FROM outbox_cleanup_candidates)
RETURNING id
```

采用 `RETURNING id` 的原因是 SQLAlchemy/PostgreSQL 的通用 rowcount 语义不适合作为严格删除证据；
返回 ID 数量才是本轮实际删除数。ID 不写日志、不进入 Prometheus label。

`SKIP LOCKED` 允许多个 API 副本同时维护：一个副本已锁定的候选不会让另一副本等待。稳定
`published_at,id` 排序避免相同时间戳下的随机候选顺序。每轮最多 10,000 行，默认 500 行。

### 4.3 保留期与调度

| 配置 | 默认 | 允许范围 | 语义 |
|---|---:|---:|---|
| `EVALOPS_OUTBOX_RETENTION_SECONDS` | 604800（7 天） | 3600–31536000 | 已确认发布行的最低保留时间 |
| `EVALOPS_OUTBOX_CLEANUP_INTERVAL_SECONDS` | 60 | `>0`–3600 | maintenance 轮询间隔 |
| `EVALOPS_OUTBOX_CLEANUP_BATCH_SIZE` | 500 | 1–10000 | 单事务最多删除行数 |

7 天只是安全默认，不是法规、审计或容量结论。生产 operator 必须根据通知诊断需求、数据政策、
写入速率和数据库维护窗口确认它。

maintenance 在 API 启动后立即执行一轮，随后按 interval 等待。它与 dispatcher 使用同一个
stop event，但拥有独立 task 和 cadence。关闭顺序是：发 stop → 等两个 task → 关 Redis →
dispose engine → shutdown telemetry。

### 4.4 Durable Gauge 语义

| 指标 | 类型 | 来源 | 精确定义 |
|---|---|---|---|
| `outbox_pending` | Gauge | `/metrics` PostgreSQL refresh | `published_at IS NULL` 当前总数 |
| `outbox_oldest_pending_age_seconds` | Gauge | 同一 snapshot | `now - min(created_at)`，下限为 0 |

选择 `created_at` 而不是 `available_at`：一条反复失败并被推迟到未来的事件仍然是长期未交付，
不应因为下一次 retry 尚未到期就把 age 重置或隐藏。该 Gauge 是全局 backlog 视图，不按 tenant、
run 或 event 建 label。

Job Gauge 与 Outbox Gauge 使用同一个 `/metrics` 请求时间，但分别容错；一类查询失败不会阻止
另一类刷新。和既有 Job Gauge 一样，数据库失败时当前实现会保留进程内上一值或初始化值，
因此 scrape 必须同时观察 readiness，不能把旧 Gauge 当成新事实。

### 4.5 Counter 语义

| 指标 | 增加时机 |
|---|---|
| `outbox_retry_scheduled_total` | publish false/异常/超时后，当前 owner 成功释放并安排 retry |
| `outbox_lease_lost_total` | publish 后 ack 或失败后的 reschedule 未通过 owner/lease fencing |
| `outbox_cleanup_deleted_total` | maintenance 根据 `RETURNING` 实际删除已发布行 |

Counter 是每 API 进程本地 registry。多副本 Prometheus 必须抓取每个 API 并在查询端求和；项目
没有把 tenant/run/event ID 加入 label。

### 4.6 告警模板

`deploy/prometheus/outbox-alerts.yml` 提供：

1. `AIEvalOpsOutboxDeliveryStalled`：pending > 0 且 oldest age > 300 秒，持续 10 分钟；
2. `AIEvalOpsOutboxLeaseLoss`：10 分钟窗口 lease loss 增量 > 0，持续 5 分钟。

没有给 cleanup Counter 设阈值，因为没有合法事件量基线时，“删除少”可能只是系统没有旧行，
不能等价于 cleanup 停止。规则只有 `severity=warning` 这一个有界 label。

## 5. 方案比较与采用判断

### 5.1 在 `/metrics` scrape 时顺便删除

拒绝。GET `/metrics` 应保持观测读取；把数据库 mutation 绑定到 scrape 频率会导致：

- 没有 Prometheus 时永不清理；
- 多 scraper 重复触发；
- scrape timeout 与删除事务互相影响；
- 运维读取端拥有隐式写副作用。

### 5.2 每个 dispatcher batch 后顺便 cleanup

拒绝。delivery cadence 通常为 0.5 秒，retention cadence 为分钟级；耦合后空闲系统、Redis 故障
和高流量系统会产生不同的清理频率，也让 dispatcher 单一职责变浅。

### 5.3 新增独立 cleanup Compose 服务

当前拒绝。API 已拥有 PostgreSQL engine、生命周期和 metrics registry；`SKIP LOCKED` 已支持多个
API 副本。新增服务会扩大镜像角色、health、resource limit、部署和 scrape 拓扑，当前规模收益
不足。未来 maintenance CPU/锁负载独立扩展时可以重新评估。

### 5.4 API 内独立 maintenance task

采用。它共享基础设施但不共享 dispatcher 循环；接口只有 `cleanup_once(limit) -> int`，SQL、
cutoff、事务和 `RETURNING` 被封装在模块内。

### 5.5 无界 DELETE

拒绝。`DELETE ... WHERE published_at < cutoff` 会形成不可控事务、WAL、vacuum 压力和锁持续时间，
也无法清晰记录每轮进度。

### 5.6 归档而不是删除

本阶段不采用。Outbox 是通知意图，不是领域审计日志；归档会新增另一张表或对象存储、生命周期、
访问控制和隐私合同。如果产品以后要求通知历史审计，应独立设计，不应把 delivered Outbox 默认
冒充审计记录。

## 6. 实现文件与影响

| 文件 | 修改 |
|---|---|
| `app/events/outbox.py` | retention CTE/DELETE、maintenance 类、cleanup loop、retry/lease counters |
| `app/observability/durable.py` | pending count/min created_at 查询和值对象/refresh |
| `app/observability/metrics.py` | 两个 Gauge、三个 Counter |
| `app/api/routes_observability.py` | `/metrics` 刷新 Outbox durable snapshot |
| `app/core/config.py` | 三个有界 cleanup Settings |
| `app/main.py` | maintenance/cleanup task、共享 stop、dispatcher metrics 接线 |
| `app/persistence/orm_models.py` | published retention partial index metadata |
| `alembic/versions/20260803_0014_outbox_retention_index.py` | 新索引和精确 downgrade |
| `.env.example` | 三个 cleanup 配置示例 |
| `deploy/compose.yaml` | 全部 dispatch/cleanup 参数显式转发 |
| `deploy/prometheus/outbox-alerts.yml` | 两条机器可读告警模板 |
| unit/API/integration tests | SQL、指标、配置、生命周期、迁移和真实并发合同 |

不需要修改 `uv.lock`，没有新增依赖，没有修改历史 migration。

## 7. TDD 过程：每个 RED 与 GREEN

本阶段按单一行为纵向切片，没有先写一批测试再一次性实现。

### 7.1 Retention 查询和维护接口

| 提交 | 类型 | 实际结果与判断 |
|---|---|---|
| `d9b51cb` | RED | import `build_cleanup_outbox_statement` 失败；旧代码无删除边界 |
| `41e8fe4` | GREEN | CTE + bounded `SKIP LOCKED` + `DELETE RETURNING`；Outbox 文件 9 passed |
| `4865fa2` | RED | import `SQLAlchemyOutboxMaintenance` 失败 |
| `f152266` | GREEN | 固定时钟推导 cutoff，短事务返回实际删除数；10 passed |

第一个 GREEN 后 strict mypy 发现 `.returning()` 不是普通 `Delete`，而是
`ReturningDelete[tuple[UUID]]`；同时 Ruff 发现测试导入顺序。修复采用精确 SQLAlchemy 类型和排序，
没有加 `type: ignore` 或关闭规则。

### 7.2 Durable backlog Gauge

| 提交 | 类型 | 实际结果与判断 |
|---|---|---|
| `a5c15f7` | RED | import durable Outbox query 失败 |
| `d6727c7` | GREEN | 全局 pending count + min(created_at)，无 GROUP BY/tenant label |
| `6487dfb` | RED | `PlatformMetrics` 无 `set_outbox_pending` |
| `5c8b389` | GREEN | 两个无 label Gauge，指标测试 3 passed |
| `0aa79c6` | RED | 缺 `DurableOutboxGauges` 与 refresh 接口 |
| `2fb0d92` | GREEN | snapshot → value object → metrics，观测聚焦 7 passed |
| `0f53499` | RED | HTTP `/metrics` 在数据库 pending=3 时仍输出默认 `0.0` |
| `3cbab8d` | GREEN | 路由刷新真实 durable snapshot，API/观测聚焦 9 passed |

`0f53499` 是关键证据：只有 Gauge 定义会让 Prometheus 暴露一个看似正常的零，但不代表数据库
真的没有积压。测试防止再次把“未刷新”写成“观察到零”。

### 7.3 Retry、lease-lost 与 cleanup Counter

| 提交 | 类型 | 实际结果与判断 |
|---|---|---|
| `a957fe3` | RED | 三个 record 方法不存在 |
| `eabadd8` | GREEN | 全局无 label Counter，指标测试 4 passed |
| `9fbb5fa` | RED | dispatcher 不接受 metrics 依赖 |
| `f2c4c9a` | GREEN | batch retry_scheduled 聚合计数，Outbox 11 passed |
| `c150dae` | RED | result.lease_lost=1，但 Counter 仍为 0 |
| `5fd480b` | GREEN | lease-lost 聚合计数，Outbox 12 passed |

### 7.4 Cleanup loop 与错误恢复

| 提交 | 类型 | 实际结果与判断 |
|---|---|---|
| `ccf04a0` | RED | import `run_outbox_cleanup_loop` 失败 |
| `61bc6af` | GREEN | bounded batch、Counter、cooperative stop；13 passed |
| `3ef9095` | RED | loop 不接受 logger；数据库异常会直接结束 task |
| `198284b` | GREEN | 只记录异常类型、下一轮恢复、成功批次安全日志；14 passed |

### 7.5 告警、配置与 Compose

| 提交 | 类型 | 实际结果与判断 |
|---|---|---|
| `e08f6cd` | RED | `deploy/prometheus/outbox-alerts.yml` FileNotFoundError |
| `24af54f` | GREEN | 两条规则、无高基数 label，部署测试 7 passed |
| `9795dc0` | RED | Settings 无 retention/interval/batch 字段 |
| `04d8410` | GREEN | 三个 Pydantic 有界字段，配置测试 16 passed |
| `849fe51` | RED | Compose 第一项 `EVALOPS_OUTBOX_POLL_SECONDS` 即 KeyError |
| `5a0261c` | GREEN | 九个 dispatch/cleanup 参数示例与转发，部署测试 8 passed |

Compose RED 证明 P2-7 虽在 `.env.example` 写了 relay 参数，容器运行时仍无法从宿主覆盖；这不是
P2-8 新需求，而是检查 lifecycle 时发现并修复的实际部署缺口。

### 7.6 Migration 与 ORM metadata

| 提交 | 类型 | 实际结果与判断 |
|---|---|---|
| `3c27682` | RED | offline head 没有 published retention index |
| `06f00f2` | GREEN | 新 `0014` upgrade 创建 partial index |
| `cfd65f7` | RED | downgrade 只更新 Alembic version，不 DROP index |
| `cc18b8c` | GREEN | `0014 → 0013` 只删除新索引；4 migration tests，唯一 head 0014 |
| `cbf317d` | RED | ORM metadata 查找同名索引得到 KeyError |
| `241e8b0` | GREEN | ORM/migration 同名、同列、同 predicate；持久层聚焦 18 passed |

upgrade 和 downgrade 分开做 RED/GREEN，是为了明确证明回滚不是空函数，也不会误删 Outbox 表。

### 7.7 API lifespan 与真实接线

| 提交 | 类型 | 实际结果与判断 |
|---|---|---|
| `887571b` | RED | dispatcher 启动，但 cleanup event 等待 1 秒超时 |
| `4eaf009` | GREEN | 创建 maintenance/task、共享 stop、关闭前 gather；接线测试通过 |
| `efe8516` | RED | 捕获 dispatcher 构造参数没有 `metrics` key |
| `5c796f7` | GREEN | 注入 API registry；lifespan + Outbox 聚焦 15 passed |

### 7.8 真实服务合同

| 提交 | 类型 | 结果 |
|---|---|---|
| `69cba41` | integration contract | 本机 `1 skipped`；Ruff/mypy passed；GitHub Actions #31 真实执行成功 |
| `5b374d2` | code + evidence docs | GitHub Actions #32 两个 job success，首版证据文档已进入远端验证头 |

真实 integration 在原 Outbox 场景后增加：

1. 两条 8 天前已发布行；
2. 一条 1 天前已发布行；
3. 一条 8 天前 pending 行；
4. 两个 maintenance 实例并发、各 `limit=1`；
5. 合计删除结果必须为 `[1,1]`；
6. 两条旧 delivered 消失，近期 delivered 与旧 pending 保留；
7. durable Gauge 必须是 pending=1、oldest age=691200 秒。

## 8. 实际遇到的问题、原因和处理

### 8.1 PowerShell 原生命令退出码没有阻止后续 commit

在 RED `3ef9095` 前执行了：

```text
ruff format --check
ruff check
git diff --check
git add
git commit
```

`ruff format --check` 正确返回非零，并指出一个 assertion 会被 formatter 折叠；但 PowerShell 的
`$ErrorActionPreference = 'Stop'` 主要处理 PowerShell error record，不会自动把每个原生程序的
非零 `$LASTEXITCODE` 转成终止异常，因此后面的 `git commit` 仍然执行。

影响：

- RED 的行为证据仍然有效；
- 该提交里有一处 Ruff format 偏差；
- 后续 GREEN `198284b` 同时做了纯格式修正；
- 最终全仓 Ruff format/lint 均通过。

处理：之后所有串联命令在每个原生工具后显式执行：

```powershell
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

没有 amend、隐藏或删除这个过程，保留为可复盘的工具链教训。

### 8.2 本机真实服务仍不可用

本机 `tests/integration/test_transactional_outbox.py` 输出 `1 skipped`，原因是没有设置
`EVALOPS_RUN_INTEGRATION=1` 和 migrated PostgreSQL/Redis。它被记录为 `NOT_RUN_LOCAL`，没有写成
PASS。实现 head 的真实结果来自 GitHub Actions #31，代码与首版证据文档 head 又由 #32 验证。

### 8.3 Compose 参数转发缺失

测试最初在 `environment["EVALOPS_OUTBOX_POLL_SECONDS"]` 得到 KeyError。根因不是 Pydantic：代码
能解析环境变量；问题是 Compose 的 `x-app-environment` 没把宿主变量放进容器。修复覆盖 P2-7
已有六个 dispatcher 参数和 P2-8 三个 cleanup 参数。

### 8.4 CI 没有发现新的并发或 migration 缺陷

与 P2-7 #27 不同，#31 的真实 cleanup、原双 Reaper、全部 integration、migration round-trip、
image 和 Compose 均成功。本阶段不能虚构一个 CI 故障；有价值的发现主要来自前述 RED 与部署审计。

## 9. 验证结果

| 检查 | 结果 | 证据等级 |
|---|---|---|
| retention SQL/maintenance/loop 聚焦 | 14 passed | `VERIFIED` |
| API + observability 聚焦 | 9 passed | `VERIFIED` |
| Settings | 16 passed | `VERIFIED` |
| deployment config/alerts | 8 passed | `VERIFIED` |
| ORM + migration 聚焦 | 18 passed | `VERIFIED` |
| lifespan + Outbox 聚焦 | 15 passed | `VERIFIED` |
| `uv lock --check` | 70 packages | `VERIFIED` |
| Ruff format | 260 files | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | app/scripts/integration/concurrency，119 source files | `VERIFIED` |
| 本地非 integration 全量 | 504 passed, 9 deselected in 248.23s | `VERIFIED` |
| 本地真实 Outbox integration | 1 skipped | `NOT_RUN_LOCAL` |
| Alembic | 唯一 head `20260803_0014`；offline upgrade/downgrade passed | `VERIFIED` |
| GitHub Actions #31 | 实现 head 两个 job success | `VERIFIED_REMOTE` |
| GitHub Actions #32 | 代码与首版证据文档 head 两个 job success | `VERIFIED_REMOTE` |
| Prometheus rule YAML | parse/contract passed | `CONTRACT_VERIFIED` |
| 真实 Prometheus/Alertmanager rule evaluation | 未部署、未触发 | `NOT_RUN` |
| 正式 500-case/32-arm/soak | 未授权、未运行 | `NOT_RUN` |

[GitHub Actions #31](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759184986)
绑定 head `69cba416ed7c8254e4bc0eb4247568652c0f78e4`。步骤级结果确认：

- lock、format、lint、strict mypy；
- 非 integration 全量；
- migration apply；
- 原有并发/fencing/human review/tenant/artifact/readiness/Redis/idempotency integration；
- transactional Outbox delivery/replay/retention；
- P2 downgrade/re-upgrade；
- application image；
- 完整 Compose topology、迁移、readiness 和 hardening。

[GitHub Actions #32](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759680786)
绑定 head `5b374d22fd9fdc48d93b14103b405b31dd0dd3bb`，同样由
`quality-and-integration` 与 `compose-smoke` 两个 job 成功完成。它验证的是代码、CI 步骤命名和
首版 P2-8 证据文档共同存在时，完整流水线仍保持通过。

## 10. Migration 与部署顺序

### 10.1 Upgrade

推荐顺序：

1. 评估当前 delivered 行数、表大小和数据库维护窗口；
2. 应用 migration `0014`，先建立 retention partial index；
3. 部署包含九个 Outbox 环境变量的新 Compose/API；
4. 确认 API cleanup task 没有 `outbox_cleanup_iteration_failed`；
5. 抓取 `/metrics`，观察 pending、oldest age、retry、lease loss、cleanup deleted；
6. 根据实际 SLO 调整规则阈值，并由 operator 把模板加载到真实 Prometheus；
7. 观察 autovacuum/WAL/锁等待，确认 cleanup batch/interval 合适。

旧应用可以看到多出的索引而不受影响，所以“先 migration、后应用”兼容。新应用在 `0013` 上也能
执行 SQL，但缺索引会放大扫描成本，因此不推荐反向顺序。

### 10.2 索引构建风险

`0014` 使用普通 `CREATE INDEX`，不是 `CREATE INDEX CONCURRENTLY`。CI 只在小型受控数据库证明
语法和 round-trip；对于已经有大量 delivered 行的生产表，普通建索引可能阻塞写入。正式部署前
应根据表大小选择维护窗口，或另行设计 Alembic autocommit/concurrent migration；本阶段没有伪称
已验证大型在线索引构建。

### 10.3 Downgrade

推荐顺序：

1. 先部署/恢复不运行 cleanup task 的旧 API，停止新的删除；
2. 从 Prometheus 配置中移除或调整新指标规则，避免 absent-series 告警；
3. downgrade `0014 → 0013`，只删除 retention index；
4. 保留 `progress_event_outbox` 表、pending 行和全部业务状态。

重要边界：在 P2-8 运行期间已经按 retention 删除的 delivered 行无法由 migration downgrade 恢复。
它们不是 Run/Job/Result 事实，但可能具有通知诊断价值。若组织要求更长审计保留，必须在启用
cleanup 前提高 retention 或设计独立归档，不能指望 rollback 找回已删除行。

## 11. 达成效果

修改前：

```text
published row -> remains forever
pending delivery -> only inferred from logs
host env override -> not forwarded by Compose
```

修改后：

```text
published row older than retention
    -> bounded ordered CTE
    -> SKIP LOCKED claim
    -> DELETE RETURNING in one short transaction

pending row
    -> excluded from cleanup
    -> counted from PostgreSQL on /metrics scrape
    -> oldest created age exposed for alerting
```

本阶段真正证明的是：

- 删除 eligibility 有明确 SQL 合同；
- 多 maintenance 实例在真实 PostgreSQL 下可并发清理不同有界候选；
- pending 与近期 delivered 在真实测试中保留；
- Gauge 不再只是默认 0，而从数据库刷新；
- retry/lease-lost/cleanup 发生量有低基数指标；
- Compose operator 可以覆盖 Outbox 参数；
- schema upgrade/downgrade 和应用生命周期都有自动化合同。

## 12. 仍未证明和残余风险

1. **没有 strict table-size 上限**：cleanup 是吞吐受限的渐进删除。如果 delivered 写入速率长期
   高于 `batch_size / interval`，历史仍会增长。
2. **没有 dead-letter/max attempts**：pending 仍可无限重试；这是保留 P2-7“不静默丢通知”的
   选择，不是遗漏删除条件。
3. **没有 delivered backlog Gauge**：当前可看 cleanup Counter，但无法直接告警“超过 retention
   的 delivered 行仍有多少”。
4. **Gauge freshness 未暴露**：数据库 refresh 失败会保留旧值/默认值；必须结合 readiness，未来
   可增加 refresh success timestamp/failure Counter。
5. **规则未真实部署**：YAML 只做 parse/contract；没有 Prometheus server、Alertmanager、通知
   路由、静默策略或 on-call 演练证据。
6. **Counter 是 per-process**：多 API 必须全量 scrape 并聚合，API 重启会 reset。
7. **所有 API down 时停止清理**：pending delivery 本来也停止；应用恢复后 cleanup 会继续。
8. **删除不可恢复**：downgrade 不会找回已经清理的 delivered notification intent。
9. **普通 CREATE INDEX 风险**：没有大型表在线建索引证据。
10. **默认 7 天未经业务/合规确认**：它只是工程默认。
11. **没有 archive 或逐行 audit**：日志/Counter 只记录批量数量，不记录 event ID。
12. **没有 statement timeout 新合同**：极端数据库卡顿可能拖慢 shutdown。
13. **没有多区域、网络分区、30–60 分钟 soak 或容量实测**。
14. **Pub/Sub 仍无历史回放，客户端仍需 snapshot-first 和 event ID 去重**。
15. **正式 Gate 仍未运行**：没有吞吐、p95/p99、资源曲线、容量 knee 或 adoption 结论。

## 13. 对 Gate 1 prepared evidence 的影响

source commit、migration head、Compose hash、测试和文档均已变化。任何在 `762bcf9` 或更早提交
prepare 的 bundle 只能保留为历史只读；正式 Gate 前必须从最终干净提交重新 prepare 和 preflight。

本阶段没有修改 prepared/result/final-bundle/Prometheus evidence schema，因为正式 artifact 语义
没有改变。不能为了 source 变化无意义升 schema，但必须让 hash/preflight 使旧 bundle 失效。

## 14. 学习与面试表述

推荐表述：

> Transactional Outbox 解决了状态和通知意图的双写原子性，但已确认发布行如果永不清理，
> 会把可靠性方案变成无限增长的运维负债。我先用 RED 冻结只删除 `published_at` 超过保留期的
> 有界 CTE，并用 `FOR UPDATE SKIP LOCKED` 允许多 API 副本并发维护；pending 行不进入候选。
> 我新增 `(published_at,id)` 部分索引、独立 cleanup task、PostgreSQL durable backlog Gauge 和
> retry/lease-lost/cleanup Counter。真实 CI 用两个 maintenance、batch=1 证明两条旧 delivered
> 被删除，而近期 delivered 和旧 pending 保留。告警规则只是模板，未部署；交付仍是
> at-least-once，downgrade 也不能恢复已经按 retention 删除的 delivered intent。

值得记住的工程点：

- retention 是数据生命周期合同，不只是定时 `DELETE`；
- eligibility、批量上限、排序、并发锁、索引和 rollback 必须一起设计；
- `/metrics` 不应产生 cleanup 写副作用；
- 定义 Gauge 不等于正确观测，必须证明数据库值真正刷新，避免默认零；
- long-running retry 的 age 应从 durable creation 计算，不能被未来 `available_at` 隐藏；
- alert rule 文件通过测试不等于真实告警链已验证；
- PowerShell 对原生程序非零退出要显式检查 `$LASTEXITCODE`；
- migration rollback 能撤销 schema，不一定能撤销后台任务已经执行的数据生命周期操作。

## 15. 下一步建议

技术上最值得继续的是先由用户/operator 冻结通知 SLO 与 dead-letter 产品合同：允许多少重试、
是否归档、谁能 replay/ack、告警阈值和 delivered retention 是否满足业务/合规。若不扩展产品语义，
下一项应是经单独授权后重新 prepare 正式 Gate 1，再由用户监督 500-case/32-arm 容量实验；不能把
本阶段 CI 成功当作容量结论。
