# Phase 9 执行日志：可观测性、故障与负载实验、项目材料

日期：2026-07-29

起始 SHA：`51a9ac4`

可观测性提交：`5af65ca`

实验工具提交：`36b2baf`
失败证据保留修复：`80ed75e`
指标/取消竞态合同：`eff9b2e`

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
mypy app scripts tests/integration tests/concurrency: 103 source files, no issues
pytest non-integration: 235 passed, 6 deselected
pytest integration contract locally: 6 skipped, 235 deselected
uv lock --check: resolved 60 packages
Alembic: one head 20260729_0008; offline SQL complete
Docker: CommandNotFound
Docker Compose: CommandNotFound
GitHub Actions Run #7: 235 non-integration + 6 real-service contracts passed
GitHub Actions Compose smoke: image, migration, API/Worker/Reaper, readiness passed
```

## 7. 提交

- `5af65ca feat(obs): add metrics traces and fault telemetry`
- `36b2baf test(experiments): add reproducible phase 9 scenarios`
- `80ed75e fix(experiments): preserve failed run evidence`
- `eff9b2e test(obs): cover metric replay and cancel race`

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
- cancel/result 的真实数据库竞态合同已编码，但本机没有执行结果；
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

## 12. GitHub 首次发布后的 CI 诊断与修复

仓库首次推送后没有把“push 成功”当成完成，而是继续读取公开仓库和 Actions 的实际状态。
最终成功运行是
[Run #7](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30425559361)，
提交 `06dc670`。

### 12.1 Run #1：工作流在创建 job 前失败

- 现象：workflow conclusion 是 failure，但 API 返回 `0 jobs`，创建与结束时间相同。
- 假设：YAML 能解析，但 job 级表达式语义无效。
- 反馈循环：下载并校验官方 `actionlint v1.7.12`，对原 `ci.yml` 执行检查。
- 根因：job 级 `env` 使用 `${{ runner.temp }}`；Runner 尚未分配时该 context 不可用。
- 修复：改用该 Ubuntu job 的明确路径 `/tmp/evalops-artifacts`。
- 效果：提交 `2cee9f5` 后 Actions 正常创建两个 job。

### 12.2 Run #2–#4：把分组失败变成可定位证据

- Run #2 已通过 format、lint、mypy、231 个非集成测试和 migration，但集成测试组与
  `docker compose up --build --wait` 失败。
- 将 6 个真实合同拆成具名步骤，并把 Docker build 与 Compose start 分开；同时删除
  会重复执行 `tests/concurrency` 的旧步骤。
- 结果证明 Docker image build 成功，失败边界在真实 PostgreSQL 写路径与 Compose
  topology-wide wait。
- 匿名 GitHub API 不能下载完整 job logs，因此新增受单元测试保护的
  `scripts/ci_annotations.py`：读取 JUnit/Compose 诊断、转义 workflow command、限制
  长度并生成公开 error annotation。
- GitHub annotation 硬限制为 4096 字符；工具最终使用 3500 字符并保留头尾，避免异常
  摘要或底层数据库错误被截掉。

### 12.3 Run #4–#6：修复 fixture、Compose 与过期断言

- 三个合同使用不存在的 `GeneratedAPIKey.key_prefix`，真实字段是 `.prefix`。
- 多个集成 fixture 同一 flush 插入 parent/child，但 ORM 未声明 relationship 排序；
  按生产脚本做法显式分层 flush。
- 将 CI mypy 扩展到 app、scripts、integration 和 concurrency，共 103 个源文件，
  防止测试字段漂移再次只在运行时暴露。
- topology-wide `docker compose up --wait` 会把正常退出的 one-shot `migrate` 当作
  非运行服务；改为依赖健康、单独 migration、长运行进程、readiness 四阶段。
- 10 Worker 已领取全部 100 Jobs，因此 Attempt 正确数量是 100；旧断言 20 来自早期
  规模，修正测试而不是改坏领取实现。
- 效果：Compose smoke 全绿，身份/数据集、readiness、Redis 和 Run 幂等合同转绿。

### 12.4 Run #6–#7：真实 schema 缺陷与最终闭环

- 人工评审 packet 写入报 `value too long for type character varying(14)`。
- 根因：Phase 8 扩展 artifact CHECK 约束允许 19 字符 `human_review_packet`，但初始
  Enum 列仍是按最长旧值生成的 `VARCHAR(14)`。
- 没有篡改已经发布的 `0007`，而是新增 `20260729_0008` 将列安全扩宽为
  `VARCHAR(32)`；offline SQL 明确生成对应 `ALTER COLUMN`。
- cancel/result race 的第二组 fixture 也在 Run 后补显式 flush。
- Run #7 中两个 job 均成功：235 个非集成测试、6 个真实服务合同、Docker build、
  Compose migration/start/readiness 全部通过。

### 12.5 证据边界

- CI 证明真实 PostgreSQL/Redis 合同和一次 Compose smoke 成功。
- CI 不提供 500-case 1/2/4/8 Worker 吞吐、p50/p95、lock wait、故障恢复时间或 soak
  结论。
- 因此负载与故障实验仍保持 NOT-RUN，不能把合同通过改写成生产容量认证。

### 12.6 最终文档提交前的本机复验插曲

- 新开的 PowerShell 执行上下文没有在 `PATH` 中找到此前使用的 `uv`。这不说明项目
  缺少依赖，也不适合为了最后一次检查重新安装工具；因此直接调用仓库现有
  `.venv/Scripts` 中的 Ruff、mypy、pytest 和 Alembic 可执行文件。
- 第一次 pytest 复验得到 222 passed、13 errors；全部 error 都发生在 `tmp_path`
  fixture 清理旧 `.pytest-tmp` 时，错误为 Windows `PermissionError`，没有测试断言
  失败。判断这是旧临时目录的 ACL/占用问题，而不是修改代码来掩盖它。
- 使用明确的新系统临时目录覆盖 `--basetemp` 后重新执行同一非集成测试集，结果为
  235 passed、6 deselected。Ruff、mypy、Alembic head/offline SQL 也全部通过。
- 文档本地链接另做只读扫描：27 个仓库内 Markdown 链接全部存在。

这一插曲的效果是保留了可重复的失败证据，同时通过单变量复验确认根因；项目文件没有
为适应当前机器的临时目录权限而引入不必要改动。
