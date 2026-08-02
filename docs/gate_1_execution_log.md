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

- 从干净 Docker build context 构建并 inspect `ai-evalops-platform:phase9`，冻结本地
  `sha256:...` image ID、OCI/build-input 标签和 Python/OS/architecture；
- 构建成功后才生成协议、Dataset、arm order、manifest 和空证据目录；
- manifest 保存源码 commit、原 Compose 文件 SHA、Dockerfile/context SHA、image
  repository/tag/immutable ID、构建时间、协议 SHA、seed、采样间隔和采用门槛；
- 不创建服务端 Dataset，不缩放容器，不启动 formal run。

`--execute-prepared`：

- 要求安全 run ID；
- 验证 source commit、tracked worktree、Docker/Compose、服务健康、20 GiB 磁盘、
  API Key/DB URL 的“存在性”、质量门槛确认和采用门槛确认；
- inspect Compose 列出的具体 API/Worker/Reaper 容器，逐一核对 immutable image ID、
  revision、Compose project、Dockerfile/context 标签；
- 只保存渲染后 Compose SHA，不保存可能含密码的正文；
- 保存 Docker/Compose 版本、镜像验证状态与经筛选的容器身份、OS/Python/CPU/磁盘；
- blocker 全部写入 `failures/preflight.json`，`raw/` 保持空；
- 通过后按冻结 arm order 执行；
- 每次 scale 后验证恰好 N 个 Worker、核心服务健康、全局非终态队列为空；
- warm-up 先做完整 PostgreSQL 对账；
- measured arm 才启动 collectors；
- 失败立即停止后续 arm，并只记录 exception type，不记录可能含秘密的异常消息。

### 4.9 可复现 PNG 图表

观察：执行器已经能写 `aggregate.json` 和 `arms.csv`，但 `plots/` 永远为空。仅预建目录不能
满足正式证据输出；同时不能为了“看起来完成”生成空白图或把缺测值画成 0。

判断：

- Matplotlib 放入 `dev` dependency group，而不是生产 dependencies；
- `uv.lock` 冻结实际版本，Dockerfile 的 `UV_NO_DEV=1` 继续排除它；
- 正式执行器使用延迟导入，普通生产脚本导入不依赖绘图库；
- 一个公开入口一次写 aggregate、CSV、五张 PNG 和图表 manifest；
- manifest 保存所有 arm 原始绘图点、证据等级、折线分组、renderer 版本、backend 和 DPI；
- 图只连接同一 workload、同一 repetition，并按 Worker 数排序；
- case latency/end-to-end、CPU/RSS 分别使用双 y 轴；
- 任一目标文件已存在时，在开始绘图前整体拒绝。

TDD 与问题记录：

1. RED：`scripts.gate1_plots` 不存在；GREEN：生成五张带 PNG signature、大小超过 1 KiB
   的图和 manifest。
2. RED：后面的 `database.png` 已存在时，旧实现会先写前三张图，再抛
   `FileExistsError`；GREEN：预检全部六个目标并统一抛 `ExperimentError`，没有部分写入。
3. RED：finalization 遇到旧图时已先写 aggregate/CSV；GREEN：入口预检两张表和全部图表
   目标，在第一个写操作前拒绝。
4. RED：正式汇总入口不存在；GREEN：`finalize_gate1_run_evidence` 同时生成表格和图。
5. RED：随机 arm 顺序没有可审计的 repetition 分组；GREEN：manifest 保存
   `line_series`，绘图共用同一有序分组。
6. RED：manifest 没有 renderer provenance；GREEN：保存 Matplotlib 版本、`Agg` 和
   144 DPI。
7. 视觉抽查第一次发现 end-to-end 数万毫秒把几十毫秒 case latency 压平；改为双 y 轴。
8. 第二次视觉抽查发现 RSS 接近时自动 offset 难读；关闭 offset，并固定 x 轴为实际 Worker
   刻度。

合成预览仅用于验证版式，没有放入 `docs/results/`，也不作为容量证据。正式 PNG 只有完成
真实 32-arm 后才会出现。

## 5. 输出

P1-3 原子发布加固后，run 根目录与正式 bundle 的边界为：

```text
<run_id>/
  manifest.json
  protocol.md
  preflight.json
  execution.json
  dataset/
  arm_order.json
  raw/<arm_id>/                  # 执行期工作证据
  summary/<arm_id>.json          # 执行期工作证据
  failures/index.json
  plots/                         # prepare 时预建；不是正式发布标志
  final/                         # 只有该目录整体出现才表示正式发布
    manifest.json                # final-bundle schema v1 + 全部 payload SHA-256
    raw/<arm_id>/
    summary/<arm_id>.json
    summary/aggregate.json
    summary/arms.csv
    plots/manifest.json
    plots/throughput.png
    plots/latency.png
    plots/queue_and_claim.png
    plots/database.png
    plots/cpu_and_rss.png
```

根级 `raw/` 与 per-arm `summary/` 允许逐步形成，因为它们是工作区；跨 arm 表格和图只在
同文件系统 staging 中生成。所有 payload 的文件数、schema、arm 引用、字节数和 SHA-256
复验通过后，staging 才以一次目录重命名发布为 `final/`。已有 partial/complete `final/`
一律拒绝覆盖；失败会清理 staging。

绘图工具合同已闭合，Matplotlib 3.11.1 由 `uv.lock` 固定在 dev 组。当前仍没有正式
32-arm 数据，所以正式 `final/plots/*.png` 是 `NOT_RUN`；单元测试生成的合成图只证明
渲染和原子发布合同，不证明任何容量结果。

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
7. 新会话最初在 `PATH` 中找不到 `uv`；这不是产品 RED。定位到项目级
   `.codex-tools/Scripts/uv.exe` 后，用绝对路径管理依赖和锁文件。
8. Matplotlib 初版类型检查发现 selector 二次调用后仍可能为 `None`，以及含默认参数的
   lambda 无法推断；改为单次取值和显式 selector 工厂后 strict mypy 通过。
9. 合成图视觉抽查发现双量级同轴与 RSS offset 问题；修正后重新生成并复查。

## 7. 当前验证结果

- `uv lock --check`：70 packages resolved；
- Ruff lint：All checks passed；
- Ruff format：216 files already formatted；
- mypy strict：109 source files，无问题；
- 非 integration：265 passed、6 deselected；
- Gate 1 collectors/preflight/reconciliation/experiment/metrics/worker 定向回归：
  41 passed；
- Gate 1 plot 公开产物合同：5 passed；
- 正式 500-case：`NOT_RUN`；
- 真实 PostgreSQL collector：`NOT_RUN`；
- Docker scale/health/resource scrape：`NOT_RUN`；
- required PNG renderer：`CONTRACT_VERIFIED`；
- 正式数据 PNG plots：`NOT_RUN`。

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
- create-new 的五图 bundle、机器可审计 manifest 和正式执行器接线；
- 不自动改变 Worker 数。

未达到：

- 没有正式吞吐、p95/p99、queue/claim/lock、CPU/RSS 或连接曲线；
- 没有证明正式适配层能在当前主机连接服务；
- 没有正式数据绘图产物；合成预览不算实验结果；
- 没有生产容量结论；
- 没有 exactly-once、故障恢复、soak、SSRF、跨进程 trace 或真人双评结论。

只有在独占 Docker 主机满足 preflight、用户明确确认两个 gate，并完成服务级 dry run 后，
才能启动正式矩阵。绘图工具冻结已经完成，但没有消除基础设施 blocker。

## 9. 提交后 prepare-only 与 preflight 实证

工具代码提交：

```text
c72e8c5c2ca0ab5610e3ee7a0d131bfe437ffa00
feat(eval): build evidence-first worker scaling harness
```

在 tracked worktree 干净时实际执行：

```text
python -m scripts.run_load_test \
  --prepare-only \
  --output-root docs/results/gate_1 \
  --run-id gate1-plan-c72e8c5-20260729T150959Z
```

生成结果：

- manifest status：`prepared`；
- `formal_run_started=false`；
- source commit：`c72e8c5c2ca0ab5610e3ee7a0d131bfe437ffa00`；
- protocol SHA：重新计算匹配；
- measurement：500 行，SHA 重新计算匹配；
- warm-up：50 行，SHA 重新计算匹配；
- arm algorithm：`position-balanced-v1`；
- arm count：32；
- prepare 后 raw entry count：0。

随后带两个确认 gate 执行 `--execute-prepared`。preflight 结果：

- `source_commit_matches=true`；
- `tracked_worktree_clean=true`；
- `quality_gate_confirmed=true`；
- `adoption_gate_confirmed=true`；
- `docker_cli_available=false`；
- `compose_config_valid=false`；
- `required_services_healthy=false`；
- `api_key_present=false`；
- `database_url_present=false`；
- `ready=false`；
- preflight 后 raw entry count 仍为 0。

因此执行器只保存
`docs/results/gate_1/gate1-plan-c72e8c5-20260729T150959Z/failures/preflight.json`，
没有上传 Dataset、缩放 Worker 或启动任何 arm。该失败证明 fail-closed 状态机生效，不是
正式容量实验失败。

## 10. 图表工具提交后的第二次 prepare-only 与 preflight

图表工具和更新后的冻结协议提交：

```text
e21c31cbb85fdf6b24cdfd0ef7bcbdf40a948ff8
feat(eval): add reproducible Gate 1 plots
```

在该提交的 tracked worktree 干净时实际执行：

```text
python -m scripts.run_load_test \
  --prepare-only \
  --output-root docs/results/gate_1 \
  --run-id gate1-plan-e21c31c-20260729T162352Z
```

独立重算结果：

- manifest status：`prepared`；
- `formal_run_started=false`；
- source commit：`e21c31cbb85fdf6b24cdfd0ef7bcbdf40a948ff8`；
- protocol SHA-256：
  `bc46870ab7599b31aff4ce686f5220903fe971793107956d57e2b59d6dd8ced2`，重算匹配；
- measurement：500 行，SHA-256
  `dd9e1a59c2176214196937f3a0ece15fe324ef310dda0396f95577db2b0751aa`，重算匹配；
- warm-up：50 行，SHA-256
  `d94ea6bb5273224c2680d8510f1218be4414b4d839816023b5a4d8b0c70745aa`，重算匹配；
- arm algorithm：`position-balanced-v1`；
- arm count：32；
- prepare 后 `raw/` 和 `plots/` entry count 均为 0。

随后实际执行：

```text
python -m scripts.run_load_test \
  --execute-prepared \
  --output-root docs/results/gate_1 \
  --run-id gate1-plan-e21c31c-20260729T162352Z \
  --confirm-quality-gate \
  --confirm-adoption-gate
```

结果为预期的退出码 1 和 fail-closed blocker：

- `source_commit_matches=true`；
- `tracked_worktree_clean=true`；
- `disk_space_sufficient=true`；
- `quality_gate_confirmed=true`；
- `adoption_gate_confirmed=true`；
- `docker_cli_available=false`；
- `compose_config_valid=false`；
- `required_services_healthy=false`；
- `api_key_present=false`；
- `database_url_present=false`；
- `ready=false`；
- preflight 后 `raw/` 和 `plots/` entry count 仍为 0。

保存位置：

```text
docs/results/gate_1/gate1-plan-e21c31c-20260729T162352Z/
```

因此第二次计划已绑定新增图表协议，但仍未产生任何正式图。这个结果同时证明两点：新的
source/protocol 绑定生效；基础设施 blocker 没有被绘图工具变化掩盖或绕过。

## 11. P1-4 不可变本地镜像绑定

状态：`CONTRACT_VERIFIED / REAL_DOCKER_BUILD_NOT_RUN`。

P1-4 修复前，Compose 只声明可变标签 `ai-evalops-platform:phase9`，preflight 只保存
`docker compose images --quiet` 的一组 ID。旧逻辑不能证明正在运行的
API/Worker/Reaper：

- 来自本次准备所绑定的 source commit；
- 使用准备时的 Dockerfile 和 build context；
- 属于目标 Compose project；
- 不是同名标签后来重新指向的另一张镜像。

本阶段增加 `scripts/gate1_image_evidence.py`。`--prepare-only` 现在要求 build context
没有未提交、未跟踪或“被 Git 忽略但仍进入 Docker context”的路径，然后：

1. 计算 Dockerfile SHA-256 和规范化 context SHA-256；
2. 使用 revision/source/created、Dockerfile/context/Python 标签构建镜像；
3. 构建后重算 Git 状态和 context hash，拒绝构建过程中的输入漂移；
4. inspect 标签、不可变本地 image ID、创建时间、OS 和 architecture；
5. 用不可变 image ID 临时执行 `python --version` 并要求 `3.12.13`；
6. 将 repository、human-readable tag、immutable ID、source commit、全部 hash、构建时间
   和 runtime 写入 prepared manifest schema v3。

本地 Docker image ID 明确记为 `LOCAL_IMAGE_ID_VERIFIED`，`registry_digest` 为 `null`。
本阶段没有访问 registry，因此没有声称 `REGISTRY_DIGEST_VERIFIED`。

`--execute-prepared` 在任何 arm 前先重算 context hash，再对 Compose 返回的具体容器 ID
执行 `docker inspect`。API/Worker/Reaper 必须同时满足：

- 三类必需服务都存在，且每个 `.Image` 精确等于 manifest immutable ID；
- `org.opencontainers.image.revision` 存在并等于 manifest source commit；
- `com.docker.compose.project=ai-evalops-platform`；
- Dockerfile/context 标签等于 manifest；
- Compose 顶层 `name` 固定为 `ai-evalops-platform`。

对应失败状态分别保留为 `IMAGE_ID_MISMATCH`、
`IMAGE_REVISION_LABEL_MISSING`、`IMAGE_REVISION_MISMATCH`、
`COMPOSE_PROJECT_MISMATCH` 和 `IMAGE_BUILD_INPUT_MISMATCH`，不会被统一吞成
`ENVIRONMENT_BLOCKED`。Docker/Compose 或必需服务本身不可用时仍优先报告环境阻断。

TDD 覆盖了同 tag 不同 ID、revision 不匹配、revision 缺失、旧 Dockerfile 镜像、
build-context 中未跟踪 Python、manifest 缺失/畸形 image、错误 Compose project、
已跟踪 Dockerfile 修改、构建过程中 context 变化，以及镜像构建失败不留下半成品 run
目录。

最终验证：

- P1-4 相关四个单测文件：56 passed；
- 非 integration 全量：333 passed、6 deselected；
- integration 标记：6 skipped，因为没有启用真实 PostgreSQL/Redis；
- Ruff：223 files already formatted，lint 全部通过；
- strict mypy：106 source files，无问题；
- `git diff --check`：无 whitespace error；
- Docker CLI：`DOCKER_UNAVAILABLE`，真实 build/Compose smoke 为 `NOT_RUN`。

本阶段没有生成或修改任何 `docs/results/` 正式实验 artifact，没有启动 500-case/32-arm，
没有得出 Worker 数或容量结论。manifest schema v1/v2 保持历史只读；P1-4 之后必须从最终
干净提交重新执行 `--prepare-only`，不能给旧 manifest 手工补 image 字段。

P1-5 仍需继续审计 Dockerignore 完整语义、symlink、ignore precedence、secret 文件和
精确 build-context 边界。因此 P1-4 的 `docker-context-sha256-v1` 是当前受测合同，不应
被表述为已完成所有 build-context hardening。

## 12. P1-5 Build context / Git commit 一致性加固

状态：`CONTRACT_VERIFIED / REAL_DOCKER_BUILD_NOT_RUN`。

实现提交：

```text
eb33de494bbda4850b7f29240dcce54146a42339
fix(gate1): audit Docker build context against Git
```

### 修改前风险

P1-4 已有 `docker-context-sha256-v1`，但它仍不足以作为正式 Gate 1 输入证明：

- image builder 只拒绝“实际进入 context 的 Git 状态行”，所以被 Docker 排除的 staged
  变更不会在构建前失败；
- prepare 与 execute 各自维护一份近似 `.dockerignore` 匹配器，根路径、嵌套路径和
  `**` 可能得到不同结论；
- Git porcelain 文本会转义非 ASCII 路径，逐行切片会把路径记录错；
- Dockerfile 专用 ignore 文件会覆盖根 `.dockerignore`，但 manifest 只绑定根文件；
- 干净 Git 提交中的 symlink 或 `.env*` 仍可能进入 context；
- builder 相信调用者传入的 source commit，且没有在构建后确认 `HEAD` 没有前进；
- 旧 schema v3 无法表达 P1-5 新语义，却仍会被当作当前可执行 bundle。

### 最终合同

本阶段保留“内容指纹”方案，同时加上严格 Git 前置条件：

1. tracked 或 staged 变更无论是否被 Docker 排除，一律阻断；
2. untracked / Git-ignored 文件只有实际进入 root `.dockerignore` 定义的 context 时才阻断；
3. Git 路径通过 NUL 分隔接口读取，不解析面向人的引号或 rename 文本；
4. root pattern 只匹配相应根路径；递归规则显式使用独立 `**` 路径段；
5. UTF-8 BOM、首列注释和 last-match negation 按冻结子集处理；
6. 复合 `foo**bar` 之类未审计语法、Dockerfile 专用 ignore、实际进入 context 的 Git
   symlink 和 `.env*` 路径统一返回 `UNSAFE_BUILD_CONTEXT`；
7. 构建前后都运行完整审计并比较 `docker-context-sha256-v2`；
8. 构建前后都要求仓库 `HEAD` 等于 manifest source commit；
9. prepared verifier 复用同一个公共审计入口，不再维护第二份 matcher；
10. prepared manifest 升为 schema v4；v1/v2/v3 只读，不迁移、不改号。

`docker-context-sha256-v2` 是平台自己的规范化输入绑定，不冒充 Docker/BuildKit 内部
context digest。它记录按路径排序的普通文件 path、kind、size 和内容 SHA-256；symlink
target 只用于形成可诊断快照，正式安全审计会先拒绝实际进入 context 的 symlink。

### 已验证

- P1-5 与 Gate 1 聚焦矩阵：79 passed；
- 最终非 integration 全量：356 passed、6 deselected；
- integration 标记：6 skipped、356 deselected，原因仍是未启用真实 PostgreSQL/Redis；
- `uv lock --check`：70 packages resolved；
- Ruff lint：`All checks passed!`；
- Ruff format：224 files already formatted；
- strict mypy：106 source files，无问题；
- `git diff --check`：无 whitespace error；
- Docker 只读探测：PowerShell `CommandNotFoundException`，所以真实
  build/inspect/Compose smoke 为 `NOT_RUN`。

覆盖的关键样例包括 tracked、staged、未跟踪 `app/*.py`、根 `tests/` 排除文件、
Git-ignored 但进入 context 的文件、嵌套 generated cache、嵌套 `.env`、已提交
symlink、Dockerfile 专用 ignore、修改 Dockerfile、修改 `uv.lock`、非 ASCII Git
路径、构建期间 context 变化，以及构建期间提交排除文件导致 `HEAD` 前进。

### 仍未证明

- 本机没有 Docker CLI/daemon，因此没有比较真实 Docker/BuildKit 行为与受控 CLI
  boundary；
- matcher 是明确冻结且失败关闭的受测子集，不是 Moby patternmatcher 的完整重实现；
- `.env*` 是本阶段明确的敏感路径规则，不等于通用 secret scanner；
- 构建前后快照和 `HEAD` 检查缩小并检测已覆盖竞态，但不是对 Docker 实际发送 tar
  stream 的内部密码学证明；
- 没有创建新的 `docs/results/` bundle，没有运行 500-case/32-arm，没有容量结论。

本阶段没有 push、没有 PR。后续阶段必须另行确认；正式 Gate 1 仍不能启动。

## 13. P2-5 quality/adoption flags 自动检查

状态：`LOCAL_AND_REMOTE_VERIFIED / FORMAL_GATE_NOT_RUN`。

修改前，`--confirm-quality-gate` 与 `--confirm-adoption-gate` 只是用户授权运行的 Boolean；
aggregate 除固定 `automatic_adoption_decision=null` 外，没有根据冻结 arm plan 自动判断证据是否
完整或有效。Boolean 确认不能被当成结果证据。

本阶段用 RED `a9a1324` 和 GREEN `3ee4480` 冻结以下边界：

- prepared manifest 升为 schema v5，声明 result schema v3 和不可弱化的 quality policy v1；
- finalizer 必须显式接收启动前读取的 expected arm plan；
- expected/observed arm 重复、unexpected 或身份不一致 fail-closed；
- 任一 invalid arm 使 quality 为 `FAILED`；缺 arm 且没有已知 invalid 时为 `UNKNOWN`；全部
  expected arms 完整有效时为 `VERIFIED`；
- quality 通过只产生 `READY_FOR_HUMAN_REVIEW`，adoption 本身保持 `NOT_RUN`；
- `automatic_worker_count_change=false`、`automatic_adoption_decision=null`、
  `selected_worker_count=null`；
- 负扩展保留为证据，不自动判 quality 失败，也不自动选择 Worker。

schema 轴保持独立：prepared v5、result v3、final-bundle v1、Prometheus evidence v2。旧
prepared v1–v4 和 result v1–v2 只读，不迁移、不覆盖；必须从新的干净提交重新 prepare。

本地最终证据：Gate 1 相关 132 passed；finalization 收紧 16 passed；非 integration 全量
`463 passed, 8 deselected`；Ruff 250 files、lint、117-source strict mypy 与 70-package lock
全部通过。详细 RED/GREEN、方案比较、遇到的问题、schema 影响和回滚见
[`reviews/p2_5_gate_automation_log.md`](reviews/p2_5_gate_automation_log.md)。

这些结果只证明自动化合同。没有运行真实 500-case/32-arm，没有用户数值 performance policy，
因此没有 throughput、p95/p99、容量 knee 或部署 Worker 数结论。

后续远端证据：绑定 head `fa526f7ad6ada27ba5f9e6492afb5a8ab368b5a6` 的
[GitHub Actions Run #23](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30734753325)
最终 success。两个 job 均成功，步骤级结果确认全部真实服务 integration、P2 migration
round-trip、application image、完整 Compose topology、readiness 与 hardening inspect 实际执行。
该证据不包含正式 500-case/32-arm，不改变 adoption `NOT_RUN`。

## 14. P2-6 Worker 集群资源按快照聚合

状态：`LOCAL_AND_REMOTE_VERIFIED / FORMAL_GATE_NOT_RUN`。

旧实现把 API、Worker、Reaper、PostgreSQL、Redis 的 CPU/RSS 样本压平，summary 和图表实际
展示最大单容器 peak；它不是 Worker cluster total。直接把各容器跨时间 peak 相加也不正确，
因为峰值可能发生在不同快照。

本阶段用 RED `646e43b` 和 GREEN `c3128a5` 冻结以下合同：

- Docker stats 完整 ID/Name 必须唯一绑定 Compose ID/Name/Service，不能靠容器名猜 Worker；
- 每轮采集写明确 `snapshot_index`；同一快照内只求和 `service=worker` 副本；
- 对快照总量计算 CPU/RSS p50/p95/p99/peak；
- 缺副本为 `UNKNOWN`，重复、无效或超出预期为 `FAILED`，数值保持 null；
- 任何非 VERIFIED Worker 资源证据使 arm 失去容量比较资格；
- 每容器 peak 仍作为带 service 的诊断字段保留，但图表和 CSV 只消费 Worker cluster 值；
- prepared schema 升为 v6，result schema 升为 v4；final-bundle v1 与 Prometheus evidence v2
  语义未变，保持原版本。

本地最终证据：Gate 1 相关 `138 passed`；非 integration 全量
`469 passed, 8 deselected`；Ruff 251 files、lint、117-source strict mypy 与 70-package lock
全部通过。首次组合聚焦测试在 184 秒被外层工具终止，拆分后 55 + 34 + 15 项全部通过；首次
静态检查暴露长行和 strict 类型收窄问题，均通过显式修正解决，没有降低规则。详细方案比较、
RED/GREEN、补丁上下文失败、工具超时、schema 影响和回滚见
[`reviews/p2_6_worker_cluster_resources_log.md`](reviews/p2_6_worker_cluster_resources_log.md)。

本机没有运行 Docker stats/Compose。绑定 head `4ad310a66b226122515be9683fe60ae3c1a183d2` 的
[GitHub Actions Run #25](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30737106451)
最终 success；两个 job 的步骤级结果确认全部真实服务 integration、P2 migration round-trip、
application image、完整 Compose topology、readiness 与 hardening inspect 实际执行。该 CI 没有
创建或修改正式 `docs/results/`，没有运行 500-case/32-arm，没有资源曲线、容量拐点或部署
Worker 数结论。

## 15. P2-7 PostgreSQL transactional outbox

状态：`LOCAL_AND_REMOTE_VERIFIED / FORMAL_GATE_NOT_RUN`。

旧 Worker、Reaper 与 cancel route 在状态事务提交后直接 best-effort Redis publish；进程若在
commit 与 publish 之间退出，通知意图没有持久恢复入口。本阶段用连续 RED 提交冻结 ORM/migration、
同事务写入、禁止直发、有界 relay、lifespan 和 observability 合同，再由 `9c0820a` 实现：

- migration `20260802_0013` 新增 tenant/run 复合 FK 的 `progress_event_outbox`；
- Claim、Result、Failure、Reaper、Cancellation 在原状态事务写稳定 event ID；
- API relay 以 `FOR UPDATE SKIP LOCKED` 和短租约认领，事务外发布 Redis，再 fenced ack；
- failure/timeout 释放 owner 并有界指数退避；publish-before-ack crash 会以同一 ID 重放；
- Worker/Reaper 移除 Redis 直连，`progress.publish` span 改由真正执行 publish 的 API relay 拥有；
- SSE 保持 snapshot-first；交付是 at-least-once，不是 exactly-once，也没有 Pub/Sub 历史回放。

GitHub Actions #27 中新增 Outbox integration 本身通过，但原有双 Reaper 场景暴露真实 PostgreSQL
外键锁升级死锁：两个事务先插 Outbox 取得同一 Run key-share，再同时升级 Run `FOR UPDATE`。
RED `45d3354` 固定“聚合前无 Outbox”，修复 `2174324` 改为先 flush Job、按固定 Run ID 顺序聚合
并取得更新锁，再插入 Job/Run Outbox。绑定该 head 的
[GitHub Actions #28](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30738964791)
最终两个 job success，真实双 Reaper、Outbox rollback/FK/双 relay/retry/replay、migration
round-trip、image、完整 Compose/readiness/hardening 均成功。

补齐 relay `progress.publish` tracing 和本阶段文档后，绑定 head
`5092f49eccc504b3d13a960e872305eb08c010b9` 的
[GitHub Actions #29](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30739846288)
再次得到两个 job success；非集成回归、全部真实服务集成、migration、image 与 Compose 均执行，
因此最终 P2-7 代码/文档 head 不是沿用 #28 的旧成功结论。

最终本地全量 `488 passed, 9 deselected`；锁 70 packages、Ruff 259 files、lint 与 119-source
strict mypy 通过。真实 Outbox integration 本机因无服务 `1 skipped`。详细方案比较、全部
RED/GREEN、#27 失败锁图、回滚顺序与 retention/backlog 等残余风险见
[`reviews/p2_7_transactional_outbox_log.md`](reviews/p2_7_transactional_outbox_log.md)。

本阶段没有创建/修改正式 `docs/results/`，没有运行 500-case/32-arm，没有 throughput、p95/p99、
容量 knee、资源曲线或 adoption 结论。source/migration head 已变化，旧 prepared bundle 只能保留
历史只读，正式执行前必须从最终干净提交重新 prepare。

## 16. P2-8 Outbox retention 与运维可观测性

状态：`LOCAL_AND_REMOTE_VERIFIED / ALERT_RUNTIME_NOT_RUN / FORMAL_GATE_NOT_RUN`。

P2-7 后 delivered Outbox 行没有生命周期，pending 只能从日志推断。P2-8 用 19 组纵向
RED→GREEN 冻结：

- 只选择早于 retention cutoff 的 `published_at IS NOT NULL` 行；
- CTE 按 `published_at,id` 排序、限定 batch、`FOR UPDATE SKIP LOCKED`，同事务 DELETE RETURNING；
- API 独立 cleanup task 与 dispatcher 共享 stop、不共享 cadence；单轮异常只记录类型并恢复；
- PostgreSQL durable refresh 输出无 label 的 pending 与 oldest-created age；
- retry、lease-lost、cleanup 删除量使用每 API 进程的无 ID Counter；
- `0014` 与 ORM metadata 新增 `(published_at,id) WHERE published_at IS NOT NULL`；
- `.env.example` 与 Compose 显式转发六个 dispatcher、三个 cleanup 参数；
- Prometheus 模板覆盖持续 oldest backlog 和 lease loss，但不声称已部署。

真实 integration 建立两条 8 天前 delivered、一条近期 delivered 和一条 8 天 pending；两个
maintenance 并发且 batch=1，合计只删除两条旧 delivered，近期 delivered/pending 保留，durable
Gauge 为 pending=1、oldest=691200 秒。绑定 head
`69cba416ed7c8254e4bc0eb4247568652c0f78e4` 的
[GitHub Actions #31](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759184986)
两个 job success；非 integration、全部真实服务 integration、P2 migration round-trip、image、
完整 Compose/readiness/hardening 均实际执行。随后绑定代码与首版证据文档 head
`5b374d22fd9fdc48d93b14103b405b31dd0dd3bb` 的
[GitHub Actions #32](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759680786)
也由 `quality-and-integration` 与 `compose-smoke` 两个 job 成功完成，确认文档收口没有破坏流水线。

本地最终 `504 passed, 9 deselected in 248.23s`；70-package lock、260-file Ruff format、lint 与
119-source strict mypy 通过；本地真实 integration `1 skipped`。详细 RED 失败、PowerShell
`$LASTEXITCODE` 问题、方案比较、部署/回滚和残余风险见
[`reviews/p2_8_outbox_operations_log.md`](reviews/p2_8_outbox_operations_log.md)。

本阶段没有创建或修改正式 `docs/results/`。source、Compose 和 migration head 已变化，旧
prepared bundle 只能历史只读，正式 Gate 前必须从最终干净提交重新 prepare。没有吞吐、p95/p99、
容量 knee、资源曲线或 adoption 结论。
