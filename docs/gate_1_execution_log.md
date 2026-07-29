# Gate 1 执行日志：500-case Worker 扩展证据工具

状态：`HARNESS_CONTRACT_VERIFIED / FORMAL_500_CASE_NOT_RUN`

分支：`codex/evidence-gate-1`

本日志记录 Gate 1 工具建设，不把单元测试或计划目录误写成容量实验。当前 Windows
主机没有 Docker、PostgreSQL、Redis，因此 32 个正式测量 arm 尚未启动，也没有吞吐、
延迟拐点或推荐 Worker 数。

## 1. 开始前判断

Gate 0 已证明代码合同和远端 CI 基线存在，但旧 `run_load_test.py` 只有一次顺序执行、
一个 workload 和一个扁平 JSON。直接运行它不满足重复、平衡顺序、独立 warm-up、数据库
对账、资源采样或不可覆盖证据目录要求。

本阶段采用 TDD：每个行为先写一个可观察的失败合同，只做使该合同通过的最小修改，再运行
相关回归。正式外部适配层无法在本机连接真实服务，因此只声明严格类型和纯逻辑合同通过；
真实连接仍为 `NOT_RUN`。

## 2. 并发任务冲突与处理

开始时发现另一个 Codex 任务正在同一工作目录、同一分支修改 Gate 1 文件。两个任务若继续
并发，可能覆盖测试和协议。处理方式：

1. 查询任务状态，确认它已完成若干 prepare-only TDD 切片；
2. 要求其完成当前切片后暂停，不提交、不推送；
3. 保留其 Gate 0 复验证据和 Gate 1 未提交代码；
4. 本任务统一协议冲突并继续。

没有删除另一任务的文件。Gate 0 第二次复验证据单独提交为 `a1812d6`，避免与 Gate 1
生产/测试变更混在一起。

## 3. 协议判断：为什么默认 4 次而不是 3 次

原始要求是“至少 3 次”。另一份草案写 3 次、24 arms；已确认的主审计日志建议 4 次，
因为 1/2/4/8 四个 Worker 数可以在每个 workload 的四个顺序位置各出现一次。

最终决定：

- 默认 4 次、2 workloads、32 measured arms；
- 使用四个平衡顺序；
- workload/repetition block 用记录的 seed 和 SHA-256 确定顺序；
- 显式 `--repetitions 3` 仍受支持，生成 24 arms，并拒绝连续三个相同 Worker 数；
- 不允许观察结果后重排。

这比“随机打散三次”更能控制顺序位置偏差，同时仍满足“至少三次”。

## 4. RED → GREEN 记录

### 4.1 版本化 workload 名称

观察：arm plan 使用 `io_latency_v1`/`transient_5pct_v1`，Dataset metadata 仍使用旧名称。
正式运行会在计划生成成功后找不到 case profile。

- RED：Dataset 合同预期版本化名称，实际得到旧名称；
- 修复：Dataset 和 3-repeat 兼容计划统一使用版本化名称；
- GREEN：两个定向测试各 `1 passed`。

### 4.2 独立 warm-up Dataset

判断：不能复用 500-case measurement Dataset，否则容易把 warm-up 混入统计或幂等空间。

- RED：`dataset/warmup.jsonl` 不存在；
- 修复：生成 50 个 `warmup-*` case，和 500 个 `load-*` ID 不重叠；
- 每个文件保存 byte count、case count、SHA-256；
- GREEN：文件、哈希、ID 隔离合同 `1 passed`。

50 cases 是受控启动成本，不是测量结果；正式汇总明确排除。

### 4.3 不可覆盖证据目录

- RED：`raw/summary/failures/plots` 不存在；
- 修复：run ID 目录使用 create-new，预建四个证据目录；
- `JsonlEvidenceWriter` 使用文件模式 `x`，逐条 flush，已有文件拒绝覆盖；
- GREEN：目录合同与 JSONL 写入合同通过。

Windows 旧 `.pytest-tmp` ACL 会拒绝删除。所有测试改用独立 basetemp；本轮产生的
`.pytest-tmp-gate1-*` 同样无法删除，因此 `.gitignore` 从只忽略 `.pytest-tmp/`
扩展到 `.pytest-tmp*/`。没有提权、改 ACL 或强删。

### 4.4 PostgreSQL correctness reconciliation

API case 列表缺少完整 Job/Attempt 时序，不能独立证明持久化唯一性。新增纯对账函数，输入
只读 PostgreSQL 快照并检查：

- 实际 Job 数是否等于协议期望；
- 每个 succeeded Job 是否恰好一个 CaseResult；
- `job_id` 和 `(run_id, case_id)` 两个维度是否重复；
- Run counters 是否等于 fresh Job group-by；
- 是否残留 queued/running/retry_wait/cancelling；
- Run 终态是否与 Job 聚合一致；
- Attempt 编号是否从 1 连续到 `attempt_count`；
- Dataset Version ID、Dataset SHA、target/evaluator config hash、source commit 是否匹配。

每个错误产生稳定 violation code。任何 violation 都使 arm
`valid_for_capacity_comparison=false`，但不删除证据。

对应 RED 分别表现为缺少结果、计数/终态不一致、Attempt `[1,3]`、499/500 行和来源哈希
不一致；最终 9 个对账/汇总测试通过。

### 4.5 指标“缺测不能写 0”

汇总合同固定：

- 有原始数值序列才输出 `VERIFIED` p50/p95/p99；
- PostgreSQL lock wait 是一秒采样时输出 `DIRECTIONAL`，不伪造成连续毫秒；
- 没有采样输出 `UNKNOWN` 和 `value: null`；
- stale submission 没有主动诱发时输出 `NOT_TESTED`，即使观察值为 0；
- 首次 queue wait 与 retry queue wait 分开；
- 所有重复点、median/min/max 和负扩展差值都保留；
- `automatic_adoption_decision` 固定为 `null`。

### 4.6 claim/result/failure/reaper 数据库耗时

观察：已有 trace span，但 Prometheus 没有可由实验采集器稳定抓取的事务耗时。

新增：

```text
db_operation_duration_seconds{operation="claim|result|failure|reaper"}
```

标签集合固定，不允许 tenant/run/job/attempt ID。计时包在已有 await 调用外层的
`perf_counter()`/`finally` 中，不修改事务、异常、锁、lease、retry 或提交顺序。

RED：Metrics 注册表没有方法；随后 Worker/Reaper 接线测试看不到对应 count。

GREEN：

- Metrics 合同通过；
- Worker claim/result/failure 路径通过；
- Reaper 单次迭代通过；
- 相关定向回归 23 passed。

### 4.7 Docker、PostgreSQL 与 Prometheus collectors

新增工具：

- Docker stats JSON 解析，保留原值并统一 CPU 百分比、RSS/limit bytes；
- 未知单位报 `CollectorParseError`，不写 0；
- PostgreSQL 一秒采样 active/idle/idle-in-transaction 与 lock waiter count；
- 同一只读 repeatable-read 事务读取 Run/Job/Attempt/CaseResult；
- 每个 API/Worker/Reaper 容器分别保存 Prometheus before/after 原文；
- cumulative counter/histogram 只在同一容器 ID 上做 delta；
- 容器集合改变或 counter 倒退会使 arm 失败；
- CPU/RSS 同时输出全局和逐容器峰值。

Prometheus histogram bucket 推导标为 `DIRECTIONAL`。Redis publication failure 使用
per-container counter delta，仍以 PostgreSQL durable state 作为正确性事实。

### 4.8 preflight 与执行状态机

`--prepare-only`：

- 只生成协议、Dataset、arm order、manifest 和空证据目录；
- manifest 保存源码 commit、原 Compose 文件 SHA、协议 SHA、seed、采样间隔和采用门槛；
- 不创建服务端 Dataset，不缩放容器，不启动 formal run。

`--execute-prepared`：

- 要求安全 run ID；
- 验证 source commit、tracked worktree、Docker/Compose、服务健康、20 GiB 磁盘、
  API Key/DB URL 的“存在性”、质量门槛确认和采用门槛确认；
- 只保存渲染后 Compose SHA，不保存可能含密码的正文；
- 保存 Docker/Compose 版本、镜像 ID、OS/Python/CPU/磁盘；
- blocker 全部写入 `failures/preflight.json`，`raw/` 保持空；
- 通过后按冻结 arm order 执行；
- 每次 scale 后验证恰好 N 个 Worker、核心服务健康、全局非终态队列为空；
- warm-up 先做完整 PostgreSQL 对账；
- measured arm 才启动 collectors；
- 失败立即停止后续 arm，并只记录 exception type，不记录可能含秘密的异常消息。

## 5. 输出

完成的正式 run 设计为：

```text
<run_id>/
  manifest.json
  protocol.md
  preflight.json
  execution.json
  dataset/
  arm_order.json
  raw/<arm_id>/
  summary/<arm_id>.json
  summary/aggregate.json
  summary/arms.csv
  failures/index.json
  plots/
```

当前没有 Matplotlib/Pillow。为避免给后端项目引入大型运行时依赖，且没有正式数据，本阶段
没有生成空白或伪造 PNG。正式图表仍是已知未闭合项；必须在正式主机冻结可复现的绘图工具
后生成，或把协议改为无需外部依赖的 SVG 并经用户确认。未生成图表状态为 `NOT_RUN`。

## 6. 遇到的问题

1. 仓库级 `uv` 首次使用用户缓存，被沙箱拒绝；改用项目内
   `.codex-tools/cache` 后继续。
2. 默认 `.pytest-tmp` 和本轮独立临时目录存在 Windows ACL 删除拒绝；使用每次唯一
   basetemp 完成测试，并忽略临时目录。
3. 两个 Codex 任务曾共享目录；暂停另一个任务后统一协议，没有并发提交。
4. 初始 Dataset 测试本身一处筛选键仍是旧名称；先修正测试内部矛盾，再得到真实 GREEN。
5. 格式检查多次报告机械换行；运行 Ruff formatter 后复查。
6. 本机没有 Docker/PostgreSQL/Redis，因此数据库查询、Compose scale、per-replica scrape
   和 32-arm 正式矩阵无法运行。

## 7. 当前验证结果

- `uv lock --check`：60 packages resolved；
- Ruff lint：All checks passed；
- Ruff format：213 files already formatted；
- mypy strict：108 source files，无问题；
- 非 integration：260 passed、6 deselected；
- Gate 1 collectors/preflight/reconciliation/experiment/metrics/worker 定向回归：
  35 passed；
- 正式 500-case：`NOT_RUN`；
- 真实 PostgreSQL collector：`NOT_RUN`；
- Docker scale/health/resource scrape：`NOT_RUN`；
- required PNG plots：`NOT_RUN`。

## 8. 已达到与未达到

已达到：

- 可复现的 500/50 Dataset 和哈希；
- 默认 32-arm 位置平衡顺序；
- create-new 证据目录；
- preflight fail-closed；
- PostgreSQL 独立 correctness reconciliation；
- bounded Prometheus database-operation metrics；
- Docker/PostgreSQL/Prometheus 原始采集接口；
- per-arm 与跨重复汇总保留负扩展；
- 不自动改变 Worker 数。

未达到：

- 没有正式吞吐、p95/p99、queue/claim/lock、CPU/RSS 或连接曲线；
- 没有证明正式适配层能在当前主机连接服务；
- 没有绘图产物；
- 没有生产容量结论；
- 没有 exactly-once、故障恢复、soak、SSRF、跨进程 trace 或真人双评结论。

只有在独占 Docker 主机满足 preflight、用户明确确认两个 gate，并完成 dry run/绘图工具冻结
后，才能启动正式矩阵。
