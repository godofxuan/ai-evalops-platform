# Gate 1 Prepared Evidence 加固记录（P1-1）

日期：2026-07-30

项目：AI EvalOps Platform / 多租户异步 AI 评测与任务编排平台

本地仓库：`D:\文档\ai-evalops-platform`

起始锚点：`f6a3a2892d8f0f3e39336990debdade8858031c1`

起始分支：`codex/evidence-gate-1`

工作分支：`codex/gate1-evidence-hardening`

实现提交：`f72893a fix(gate1): revalidate prepared evidence before execution`

阶段结论：P1-1 代码与本地合同 `VERIFIED`；正式 500-case、真实服务集成和容量结论均为
`NOT_RUN`。

## 1. 本阶段只解决什么

本阶段只解决 P1-1：执行一个已经 prepare 的 Gate 1 bundle 前，必须重新验证该 bundle
及其来源状态，不能只相信 prepare 当时写入的 manifest。

明确不在本阶段执行：

- 不运行正式 500-case × 1/2/4/8 Worker 矩阵；
- 不执行 32 个正式 arm；
- 不执行容器中断、数据库中断或其他破坏性 fault injection；
- 不自动修改 Worker 部署值；
- 不创建数据库 migration；
- 不开始 P1-2；
- 不 push、不创建 PR。

## 2. 证据词表

本记录只使用以下证据状态：

| 状态 | 含义 |
|---|---|
| `VERIFIED` | 本机实际执行了对应静态检查、测试或只读核验，并得到记录中的结果 |
| `FAILED` | 命令实际执行但没有满足前置条件或断言；必须同时写清失败边界 |
| `NOT_RUN` | 没有执行对应实验或真实服务合同 |
| `UNKNOWN` | 当前证据不足，不能得出结论 |
| `DIRECTIONAL` | 只能用于形成方向性判断，不能作为硬性结论 |

`READY`、`HASH_MISMATCH`、`SOURCE_MISMATCH`、`DIRTY_BUILD_CONTEXT`、
`MANIFEST_INVALID` 和 `ENVIRONMENT_BLOCKED` 是 preflight 结果类别，不是上述证据等级。

## 3. 修改前基线与阅读范围

### 3.1 Git 基线

- 修改前 `git status --short` 为空：`VERIFIED`；
- 修改前分支为 `codex/evidence-gate-1`：`VERIFIED`；
- 修改前 HEAD 与指定锚点
  `f6a3a2892d8f0f3e39336990debdade8858031c1` 完全一致：`VERIFIED`；
- 本地相对 `origin/main` 的计数为 `0 0`：`VERIFIED`；
- 仓库中没有 `AGENTS.md`：`VERIFIED`；
- 新建 `codex/gate1-evidence-hardening` 后才开始修改：`VERIFIED`。

### 3.2 重新阅读的材料

本轮在动代码前重新检查了：

- `README.md`、`pyproject.toml`、`uv.lock`；
- `Dockerfile`、`.dockerignore`、`.gitignore`、`deploy/compose.yaml`；
- `.github/workflows/ci.yml`；
- `docs/engineering_journal.md`、`docs/phase_9_execution_log.md`；
- `docs/results/phase_9_environment_and_blockers.md`；
- `docs/gate_1_execution_log.md`；
- `docs/reviews/project_audit_and_improvement_log.md`；
- 两个已有 Gate 1 prepared bundle 的 manifest、dataset hashes、arm plan 和失败 preflight；
- `scripts/run_load_test.py`、现有 preflight、collector、database、evidence、plot 和协议代码；
- 所有现有 Gate 1 单元测试；
- `app/targets/http_rag.py`；
- `app/artifacts/*`、`app/persistence/*`；
- Alembic 0001 至 0008 全部 migration。

重新解析 `uv.lock` 得到 70 个 package entry，Python 约束为 `==3.12.*`。本阶段没有修改
依赖，也没有修改数据库模型，因此不需要更新 lock 或新增 migration。

## 4. 修改前发现的真实缺陷

### 4.1 原执行入口实际做了什么

旧的 `--execute-prepared` 会读取 manifest 中的 source commit，然后调用环境 preflight。
它只检查：

- 当前 HEAD 是否等于 manifest 的 source commit；
- `git status --porcelain --untracked-files=no` 是否为空；
- Docker/Compose、服务健康、磁盘、环境变量和两个确认 gate。

随后执行器会重新直接读取：

- `manifest.json`；
- `arm_order.json`；
- `measurement.jsonl`；
- `warmup.jsonl`。

### 4.2 原执行入口没有做什么

它不会在执行前重新计算和比较：

- measurement SHA；
- warm-up SHA；
- protocol SHA；
- arm plan SHA；
- configuration SHA；
- Compose SHA；
- Dockerfile SHA；
- `.dockerignore` SHA；
- 关键执行脚本 SHA。

同时，`--untracked-files=no` 明确忽略全部未跟踪文件。因此一个未跟踪的
`app/untracked_source.py` 可以进入 Docker build context，却不会让旧 preflight 失败。

### 4.3 风险判断

这是实际证据完整性缺陷，不是纯代码风格问题，优先级为 P1，原因是：

1. prepare 和 execute 之间可以隔很长时间；
2. 数据、协议、脚本或镜像输入发生漂移后，旧执行器仍可能运行；
3. 结果 manifest 会声称绑定旧来源，但实际运行的是新内容；
4. 这会直接破坏 Gate 1 的可复现性和可审计性；
5. 在修复前不应启动正式 Gate 1。

## 5. 旧 prepared evidence 的复核与兼容决定

已有两个 bundle：

| Bundle | source commit | manifest schema | 内部已有 SHA 复算 |
|---|---|---:|---|
| `gate1-plan-c72e8c5-20260729T150959Z` | `c72e8c5...` | 1 | protocol、measurement、warm-up 均匹配 |
| `gate1-plan-e21c31c-20260729T162352Z` | `e21c31c...` | 1 | protocol、measurement、warm-up 均匹配 |

它们的 schema v1 没有 configuration、arm plan、Dockerfile、`.dockerignore` 和关键脚本的
完整执行绑定，因此不能安全地“原地补字段”后继续执行。

采用的兼容策略：

- manifest schema 升为 2；
- schema v1 保留为历史、只读证据；
- 新执行器对 schema v1 返回 `MANIFEST_INVALID`；
- 不静默迁移、不修改旧 manifest、不伪造旧 prepare 时间点的新哈希；
- 若未来要运行，必须在目标 source commit 的干净仓库重新 prepare；
- 这不是数据库 schema，故不需要 Alembic migration。

## 6. 新的 manifest v2 绑定

未来 prepare 会写入并绑定：

| 类别 | v2 内容 | 执行前处理 |
|---|---|---|
| Manifest | `schema_version=2`、`status=prepared`、`formal_run_started=false` | 验证结构和不变量 |
| Source | Git source commit | 比较当前 HEAD |
| Workspace | tracked 状态 | 必须干净 |
| Build context | 未跟踪和 Git ignored 候选 | 只要实际会进入 context 就阻断 |
| Configuration | 所有影响正式运行的非秘密参数 + canonical JSON SHA | 同时校验 manifest 自身和本次 CLI |
| Dataset | measurement、warm-up、`hashes.json` 的路径与 SHA | 逐文件复算 |
| Protocol | bundle 内 `protocol.md` 路径与 SHA | 复算 |
| Arm plan | `arm_order.json` 路径与 SHA | 复算 |
| Compose | 仓库相对路径与 SHA | 复算并比较本次 CLI path |
| Image definition | Dockerfile、`.dockerignore` 路径与 SHA | 复算 |
| Execution scripts | 9 个关键脚本的逐文件 SHA | 复算并指出具体漂移脚本 |

冻结 configuration 包括：

- API URL；
- API key 环境变量名；
- database URL 环境变量名；
- Worker 列表；
- measurement/warm-up case 数；
- MockTarget delay；
- poll、arm deadline、readiness deadline；
- collector interval；
- seed；
- repetitions。

只保存环境变量名，不保存 credential value。

## 7. 状态分类

验证器保留全部失败 check，同时选择一个主要类别：

1. manifest 结构、schema 或受限路径无效：`MANIFEST_INVALID`；
2. Git 仓库状态无法读取：`ENVIRONMENT_BLOCKED`；
3. 当前 HEAD 不等于准备时 commit：`SOURCE_MISMATCH`；
4. 任一证据、来源文件或执行参数 SHA 不一致：`HASH_MISMATCH`；
5. tracked worktree 不干净，或有文件会进入 Docker context：`DIRTY_BUILD_CONTEXT`；
6. 证据通过但 Docker、服务、磁盘、credential 或人工 gate 不满足：
   `ENVIRONMENT_BLOCKED`；
7. 全部满足：`READY`。

`HASH_MISMATCH` 的优先级高于 dirty worktree，是为了在“脚本既被修改又造成 worktree dirty”
时直接指出更具体的漂移文件；全部失败 check 仍会保留。

## 8. Docker build context 的范围判断

本轮不是简单地“所有 untracked 一律失败”，而是按当前 `.dockerignore` 判断它是否真的会
进入 build context。

| 文件类型 | 决定 |
|---|---|
| tracked 文件被修改、删除或 staged | 阻断；source commit 已不能完整代表工作区 |
| 普通 untracked 且未被 `.dockerignore` 排除 | 阻断 |
| Git ignored 但未被 `.dockerignore` 排除 | 阻断 |
| `docs/` 下未跟踪结果 | 不因 build context 阻断；`docs` 已明确排除 |
| `.pytest-tmp*` 等测试临时目录 | 不因 build context 阻断；已对齐排除规则 |
| `.env`、`.env.local` 等环境覆盖文件 | 必须排除；规则从 `.env` 修为 `.env*` |
| `app/`、`scripts/` 下临时脚本或 fixture | 如果没有 Docker 排除规则则阻断 |
| 仓库外执行目录或副本 | 不属于该仓库 build context，不参与本次检查 |

本轮还修正了两个真实规则差异：

- Git 忽略 `.env.*`，旧 `.dockerignore` 只排除 `.env`；
- Git 忽略 `.pytest-tmp*`，旧 `.dockerignore` 只排除 `.pytest-tmp`。

这两类文件原本都可能被发送给 Docker builder。

## 9. TDD 过程记录

每个关键行为都先得到可解释的 RED，再做最小 GREEN。下面的“原行为”是测试实际观察结果，
不是事后推测。

| # | RED 场景 | RED 时观察到的行为 | GREEN 修改与效果 |
|---:|---|---|---|
| 1 | producer 应生成 schema v2 | manifest 仍是 schema 1 | prepare 写 v2 和完整哈希 |
| 2 | 篡改 measurement | verifier 尚不存在 | 新增 verifier；返回 `HASH_MISMATCH` |
| 3 | 篡改 warm-up | 仍返回 `READY` | 增加 warm-up SHA 复算 |
| 4 | 篡改 protocol | 仍返回 `READY` | 增加 protocol SHA 复算 |
| 5 | 篡改 Compose | 仍返回 `READY` | 增加 Compose SHA 复算 |
| 6 | 篡改 arm plan | 仍返回 `READY` | 增加 arm plan SHA 复算 |
| 7 | 篡改 collector 脚本 | 仍返回 `READY` | 逐脚本复算并记录具体 path |
| 8 | source commit 前进 | 仍返回 `READY` | 真实 Git HEAD 比较；`SOURCE_MISMATCH` |
| 9 | 未跟踪 `app/*.py` | 仍返回 `READY` | 增加 build context dirty 检查 |
| 10 | manifest 缺 measurement hash | 抛 `KeyError` | fail closed 为 `MANIFEST_INVALID` |
| 11 | schema 999 | 仍返回 `READY` | 只接受 schema 2 |
| 12 | 修改 configuration value | 仍返回 `READY` | canonical JSON SHA 复算 |
| 13 | 修改 Dockerfile | 只得到 dirty 类别 | 增加 Dockerfile SHA，明确为 hash mismatch |
| 14 | 修改 `.dockerignore` | 只得到 dirty 类别 | 增加 `.dockerignore` SHA |
| 15 | 修改 `hashes.json` | 仍返回 `READY` | 绑定 dataset hash record |
| 16 | execute 使用另一个 Compose path | 仍返回 `READY` | 比较本次 path 与准备时 path |
| 17 | Git ignored 文件进入 context | 仍返回 `READY` | 状态采集加入 ignored 候选 |
| 18 | `docs/` 下 untracked 文件 | 被错误阻断 | 按 `.dockerignore` 过滤候选 |
| 19 | `.env.local` | 被识别为会进入 context | `.dockerignore` 改为 `.env*` |
| 20 | `.pytest-tmp-*` | 被识别为会进入 context | `.dockerignore` 改为 `.pytest-tmp*` |
| 21 | manifest 路径逃出 bundle | 仅返回 hash mismatch | 路径必须为受限 root 内相对路径 |
| 22 | `.dockerignore` 被删除 | 抛 `FileNotFoundError` | 记录 observed SHA 为 null 并 fail closed |
| 23 | Git metadata 不可用 | 错分为 source mismatch | 改为 `ENVIRONMENT_BLOCKED` |
| 24 | CLI 篡改后执行 | 旧入口写 `ENVIRONMENT_BLOCKED` | verifier 接到环境探测之前 |
| 25 | 环境前置条件失败 | 只有 `ready=false` | 明确 `ENVIRONMENT_BLOCKED` |
| 26 | execute 改 collector interval | 旧入口进入环境探测 | 比较本次 configuration SHA |
| 27 | 环境探测时 source/worktree 漂移 | 被归为环境失败 | 保留 source/dirty 独立类别 |
| 28 | 未诱发 stale submission 的词表 | 输出 `NOT_TESTED` | 统一为 `NOT_RUN` |
| 29 | `formal_run_started=true` 的 manifest | 仍返回 `READY` | 只接受 pristine prepared manifest |

新增验证使用真实临时 Git 仓库和真实文件系统；没有 mock 自己的 verifier 或 manifest
validator。这样测试同时覆盖 Git source、tracked/untracked/ignored 状态和路径行为。

## 10. 遇到的问题、判断和处理

### 10.1 `uv` 不在 PATH

第一次基线命令没有进入测试，PowerShell 报 `uv` CommandNotFound。这不是产品 RED。

处理：

- 找到项目 `.venv\Scripts\python.exe` 运行 pytest；
- 后续找到 `.codex-tools\Scripts\uv.exe`；
- 最终使用该固定路径执行 `uv lock --check`。

效果：避免把本机 PATH 问题误报成项目失败。

### 10.2 Git dubious ownership

第一次真实基线得到 28 passed / 5 failed，5 个失败全部发生在 `git rev-parse HEAD`，
原因是 Git safe.directory 拒绝当前 Windows ownership。

处理：

- 先给单次测试进程注入 safe.directory，确认真实基线为 33 passed；
- prepare 与 verifier 的 Git 调用都显式使用仓库级 `-c safe.directory=...`；
- 没有修改用户全局 Git 配置。

效果：可复现地消除环境噪声，同时保留 Git 安全边界。

### 10.3 开发中 worktree 本来就 dirty

接入 verifier 后，旧环境 preflight 测试会先被当前开发改动阻断，无法再测试
Docker/credential gate。

处理：

- 测试 fixture 创建临时干净 Git 仓库；
- 复制真实关键来源，真实 commit 后再 prepare/execute；
- 输出目录放在临时仓库外。

效果：测试的失败原因稳定地来自目标行为，而不是开发中的工作树。

### 10.4 Ruff 命令误把 `.dockerignore` 当 Python

第一次局部 lint 命令把 `.dockerignore` 放进 Python 文件列表，产生多条 invalid syntax。
这是命令误用，不是源代码问题。

处理：Python 文件与 Docker ignore 文件分开检查。真正代码问题只有一处长行，随后修复。

### 10.5 格式与类型问题

- Ruff format 要求调整几个列表推导和断行；
- Ruff 发现一个可合并条件；
- strict mypy 要求给 Docker ignore rule 列表和全部 `monkeypatch` 参数补类型。

处理：执行格式化并补显式类型；没有降低 Ruff/mypy 严格度，没有加入 ignore。

## 11. 修改文件与原因

| 文件 | 修改原因 |
|---|---|
| `.dockerignore` | 排除 `.env*` 和 `.pytest-tmp*` |
| `scripts/gate1_prepared_evidence.py` | 新增 schema/manifest/source/context/hash verifier |
| `scripts/run_load_test.py` | 生成 v2 manifest；在环境与 arm 前调用 verifier |
| `scripts/gate1_preflight.py` | 输出清晰的 preflight 类别 |
| `scripts/gate1_evidence.py` | 把未诱发行为统一标为 `NOT_RUN` |
| `scripts/worker_scaling_protocol.md` | 冻结 v2 evidence gate 和状态语义 |
| `tests/conftest.py` | 提供真实、干净的临时 Git 仓库 fixture |
| `tests/unit/scripts/test_gate1_prepared_evidence.py` | 24 个 verifier/兼容/安全边界测试 |
| `tests/unit/scripts/test_experiment_scripts.py` | producer 和公开 execute 入口合同 |
| `tests/unit/scripts/test_gate1_preflight.py` | 状态分类合同 |
| `tests/unit/scripts/test_gate1_evidence.py` | 证据词表合同 |

## 12. 最终验证结果

| 检查 | 结果 | 证据状态 |
|---|---|---|
| `uv lock --check` | Resolved 70 packages in 3ms | `VERIFIED` |
| Ruff format 全仓 | 219 files already formatted | `VERIFIED` |
| Ruff lint 全仓 | All checks passed | `VERIFIED` |
| strict mypy | 110 source files，无问题 | `VERIFIED` |
| Gate 1 定向回归 | 60 passed in 15.55s | `VERIFIED` |
| 非 integration 全量 | 292 passed，6 deselected in 20.13s | `VERIFIED` |
| 真实服务合同收集 | 6 skipped，要求真实 PostgreSQL/Redis | `NOT_RUN` |
| Docker CLI | 当前 shell 未找到命令 | `FAILED`（环境前置条件） |
| 正式 500-case / 32-arm | 未启动 | `NOT_RUN` |
| fault injection | 未启动 | `NOT_RUN` |
| P1-2 | 未开始 | `NOT_RUN` |

这里的 Docker `FAILED` 只表示本机环境前置条件不满足，不表示产品 Docker/Compose 合同失败。
真实服务合同和正式 Gate 1 仍是 `NOT_RUN`，不能根据 292 个本地测试推断容量。

## 13. 已达到的效果

- prepare 产出 manifest schema v2；
- 所有要求的准备证据都能在执行前重算；
- source commit 和 tracked workspace 必须一致；
- 会进入 Docker context 的 untracked/ignored 文件会阻断；
- manifest 缺字段、schema 不支持、路径逃逸会 fail closed；
- runtime CLI 配置漂移会在 Docker 前阻断；
- 失败记录能指出具体 check、path、expected SHA 和 observed SHA；
- preflight 能区分六类结果；
- 旧 schema v1 bundle 被明确保留为历史只读证据；
- 没有运行任何 arm，没有改变 Worker 数，没有产生容量结论。

## 14. 仍未解决和信任边界

### 14.1 Manifest 本身没有签名

当前 verifier 证明的是“文件与 manifest 一致”。如果攻击者同时改写 manifest 内容和全部
SHA，单靠自描述 manifest 无法证明真实性。

未来可选方案：

- 把 manifest 放入受保护、签名的 artifact store；
- 使用 CI provenance/attestation；
- 对整个 bundle 生成外部签名或透明日志记录。

本轮没有假装普通 SHA 能替代签名。

### 14.2 检查与使用之间仍有本地 TOCTOU 窗口

验证完成后到 Docker/文件读取之间仍有很小的并发修改窗口。当前合同假设正式实验运行在
独占、受控工作区。

未来可选方案：

- 从已验证字节构造只读 archive；
- 使用 content-addressed snapshot；
- 直接绑定构建后的 image digest；
- 在独占 CI runner 中运行。

### 14.3 Docker ignore matcher 针对当前规则集

当前 matcher 覆盖本仓库实际使用的注释、普通 pattern、wildcard 和 negation 顺序，并有
对应测试。若未来引入复杂 Docker 特有 pattern，必须先补兼容测试或改用 Docker 官方解析
能力，不能无审查扩展。

### 14.4 真实基础设施证据仍为空

本机没有 Docker/PostgreSQL/Redis 运行栈，因此：

- Compose build、scale、health：`NOT_RUN`；
- PostgreSQL collector：`NOT_RUN`；
- Redis/Prometheus 多副本采集：`NOT_RUN`；
- 500-case 吞吐、p95/p99、锁等待、CPU/RSS：`UNKNOWN`；
- Worker 推荐值：`UNKNOWN`。

## 15. 回滚与下一步

本阶段没有数据库 migration、没有远端状态修改、没有正式实验结果，回滚边界清晰：

- 回滚实现提交 `f72893a` 即可恢复旧行为；
- 已有 schema v1 历史 bundle 没有被改写；
- 新 schema v2 bundle 若由本实现生成，旧执行器不认识，应该删除并重新 prepare，而不是
  降级字段；
- `.dockerignore` 的安全排除规则即使回滚 verifier，也建议保留。

停止条件已经满足：P1-1 完成，P1-2 尚未开始。下一步必须由用户确认后再进入 P1-2 或在有
Docker/PostgreSQL/Redis 的独占环境重新 prepare；不能直接复用旧 schema v1 bundle。
