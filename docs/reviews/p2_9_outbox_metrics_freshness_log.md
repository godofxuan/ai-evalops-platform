# P2-9 Outbox 指标刷新新鲜度完整记录

## 1. 基本信息与当前结论

- 项目：AI EvalOps Platform（多租户异步 AI 评测与任务编排平台）。
- 阶段：P2-9，Outbox durable metrics refresh health/freshness。
- 分支：`codex/gate1-evidence-hardening`。
- 起始提交：`b0a7b5f816e1b39e7124c9f6438694cd099dfe2c`。
- 首轮代码与测试验证提交：`30d4d372802db0d26778344a10ddbc9e13579f13`。
- CI 可读性提交：`20cf325`，只调整 Outbox integration 步骤名称，不改变执行命令。
- 首轮远端证据：
  [GitHub Actions #34](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30774192971)，
  绑定 `30d4d372802db0d26778344a10ddbc9e13579f13`，两个 job 均为 `success`。
- migration：无新增；数据库 head 仍为 `20260803_0014_outbox_retention_index`。
- 正式 500-case/32-arm Gate：`NOT_RUN`。
- 真实 Prometheus/Alertmanager：未部署、未评估、未路由，状态 `NOT_RUN`。

最终行为：

1. 每次 durable Outbox Gauge snapshot 全部成功后，记录
   `outbox_metrics_last_success_timestamp_seconds`；
2. snapshot 任何阶段失败时，增加 `outbox_metrics_refresh_failures_total` 后原样重新抛出；
3. `/metrics` 保持原有隔离边界，失败时仍返回进程指标和上一次成功 snapshot；
4. 失败不会把 last-success 重置为 0，也不会伪造新的成功时间；
5. Prometheus 模板在连续 5 分钟没有成功刷新时产生
   `AIEvalOpsOutboxMetricsStale` warning；
6. 两个新指标均无 tenant/run/event 等 ID label，保持低基数。

## 2. 为什么继续做 P2-9

P2-8 已经让 `/metrics` 从 PostgreSQL 刷新：

- `outbox_pending`；
- `outbox_oldest_pending_age_seconds`。

路由为了不让一次数据库故障使整个 Prometheus scrape 消失，分别隔离 Job 和 Outbox refresh
异常。这一可用性选择是合理的，但留下一个观测正确性问题：

- refresh 失败时旧 Gauge 继续暴露；
- 进程刚启动且从未成功 refresh 时 Gauge 默认是 0；
- 观察者无法区分“PostgreSQL 中确实没有 pending”与“查询根本没有成功”；
- backlog alert 只看到 `pending=0` 时可能误以为系统正常。

所以 P2-8 的 backlog Gauge 还缺少“这个 snapshot 有多新”的证据。P2-9 的目标不是增加更多
业务状态，而是防止旧值或默认值冒充新事实。

## 3. 为什么没有直接做文档建议中的另外两条路线

### 3.1 没有擅自实现 dead-letter/max-attempts

dead-letter 会改变通知交付的产品语义，至少必须先回答：

- 允许尝试多少次或多长时间；
- 到达上限后是停止、归档、告警还是继续低频重试；
- 谁能 replay、ack、删除或导出；
- payload/event 是否受合规保留期约束；
- replay 是否必须沿用同一 event ID；
- 对客户承诺的是最终交付、尽力通知还是只保留平台意图。

用户的一句“继续”授权继续改进项目，但不足以替用户冻结这些业务和权限合同，因此本阶段没有
增加 attempt ceiling、dead-letter 状态、管理 API 或人工 replay。

### 3.2 没有启动正式 Gate

正式 Gate 会运行 500-case/32-arm、产生不可覆盖实验结果并使用真实资源。仓库文档要求：

- 从最终干净提交重新 prepare；
- 单独明确授权；
- 用户监督；
- 保存负面和部分完成结果；
- 用户提供 performance/adoption policy。

“继续”不是对上述资源实验的明确单独授权。本阶段没有创建或修改 `docs/results/`，没有启动
Docker 负载、强杀或正式容量实验。

### 3.3 为什么 freshness 可以独立推进

freshness 只增加观测证据：

- 不改变 Outbox eligibility；
- 不改变 retry、lease、fencing 或 retention；
- 不改变 API 权限；
- 不修改数据库 schema；
- 不删除或重放事件；
- 可通过删除两个指标、一个接线块和一条告警规则完整回滚。

因此它是一个低耦合、可测试、可回滚的独立垂直切片。

## 4. Zoom-out 模块与调用者地图

实际调用链：

```text
Prometheus scraper
        |
        v
GET /metrics
app/api/routes_observability.py::get_metrics
        |
        +--> refresh_durable_job_gauges(...)       独立异常边界
        |
        +--> refresh_durable_outbox_gauges(...)    独立异常边界
                 |
                 v
       PostgreSQL aggregate snapshot
                 |
                 v
       app/observability/metrics.py::PlatformMetrics
                 |
                 +--> backlog/oldest-age Gauge
                 +--> last-success timestamp Gauge
                 +--> refresh-failure Counter
                 |
                 v
deploy/prometheus/outbox-alerts.yml
```

相关模块与职责：

| 模块 | 既有职责 | P2-9 变化 |
|---|---|---|
| `app/api/routes_observability.py` | scrape 前分别刷新 Job/Outbox durable Gauge；异常隔离 | 无代码变化；继续负责降级边界 |
| `app/observability/durable.py` | 查询 PostgreSQL snapshot 并更新 Gauge | 成功标记时间；失败计数后重抛 |
| `app/observability/metrics.py` | 每进程 Prometheus registry | 新增无标签 timestamp Gauge 与 failure Counter |
| `deploy/prometheus/outbox-alerts.yml` | Outbox 告警模板 | 新增 stale refresh rule |
| `tests/unit/observability` | registry 与 durable snapshot 合同 | 验证新指标和成功接线 |
| `tests/api/test_observability.py` | `/metrics` 公共 HTTP 行为 | 验证失败仍 200、保留旧时间并计数 |
| `tests/integration/test_transactional_outbox.py` | 真实 PG/Redis Outbox 合同 | 验证真实 snapshot 写入精确时间 |
| `tests/unit/test_deployment_config.py` | Compose/告警 YAML 合同 | 验证 stale rule 完整内容 |

探索时曾假设路由位于 `app/api/routes/metrics.py`，读取命令得到 path-not-found。通过符号
`refresh_durable_outbox_gauges` 和 `/metrics` 反查后，确认真实入口是
`app/api/routes_observability.py`。该探索失败没有修改文件。

## 5. 冻结的公共合同

### 5.1 最近成功时间

指标：

```text
outbox_metrics_last_success_timestamp_seconds
```

类型：Gauge。

语义：当前 API 进程最近一次完整成功取得并写入 durable Outbox snapshot 的 Unix timestamp。

更新时间点：

1. PostgreSQL 查询成功；
2. 结果能转换为 `DurableOutboxGauges`；
3. pending Gauge 已更新；
4. oldest-age Gauge 已更新；
5. 最后才写 last-success。

失败时不能更新，也不能重置。这使 stale 值仍可用于诊断，但不会被误认作当前 snapshot。

### 5.2 刷新失败计数

指标：

```text
outbox_metrics_refresh_failures_total
```

类型：Counter。

语义：当前 API 进程中 durable Outbox refresh 抛出的异常次数。

Counter 不带异常消息、数据库 URL、tenant、run 或 event ID。它用于频率和趋势诊断，不替代
last-success freshness。

### 5.3 HTTP 降级合同

Outbox refresh 失败后：

- `refresh_durable_outbox_gauges` 先计数再重新抛出；
- 路由的既有独立异常边界抑制该异常；
- Job refresh 的结果仍保留；
- `/metrics` 返回 200；
- registry 渲染上一次 Outbox snapshot、last-success 和 failure Counter；
- readiness/数据库监控仍负责表达依赖不可用。

没有把 `/metrics` 改成 503，因为监控入口消失会同时丢失用于诊断故障的进程内 Counter。

### 5.4 告警合同

```promql
time() - outbox_metrics_last_success_timestamp_seconds > 300
```

规则名：`AIEvalOpsOutboxMetricsStale`；`for: 5m`；`severity: warning`。

含义：指标值超过 5 分钟没有成功更新，并持续 5 分钟。初始 Gauge 为 0，所以进程启动后一直
无法成功 refresh 也会满足表达式；短暂单次失败只增加 Counter，不立即触发 stale alert。

该规则不处理 scrape target 完全消失；目标不可达应由 Prometheus `up`/service discovery 告警
覆盖。仓库没有部署 Prometheus/Alertmanager，因此当前只有 YAML/表达式合同证据。

## 6. 方案比较与取舍

### 6.1 只记录日志

未采用。日志适合单次异常细节，但不便宜地回答“多久没有成功刷新”“过去 10 分钟失败几次”，
也难以直接参与 PromQL 告警。

### 6.2 二值 health Gauge

未采用。`0/1` 能表达最后一次结果，却无法区分失败 10 秒与失败 1 小时；进程崩溃后也不会继续
更新。timestamp 让 Prometheus 用自己的当前时间计算 age。

### 6.3 直接暴露 refresh-age Gauge

未采用。若 age 只在成功 refresh 时写入，它会停在旧的小值，恰好掩盖故障；若依赖失败路径
不断更新，又要求业务进程持续执行计算。last-success timestamp 的含义更稳定。

### 6.4 失败时把 backlog Gauge 清零

拒绝。0 是一个有效业务值，清零会把未知冒充没有 backlog。

### 6.5 失败时把 Gauge 写 NaN

未采用。它会丢掉上一次 snapshot 的诊断价值，并要求所有 dashboard/query 特殊处理 NaN。
本阶段选择保留旧值并用 freshness 明确限定可信度。

### 6.6 每次失败立即告警

未采用。数据库瞬时抖动不一定需要 on-call；Counter 保留频率，stale rule 只对持续失败告警。

### 6.7 把 tenant/run/event 放进 label

拒绝。刷新是全局 aggregate 行为，加入无界 ID 会制造高基数；具体对象定位继续使用日志/trace。

## 7. TDD 垂直切片记录

### 7.1 成功时间指标定义

| 提交 | 状态 | 证据与效果 |
|---|---|---|
| `2be3d29` | RED | 调用公开 `record_outbox_metrics_refresh_success` 得到精确 AttributeError |
| `9419e3e` | GREEN | 新增 timestamp Gauge 与 datetime→Unix 秒方法；Metrics 文件 5 passed |

首个测试原先使用 2026 大时间戳，写入时发现断言会耦合 Prometheus 科学计数法格式；在执行前改为
epoch 123.5 秒。第一次真正运行又被 Ruff format 挡住，因为单个调用被不必要地拆成三行；按格式器
建议机械调整后，pytest 才得到缺少方法的有效 RED。格式失败没有冒充功能 RED。

### 7.2 失败 Counter 定义

| 提交 | 状态 | 证据与效果 |
|---|---|---|
| `3810240` | RED | 缺少 `record_outbox_metrics_refresh_failure`，精确 AttributeError |
| `566f16a` | GREEN | 新增无标签 Counter 与递增方法；Metrics 文件 6 passed |

这一步只定义 registry 接口，没有提前接线 durable refresh。

### 7.3 成功 snapshot 接线

| 提交 | 状态 | 证据与效果 |
|---|---|---|
| `dca8b43` | RED | pending=3、age=45 均通过，last-success=123.5 断言失败 |
| `5f2e308` | GREEN | 所有 backlog Gauge 写入后再标记 success；observability 10 passed |

首次 RED 校验脚本还要求 pytest 的失败输出显示默认 `0.0`，但 pytest 截断了很长的 registry
字符串，导致外层校验误报。产品测试实际已经在新增断言处失败。修正校验脚本，只检查失败行是
123.5 断言后，得到有效 RED；没有修改产品测试来迎合输出。

### 7.4 HTTP 失败可见性

| 提交 | 状态 | 证据与效果 |
|---|---|---|
| `68de0dd` | RED | Job snapshot 成功、Outbox snapshot 抛错；HTTP 200 和 timestamp=0 通过，failure=1 失败 |
| `28aecb2` | GREEN | durable refresh 捕获 Exception、计数、原样重抛；API/observability 13 passed |

`28aecb2` 与 `566f16a` 的 commit subject 都是 “count outbox refresh failures”，但职责不同：前者
是 durable 接线，后者是 registry 定义。历史没有 amend 或隐藏，使用 SHA 可明确区分。

### 7.5 Stale alert

| 提交 | 状态 | 证据与效果 |
|---|---|---|
| `cb2e931` | RED | YAML 正常解析，但 rules map 缺少 `AIEvalOpsOutboxMetricsStale`，精确 KeyError |
| `ec2e31b` | GREEN | 新增 300 秒表达式、5 分钟持续时间和 warning；部署合同 9 passed |

既有 delivery-stalled 与 lease-loss 规则没有改名或改阈值。

### 7.6 真实 PostgreSQL 合同

| 提交 | 类型 | 证据与效果 |
|---|---|---|
| `1a7e3a3` | integration contract | 在 P2-8 真实 snapshot 后断言 registry 时间等于 `retention_now.timestamp()` |

这个测试本机首次运行被 Ruff 要求调整长断言格式；修正后是 `1 skipped`，原因是本机没有启用
迁移后的 PostgreSQL/Redis。它没有被写成 local PASS。GitHub Actions #34 中对应真实服务步骤
成功，才提供远端实证。

### 7.7 失败保留旧成功证据

| 提交 | 类型 | 证据与效果 |
|---|---|---|
| `30d4d37` | regression，首次 GREEN | 预置 123.5，Outbox 查询失败后仍为 123.5、failure=1、HTTP 200 |

第一次补丁因上下文相同，把预置时间加到前一个成功用例。执行测试前通过代码检查发现并移动到
失败用例；生产代码未受影响。该行为已经由前一个 GREEN 实现，因此测试首次通过，如实记录为
回归，不伪造 RED。

### 7.8 CI 可读性

| 提交 | 类型 | 效果 |
|---|---|---|
| `20cf325` | CI metadata | 步骤名补充 `metrics freshness`；命令、环境和测试文件不变 |

## 8. 实现细节

### 8.1 PlatformMetrics

新增两个无标签 collector：

```text
Gauge   outbox_metrics_last_success_timestamp_seconds
Counter outbox_metrics_refresh_failures_total
```

Prometheus Python Client 的 Counter 构造名不含 `_total`，渲染时自动补 `_total`；文档和告警使用
渲染后的正式名称。

### 8.2 Durable refresh 事务边界

聚合查询仍使用一个短只读 session snapshot。异常处理包住查询、row 转换和三个 Gauge 更新：

```text
try:
    query snapshot
    set pending
    set oldest age
    mark success timestamp
    return snapshot
except Exception:
    increment failure counter
    raise
```

没有捕获 `BaseException`，因此任务取消等控制流不会冒充数据库 refresh failure。

### 8.3 路由边界为什么不改

`routes_observability.get_metrics` 原本就把 Job 与 Outbox refresh 放在两个独立异常边界中。
P2-9 把失败计数放进 Outbox durable 模块后，路由不需要知道数据库异常类型，也不需要增加新的
条件分支。接口保持小，失败记账逻辑不会因新增调用者而遗漏。

## 9. 遇到的问题与处理

| 问题 | 判断 | 处理 | 结果 |
|---|---|---|---|
| 猜错 `/metrics` 文件路径 | 探索假设错误，不是产品错误 | 用符号引用反查真实入口 | 无文件修改 |
| 大时间戳可能依赖科学计数法 | 测试耦合文本格式 | 改为 epoch 123.5 | 断言只验证值 |
| 首个 RED 被 Ruff format 阻止 | pytest 未运行，不能算 RED | 机械改成单行调用后重跑 | 精确 AttributeError |
| RED 校验要求截断文本中出现 0.0 | 外层脚本过度约束 pytest 展示 | 只检查新增断言失败行 | 产品测试不变 |
| integration 长断言不符合 Ruff | 预检查格式问题 | 外层括号格式 | 本机明确 1 skipped |
| 回归补丁命中前一个测试 | 相同上下文导致定位过宽 | 运行前检查并移动 | 错误未进入测试/提交 |
| 预估 509 tests，实际 508 | 把既有测试新增断言误算成新 test | 重新按 test function 计数 | 504+4=508 正确 |
| PowerShell 中文读取乱码 | 未显式指定 UTF-8 | 后续使用 `-Encoding UTF8` + `rg` | 文档判断恢复可靠 |
| 本机没有 `gh` | 工具环境缺失 | 复用 GitHub 公共只读 REST API | 无额外安装 |

所有原生命令后继续显式检查 `$LASTEXITCODE`，没有重现 P2-8 中“format 失败后仍 commit”的问题。

## 10. 验证证据

### 10.1 本地

| 检查 | 结果 | 证据等级 |
|---|---|---|
| `uv lock --check` | 70 packages | `VERIFIED` |
| Ruff format | 261 Python files already formatted | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | app/scripts/integration/concurrency，119 source files | `VERIFIED` |
| P2-9 聚焦 | 22 passed | `VERIFIED` |
| deployment/alert contract | 9 passed | `VERIFIED` |
| 最终非 integration 全量 | 508 passed, 9 deselected in 241.85s | `VERIFIED` |
| 本机真实 Outbox integration | 1 skipped | `NOT_RUN_LOCAL` |
| 正式 500-case/32-arm | 未运行 | `NOT_RUN` |
| 真实 Prometheus/Alertmanager | 未部署、未触发 | `NOT_RUN` |

全量第一次执行也是 508 passed、9 deselected，但发生在“失败保留旧时间”测试强化前。为了让证据
绑定最终代码/测试头，强化后又完整运行一次，最终采用 241.85 秒这一轮结果。

### 10.2 GitHub Actions #34

[GitHub Actions #34](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30774192971)
绑定 head `30d4d372802db0d26778344a10ddbc9e13579f13`：

- `quality-and-integration`：`success`；
- `compose-smoke`：`success`；
- lock、format、lint、strict mypy：success；
- 508 项非 integration：success；
- migration apply：success；
- job claiming/trace/fencing：success；
- blinded human review：success；
- tenant/dataset、artifact ownership、tenant consistency：success；
- readiness、Redis event isolation：success；
- transactional Outbox delivery/replay/retention + P2-9 timestamp integration：success；
- Run idempotency：success；
- P2 downgrade/re-upgrade：success；
- application image：success；
- 完整 Compose build/start/migration/readiness/hardening：success。

failure annotation 步骤显示 skipped，是因为没有失败需要注释；不属于缺失验证。

## 11. 部署与告警解释

### 11.1 应用部署

没有 migration 或新环境变量。滚动部署 API 后，每个新进程的 last-success 初始为 0，直到该实例
第一次被抓取且 PostgreSQL snapshot 成功。Prometheus 必须抓取每个 API 副本，不能随机抓一个
副本再当作全局 refresh health。

### 11.2 Dashboard 使用

展示 backlog 时必须同时展示或约束 freshness，例如：

```promql
outbox_pending
time() - outbox_metrics_last_success_timestamp_seconds
rate(outbox_metrics_refresh_failures_total[10m])
```

不能只看 `outbox_pending == 0` 就宣布没有积压。

### 11.3 Alert 部署

仓库只提供 rule 模板。实际部署前 operator 仍需：

1. 配置 API 多副本 service discovery；
2. 配置 `up == 0` 或等价 target-down 告警；
3. 评估 300 秒阈值是否匹配 scrape interval 与通知 SLO；
4. 用真实 Prometheus rule evaluation 验证；
5. 配置 Alertmanager route、receiver、silence 与 on-call runbook；
6. 做一次受控数据库不可用演练。

## 12. 回滚

本阶段没有数据库 schema 或持久数据变化。回滚顺序：

1. 从 Prometheus 配置移除 `AIEvalOpsOutboxMetricsStale`；
2. 回滚 durable refresh success/failure 接线；
3. 回滚 PlatformMetrics 两个 collector/method；
4. 回滚对应测试和文档。

先移除告警规则可避免应用回滚后表达式查询不到新 metric。缺失 time series 通常不会自动产生
期望的 stale alert，因此不能把“表达式没有结果”误认作健康。

## 13. 残余风险

1. **每进程语义**：Counter 和 timestamp 属于当前 API 进程；多副本必须逐实例抓取。
2. **依赖 wall clock**：timestamp 使用应用传入的 UTC 时间；严重时钟漂移会影响 freshness。
3. **只在 scrape 时刷新**：没有 Prometheus scrape 就没有 refresh；该 metric 不是后台 DB probe。
4. **target-down 另有合同**：应用完全不可抓取时 stale 表达式可能没有 series，需要 `up` 告警。
5. **保留旧 backlog**：失败时旧值仍暴露，这是诊断选择；query/dashboard 必须结合 freshness。
6. **失败只用 Counter 表达**：路由仍静默隔离异常，没有增加包含异常类型的专用安全日志。
7. **Job Gauge freshness 未解决**：P2-9 只处理 Outbox；queue/running/heartbeat 仍依赖 readiness 和
   数据库告警判断旧值。
8. **没有 refresh latency histogram**：能看到失败和 stale，尚不能看到聚合查询逐渐变慢。
9. **告警阈值只是模板**：300 秒/5 分钟没有经过生产 SLO 或 on-call 噪声验证。
10. **真实告警链未运行**：没有 Prometheus server、Alertmanager、通知接收和演练证据。
11. **dead-letter/replay 未决**：pending 仍可能无限重试，权限和产品语义未冻结。
12. **delivered overdue Gauge 未实现**：cleanup 失败可从任务错误/删除量间接判断，没有单独 overdue。
13. **大型表与 cleanup 容量未验证**：普通 `CREATE INDEX`、batch 500、60 秒 cadence 未经过生产规模。
14. **归档/合规未冻结**：7 天已发布 retention 仍需业务和合规确认。
15. **多区域/soak/正式 Gate 未运行**：没有容量、p95/p99、资源曲线或 adoption 结论。

## 14. 面试复述

可这样回答“为什么 backlog Gauge 还要 freshness”：

> `/metrics` 为了保持可抓取，会在数据库短暂失败时返回旧 Gauge。旧值有诊断价值，但不能冒充
> 当前事实，所以我同时暴露最近成功 snapshot 的 Unix 时间和失败 Counter。成功时间只在全部
> Outbox Gauge 更新后写入；失败会计数、保留旧时间并继续返回 200。Prometheus 用自己的时间计算
> freshness，持续五分钟没有成功才告警。这个合同没有高基数 ID，也没有把普通 CI 冒充真实告警
> 部署或容量实验。

## 15. 下一步建议

技术实现已经把 P2-8 明确列出的 Outbox Gauge freshness 风险收口。下一步不应继续猜测产品语义：

1. 由 operator 冻结通知 SLO、dead-letter/max-attempts、replay/ack 权限、归档与合规保留；或
2. 由用户单独明确授权，从最终干净提交重新 prepare 正式 Gate 1，并监督 500-case/32-arm；或
3. 若只继续观测加固，另立范围处理 Job durable Gauge freshness 与真实 Prometheus 演练，不能把
   它们悄悄并入本阶段的 Outbox 合同。

在得到这些选择前，本阶段不生成吞吐、p95/p99、容量 knee、资源曲线或 Worker adoption 结论。
