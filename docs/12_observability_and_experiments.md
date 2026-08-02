# 可观测性与实验合同

## 1. 本阶段解决的问题

异步评测的 HTTP 请求在 Run 创建后已经结束，实际工作发生在另一个 Worker
进程，崩溃恢复又由 Reaper 完成。只看 API access log 无法回答以下问题：

- 请求是否真的创建了一个新 Run，还是命中了幂等重放；
- Job 卡在排队、执行、重试，还是 lease 已经失效；
- 慢点在 Target、Evaluator，还是结果提交；
- Redis 发布失败是否影响 PostgreSQL 最终状态；
- SSE 长连接是否释放；
- 多 Worker 扩容是否真的提高吞吐，还是增加锁竞争。

Phase 9 使用三类互补证据：

1. 结构化日志用于离散事件和安全摘要；
2. Prometheus 指标用于聚合趋势和告警；
3. OpenTelemetry trace 用于一次执行内部的时序关系。

PostgreSQL 仍是 Run、Job、Attempt 和 Result 的最终事实来源。指标、日志和
trace 都不能反向决定领域状态。

## 2. 设计判断

### 2.1 为什么显式业务 span，而不是只开 FastAPI 自动埋点

框架自动埋点能看到一个 HTTP 请求，却不知道 `target.call`、`evaluator.evaluate`
和 `result.persist` 的业务边界。本项目采用 OpenTelemetry SDK 手工创建 span：

- `api.request`
- `run.create`
- `run.create.database_transaction`
- `job.claim`
- `job.process`
- `target.call`
- `evaluator.evaluate`
- `result.persist`
- `failure.persist`
- `progress.publish`
- `reaper.recover_expired_leases`
- `reaper.job.recovered`
- `sse.connection`

API middleware 从 `traceparent` 提取 W3C Trace Context，所以调用方传入的合法
trace ID 会延续到 API 子 span 和日志。首次创建 Run 时，平台把当前 `run.create` span
注入的 version 00 `traceparent` 保存到 `evaluation_runs.origin_traceparent`。只保存这个
carrier，不保存 baggage、tracestate、HTTP header 全集、凭据或请求内容。

Worker 的每次 `job.process` 仍创建独立 root trace，并用 Span Link 指向 Run 创建 span；
retry 通过不同 `attempt.id`、`attempt.number` 和 root trace 区分。Reaper batch 可能包含多个
Run，所以 batch span 不绑定单个来源；每个 `reaper.job.recovered` 创建独立 linked root，
event publish 是其 child。`job.claim` 在知道 claim 结果前开始，同样保持独立。

这是刻意选择的异步 fan-out 语义，不是把数小时排队/retry 伪装成一个同步 parent-child 大
trace。tenant/run/job/attempt/worker ID 仍是 durable identity，Span Link 只用于 observability，
不能参与授权、tenant、claim、retry 或幂等判断。历史 Run、disabled telemetry 和非法 carrier
安全退化为无 Link，业务继续执行。

### 2.2 为什么 Prometheus 不使用 tenant_id/run_id/job_id 标签

这些 ID 数量无界。如果作为标签，每一个 Job 都会创建新的 time series，最终造成
高基数和 Prometheus 内存压力。因此指标只使用有界标签：

- API：method、规范化 route、status；
- 其余第一版指标：无标签。

tenant/run/job/attempt/worker ID 放入日志和 trace attribute，而不是指标标签。

### 2.3 为什么每个进程使用独立 registry

API、Worker、Reaper 是不同操作系统进程，Python 全局内存不共享。每个进程拥有
独立 `CollectorRegistry`：

- API：`GET /metrics`；
- Worker：内部端口 9101；
- Reaper：内部端口 9102。

多 Worker 部署时，Prometheus 必须抓取每一个副本并在查询端汇总 counter。不能只
抓一个随机 Worker 再把它当成全局值。

### 2.4 为什么队列和心跳 Gauge 从 PostgreSQL 刷新

`job_queue_depth`、`job_running` 和 `worker_heartbeat_age` 是当前状态，不适合只靠
进程内增减维护。API `/metrics` 抓取前执行一个聚合查询：

- queued + retry_wait 计入 queue depth；
- running + cancelling 计入 running；
- running/cancelling 中最老 heartbeat 计算最大 age。

查询失败时 `/metrics` 仍返回进程指标和上次 Gauge 值，以免监控入口因数据库短暂
故障完全消失。运维必须同时观察 readiness 和数据库告警，不能把旧 Gauge 当成新
事实。

## 3. 指标目录

| 指标 | 类型 | 写入位置 | 语义 |
|---|---|---|---|
| `api_request_total` | Counter | API middleware | 已完成 HTTP 请求 |
| `api_request_duration` | Histogram | API middleware | HTTP 请求秒数 |
| `run_created_total` | Counter | Run service | 真正提交的新 Run；幂等重放不增加 |
| `job_queue_depth` | Gauge | API durable refresh | queued + retry_wait 当前数 |
| `job_running` | Gauge | API durable refresh | running + cancelling 当前数 |
| `job_succeeded_total` | Counter | Worker | 本进程成功提交的 Job |
| `job_failed_total` | Counter | Worker/Reaper | 本进程永久失败的 Job |
| `job_retry_total` | Counter | Worker/Reaper | 本进程提交的重试转换 |
| `job_lease_expired_total` | Counter | Reaper | 本进程回收的过期 lease |
| `worker_heartbeat_age` | Gauge | API durable refresh | 最老活跃 heartbeat 秒数 |
| `case_duration` | Histogram | Worker | Target + Evaluator 秒数 |
| `sse_connections` | Gauge | SSE generator | 当前打开的 SSE iterator |
| `redis_publish_failures_total` | Counter | Redis publisher | best-effort 发布失败 |

Prometheus Python Client 会为 Counter 暴露 `_total` 后缀，因此逻辑名称
`redis_publish_failures` 的文本格式名称是 `redis_publish_failures_total`。

## 4. 日志合同

适用时记录：

- `request_id`
- `trace_id`
- `tenant_id`
- `run_id`
- `job_id`
- `attempt_id`
- `worker_id`
- `event`
- `duration_ms`
- `outcome`
- `error_code`

按字段名递归脱敏：

- API key、Authorization、密码、数据库/Redis URL、token、secret；
- question、prompt、input、expected_answer、answer、response、evidence、trace。

该策略依赖调用者正确命名字段。它不是任意文本的 DLP 引擎，所以代码审查仍必须
阻止把秘密拼进 `message`、普通字符串或异常文本。

## 5. 配置和抓取

主要配置：

```text
EVALOPS_METRICS_ENABLED=true
EVALOPS_METRICS_HOST=0.0.0.0
EVALOPS_WORKER_METRICS_PORT=9101
EVALOPS_REAPER_METRICS_PORT=9102
EVALOPS_OTEL_ENABLED=true
EVALOPS_OTEL_SERVICE_NAME=ai-evalops-platform
EVALOPS_OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318/v1/traces
```

OTLP endpoint 不配置时仍创建 SDK span 和 trace ID，但不会把 span 发往外部后端。
生产环境应把 OTLP/HTTP endpoint 指向 OpenTelemetry Collector，而不是把 Console
exporter 当成长期存储。

API 抓取：

```bash
curl http://127.0.0.1:8000/metrics
```

Worker/Reaper 端口只在 Compose 网络中 `expose`，默认不发布到宿主机。

## 6. 可复现实验入口

所有脚本从 `EVALOPS_EXPERIMENT_API_KEY` 读取密钥，不接受命令行明文密钥，避免密钥
进入 shell history 和进程列表。

### Worker 扩容

```bash
uv run python -m scripts.run_load_test
```

默认创建 500 个 synthetic case，依次扩缩到 1/2/4/8 Worker，记录：

- wall time；
- cases/s；
- case latency p50/p95；
- duplicate case count；
- retry count；
- failure count。

### 幂等并发

```bash
uv run python -m scripts.run_concurrency_test
```

默认 20 个并发请求使用同一个 Idempotency-Key，并保存 status code、唯一 run ID 数量
和 5xx 数量。真实 PostgreSQL 集成合同也使用 20 个并发请求。

### 故障注入

```bash
uv run python -m scripts.run_failure_scenarios --allow-service-disruption
```

该命令会停止/杀死开发 Compose 服务，只能用于独占的本地实验环境。场景包括：

- Redis 中断后 Worker durable path 继续，恢复后新 Run 继续发布；
- Worker claim 后被 kill，lease 到期后由 Reaper 和新 Worker 接管；
- running Job 中途取消；
- PostgreSQL 中断时 liveness/readiness 分离。

### Run 比较

```bash
uv run python -m scripts.run_comparison_experiment
```

同一 Dataset Version 的四个 synthetic case 分别制造 improvement、decline、
new failure 和 recovery，然后保存完整 case-level comparison。

结果文件默认写到 `docs/results/`，并拒绝覆盖已有文件。失败结果不能通过重跑覆盖；
应改用新的输出文件名保留每次证据。

## 7. 当前实现能证明和不能证明什么

能证明：

- 指标名称、label 边界和文本暴露有自动化测试；
- W3C 传入 trace ID 能进入 API 日志；
- Run 创建 carrier 只保存平台 span 的 traceparent，幂等 replay 不覆盖首次来源；
- Worker/Reaper linked root 和内部业务 span 父子关系有 in-memory exporter 自动化测试；
- SSE 关闭会归零连接 Gauge 并关闭底层 subscriber；
- Redis 第一次失败、恢复后第二次发布可继续；
- 数据库单次迭代异常被记录后 Worker loop 可继续下一轮；
- 20 并发幂等和 100 Job/10 Worker/2 Reaper 的真实 PostgreSQL 测试合同已编码。

不能证明：

- 本机没有 Docker/PostgreSQL/Redis，真实并发和容量结果未执行；
- 没有 Collector/trace backend，无法证明 OTLP 网络导出和后端查询；
- 没有 Prometheus server，无法证明多副本 service discovery 和告警规则；
- API 与 Worker/Reaper 按设计不是同一个 trace；没有真实 backend 证据证明 Span Link 在目标
  UI、采样和保留策略下可查询，历史 NULL carrier 也不会被反向补齐；
- 没有生产流量、长时间 soak test、DB lock wait 和资源上限数据；
- 项目没有通过生产可靠性、安全或性能认证。

## 8. 未采用的方案

- **只用日志**：无法低成本做百分位、趋势和告警。
- **只用自动框架埋点**：看不到业务流水线内部边界。
- **tenant/run/job 作为指标标签**：高基数风险不可接受。
- **Worker 继续 API parent**：会把长时间排队、fan-out 和 retry 合并成超大 trace；采用新
  root + Span Link 表达异步因果。
- **Redis 保存 durable 指标状态**：违反 PostgreSQL 最终事实来源。
- **在本机伪造负载结果**：脚本存在不等于实验执行，违反证据要求。

实现参考 OpenTelemetry Python 的手工埋点与 exporter 建议，以及 Prometheus Python
Client 的 ASGI/registry 接口。版本由 `uv.lock` 固定。
