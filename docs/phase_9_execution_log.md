# Phase 9 执行日志：可观测性、故障与负载实验、项目材料

日期：2026-07-29  
起始 SHA：`51a9ac4`  
可观测性提交：`5af65ca`  
实验工具提交：`36b2baf`
失败证据保留修复：`80ed75e`

## 1. 阶段目标

1. 增加 Prometheus 指标和抓取入口；
2. 增加 OpenTelemetry API/Worker/Reaper/SSE 业务 span；
3. 用 request ID、trace ID 和领域 ID 关联日志；
4. 禁止日志记录凭证、完整问题和答案；
5. 建立 failure-injection 合同；
6. 把真实并发合同提升到 20 并发幂等、100 Jobs/10 Workers/2 Reapers；
7. 提供 500-case、1/2/4/8 Worker 的可复现实验脚本；
8. 提供故障、比较和并发实验脚本，结果拒绝覆盖；
9. 更新 README、架构图、面试问题和简历材料；
10. 真实记录本机无法运行 Docker 实验的阻塞。

## 2. 开始前的设计判断

### 2.1 选择手工 OpenTelemetry SDK span

查阅当前官方 OpenTelemetry Python 文档后确认：

- API/SDK 包用于手工埋点；
- `TracerProvider` 可以由应用直接持有，不必须污染全局 provider；
- production exporter 推荐 OTLP + Collector；
- batching 适合正式导出。

决定：

- API/Worker/Reaper 各自创建 provider；
- 测试注入 `SimpleSpanProcessor + InMemorySpanExporter`；
- 生产可选 OTLP/HTTP + `BatchSpanProcessor`；
- 未配置 endpoint 时不输出 Console 噪声。

没有使用 FastAPI 自动埋点作为唯一方案，因为它无法表达 Target/Evaluator/Result
业务边界。

### 2.2 选择 Prometheus process-local registry

决定：

- 每个进程独立 registry，避免测试和多 app factory 的全局注册冲突；
- API `/metrics`；
- Worker 9101、Reaper 9102；
- tenant/run/job/attempt ID 禁止作为 label；
- queue/running/heartbeat 当前值由 PostgreSQL 聚合刷新。

替代方案是 Prometheus multiprocess mode，但它需要共享目录生命周期、进程清理和
Gunicorn 特定配置，超出本项目当前多角色进程模型，且不能替代每副本 scrape。

### 2.3 Trace 跨进程边界

API 读取 W3C `traceparent`。Worker/Reaper 当前创建新 trace，通过领域 ID 关联。没有
提前宣称“API 到 Worker 是一条完整 distributed trace”，因为 Job 表没有持久化 parent
trace context。

## 3. 计划修改文件

核心：

- `app/core/telemetry.py`
- `app/observability/metrics.py`
- `app/observability/durable.py`
- `app/api/routes_observability.py`
- `app/api/middleware.py`
- `app/workers/worker.py`
- `app/workers/runtime.py`
- `app/events/publisher.py`
- `app/events/sse.py`
- `app/main.py`

实验：

- `scripts/experiment_support.py`
- `scripts/run_load_test.py`
- `scripts/run_concurrency_test.py`
- `scripts/run_failure_scenarios.py`
- `scripts/run_comparison_experiment.py`

测试：

- `tests/api/test_observability.py`
- `tests/unit/core/test_telemetry.py`
- `tests/unit/observability/*`
- `tests/failure_injection/test_fault_matrix.py`
- 并发/集成和既有 Worker/Event 测试。

文档：

- `docs/12_observability_and_experiments.md`
- `docs/13_failure_injection_matrix.md`
- `docs/results/phase_9_environment_and_blockers.md`
- 本执行日志、架构图、面试问题、简历材料、README 和 engineering journal。

## 4. TDD 过程

### 4.1 RED-1：指标和 trace 模块不存在

先新增测试：

- 必需的 13 类指标都能在 registry 文本中出现；
- 指标文本不含 tenant/run/job ID 标签；
- SSE connection 加一/减一；
- 内存 exporter 能看到嵌套 span；
- disabled telemetry 无 trace ID；
- API 延续传入 traceparent；
- Redis failure counter；
- question/answer 日志脱敏；
- observability 配置默认值。

执行结果：4 个 collection error。

```text
ModuleNotFoundError: No module named 'app.observability'
ModuleNotFoundError: No module named 'opentelemetry'
```

结论：失败由功能缺失造成，RED 有效。

### 4.2 GREEN-1：最小指标、trace 与 API 接线

新增并锁定：

- `opentelemetry-api/sdk/exporter-otlp-proto-http 1.44.0`
- `prometheus-client 0.26.0`

实现 process-local registry、Telemetry provider、API middleware、`/metrics`、Redis
failure counter、SSE Gauge 和 Run-created counter。

第一次结果：13 passed，2 failed。

失败 A：stdout 有正确 JSON，但 caplog 为空。根因是应用日志初始化替换 handler。
修正测试读取真实 stdout。

失败 B：SSE subscriber 未关闭。根因是外层 async generator 未关闭内层。加入
`aclosing`。

第二次结果：15 passed。

### 4.3 RED/GREEN-2：Worker span 与 durable Gauge

RED 测试要求 Worker 产生：

- job.claim
- job.process
- target.call
- evaluator.evaluate
- result.persist
- progress.publish

并要求 success counter/case duration；durable SQL 同时统计 queue/running/oldest
heartbeat。

第一次 GREEN 出现两个问题：

- SQL Enum 实际是小写，测试错误预期大写；
- SSE trace helper 再次增加 generator 层，close 传播再次中断。

修正测试的 Enum 预期；移除 helper generator，在 span 内直接 `aclosing`。

结果：10 passed，`mypy` 只剩 SpanProcessor 导出位置问题；改用 1.44.0 公开类型路径后
`mypy app` 通过 88 个文件。

### 4.4 RED/GREEN-3：comparison profile

RED：`MockTarget({"profile": "left"})` 因 extra field 被拒。

GREEN：

- profile 是 1–64 字符、有 pattern 的有界配置；
- case metadata 可提供 `mock_profiles`；
- 选中 profile 后仍由 Pydantic strict validation；
- 通用 `metadata.mock` 作为最后覆盖。

效果：同 Dataset Version 的左右 Run 可以 deterministic 地制造四种 diff。

### 4.5 RED/GREEN-4：数据库单轮故障和实验结果保护

RED：

- runtime 缺少可单测的 `run_worker_iteration`；
- 实验工具必须用 type-7 线性插值；
- result writer 必须拒绝覆盖。

GREEN：

- 抽出单轮边界，ConnectionError 记录 error type 并让 loop 继续；
- 结果 JSON 临时写入后 replace；
- 已存在结果直接失败，不覆盖负面证据；
- API Key 只从环境变量读取。

结果：12 passed，Ruff 和 `mypy app scripts` 通过。

## 5. 实现效果

### 5.1 指标

完整目录见 `docs/12_observability_and_experiments.md`。API scrape 会尽力刷新 durable
Gauge；刷新失败仍返回 process metrics，避免监控入口与依赖同时消失。

### 5.2 Trace

API 延续 W3C context；Worker 对 claim/target/evaluator/persist/publish 分段；Reaper 和
SSE 有独立 span。trace ID 进入结构化日志。

### 5.3 日志安全

新增 question/prompt/input/expected_answer/answer/response/evidence/trace 脱敏字段。
仍明确记录：字段名脱敏不是任意文本 DLP。

### 5.4 并发合同加强

- 同 key 并发 Run 从 2 请求提高到 20；
- 竞争领取从 20 Jobs 提高到 100 Jobs；
- 10 Worker 每个最多 claim 20；
- 成功提交一个后，两个 Reaper 并发回收剩余 99；
- stale heartbeat/result 和唯一 CaseResult 断言保留。

这些是真实 PostgreSQL 测试代码，但本机没有服务，因此运行状态是 skipped。

### 5.5 实验脚本

- load：500 cases，1/2/4/8 Worker；
- concurrency：20 同 key；
- failure：Redis stop/start、Worker kill、cancel、PostgreSQL outage；
- comparison：improvement/decline/new failure/recovery。

脚本存在只证明实验可执行入口已准备，不证明实验已经跑过。

## 6. 最终验证

```text
Python (uv): 3.12.13
uv: 0.11.32
Ruff: All checks passed
mypy app scripts: 96 source files, no issues
pytest non-integration: 230 passed, 6 deselected
pytest integration contract: 6 skipped, 230 deselected
uv lock --check: resolved 60 packages
Alembic: one head 20260729_0007; offline SQL complete
Docker: CommandNotFound
Docker Compose: CommandNotFound
```

## 7. 提交

- `5af65ca feat(obs): add metrics traces and fault telemetry`
- `36b2baf test(experiments): add reproducible phase 9 scenarios`
- `80ed75e fix(experiments): preserve failed run evidence`

文档提交在本日志完成后创建。

## 8. 当前实现能证明什么

- 指标目录、低基数边界、trace parent、Worker span 和日志关联受测试保护；
- SSE 断连释放与 Redis 恢复后新发布受测试保护；
- retry classification、stale fencing SQL、artifact failure cleanup 等合同存在；
- 真实 PostgreSQL 并发测试规模符合 Phase 9 目标。

## 9. 当前实现不能证明什么

- 500-case 吞吐和 p50/p95；
- 1/2/4/8 Worker scaling efficiency；
- PostgreSQL lock wait；
- 真实 Redis/DB outage recovery 时间；
- OTLP Collector 和 Prometheus 多副本抓取；
- cancel/result 的真实数据库竞态结果；
- 生产容量、安全或可靠性。

## 10. 为什么没有采用其他方案

- 没用 tenant/run/job Prometheus label：高基数。
- 没用 Console exporter：会污染 JSON stdout，且不是 trace backend。
- 没把 Redis 变成状态来源：违反 durable correctness。
- 没用 SQLite 跑并发：不能验证 PostgreSQL row lock/constraint。
- 没编造 load 数字：Docker 不存在，任何吞吐都是无证据数字。
- 没把 integration skipped 写成 passed：测试合同与真实执行是两种证据等级。

## 11. 学习清单

建议亲自逐行阅读：

1. `app/api/middleware.py` 的 context extract 和 finally 指标；
2. `app/core/telemetry.py` 的 provider/exporter 生命周期；
3. `app/observability/metrics.py` 为什么不用高基数标签；
4. `app/observability/durable.py` 的 filtered aggregate；
5. `app/workers/worker.py` span 与 lease/result 路径；
6. `app/events/sse.py` 的 `aclosing`；
7. `scripts/run_load_test.py` 如何计算并保存证据；
8. `docs/13_failure_injection_matrix.md` 中 PASS、CONTRACT、SKIPPED、NOT-RUN 的区别。
