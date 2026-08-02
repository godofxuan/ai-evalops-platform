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

# P1-2：缺失指标不能写成 VERIFIED 0

执行日期：2026-07-30（Asia/Shanghai）

阶段起始分支：`codex/gate1-evidence-hardening`

阶段起始 SHA：`003b29c202becf9da48eac433407151e4ae367b3`

实现提交：`fdae758c2b0e625085f269db61d4d1fa352197ad`

远端操作：未 push、未创建 PR。

## 问题名称

Prometheus 缺失或失败的指标被默认值改写成 `VERIFIED 0`

### 原始行为

问题位于 `scripts/gate1_collectors.py` 的 `summarize_prometheus_deltas()`：

1. 函数预先为 `claim`、`result`、`failure`、`reaper` 创建 count/sum/buckets 全零对象；
2. 计算 before/after delta 时使用 `mapping.get(key, 0.0)`；
3. Redis publication failure delta 从 `0.0` 开始累加；
4. 最终所有预初始化的零对象都获得 `evidence: VERIFIED`；
5. 调用方没有 `status`、`observation` 或采集失败来源可用于区分：
   - 指标存在且 delta 为零；
   - scrape 成功但指标不存在；
   - before/after 只有一侧存在；
   - endpoint 请求失败；
   - exposition 无法可信解析。

阶段开始时执行了真实复现：

```text
before={"worker-abc": ""}
after={"worker-abc": ""}
```

旧输出把四类数据库操作都写成：

```json
{
  "evidence": "VERIFIED",
  "count": 0.0,
  "sum_seconds": 0.0,
  "mean_ms": null,
  "buckets": {}
}
```

同时把 Redis 指标写成：

```json
{
  "evidence": "VERIFIED",
  "delta": 0.0
}
```

这是“没有观测”被改写成“已验证为零”，不是展示格式问题。

### 证据

| 证据 | 观察 |
|---|---|
| 原始源码 | 四类 operation 预初始化为 0 |
| 原始源码 | before/after 缺键使用 `0.0` 补齐 |
| 原始源码 | Redis 未见任何序列时仍返回 `VERIFIED` |
| 原有测试 | collector 5 tests 全部通过 |
| 真实复现 | 空 scrape 返回四组 `VERIFIED` 零对象 |
| 现有协议 | 已写明 missing measurement 应为 `UNKNOWN` |

现有测试没有发现问题，因为唯一的 Prometheus delta 测试只覆盖：

- 同一个 Worker container；
- before/after 都有 claim histogram；
- before/after 都有 Redis counter；
- 所有值格式合法；
- label 完全符合预期；
- 没有 endpoint、重复、非有限值或缺失场景。

该测试证明了“正常输入可以算 delta”，没有证明“缺失输入不会被补零”。

### 风险

该问题是正式 Gate 1 的阻断缺陷：

1. `VERIFIED 0` 会被图表、汇总或人工采用判断当成真实证据；
2. 多 Worker 场景只要部分容器有序列，旧聚合可能掩盖其他容器缺失；
3. before/after 单侧缺失会被当成从 0 增长或归零；
4. Redis failure 为 0 可能被错误表述为“已验证无发布失败”；
5. `NaN`/`Inf` 可能进入非标准 JSON 数值；
6. 重复序列会后值覆盖前值；
7. 带意外 label 的序列会被静默聚合，破坏冻结协议和低基数合同；
8. endpoint 失败直接抛异常，缺少 per-source 机器可读原因；
9. 即使 PostgreSQL reconciliation 通过，必需 Prometheus 证据缺失时 arm 仍可能保留
   `valid_for_capacity_comparison=true`。

修复前不得运行正式 Gate 1，也不得根据这些零值形成 Worker 采用结论。

### RED 测试

严格按垂直切片执行；每次只新增一个行为测试，再写最小 GREEN。后续测试若已被前一个
最小实现自然覆盖，则如实记录为“新增时已 GREEN”，没有为了制造失败而加入多余实现。

| # | 行为 | RED/首次观察 | GREEN 效果 |
|---:|---|---|---|
| 1 | 空 scrape | `required_metrics_complete` 不存在；旧复现为 `VERIFIED 0` | 返回 `MISSING/UNKNOWN/null` |
| 2 | scrape 成功但目标不存在 | tracer fix 后新增时已 GREEN | 与空正文分开形成回归合同 |
| 3 | 指标真实存在且 delta=0 | 成功对象没有 `status/observation/value` | `OBSERVED_ZERO/VERIFIED/0` |
| 4 | 指标存在且 delta>0 | DB histogram 仍是旧形状 | `OBSERVED_VALUE`，保留 count/sum/mean/buckets |
| 5 | 非法 exposition | 第三方 parser 的 `ValueError` 直接穿透 | 统一为结构化 `COLLECTION_FAILED/null` |
| 6 | endpoint 请求失败 | `CalledProcessError` 直接终止 | scrape 保存 `endpoint_request_failed` |
| 7 | 同一指标重复 | 后值覆盖前值并输出 `VERIFIED 0` | 重复键使该来源 collection failed |
| 8 | label 组合不符合协议 | 带 `tenant` 的 claim 被接受并输出 `VERIFIED 0` | 冻结目标 label 集合并 fail closed |
| 9 | `NaN`、`+Inf`、`-Inf` | 前两者为 VERIFIED 非有限值；后者抛 counter decreased | 三者统一 `COLLECTION_FAILED/null` |
| 10 | before/after 单侧缺失 | 无关 metric 消失先触发 counter decreased | 只处理 Gate 1 目标；单侧目标为 `MISSING` |
| 11 | 必需指标在一个 Worker 缺失 | 另一个 Worker 有 claim 即输出 VERIFIED | 要求覆盖每个应采集 Worker；arm 不可比较 |
| 12 | 可选指标缺失 | 前述实现完成后新增时已 GREEN | `UNKNOWN/null`，不误伤必需证据完整性 |
| 13 | 缺失必需证据接入 arm | 不存在公开合并合同，测试 ImportError | 合并接口令 comparison fail closed |
| 14 | Prometheus schema v2 | `schema_version` 不存在 | collector 结果显式为 v2 |
| 15 | Gate 1 result schema v2 | aggregate 没有版本字段 | summary/aggregate/execution/plot 统一 v2 |

测试还补充了：

- optional metric collection failure 映射为 `UNKNOWN/COLLECTION_FAILED/null`；
- raw snapshot writer 保存失败 reason code，不创建伪 `.prom` 文件；
- DB histogram 真实零也是 `OBSERVED_ZERO`；
- plot manifest 和 aggregate artifact 明确为 schema v2。

### 方案比较

#### 方案 A：继续使用数字，只加一个布尔字段

例如保留 `value=0`，另加 `collected=false`。

拒绝原因：

- 旧消费者仍可能只读取数字；
- `0` 仍同时承载两种互斥语义；
- 无法表达 missing 与 endpoint/parse failure 的差异。

#### 方案 B：任何缺失或失败都抛异常并终止 arm

优点是 fail closed，实现较小。

拒绝作为唯一方案的原因：

- 无法保留哪个 source、哪个 metric 失败；
- 可选 failure/reaper 指标缺失不应与必需 claim/result 缺失完全等价；
- 不利于保存 partial evidence；
- endpoint failure 只能留下顶层异常类型，不能形成机器可读 metric evidence。

#### 方案 C：只使用 `float | None`

这能避免 UNKNOWN 变成 0，但不能区分 `MISSING` 与 `COLLECTION_FAILED`，也不能证明 0
确实来自配对序列。

#### 方案 D：显式 scrape 状态 + per-metric 结果（采用）

使用一个很小的 `PrometheusScrape` 值对象保留：

- `COLLECTED + text`；
- `COLLECTION_FAILED + reason`。

随后通过同一公开汇总接口生成：

```json
{
  "status": "VERIFIED | UNKNOWN | FAILED",
  "evidence": "VERIFIED | DIRECTIONAL | UNKNOWN | FAILED",
  "observation": "OBSERVED_ZERO | OBSERVED_VALUE | MISSING | COLLECTION_FAILED",
  "value": "number | null",
  "reason": "...",
  "source": "...",
  "sample_count": 0
}
```

采用原因：

- 直接表达用户要求的三种核心语义；
- 保留 `evidence` 供现有图表/读者使用；
- UNKNOWN/FAILED 一律是 `value=null`；
- 真实零仍是数值零；
- required/optional 映射可以集中执行；
- 失败 raw evidence 可以保留；
- 不需要新模块、数据库或大规模重构。

### 选择的最小方案

#### 1. Scrape 边界

`collect_prometheus_snapshot()` 不再让单个 endpoint 的 `CalledProcessError` 丢失上下文。
每个 API/Worker/Reaper source 返回：

- `COLLECTED`：包含原始 exposition text；
- `COLLECTION_FAILED`：`text=null`，reason 为稳定 reason code。

成功 `.prom` 原文保持不变。失败来源写入同一 phase 目录的
`collection_failures.json`，不创建内容为零或空的伪 `.prom` 文件。

#### 2. Parser 边界

parser 现在：

- 把第三方 `TypeError/ValueError` 统一为 `CollectorParseError`；
- 拒绝重复 sample key；
- 拒绝 `NaN` 和正负无穷；
- 对 Gate 1 目标指标冻结 label 集合；
- Redis counter 不允许 label；
- DB count/sum 只允许 `operation`；
- DB bucket 只允许 `operation` 与 `le`；
- operation 只允许 `claim/result/failure/reaper`；
- 无关 Prometheus 指标不会参与 Gate 1 delta，也不会因普通增减影响目标结果。

#### 3. 配对和 source 完整性

只有同一个 source、同一个 metric、同一个 label key 同时存在于 before/after 时才计算
delta。任一侧缺失均为 `MISSING`，不使用 `0.0` 补齐。

来源合同：

- `claim/result/failure`：Worker；
- `reaper`：Reaper；
- `redis_publish_failures_total`：所有已 scrape 的 API/Worker/Reaper。

`claim` 和 `result` 必须覆盖每个 Worker；Redis counter 必须覆盖每个已 scrape source。

#### 4. required 与 optional

| 指标 | 必需性 | MISSING | COLLECTION_FAILED |
|---|---|---|---|
| claim DB histogram | required | `UNKNOWN/null`，arm 不可比较 | `FAILED/null`，arm 不可比较 |
| result DB histogram | required | `UNKNOWN/null`，arm 不可比较 | `FAILED/null`，arm 不可比较 |
| Redis publish failures | required | `UNKNOWN/null`，arm 不可比较 | `FAILED/null`，arm 不可比较 |
| failure DB histogram | optional | `UNKNOWN/null` | `UNKNOWN/null` |
| reaper DB histogram | optional | `UNKNOWN/null` | `UNKNOWN/null` |

failure/reaper 是否发生取决于 workload 与运行事实，不能把“没出现序列”写成真零。

#### 5. arm fail-closed

新增 `merge_prometheus_evidence()`，集中完成：

- claim 字段接入；
- result/failure/reaper 字段接入；
- Redis 字段接入；
- `required_metrics_complete=false` 时强制
  `valid_for_capacity_comparison=false`。

它返回新字典，不修改调用方传入对象，便于测试并降低隐式副作用。

#### 6. Schema version

两类 schema 必须区分：

1. prepared manifest schema v2：P1-1 的执行前证据绑定；
2. Gate 1 result schema v2：P1-2 的指标语义。

本阶段将以下新结果升级为 result schema v2：

- Prometheus delta；
- per-arm summary wrapper；
- aggregate summary；
- execution report；
- plot manifest。

没有把 prepared manifest 升为 v3，因为其结构没有因 P1-2 改变；新的 source commit、脚本
SHA 和 protocol SHA 已足以使旧 prepared bundle fail closed。

### 修改文件

| 文件 | 修改原因 |
|---|---|
| `scripts/gate1_collectors.py` | scrape 状态、parser 校验、配对/source 完整性、三态输出 |
| `scripts/gate1_evidence.py` | result schema v2 常量和 Prometheus evidence 合并 |
| `scripts/run_load_test.py` | 使用 fail-closed 合并；per-arm/execution 写 result schema v2 |
| `scripts/gate1_plots.py` | plot manifest 随嵌入 point 形状升级为 schema v2 |
| `scripts/worker_scaling_protocol.md` | 冻结 required/optional、状态、source 和兼容合同 |
| `tests/unit/scripts/test_gate1_collectors.py` | 指定的 scrape/metric 异常矩阵 |
| `tests/unit/scripts/test_gate1_evidence.py` | arm fail-closed 与 aggregate schema |
| `tests/unit/scripts/test_gate1_plots.py` | plot/aggregate artifact schema v2 |

没有新增文件或为了抽象拆分新模块。核心复杂性仍隐藏在既有 collector 公共接口后。

### Migration，如有

数据库 migration：无。

理由：

- 没有修改 ORM、表、列、约束或持久化数据；
- 变化只影响新 Gate 1 文件 artifact；
- Alembic 历史 migration 没有被修改；
- `20260729_0008` 仍是唯一 head；
- 全历史离线 SQL 可以生成。

Result schema v1 没有执行原地迁移。原因是 v1 已丢失关键事实：历史
`VERIFIED 0` 无法区分真零与缺失，任何自动迁移都会猜测并伪造证据。

### 修改中遇到的问题

#### 1. 附件第一次按默认编码读取出现乱码

原因：PowerShell 默认解码没有按 UTF-8 解释附件。

处理：所有后续读取显式指定 `-Encoding UTF8`，重新逐段核对 P1-2 和全局约束。

影响：只影响第一次终端展示；没有在乱码状态下修改文件。

#### 2. PowerShell `foreach` 直接接格式化管道失败

表现：检查两个 manifest 的临时命令报 `An empty pipe element is not allowed`。

处理：改为循环内显式输出。

影响：命令没有执行到写操作，仓库未改变。

#### 3. uv 默认 cache 无写权限

表现：`C:\Users\xuan\AppData\Local\uv\cache` 报拒绝访问。

处理：只对当前验证命令设置仓库内 `.uv-cache`。

影响：第一次 pytest 没有启动，不能记为测试失败；重跑后正常。

#### 4. Git dubious ownership

表现：不同沙箱执行身份触发 Git 安全保护。

处理：没有修改全局 Git 配置；只对当前命令增加仓库级
`-c safe.directory=D:/文档/ai-evalops-platform`。

影响：没有降低其他仓库的 Git 安全边界。

#### 5. 非有限值出现三种不一致旧行为

表现：

- `NaN` → `VERIFIED` 且 value 为 NaN；
- `+Inf` → `VERIFIED` 且 value 为 Inf；
- `-Inf` → counter decreased 异常。

处理：在 parser 边界统一拒绝所有非有限值。

效果：三类输入都得到一致的 `COLLECTION_FAILED/null`。

#### 6. 单侧缺失先被无关指标误伤

测试使用一个无关 process metric 和单侧 Redis metric 时，旧循环先把无关 metric 的消失
判断成 counter decreased。

处理：delta 循环只处理冻结的 Gate 1 目标 metric；无关 metric 不参与。

效果：单侧目标缺失准确得到 `MISSING`，不被无关序列覆盖。

#### 7. Ruff 与 mypy 自审问题

第一次自审：

- Ruff 报 2 个文件需要格式化；
- mypy 报 3 个问题，来自跨分支复用 `operation`/`aggregate` 变量名；
- Redis 结果的嵌套三元表达式可读性差。

处理：

- 在 GREEN 状态下改为语义独立变量名；
- Redis 分支改成普通 `if/elif/else`；
- 执行 Ruff formatter；
- 没有增加 ignore，也没有降低 strict 配置。

效果：相关测试仍绿，strict mypy 0 issue。

### 定向测试结果

最终定向命令覆盖：

```text
tests/unit/scripts/test_gate1_collectors.py
tests/unit/scripts/test_gate1_evidence.py
tests/unit/scripts/test_gate1_plots.py
tests/unit/scripts/test_experiment_scripts.py
```

结果：

```text
48 passed in 5.07s
```

完整 Gate 1 相关单元回归：

```text
tests/unit/scripts/test_gate1_collectors.py
tests/unit/scripts/test_gate1_evidence.py
tests/unit/scripts/test_gate1_plots.py
tests/unit/scripts/test_gate1_preflight.py
tests/unit/scripts/test_gate1_prepared_evidence.py
tests/unit/scripts/test_experiment_scripts.py
```

最终结果：

```text
75 passed in 17.03s
```

### 回归结果

| 检查 | 结果 | 证据状态 |
|---|---|---|
| `uv lock --check` | Resolved 70 packages in 2ms | `VERIFIED` |
| Ruff format 全仓 | 220 files already formatted | `VERIFIED` |
| Ruff lint 全仓 | All checks passed | `VERIFIED` |
| strict mypy | 110 source files，无问题 | `VERIFIED` |
| Gate 1 定向回归 | 75 passed in 17.03s | `VERIFIED` |
| 非 integration 全量 | 307 passed，6 deselected in 22.36s | `VERIFIED` |
| integration 标记收集 | 6 skipped，307 deselected in 2.45s | `NOT_RUN` |
| Alembic heads | `20260729_0008 (head)` | `VERIFIED` |
| Alembic history | 单线历史到 `20260729_0008` | `VERIFIED` |
| Alembic offline SQL | 完整生成，无错误 | `VERIFIED` |
| Docker CLI | 当前 shell 不存在 | `NOT_RUN`（环境前置条件） |
| Docker build / Compose smoke | 未执行 | `NOT_RUN` |
| 正式 500-case / 32-arm | 未启动 | `NOT_RUN` |
| 长时间 soak / 破坏性故障注入 | 未启动 | `NOT_RUN` |

真实服务测试的 6 个 skip 原因仍是没有设置 `EVALOPS_RUN_INTEGRATION=1` 且没有提供已迁移
PostgreSQL/Redis。它们不能写成 passed，也不表示业务断言失败。

### 本次证明了什么

- 空 scrape 不再产生 `VERIFIED 0`；
- 成功 scrape 中缺失目标不再产生数字；
- before/after 单侧缺失不再用 0 补齐；
- 指标存在且 delta=0 能明确表示为 `OBSERVED_ZERO/VERIFIED/0`；
- 指标存在且 delta>0 能明确表示为 `OBSERVED_VALUE`；
- endpoint、非法格式、重复、非法 label、NaN/Inf 都不会产生 VERIFIED 数字；
- required 与 optional 的缺失/失败映射不同；
- claim/result/Redis 必需证据缺失会令 arm 不可用于容量比较；
- 多 Worker 必须逐 source 完整，不会由一个 Worker 的序列代表全体；
- 新结果带 schema v2；
- 旧 `evidence` 字段仍保留；
- raw endpoint failure reason code 会被保存；
- 没有更改数据库或历史 migration；
- 没有运行正式实验、没有改变 Worker 数、没有生成容量数字。

### 仍未证明什么

- 没有真实 Docker/Compose scrape；
- 没有证明 API/Worker/Reaper 实际 endpoint 在本机都可访问；
- 没有真实多 Worker 的 source 覆盖结果；
- 没有真实 PostgreSQL/Redis integration 执行；
- 没有正式 500-case、32-arm、吞吐、p95/p99 或资源曲线；
- 没有证明生产 Prometheus service discovery；
- 没有运行容器重启后的 counter reset 场景；
- 同 container identity 下 cumulative counter decrease 仍会使 arm fail closed，而不是生成
  可比较 metric；
- source role 判断依赖 collector 自己生成的 `service-containerid` key；若未来改变 key 格式，
  必须先升级协议和测试；
- result schema v1 的历史零值仍然是不可恢复的歧义证据；
- P1-3 的 finalization 原子发布尚未开始；
- image digest、完整 build-context、SSRF 和 artifact ownership 等后续 P1 finding 尚未处理。

### 对旧 prepared evidence 的影响

仓库内两个旧 bundle 仍是：

- `gate1-plan-c72e8c5-20260729T150959Z`：prepared manifest schema v1；
- `gate1-plan-e21c31c-20260729T162352Z`：prepared manifest schema v1。

P1-1 已经决定它们只读保留、不可执行。本阶段没有改写其中任何文件。

P1-2 又修改了：

- `scripts/gate1_collectors.py`；
- `scripts/gate1_evidence.py`；
- `scripts/gate1_plots.py`；
- `scripts/run_load_test.py`；
- frozen protocol。

因此，即使外部存在基于 `003b29c` 生成的 prepared manifest schema v2 bundle，当前 P1-1
verifier 也应通过 source commit、execution-script SHA 或 protocol SHA 将其拒绝。正确做法
是在 `fdae758` 或后续目标 commit 的干净、独占工作区重新 prepare，不得原地补 hash。

新结果 artifact：

- 只生成 result schema v2；
- schema v1 结果保持只读；
- 不覆盖旧结果；
- 不尝试把旧 `VERIFIED 0` 自动迁移为 OBSERVED_ZERO；
- 若必须读取 v1，只能标注其“缺失与真零不可区分”的限制，不能用于正式证据升级。

### 简历与面试表述

可以表述为：

> 在多租户异步 AI 评测平台的 Worker 扩展实验中，我通过 TDD 修复了 Prometheus collector
> 把缺失序列默认成 `VERIFIED 0` 的证据污染问题。我建立了
> `OBSERVED_ZERO / MISSING / COLLECTION_FAILED` 语义，冻结 per-service label/source
> 合同，拒绝重复与 NaN/Inf，并让 claim/result/Redis 必需证据缺失时 fail closed，
> 同时把新实验结果升级为 schema v2、保留旧 artifact 只读。

更简短的简历条目：

> Hardened evidence-first load-test collectors with explicit missing/failure semantics,
> per-replica completeness checks, schema-versioned artifacts, and TDD regression coverage,
> preventing absent Prometheus series from being reported as verified zero.

不能表述为：

- 已验证 500-case 性能；
- 已证明 8 Worker 优于 1 Worker；
- 已完成生产容量认证；
- 已验证真实多副本 Prometheus；
- 已完成 Gate 1；
- 已完全解决所有实验 artifact 原子性问题。

## P1-2 阶段结论与停止点

P1-2 的 RED → GREEN → 必要重构 → 定向测试 → 全仓回归 → 协议 → 实现提交已经完成。

回滚边界：

- `git revert fdae758` 可回滚 P1-2 实现、测试和协议；
- 不需要数据库 downgrade；
- 没有远端 push 或 PR；
- 没有正式运行结果需要删除；
- 历史 bundle 未被修改。

当前代码已经消除了已复现的 `MISSING -> VERIFIED 0` 路径，但正式 Gate 1 仍不能运行：

1. P1-3 finalization 部分发布风险尚未修复；
2. P1-4/P1-5 镜像与 build-context 不可变绑定尚未完成；
3. 当前机器没有 Docker/PostgreSQL/Redis 实验环境；
4. 必须在所有阻断 finding 修复并再次确认后，重新 prepare 新 bundle。

本阶段停止在 P1-3 之前。

## P1-3：Gate 1 finalization 整体防止部分发布

### 阶段时间、起点与边界

- 执行日期：2026-07-30；
- 起始分支：`codex/gate1-evidence-hardening`；
- 起始 HEAD：`312c5971e9a1f1be7704e2d7c43cf9da7353ca90`；
- P1-3 实现提交：
  `67779aea2f3f78c19ed1a8275eb24ace4f1e450e`；
- 提交说明：`fix(gate1): publish final evidence atomically`；
- 本阶段没有 push、没有 PR、没有修改 Worker 数量；
- 没有运行正式 500-case/32-arm，没有生成或覆盖正式容量结果；
- 没有进入 P1-4 的 image digest，也没有提前处理后续 P1 finding。

开始前重新核对了 P1-3 指令。`staging + validate + publish` 对这个问题是合适的，但不能只把
五张 PNG 放进 staging：旧执行器在 arm 执行期间已经逐个写入根级 `raw/<arm_id>/` 和
`summary/<arm_id>.json`。如果继续把这些根级路径称为“正式结果”，无论图片怎么原子化，
仍然可能存在半套正式 bundle。因此先明确了两个不同状态：

- 根级 `raw/` 和 per-arm `summary/`：执行期工作证据，可以逐步形成；
- `<run_id>/final/`：唯一正式发布目录，只有完整目录一次出现才表示发布成功。

这是本阶段最重要的设计判断。已有 run 根目录在 prepare 阶段就存在，无法再用一次 rename
原子替换整个 run；而分别 rename `raw/`、`summary/`、`plots/` 又会重新产生多个提交点。
把全部正式 payload 收敛到一个新的 `final/` 目录，才有一个明确、可测试的 commit point。

### 修改前证据

修改前的入口是 `scripts/run_load_test.py::finalize_gate1_run_evidence`，执行顺序为：

```text
检查 aggregate/CSV/plot 目标是否存在
  -> 写 summary/aggregate.json
  -> 写 summary/arms.csv
  -> 写 plots/throughput.png
  -> 写 plots/latency.png
  -> 写 plots/queue_and_claim.png
  -> 写 plots/database.png
  -> 写 plots/cpu_and_rss.png
  -> 写 plots/manifest.json
```

`scripts.experiment_support.write_report` 对单个 JSON 使用 `.tmp -> replace`，只能保证一个
JSON 文件不会写一半；它不能把 JSON、CSV 和多张 PNG 组合成一个文件系统事务。

原测试只证明：

- 所有文件均成功时能生成表格和图片；
- 在写入前已经发现某张旧图时会拒绝覆盖。

原测试没有覆盖“预检已经通过，但第 N 个文件才失败”的窗口，也没有 hash 复验、文件数量
复验、跨文件系统、重复 finalize 或并发 finalize。因此原测试通过并不能证明 bundle
整体原子。

### TDD 第一个 tracer：第 1 张图之后失败

先给 `matplotlib.figure.Figure.savefig` 的第二次调用注入 `OSError`。第一次调用会真正写完
`throughput.png`，第二次在 `latency.png` 写入期间失败。测试同时记录调用前根目录的逐文件
字节快照。

最初尝试：

```text
uv run pytest ...
```

失败原因为当前 PowerShell 的 `PATH` 中没有 `uv`。这不是产品 RED，不能作为代码缺陷证据。
随后定位到项目虚拟环境，改用：

```text
.\.venv\Scripts\python.exe -m pytest \
  tests/unit/scripts/test_gate1_plots.py::test_gate1_finalization_failure_after_first_plot_leaves_working_evidence_unchanged
```

真实 RED 为：

```text
1 failed
```

失败后的目录比调用前多出：

- `summary/aggregate.json`；
- `summary/arms.csv`；
- 完整的 `plots/throughput.png`；
- 0 字节的 `plots/latency.png`。

这证明部分发布风险可以稳定复现。第一步最小 GREEN 是在 run 所在文件系统内创建
`.gate1-final-*` staging，将 aggregate/CSV/plots 全写入 staging，成功后才 rename 为
`final/`，异常时在 `finally` 清理 staging。结果：

```text
1 passed
```

此时只证明了图中途失败不会污染根目录，还没有宣称正式 bundle 已经完整。

### TDD 第二个 tracer：成功路径必须发布完整 bundle

第二条测试要求成功后的 `final/` 同时包含：

- 每个 arm 的全部 raw 文件；
- 每个 arm 的 result schema v2 summary；
- `summary/aggregate.json`；
- `summary/arms.csv`；
- 五张 PNG；
- `plots/manifest.json`；
- 根级 `manifest.json`，列出每个 payload 的 SHA-256 和字节数。

RED 为：

```text
1 failed
```

首个明确失败点是 `final/raw/io-w1-r1/jobs.json` 不存在。这说明“只把汇总与图片放入 staging”
仍不是完整 bundle。

GREEN 增加：

1. 将根级 `raw/` 完整复制到 staging；
2. 只复制本次 `summary_records` 对应的 per-arm summary，避免混入根级旧 aggregate/CSV；
3. 在所有表格和图片生成后枚举 payload；
4. 为每个 payload 写入 SHA-256 与 `size_bytes`；
5. bundle manifest 自身不做自哈希，避免循环定义。

结果：

```text
2 passed
```

### 完整故障矩阵：先 RED，再补验证与并发语义

随后一次写全 P1-3 剩余矩阵。第一次运行结果：

```text
5 failed, 10 passed
```

五个仍然存在的真实缺口为：

| 缺口 | RED 表现 |
|---|---|
| staging 与 final 不同文件系统 | finalizer 没有 `staging_parent`/设备校验合同，直接 `TypeError` |
| hash 复验失败 | SHA-256 只计算一次，第二次返回不同值也没有异常 |
| 文件数不完整 | manifest 写完后删除一张图，仍然发布 |
| summary 交叉引用不一致 | `io-w1-r1.json` 内写成另一个 arm，仍然发布 |
| 两个并发 finalize | 只有一个成功，但失败方泄漏底层 `FileExistsError` |

同一批测试中已经通过的场景说明最初 staging 修复具有正确的泛化效果：

- 第 1 张图后失败；
- 第 3 张图后失败；
- aggregate summary 写入失败；
- plot manifest 写入失败；
- 已存在一个 partial `final/` 文件；
- 已存在 complete `final/`；
- 重复 finalize。

为关闭五个缺口，实现了：

1. 用 `os.stat(...).st_dev` 在任何 staging 写入前检查 staging parent 与 run/final parent；
2. 用 run-local `.gate1-finalize.lock` 原子目录锁串行化 finalize；
3. 锁后再次检查 `final/`，验证后、rename 前第三次检查 `final/`；
4. 写完 manifest 后重新读取 manifest，而不是信任内存对象；
5. 重新枚举实际 payload，要求 manifest 数量、manifest key 集合和磁盘文件集合完全相等；
6. raw 顶层目录必须与 arm 集合完全相等，并且每个 arm 至少有一个 raw 文件；
7. 非 raw payload 必须精确等于 per-arm summary、aggregate、CSV、五图和 plot manifest；
8. per-arm summary 必须是 result schema v2、arm ID 正确，并与传入 record 完全相等；
9. aggregate 必须与重新执行 `aggregate_arm_summaries(summary_records)` 的结果完全相等；
10. CSV arm 顺序必须与本次 records 相等；
11. plot manifest 的 schema、arm、plot 清单、points 和 line-series 交叉引用必须一致；
12. 每张图必须具有 PNG signature；
13. 每个 manifest path 必须是安全相对 POSIX 路径；
14. 禁止 final bundle 中出现 symlink；
15. 对每个 payload 重新计算字节数与 SHA-256；
16. rename 的文件系统异常统一映射为受控的 `ExperimentError`；
17. 任意异常路径都清理本次 staging 和 finalization lock。

完整矩阵转为：

```text
15 passed
```

随后增加单独的 per-arm summary schema v1 拒绝测试，并把非 raw 文件集合从“包含 required”
收紧为“精确等于 required”。最终 P1-3 artifact 测试为：

```text
16 passed in 8.64s
```

### 为什么 final-bundle schema 是 v1，而 result schema 仍是 v2

P1-2 升级的 result schema v2 描述指标语义，尤其是 `OBSERVED_ZERO / MISSING /
COLLECTION_FAILED`。P1-3 新增的是另一种合同：bundle 的目录、文件列表、hash 和发布方式。

因此没有把指标结果再机械升级为 v3，而是建立独立版本轴：

```json
{
  "schema_version": 1,
  "result_schema_version": 2,
  "status": "complete",
  "hash_algorithm": "sha256",
  "publication_method": "same_filesystem_atomic_directory_rename",
  "arm_ids": ["..."],
  "file_count": 0,
  "files": {
    "relative/path": {
      "sha256": "...",
      "size_bytes": 0
    }
  }
}
```

这样后续可以独立升级布局合同或指标合同，不会把两个概念混在同一个版本号里。

### 重构判断

第一版 GREEN 直接写在 `run_load_test.py`，使 runner 一次增加 400 多行。继续保留会把：

- 实验编排；
- bundle 构建；
- 完整性验证；
- 文件系统发布；

放在同一个大文件中。完成行为 GREEN 后执行纯重构，新增
`scripts/gate1_finalization.py`，对外保留：

- `finalize_gate1_run_evidence(...)`；
- `validate_gate1_final_bundle(...)`。

`run_load_test.py` 只导入并调用 finalizer。重构前后矩阵均为 `15 passed`，之后加 schema
测试成为 16 条。新模块被加入 `KEY_EXECUTION_SCRIPT_PATHS`，因此 finalization 实现改变时，
P1-1 verifier 会通过 execution-script SHA-256 拒绝旧 prepared bundle。

### 文件级修改及原因

| 文件 | 修改 | 原因 |
|---|---|---|
| `scripts/gate1_finalization.py` | 新增 staging、manifest、复验、锁和原子 rename | 把正式发布做成一个深模块 |
| `scripts/run_load_test.py` | 删除旧逐文件 finalizer，导入新入口 | runner 只负责编排 |
| `scripts/gate1_prepared_evidence.py` | 新模块加入关键执行脚本 hash | prepared evidence 必须绑定真正执行的 finalizer |
| `tests/unit/scripts/test_gate1_plots.py` | 加入完整成功合同和全部失败矩阵 | 证明失败不留下新 partial formal bundle |
| `tests/unit/scripts/test_experiment_scripts.py` | 更新关键脚本期望 | 与 prepared manifest 生产者一致 |
| `scripts/worker_scaling_protocol.md` | 冻结工作证据/正式 bundle 边界与发布步骤 | 防止未来把根级 partial 误认成正式结果 |
| `docs/gate_1_execution_log.md` | 更新输出树与 `NOT_RUN` 路径 | 文档与新合同一致 |

没有修改数据库模型、migration、API、Worker、Reaper 或历史 `docs/results/`。

### 遇到的问题、判断与处理

#### 1. 当前 shell 找不到 `uv`

`uv run pytest` 报命令不存在。改用仓库 `.venv` 中的 Python 运行测试。锁文件检查时定位到：

```text
.\.codex-tools\Scripts\uv.exe
```

#### 2. uv 默认缓存 ACL 拒绝

`uv lock --check` 首次访问：

```text
C:\Users\xuan\AppData\Local\uv\cache
```

时收到 Windows `Access is denied`。改用仓库已有 `.uv-cache`：

```powershell
$env:UV_CACHE_DIR = (Join-Path (Get-Location) '.uv-cache')
.\.codex-tools\Scripts\uv.exe lock --check
```

结果为：

```text
Resolved 70 packages in 2ms
```

#### 3. Gate 1 定向回归第一次为 83 passed、2 failed

一个失败是测试仍硬编码旧关键脚本清单，加入 `gate1_finalization.py` 后更新期望即可。

另一个失败来自测试运行位置：临时 Git 仓库创建在主仓库的 `.pytest-tmp-*` 内，测试移走
内层 `.git` 后，Git 会向上发现主仓库，于是返回 `SOURCE_MISMATCH`，不是期望的
`ENVIRONMENT_BLOCKED`。将 `--basetemp` 放到系统临时目录后，同一测试通过：

```text
1 passed
```

这证明是嵌套临时仓库隔离问题。本阶段没有借机改变 P1-1 verifier 的生产语义。最终 Gate 1
定向回归使用主仓库外 basetemp：

```text
85 passed in 23.96s
```

#### 4. 格式化检查发现一处机械缩进

新增关键脚本期望时缩进需要 Ruff formatter 调整。格式化后全仓复查通过，没有手工改变
测试语义。

#### 5. `git diff --check` 在长组合命令末尾偶发报告不在仓库

同一轮组合命令中的 uv、Ruff 和 mypy 都完成，但末尾 `git diff --check` 一次报告
`Not a git repository`。在明确指定工作目录的独立命令中立即复跑，`git diff --check`、
`git status` 和 `git diff --stat` 均正常。这没有被误写为产品失败。

### 最终验证证据

#### 静态与依赖

| 检查 | 结果 | 证据状态 |
|---|---|---|
| `uv lock --check` | 70 packages，2 ms | `VERIFIED` |
| Ruff format 全仓 | 221 files already formatted | `VERIFIED` |
| Ruff lint 全仓 | All checks passed | `VERIFIED` |
| strict mypy | 105 source files，无问题 | `VERIFIED` |
| `git diff --check` | 无 whitespace error | `VERIFIED` |

#### 测试

| 测试 | 结果 | 证据状态 |
|---|---|---|
| P1-3 finalization/plot artifact 定向 | 16 passed in 8.64s | `VERIFIED` |
| Gate 1 定向回归 | 85 passed in 23.96s | `VERIFIED` |
| 非 integration 全量 | 318 passed，6 deselected in 49.07s | `VERIFIED` |
| integration 标记 | 6 skipped，318 deselected in 1.67s | `NOT_RUN` |

六个 integration skip 的原因仍是没有设置 `EVALOPS_RUN_INTEGRATION=1`，并且没有提供已迁移
的真实 PostgreSQL/Redis。它们不能写成 passed。

#### Migration 与运行环境

| 检查 | 结果 | 证据状态 |
|---|---|---|
| Alembic heads | `20260729_0008 (head)` | `VERIFIED` |
| Alembic history | 单线从 base 到 `20260729_0008` | `VERIFIED` |
| Alembic offline SQL | 374 行，成功生成到 head | `VERIFIED` |
| Docker CLI | 当前 shell 不存在 | `NOT_RUN` |
| Docker build / Compose smoke | 未执行 | `NOT_RUN` |
| 正式 500-case / 32-arm | 未执行 | `NOT_RUN` |
| 长时间 soak / 破坏性故障 | 未执行 | `NOT_RUN` |

### 本阶段已经证明什么

- 第 1 或第 3 张图之后失败不会留下新 `final/`；
- summary 或 plot manifest 写入失败不会留下新 `final/`；
- partial/complete 旧 `final/` 都不会被覆盖；
- 重复 finalize 不会改变已发布 bundle；
- 两个线程并发 finalize 时恰好一个成功，另一个得到受控错误；
- staging 与 final 的设备号不同时会在写入前拒绝；
- manifest 写完后 payload hash 改变会在发布前失败；
- manifest 写完后文件减少会在发布前失败；
- per-arm、aggregate、CSV 和 plot manifest 的 schema/arm 引用会复验；
- 成功发布的 bundle 为 bundle schema v1，内部结果保持 result schema v2；
- 正式发布只有一个目录 rename commit point；
- 根级工作证据不会再被文档误称为完整正式结果；
- 失败清理不会删除或改写已有 formal bundle；
- 新 finalization 代码已进入 prepared evidence 的不可变脚本 hash。

### 本阶段仍未证明什么

- 没有真实 500-case/32-arm 数据，不能得出任何容量或 Worker 数建议；
- 没有 Docker/Compose，未证明容器内 Matplotlib/dev 运行环境；
- 跨文件系统拒绝使用 `st_dev` 故障注入验证，本机没有使用第二个真实可写文件系统做实测；
- 并发测试证明了同一进程两个线程；没有做多进程、跨主机或网络文件系统测试；
- `finally` 可以清理普通异常；进程被强制终止或机器断电时可能留下隐藏 staging 或 stale
  lock，但仍不会把 staging 命名成 `final/`；
- 没有加入目录 `fsync`，因此没有声明断电级持久性保证；
- P1-4 的不可变 image digest 尚未开始；
- 后续 build-context、SSRF、artifact ownership 等 finding 尚未处理。

### 对旧 artifact 与 prepared evidence 的影响

- 历史 result schema v1/v2 artifact 没有被原地修改；
- 历史目录中没有新增 `final/`，也没有自动迁移；
- 新的 final-bundle schema v1 只适用于今后重新执行产生的 `final/`；
- 本提交修改了 protocol、runner、关键脚本列表，并新增 finalization 模块；
- 因此任何在 `67779ae` 之前 prepare 的 bundle 都应被 source commit、protocol SHA 或
  execution-script SHA 拒绝；
- 正确流程是在所有阻断 P1 finding 完成后，从干净、独占、已提交的目标 HEAD 重新
  `--prepare-only`，不能给旧 manifest 手工补 hash。

### 回滚边界

- `git revert 67779aea2f3f78c19ed1a8275eb24ace4f1e450e` 可回滚 P1-3 实现、测试、协议和输出合同；
- 不需要数据库 downgrade；
- 没有正式运行结果需要删除；
- 没有远端 push 或 PR；
- 若未来已经产生 bundle，回滚代码前必须先保留其只读审计副本，不能让旧代码覆盖它。

### 简历与面试表述

可以表述为：

> Hardened an evidence-first AI evaluation finalizer with same-filesystem staging,
> manifest-driven SHA-256 revalidation, exact schema/cross-reference checks, concurrency
> exclusion, and atomic directory publication, preventing failed runs from exposing
> partial formal evidence bundles.

不能表述为：

- 已完成 Gate 1 容量认证；
- 已证明某个 Worker 数最优；
- 已在真实多机或网络文件系统证明原子性；
- 已完成镜像 digest/build-context 绑定；
- 已运行正式性能矩阵；
- 已解决所有 P1 finding。

## P1-3 阶段结论与停止点

P1-3 的修改前审计、RED → GREEN、完整失败矩阵、必要重构、冻结协议、静态检查、Gate 1
定向回归、非 integration 全量回归和本地实现提交已经完成。

当前停止在 P1-4 之前。正式 Gate 1 仍不能运行，因为：

1. P1-4 image digest 不可变绑定尚未完成；
2. 后续 build-context 与其他阻断 finding 尚未完成；
3. 当前机器没有 Docker/PostgreSQL/Redis 正式实验环境；
4. 必须等所有阻断项完成后，从最终干净提交重新 prepare 新 bundle。

---

## P1-4：不可变本地镜像身份、构建来源与运行容器绑定

日期：2026-07-30

实现提交：

```text
243883ab7e7d4d33e9c2e4d819706114de898aab
fix(gate1): bind prepared runs to immutable images
```

阶段状态：`IMPLEMENTED_AND_CONTRACT_VERIFIED / REAL_DOCKER_NOT_RUN`。

### 接到阶段指令后的适合性判断

进入 P1-4 前没有直接照抄建议实现，而是先检查它是否适合当前仓库。结论是：风险真实、
优先级合理，但必须把“registry digest”和“本地 Docker image ID”分开，不能因为两者都
长得像 `sha256:...` 就混写证据等级。

修改前的证据为：

| 位置 | 修改前事实 | 风险 |
|---|---|---|
| `deploy/compose.yaml` | 应用服务共用 `ai-evalops-platform:phase9` 可变标签 | 同一个 tag 可在准备后指向另一张镜像 |
| `Dockerfile`/构建流程 | 没有在构建命令中写 revision/source/created 与输入 hash 标签 | 无法从运行容器反查源码和构建输入 |
| prepared manifest schema v2 | 没有 `provenance.image` | bundle 不绑定实际执行镜像 |
| `collect_preflight` | 只调用 `docker compose images --quiet` 收集一组 ID | 没有逐个绑定正在运行的 API/Worker/Reaper |
| Compose project | 依赖目录推导默认 project name | 从不同目录启动会改变 project identity |
| build context | verifier 只找 dirty path，没有冻结整体 context fingerprint | 干净路径集合相同也不能证明内容相同 |

因此采用以下设计：

1. 当前流程没有 registry push/pull，所以使用 Docker 本地不可变 image ID；
2. 证据状态只能写 `LOCAL_IMAGE_ID_VERIFIED`；
3. `registry_digest` 必须为 `null`，不能写 `REGISTRY_DIGEST_VERIFIED`；
4. human-readable repository/tag 仍保留给人阅读，但安全判断只信 immutable ID；
5. prepared manifest 升级到 schema v3，旧 v1/v2 继续历史只读，不做静默迁移；
6. `--prepare-only` 允许一个受限副作用：构建并 inspect 镜像；不启动服务、上传 Dataset、
   缩放 Worker 或启动 formal arm；
7. P1-4 只建立当前 `docker-context-sha256-v1` 合同；Dockerignore 完整语义、symlink、
   secret/ignore precedence 留给 P1-5，不提前宣称完成。

### 冻结后的 image binding

新 manifest 的 `provenance.image` 至少绑定：

```json
{
  "identity_kind": "LOCAL_IMAGE_ID",
  "verification": "LOCAL_IMAGE_ID_VERIFIED",
  "repository": "ai-evalops-platform",
  "tag": "phase9",
  "reference": "ai-evalops-platform:phase9",
  "immutable_id": "sha256:<64 hex>",
  "registry_digest": null,
  "compose_project": "ai-evalops-platform",
  "source_commit": "<40 hex>",
  "source": "https://github.com/godofxuan/ai-evalops-platform",
  "dockerfile_sha256": "<64 hex>",
  "build_context": {
    "algorithm": "docker-context-sha256-v1",
    "sha256": "<64 hex>",
    "file_count": 0
  },
  "build": {
    "created": "<UTC timestamp>",
    "image_created": "<docker inspect timestamp>"
  },
  "runtime": {
    "python": "3.12.13",
    "os": "linux",
    "architecture": "amd64"
  },
  "labels": {
    "org.opencontainers.image.revision": "<source commit>",
    "org.opencontainers.image.source": "<repository URL>",
    "org.opencontainers.image.created": "<UTC timestamp>",
    "io.ai-evalops.dockerfile.sha256": "<Dockerfile SHA>",
    "io.ai-evalops.build-context.sha256": "<context SHA>",
    "io.ai-evalops.python.version": "3.12.13"
  }
}
```

manifest 校验不只检查“这是一个字典”。上述字段会做格式校验，并做以下交叉绑定：

- image source commit 必须等于 manifest provenance source commit；
- image Dockerfile SHA 必须等于 provenance Dockerfile SHA；
- revision/source/created 标签必须等于 image 对应字段；
- Dockerfile/context/Python 标签必须等于 image 对应字段；
- LOCAL identity 下 `registry_digest` 只能为 `null`；
- build 时间必须是可解析的 UTC `Z` 时间；
- runtime Python 必须等于 Dockerfile 当前冻结版本 `3.12.13`。

### RED → GREEN 详细记录

| 步骤 | RED 观察 | 判断与最小修改 | GREEN 效果 |
|---|---|---|---|
| 1 | 新测试导入 `scripts.gate1_image_evidence` 失败 | 先建立独立模块，不把镜像安全逻辑继续塞入 runner | 模块可导入，同 tag/不同 ID 有独立比较入口 |
| 2 | 同 tag、不同 image ID 仍可能被当作可运行 | 只比较三个应用服务的 `.Image` 与 manifest immutable ID | 返回 `IMAGE_ID_MISMATCH` |
| 3 | revision 不同仍 ready | 加入 `org.opencontainers.image.revision` 精确比较 | 返回 `IMAGE_REVISION_MISMATCH` |
| 4 | revision 缺失与“不匹配”混成一个状态 | 单独记录标签存在性 | 返回 `IMAGE_REVISION_LABEL_MISSING` |
| 5 | 来自其他 Compose project 的容器仍通过 | 检查 `com.docker.compose.project` | 返回 `COMPOSE_PROJECT_MISMATCH` |
| 6 | Dockerfile/context 标签与 manifest 不同仍通过 | 加入两个 build-input 标签比较 | 返回 `IMAGE_BUILD_INPUT_MISMATCH` |
| 7 | 成功路径只返回泛化 `READY` | 明确 identity kind 与成功证据等级 | 返回 `LOCAL_IMAGE_ID_VERIFIED`，没有 registry 声明 |
| 8 | manifest 删除 `provenance.image` 后 verifier 仍 `READY` | schema 升到 v3，并把 image 设为必需 | 返回 `MANIFEST_INVALID` |
| 9 | producer 测试读取不到 image | `prepare_load_experiment` 调用镜像绑定边界并写入 manifest | producer 合同转绿 |
| 10 | build context 新增未跟踪 Python 时只走到“未实现”错误 | 构建前读取 Git porcelain，并按 `.dockerignore` 过滤 | 明确拒绝 `app/untracked_image_input.py` |
| 11 | 完整构建合同仍报 `image build binding is not implemented` | 实现 build、labels、inspect、immutable ID 与 runtime 读取 | 冻结 ID/标签/runtime 测试通过 |
| 12 | 正式 `collect_preflight` 不接受 `expected_image` | 将 manifest image 传入正式预检，inspect Compose 的具体容器 | 环境全通过但 ID 不同时返回 `IMAGE_ID_MISMATCH` |
| 13 | 畸形 image 字典仍被 verifier 判为 `READY` | 增加字段格式和跨字段一致性校验 | 缺 repository/tag/ID/hash/time/runtime/labels 均 `MANIFEST_INVALID` |
| 14 | 执行前新增 Python 只显示 dirty path，没有整体 hash 差异 | 用构建阶段同一算法重算 context | 同时得到 `docker_build_context_clean=false` 与 context hash mismatch |
| 15 | 已跟踪 Dockerfile 修改没有在 build 前被拒绝，而是继续找 Docker | Git 状态判断扩展到 staged/unstaged/tracked/untracked/ignored | 在调用 Docker 前拒绝未记录 Dockerfile 输入 |
| 16 | image build 失败后留下无 manifest 的 run 目录 | 把 Git/构建/inspect/hash 全部前置，成功后才建 run 目录 | 失败不留下半成品 run 目录 |
| 17 | 模拟 `docker build` 期间修改 Python 后仍进入 image inspect | 构建后重新计算 Git 状态和 context fingerprint | 返回 `build context changed during image build` |

### 为什么正式 preflight 不再使用 `docker compose images --quiet`

`docker compose images --quiet` 返回的是 Compose 相关镜像集合，不足以回答“哪个具体容器
正在运行哪张镜像”。新流程为：

```text
docker compose ps --format json
  -> 取 API/Worker/Reaper 的具体 container ID
  -> docker inspect <container ID>
  -> 读取 .Image、.Config.Image、受控标签
  -> 与 manifest image binding 精确比较
```

preflight 输出只保存经筛选的：

- service；
- container ID；
- image reference；
- immutable image ID；
- revision；
- Compose project。

不会把容器的任意环境变量或完整 labels 原样写入证据，避免把潜在秘密扩散到
`preflight.json`。

镜像检查成为六个必需 check：

```text
identity_kind_supported
container_image_ids_match
image_revision_labels_present
image_revision_labels_match
compose_project_matches
image_build_input_labels_match
```

状态优先级为：

1. source commit 错误；
2. tracked worktree/build context 错误；
3. Docker/Compose/必需服务不可检查；
4. 具体 image identity/revision/project/build-input 错误；
5. 凭据存在性、磁盘和人工 gate 等其余环境 blocker；
6. 全部通过才是 `READY`。

这样 Docker 本身不存在时仍得到 `ENVIRONMENT_BLOCKED`，不会被空容器列表误写成
`IMAGE_ID_MISMATCH`；当环境可检查时，镜像错误又不会被泛化状态吞掉。

### 文件级修改及原因

| 文件 | 修改 | 原因 |
|---|---|---|
| `scripts/gate1_image_evidence.py` | 新增 context fingerprint、Git clean gate、镜像 build/inspect、manifest schema、运行容器比较 | 将镜像证据做成单一安全边界 |
| `scripts/run_load_test.py` | prepare 生成 image binding；execute 传入 expected image；失败前不创建 run 目录 | 正式 producer/consumer 接线并避免半成品 |
| `scripts/gate1_prepared_evidence.py` | schema v3、image 跨字段校验、执行前 context 重算、新模块脚本 hash | prepared bundle fail-closed |
| `scripts/gate1_preflight.py` | inspect 具体容器、六项必需检查、具体失败状态、筛选后的 runtime evidence | 证明运行对象而不是只看 tag |
| `deploy/compose.yaml` | 顶层固定 `name: ai-evalops-platform` | 稳定 Compose project identity |
| `scripts/worker_scaling_protocol.md` | 冻结 schema v3、本地 ID 语义、prepare 副作用和运行容器检查 | 让每个新 bundle 带正确协议 |
| `docs/gate_1_execution_log.md` | 更新 prepare/preflight 流程与 P1-4 `NOT_RUN` 边界 | 防止历史说明误导执行者 |
| 四个单测文件 | 增加镜像、manifest、preflight、失败清理和竞态矩阵；外部 Docker 用边界替身 | 通过可复现 RED/GREEN 证明合同 |

新 `gate1_image_evidence.py` 已加入 `KEY_EXECUTION_SCRIPT_PATHS`。以后该安全实现发生任何
修改，旧 prepared bundle 会因 execution-script SHA 不一致被拒绝。

### 遇到的问题、为什么发生、怎样处理

#### 1. 当前 PowerShell 找不到 `uv`

最初执行：

```text
uv run pytest ...
```

得到 `CommandNotFoundException`。这不是产品 RED。仓库已有 `.venv`，因此后续统一使用：

```text
.\.venv\Scripts\python.exe -m pytest ...
```

没有安装新工具或改动依赖。

#### 2. 旧 `.pytest-tmp` 在 Windows 上拒绝清理

pytest 在 fixture 初始化前收到 `WinError 5`，测试体没有执行。没有强删、改 ACL 或把它
冒充产品失败，而是为每次运行使用系统临时目录下的唯一 `--basetemp`，并关闭 pytest
cacheprovider。随后同一测试真实运行并通过。

#### 3. subprocess 替身意外影响 `platform.platform()`

正式 preflight 集成测试替换了 `subprocess.run`。Windows 的 `platform.platform()` 内部
也会执行 `ver`，于是替身报告 unexpected command。判断为测试隔离问题，固定测试平台值
`test-platform`，没有修改生产平台采集语义。

#### 4. 新外部 Docker 边界让旧 prepare 单测尝试真实构建

这些测试的目标是 Dataset、manifest、状态机或 hash，不是 Docker daemon。为它们注入
结构完整、使用真实 Dockerfile/context hash 的 fake local image binding；真实 builder
继续在独立测试中模拟 Docker CLI 并验证命令、labels、inspect 和 runtime，没有把核心
逻辑整体 mock 掉。

#### 5. Ruff 与 mypy

Ruff 首次报告 3 处 import order 和 5 个文件的机械格式；自动修复后全仓通过。mypy 唯一
问题是通过布尔变量间接判断 timestamp 为字符串时无法完成类型收窄；改为在
`isinstance(str)` 分支内解析，运行语义不变，strict mypy 转绿。

#### 6. 文档合同仍写 schema v2

代码升级到 v3 后检查冻结协议，发现仍写“Only manifest schema v2 is executable”。
如果不修，未来可能按错误协议解释 bundle。更新协议和执行日志后重新跑 56 条定向测试。

#### 7. 当前机器没有 Docker

最终探测结果：

```text
DOCKER_UNAVAILABLE
```

因此没有真实运行 `docker build`、`docker image inspect`、`docker compose config/up`
或容器 smoke。所有 Docker 命令路径都通过受控 unit boundary 测试，但证据状态只能是
`CONTRACT_VERIFIED`，真实 Docker 为 `NOT_RUN`。

### 最终验证证据

#### 定向与全量测试

| 检查 | 结果 | 状态 |
|---|---|---|
| P1-4 image/preflight/prepared/runner 定向矩阵 | 56 passed in 39.09s | `VERIFIED` |
| 非 integration 全量 | 333 passed、6 deselected in 51.46s | `VERIFIED` |
| integration 标记 | 6 skipped、333 deselected in 1.64s | `NOT_RUN` |

六个 integration skip 仍要求显式设置 `EVALOPS_RUN_INTEGRATION=1`，并提供已迁移真实
PostgreSQL/Redis。它们没有被写成 passed。

#### 静态与仓库检查

| 检查 | 结果 | 状态 |
|---|---|---|
| Ruff lint 全仓 | All checks passed | `VERIFIED` |
| Ruff format 全仓 | 223 files already formatted | `VERIFIED` |
| strict mypy | 106 source files，无问题 | `VERIFIED` |
| `git diff --check` | 无 whitespace error | `VERIFIED` |
| Docker CLI | `DOCKER_UNAVAILABLE` | `NOT_RUN` |
| Docker build / Compose smoke | 未执行 | `NOT_RUN` |
| 正式 500-case / 32-arm | 未执行 | `NOT_RUN` |

### 本阶段已经证明什么

- 同一个可变 tag 指向不同 image ID 时会被拒绝；
- revision 标签缺失和 revision 不匹配有不同状态；
- 其他 Compose project 的容器会被拒绝；
- Dockerfile/context 标签与 manifest 不同会被拒绝；
- LOCAL image ID 不会被误称为 registry digest；
- manifest 缺失或畸形 image binding 会在 Git/Docker 前失败；
- source commit、Dockerfile、context、labels 和 runtime 有跨字段绑定；
- tracked/untracked/ignored 且进入 build context 的未记录路径会在 build 前失败；
- prepare 与 execute 使用同一 context fingerprint 算法；
- build 过程中 context 变化会在 inspect 前失败；
- image build 失败不会留下半成品 run 目录；
- preflight inspect 的是具体运行容器，而不是只看 Compose 镜像集合；
- 预检证据不会原样持久化任意容器标签或环境变量；
- 新镜像证据实现本身进入 prepared execution-script hash。

### 本阶段仍未证明什么

- 没有真实 Docker daemon，未证明实际 Docker/BuildKit 输出与 mock 边界完全一致；
- 没有 registry 操作，未验证或声明 registry digest；
- 没有运行 Compose，未实测 project label、三类应用容器 ID 和 OCI labels；
- 当前 context matcher 不是 Docker/Moby `.dockerignore` 解析器的完整重实现；
- symlink 逃逸、复杂 `**`、negation precedence、escaped whitespace、特殊路径引用和
  Dockerfile-specific ignore file 仍属于 P1-5；
- 没有证明 secrets 一定不会进入所有可能的构建上下文；
- 构建前后双快照缩小了竞态窗口，但不是 BuildKit 对实际发送 tar stream 的密码学证明；
- 没有 PostgreSQL/Redis integration、正式 500-case 数据或 Worker 容量结论；
- P1-5 及 SSRF、artifact ownership 等其他 P1 finding 尚未完成。

### 对旧 artifact 与 prepared bundle 的影响

- 没有修改任何 `docs/results/` 历史 artifact；
- 没有运行正式实验，也没有生成新 plan/bundle；
- schema v1/v2 manifest 保持历史只读；
- schema v3 是唯一可执行 prepared manifest；
- 旧 bundle 不能手工补 image 字段或重写 schema 号；
- 所有阻断 finding 完成后，应从最终干净、已提交 HEAD 重新执行 `--prepare-only`；
- 因为 prepare 现在需要 Docker，本机 `DOCKER_UNAVAILABLE` 时会在创建 run 目录前失败。

### 回滚边界

```text
git revert 243883ab7e7d4d33e9c2e4d819706114de898aab
```

可回滚 P1-4 实现、测试、Compose project name、schema v3 和冻结协议。不需要数据库
downgrade；没有正式运行结果需要删除。若未来已生成 schema v3 bundle，回滚前必须先
保留只读审计副本，不能让旧代码把它当作可执行 v2 bundle。

本阶段没有 push、没有 PR。

### 简历与面试表述

可以表述为：

> Bound prepared AI evaluation runs to immutable local Docker image IDs with
> source/build-input OCI labels, manifest cross-validation, exact running-container
> inspection, fail-closed mismatch states, and pre/post-build context stability checks.

不能表述为：

- 已验证 registry digest；
- 已在真实 Docker/Compose 环境完成 smoke；
- 已完成所有 build-context hardening；
- 已运行 Gate 1 正式容量矩阵；
- 已证明某个 Worker 数最优；
- 已解决所有 P1 finding。

## P1-4 阶段结论与下一停止点

P1-4 的修改前判断、TDD RED → GREEN、manifest schema v3、不可变本地 image ID、
OCI/build-input labels、正式 preflight 接线、构建前后 context 稳定性、冻结协议、
定向/全量/静态验证和本地实现提交均已完成。

当前停止在 P1-5 之前。正式 Gate 1 仍不能运行，因为：

1. P1-5 的完整 build-context 语义与 secret/symlink 边界尚未完成；
2. 其他阻断 P1 finding 尚未完成；
3. 当前机器没有 Docker/PostgreSQL/Redis 正式实验环境；
4. 必须等所有阻断项完成后，从最终干净提交重新 prepare schema v3 bundle。

## P1-5 Build context / Git commit 一致性

### 阶段结果

P1-5 实现提交已经在本地创建：

```text
eb33de494bbda4850b7f29240dcce54146a42339
fix(gate1): audit Docker build context against Git
```

结论是 `CONTRACT_VERIFIED / REAL_DOCKER_BUILD_NOT_RUN`。本阶段没有 push、没有 PR、
没有生成新 prepared bundle、没有运行正式 Gate 1。

### 修改前先判断：应该选哪一种证明

开始前考虑了两种方案：

1. 只要求一个完全干净的 Git checkout；
2. 继续保存实际进入 Docker context 的内容指纹。

只选方案 1 的优点是简单，但不能证明两个“看起来都干净”的目录具有相同输入内容，也
无法继续校验 P1-4 已写进 OCI label 和 manifest 的 context SHA。只选方案 2 又不够：
指纹可能稳定地绑定到错误 source commit，也可能遗漏 Dockerignore precedence、
symlink 或 secret。

最终选择是组合合同：

- 保留内容指纹并升级为 `docker-context-sha256-v2`；
- tracked/staged 必须全局干净，即使路径被 Docker 排除；
- untracked/ignored 只在实际进入 context 时阻断；
- 对无法安全模拟的语法或输入类型失败关闭；
- 构建前后同时重跑审计和核对 `HEAD`。

这个选择比“把所有 ignored 文件一刀切拒绝”更可用：根 `tests/` 下的本地测试文件、
排除的 `.env.local` 和生成缓存不会无故阻断；但 `app/untracked.py`、Git 忽略却进入
context 的文件、staged 排除文件仍会阻断。

### Dockerignore 语义依据与边界

实现判断参考了：

- [Docker build context 官方文档](https://docs.docker.com/build/concepts/context/)；
- [Moby patternmatcher](https://github.com/moby/patternmatcher/blob/main/patternmatcher.go)；
- [Moby ignorefile reader](https://github.com/moby/patternmatcher/blob/main/ignorefile/ignorefile.go)。

由此冻结以下规则：

- Dockerfile 专用 ignore 比根 `.dockerignore` 优先，因此当前 manifest 只绑定根文件时，
  专用文件必须失败关闭；
- `**` 只有作为完整路径段时由本实现审计，`foo**bar` 等复合形式返回
  `unsupported_dockerignore_patterns`；
- 最后一个匹配规则决定 include/exclude，支持 negation 顺序；
- 只在原始行第一列出现的 `#` 是注释；
- 读取规则时去除 UTF-8 BOM；
- 根 `tests` 只排除根目录，不误排除 `app/tests/...`；
- 递归 cache、bytecode 和 environment 文件必须显式使用 `**/...`。

这仍然是一个明确的受测子集，不是 Moby parser 的完整重实现。文档和错误信息都保留
这个限制，没有声称完全兼容所有 escape、平台特殊路径和 glob 组合。

### 最终审计输出

公共入口 `audit_gate1_build_context(...)` 返回：

```text
status
ready
blockers
binding
details.dirty_paths
details.tracked_or_staged_paths
details.included_symlink_paths
details.dockerfile_specific_ignore_path
details.unsupported_dockerignore_patterns
details.sensitive_paths_in_context
```

状态含义：

| 状态 | 含义 |
|---|---|
| `READY` | Git 与受测 context 合同均满足 |
| `DIRTY_BUILD_CONTEXT` | tracked/staged 变化，或有 untracked/ignored 文件进入 context |
| `UNSAFE_BUILD_CONTEXT` | symlink、`.env*`、Dockerfile 专用 ignore 或不支持的模式进入安全边界 |

Git 路径不再解析 `status --porcelain` 的人类文本，而是分别使用：

```text
git diff --name-only -z --
git diff --cached --name-only -z --
git ls-files --others --exclude-standard -z
git ls-files --others --ignored --exclude-standard -z
git ls-files --stage -z
```

这样 staged、unstaged、untracked、ignored 和 index mode 各有清晰来源，NUL 分隔也不会
把非 ASCII 路径、空格、引号或 rename 箭头解析错。

### TDD RED → GREEN 逐步记录

| 步骤 | 修改前/RED 观察 | 判断与最小修改 | 达成效果 |
|---|---|---|---|
| 1 | 新测试无法 import `audit_gate1_build_context` | 先建立单一公共审计入口和 v2 算法名 | 干净仓库返回 `READY` 与 v2 binding |
| 2 | staged 的 `tests/staged_probe.py` 被 Docker 排除，所以仍 `READY` | tracked/staged 独立于 Docker exclusion 收集 | staged 排除文件返回 `tracked_or_staged_changes` |
| 3 | 根规则 `tests` 错误隐藏 `app/tests/untracked_source.py` | pattern 按完整路径段和祖先匹配 | 根规则不再误匹配任意同名 segment |
| 4 | `app/__pycache__/generated.pyc` 进入 context | 实现独立 `**` 路径段，并把 bytecode 规则改成递归 | 嵌套 bytecode 不改变 binding |
| 5 | `app/.env.local` 进入 context | `.env*` 改为 `**/.env*` | 嵌套环境覆盖被排除，结果不含秘密值 |
| 6 | Windows `Path.symlink_to` 报 `WinError 1314`，测试体未进入产品逻辑 | 不跳过；改用 Git blob + `update-index --cacheinfo 120000` 构造可移植 index symlink | 获得真实产品 RED，而不是把权限错误冒充产品失败 |
| 7 | 已提交且进入 context 的 mode `120000` 路径仍 `READY` | 读取 `git ls-files --stage -z` | 返回 `UNSAFE_BUILD_CONTEXT / included_symlinks` |
| 8 | 已提交 `Dockerfile.dockerignore` 仍 `READY` | 检查 Dockerfile 同名专用 ignore | 返回 `dockerfile_specific_ignore` |
| 9 | `foo**bar` 被近似 matcher 接受 | 只支持完整 `**` component，其余失败关闭 | 返回具体 unsupported pattern |
| 10 | 根 `tests/local_probe.py` 未跟踪 | 这是期望反例，不改产品 | 特征测试直接 GREEN，证明不会拒绝所有 untracked |
| 11 | 修改 `uv.lock` | 现有严格 tracked + context binding 已覆盖 | 特征测试直接 GREEN 并准确报告 `uv.lock` |
| 12 | builder 遇到 staged 排除文件仍继续找 Docker，最终报 Docker 不存在 | 在任何 Docker 调用前接公共审计 | 先报 context blocker，不再误报环境问题 |
| 13 | 模拟构建期间修改 excluded tracked file 后仍进入 image inspect | 构建后重跑完整审计，不只重算 included hash | inspect 前报告具体 changed path |
| 14 | prepared verifier 对同一 staged 文件同时报 worktree dirty 和 context clean | verifier 消费公共审计 `ready` 与 details | 两项检查不再互相矛盾 |
| 15 | 接入严格审计后 4 个旧测试从 `HASH_MISMATCH` 退化成泛化 `DIRTY_BUILD_CONTEXT` | 发现 tracked 文件被同时错误放进 `dirty_paths`；拆成互斥集合并恢复状态优先级 | Compose/script/Dockerfile/dockerignore 变更继续报告更精确 hash mismatch |
| 16 | `app/本地输入.py` 被记录成八进制转义片段 | 改用 NUL 分隔 Git 命令并按 UTF-8 解码 | details 精确保留非 ASCII 路径 |
| 17 | 删除 env 排除规则并提交 `.env.production` 后仍 `READY` | 只按路径检查实际 included `.env*`，不读取/回显值 | 干净提交中的环境秘密也失败关闭 |
| 18 | 传入错误的 40 位 `source_commit` 仍一路走到 Docker | 构建前读取 `git rev-parse HEAD` 并精确比较 | 错误提交在 Docker 前被拒绝 |
| 19 | 新提交绑定令 3 个模拟成功测试失败，因为它们硬编码 `bbbb...` | 不放宽产品；测试改读各自临时仓库真实 HEAD | 测试夹具符合真实调用合同 |
| 20 | 构建期间修改并提交 excluded file 后，Git 干净且 context hash 不变，仍进入 inspect | 构建后再次比较 `HEAD` | 检测 source commit 在 build 期间前进 |
| 21 | schema v3 bundle 在新语义下仍 `READY` | 当前 prepared schema 升 v4 | v1/v2/v3 保持历史只读 |
| 22 | 带 UTF-8 BOM 的 `.dockerignore` 令 file count 从 19 激增到 69 | 规则读取改用 `utf-8-sig`，binding 仍读取原始文件字节 | BOM 不再让 `.git` 泄漏进 context |
| 23 | `" #local-generated.txt"` 被错误当注释，file count 多 1 | 在 strip 前判断首列 `#` | 与 Moby comment 顺序一致 |
| 24 | `app/.pytest_cache/...` 被 Git 忽略但进入 context | `.pytest_cache` 改为 `**/.pytest_cache` | 嵌套 pytest cache 不改变 binding |
| 25 | builder 错误写“unrecorded state”，无法准确描述已提交 secret/symlink | 抽取统一诊断格式 | 错误包含 status、blockers、paths、patterns，措辞准确 |

### 遇到的非产品问题与处理

#### 1. Windows 创建 symlink 权限不足

第一次 symlink 测试收到：

```text
WinError 1314: 客户端没有所需的特权
```

测试在调用产品前就失败，所以没有记录为产品 RED，也没有用 skip 隐藏要求。最终通过 Git
index mode `120000` 构造与平台无关的 symlink 提交，验证的是审计实际读取的 Git 类型。

#### 2. 文档/代码补丁锚点不匹配

两次 `apply_patch` 因当前行格式或选错文件末尾锚点而未应用。工具明确返回
`Failed to find expected lines`，文件没有发生部分写入。处理方式是重新读取当前实际片段，
拆成小补丁再应用，没有使用覆盖式脚本。

#### 3. schema 验证命令写错测试名

一次 pytest 命令引用不存在的
`test_prepare_only_creates_reproducible_evidence_contract`，输出 `no tests ran`。它没有被计入
通过证据；通过 `rg "^def test_"` 找到真实
`test_load_prepare_mode_creates_run_scoped_manifest` 后重跑，4 个 schema 测试才得到
`4 passed`。

#### 4. prepared 状态分类回归

公共审计初次接线后得到 `23 passed, 4 failed`。失败不是阻断失效，而是 Compose、
execution script、Dockerfile 和 dockerignore 变更从精确 `HASH_MISMATCH` 退化成
`DIRTY_BUILD_CONTEXT`。第一次只调整优先级仍失败，说明推断不完整。继续检查数据后发现
`dirty_paths` 混入 tracked 行，修正分类源头后 5 个定向测试和完整 27 个 prepared 测试
全部通过。

#### 5. 静态格式问题

首次 Ruff 检查报告一个 `SIM114` 和 5 个待格式化文件。合并等价状态分支并运行项目
formatter 后，重新检查全绿。没有用 lint ignore 压掉问题。

#### 6. Docker 不可用

只读命令：

```text
docker version --format '{{json .}}'
```

得到 PowerShell `CommandNotFoundException`。因此没有尝试真实 build、inspect 或 Compose，
也没有把 mock CLI boundary 写成 Docker 实证。

#### 7. 组合式 Git 自检触发 safe-directory 差异

一次把测试计数、`git diff` 和 `git status` 用分号放在同一 PowerShell 命令中执行时，
后续 Git 段落处于不同 sandbox 用户上下文，分别输出“not a git repository”和
“dubious ownership”。这些输出没有被当作仓库结论，也没有修改全局 Git 配置。后续
Git 自检拆成独立调用，并显式传入当前仓库 `safe.directory`。

### 文件级修改、原因与效果

| 文件 | 修改 | 为什么 | 效果 |
|---|---|---|---|
| `.dockerignore` | bytecode、pytest cache、`.env*` 使用递归规则 | 根规则不能安全代表嵌套生成物 | 嵌套本地文件不进入 binding |
| `scripts/gate1_image_evidence.py` | v2 matcher、NUL Git 分类、统一 audit、secret/symlink/precedence 检查、前后 context/HEAD 核对 | 建立单一 build-context 安全边界 | builder 在 Docker 前失败关闭，并检测 build 期间漂移 |
| `scripts/gate1_prepared_evidence.py` | schema v4；删除重复 matcher；复用公共 audit；保留精确状态优先级 | prepare 和 execute 不能使用不同语义 | 正式 preflight 与 builder 得出同一上下文结论 |
| `scripts/worker_scaling_protocol.md` | 冻结 v4/v2、严格 Git、受支持语法和限制 | 每个新 bundle 都要携带可审计合同 | 协议不再声称旧 v3/v1 语义 |
| `tests/conftest.py` | 临时 Gate 1 仓库加入 `pyproject.toml`、`uv.lock` | fixture 必须含 Dockerfile 的真实 dependency inputs | lock 修改测试有实际 context 意义 |
| `tests/unit/scripts/test_gate1_build_context.py` | 新增 15 个独立 context 合同测试 | 将每个边界变成可重复证据 | 路径、ignore、secret、symlink 和语法均可单测 |
| `tests/unit/scripts/test_gate1_image_evidence.py` | builder 前后 audit、HEAD 与竞态测试 | 单测公共函数不足以证明执行入口已接线 | Docker 调用顺序与失败关闭可验证 |
| `tests/unit/scripts/test_gate1_prepared_evidence.py` | staged excluded、专用 ignore、`uv.lock`、schema v3 历史测试 | 证明 formal verifier 使用同一合同 | prepared 状态和 details 可审计 |
| `tests/unit/scripts/test_experiment_scripts.py` | 当前 manifest 期望改为 v4 | producer 与 verifier 必须同版本 | 新 prepare 只产生 v4 |

### 最终验证

| 检查 | 结果 | 证据等级 |
|---|---|---|
| P1-5/Gate 1 聚焦矩阵 | 79 passed in 137.58s | `VERIFIED` |
| 诊断重构后的 image tests | 14 passed in 8.70s | `VERIFIED` |
| 最终态非 integration 全量 | 356 passed、6 deselected in 163.53s | `VERIFIED` |
| integration 标记 | 6 skipped、356 deselected in 1.68s | `NOT_RUN` |
| `uv lock --check` | 70 packages resolved | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| Ruff format | 224 files already formatted | `VERIFIED` |
| strict mypy | 106 source files，无问题 | `VERIFIED` |
| `git diff --check` | 无输出 | `VERIFIED` |
| Docker CLI | `CommandNotFoundException` | `NOT_RUN` |
| Docker build / image inspect / Compose smoke | 未执行 | `NOT_RUN` |
| 正式 500-case / 32-arm | 未执行 | `NOT_RUN` |

integration 的 6 个 skip 仍分别要求显式 `EVALOPS_RUN_INTEGRATION=1` 以及真实、已迁移的
PostgreSQL 和/或 Redis。它们没有被写成 passed。

### 本阶段已经证明什么

- tracked/staged 变化即使被 Docker 排除也阻断；
- untracked/ignored 只有实际 included 才阻断；
- root pattern 与 nested path 不再混淆；
- 非 ASCII Git 路径不会被 porcelain quoting 损坏；
- included Git symlink、`.env*`、Dockerfile 专用 ignore 和未支持 `**` 形式失败关闭；
- Dockerfile、dockerignore、`uv.lock` 与普通 context 内容变化都能被 binding/preflight
  检出；
- builder 与 prepared verifier 使用同一个 audit；
- builder 前后都验证 context 与 source `HEAD`；
- schema v4 是唯一当前可执行 prepared manifest；
- 失败证据只记录安全路径、hash 和 reason，不记录 `.env` 内容。

### 本阶段仍未证明什么

- 没有真实 Docker/BuildKit，因此没有实际 context tar、cache key 或镜像层实证；
- v2 是平台 evidence binding，不是 Docker 官方 digest；
- matcher 不是完整 Moby 重实现；只对冻结子集和明确失败关闭路径负责；
- symlink 通过 Git index mode 验证，没有在这台 Windows 主机创建真实 OS symlink；
- `.env*` 防线不等于扫描 PEM、云凭据或所有可能 secret；
- 前后快照不能宣称获得 Docker 内部发送流的原子密码学证明；
- 没有 PostgreSQL/Redis integration、正式 arm 数据、容量结论或其他未完成 P1 finding
  的证明。

### 对旧 artifact 与 prepared bundle 的影响

- `docs/results/` 没有修改；
- 没有生成 schema v4 bundle，因为本机没有 Docker；
- schema v1/v2/v3 继续作为历史只读证据；
- 不允许给旧 bundle 手工改 `schema_version` 或补字段；
- 所有阻断 P1 finding 完成后，必须从最终干净、已提交的 `HEAD` 重新运行
  `--prepare-only`。

### 回滚边界

实现回滚：

```text
git revert eb33de494bbda4850b7f29240dcce54146a42339
```

这会回滚 P1-5 实现、测试、schema v4 和冻结协议。没有数据库 migration，也没有新正式
artifact 需要删除。若未来已经产生 schema v4 bundle，回滚前必须保留其只读审计副本，
不能让旧代码把它当成 v3 可执行 bundle。

### P1-5 阶段结论与停止点

P1-5 的修改前判断、TDD、严格 Git/context 审计、secret/symlink/precedence 边界、
source commit 前后绑定、schema v4、冻结协议、分层验证和本地实现提交均已完成。

当前停止在下一 P1 阶段之前，等待用户确认。正式 Gate 1 仍不能运行，原因包括其他阻断
P1 finding 尚未完成，以及当前主机没有 Docker/PostgreSQL/Redis 正式环境。

## P1-6：HTTP Target operator Registry 与 DNS rebinding 加固

### 阶段判断与不可变实现

- 起始 SHA：`b519268a520c7a8f85b629eb4ee8b8e5769be1c6`
- 主实现提交：`049e59e0760a50377e0cb8b53c61d166ee7dc224`
- IDNA 边界跟进：`102cb4eda90a8a79ab66d9974b62369dec418e3e`
- Pytest 隔离跟进：`03d4832c67a3dcf4fc142363e445a5f535adbd73`
- 用户冻结合同：`A + C`，即 operator-managed Registry 加数值 IP/实际 peer 绑定
- 正式 Gate、Docker、integration、500-case、32-arm 和破坏性注入：`NOT_RUN`

原安全边界允许 tenant 同时提交 `base_url` 与 `allowed_hosts`，并在应用检查 DNS 后由 HTTPX
再次解析 hostname。P1-6 改为 tenant 只提交 `target_id`，Registry version 必须与 Run 请求精确
一致；平台在 Dataset I/O 前验证操作员配置，并把派生的精确 host 与执行配置冻结到 Run。

执行时要求 HTTPS 443、不跟随重定向、全部 A/AAAA 都是原生公网地址；连接选定数值 IP，保留
原 Host/TLS SNI，并在读取正文前从 HTTPX/HTTPCore network stream 验证实际 peer。元数据缺失、
异常、非公网、端口错误或地址不一致都失败关闭。Unicode IDN 在配置期拒绝，operator 可显式
使用 ASCII punycode；DNS resolver 也受 target timeout 约束。

### 本地验证

| 检查 | 结果 | 状态 |
|---|---|---|
| HTTP Target/真实 peer 合同 | 47 passed | `VERIFIED` |
| Registry/应用接线/部署/依赖 | 28 passed | `VERIFIED` |
| API/Worker 回归 | 14 passed | `VERIFIED` |
| 非 integration 全量（CI 同形默认命令） | 412 passed，6 deselected | `VERIFIED` |
| Ruff / mypy app / lock / diff | 全部通过 | `VERIFIED` |
| GitHub CI Run #11 | Compose、migration、6 个真实服务合同、image build success | `VERIFIED` |
| Docker、真实服务、正式 Gate 5 | 未运行 | `NOT_RUN` |

首次全量的唯一失败来自仓库内 basetemp：测试移走临时仓库 `.git` 后，Git 向父目录吸附真实项目
并误报 `SOURCE_MISMATCH`。工作树外 basetemp 使原测试直接通过，且 `rev-parse` 对照确认根因；
因此没有修改或放宽 prepared-evidence verifier。GitHub CI #10 随后证明 Pytest 全局配置仍强制
repo-local basetemp；删除该 `addopts` 后，默认聚焦与 412 项全量通过。详细逐条 RED/GREEN、
依赖合同、孤儿 Git lock 处理和残余风险见
[`p1_6_http_target_security_log.md`](p1_6_http_target_security_log.md)。

修复推送后的 GitHub CI Run #11（`30713653240`，head `1141c146...`）最终 success：两个 job、
六个真实服务合同和镜像构建均成功。该证据只提升普通 CI 合同，不改变正式 Gate 的 `NOT_RUN`。

### 仍未证明与正式 Gate 状态

- 应用层关闭了旧的二次 DNS 解析路径，但不是操作系统、NAT、透明代理或供应链的完整证明；
- 生产仍必须配置 egress firewall/NetworkPolicy/安全组，并在 HTTPX/HTTPCore 升级时回归；
- 本机没有 Docker CLI，也没有运行 PostgreSQL/Redis integration、真实攻击网络或渗透测试；
- 没有数据库 migration，没有修改 `docs/results/`，没有生成新 prepared bundle 或正式 artifact；
- 正式 Gate 1/Gate 5 继续 `NOT_RUN`，不能把 410 个本地非集成测试写成 Gate 通过。

实现回滚边界：按逆序执行
`git revert 03d4832c67a3dcf4fc142363e445a5f535adbd73`，再执行
`git revert 102cb4eda90a8a79ab66d9974b62369dec418e3e`，再执行
`git revert 049e59e0760a50377e0cb8b53c61d166ee7dc224`。两个提交都没有 schema 或正式 artifact
副作用；回滚主实现后，新的 `target_id` HTTP 请求将失去 Registry 支持，旧的不安全 tenant URL
合同会恢复，因此只能在明确接受安全回退时执行。

## P1-7：Artifact blob 去重与 tenant/Run reference 分离

### 阶段判断与实现

- 起始 SHA：`ca2a893af24572445a6de4359d24f44c65350ee8`；
- 实现提交：`de1a44b659ea1edc88d97ab7aec0eccb41868240`；
- 正式 Gate、500-case、32-arm、破坏性实验：`NOT_RUN`。

审计确认旧 `artifacts` 行同时承载物理 SHA/path/size 与 tenant/Run 所有权，唯一键
`(tenant_id, artifact_type, sha256)` 会使同 tenant 的两个 Run 无法各自引用相同内容。P1-7
新增 `artifact_blobs` 与 `artifact_references`，用 migration `20260802_0009` 保留旧 UUID、按
SHA backfill blob、切换 Dataset Version FK，再删除旧表。upgrade 遇到物理 metadata 或 owner
shape 冲突时失败；downgrade 无法无损表达多 owner 时也失败。

所有注册调用点共用 blob/reference upsert；读取与删除必须精确匹配 tenant/reference，并要求
Run 精确相等，省略 Run 只允许 Dataset reference。最后 reference 才删除 blob metadata 和经过
摘要校验的本地文件。详细 RED/GREEN、迁移/rollback、命令超时和残余风险见
[`p1_7_artifact_ownership_log.md`](p1_7_artifact_ownership_log.md)。

### 本地验证与边界

| 检查 | 结果 | 状态 |
|---|---|---|
| P1-7 定向回归 | 61 passed | `VERIFIED` |
| 非 integration 全量 | 424 passed，7 deselected | `VERIFIED` |
| Alembic offline upgrade/downgrade | 2 passed，SQL 人工筛查通过 | `VERIFIED` |
| Ruff / mypy 115 files / lock / diff | 全部通过 | `VERIFIED` |
| 新真实 PostgreSQL ownership test | 本机 1 skipped | `NOT_RUN_LOCAL` |
| GitHub CI Run #13 | 两个 job、migration、新 ownership integration、image build 成功 | `VERIFIED` |

当前仍不能证明本地 store 适合多 API 主机，也不能把数据库 transaction 与文件 unlink 写成
分布式原子提交。已知 SHA orphan 可在数据库确认无 reference 后清理，但没有定时全盘扫描 GC。
`docs/results/`、prepared bundle 和正式实验 schema 均未修改；正式 Gate 1 继续 `NOT_RUN`。

远端证据绑定 `47e844a2b3bbb3c0b51fc3db20012fee3256dbdb`：
[GitHub Actions Run #13](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30728407695)
为 `completed / success`；`quality-and-integration` 与 `compose-smoke` 均成功。新增 artifact
ownership PostgreSQL step 明确执行成功。该结果把远端普通 CI 合同提升为 `VERIFIED`，不改变
正式 Gate 的 `NOT_RUN`。

实现回滚入口是：

```text
git revert de1a44b659ea1edc88d97ab7aec0eccb41868240
```

因为该提交含 `0009` migration，已升级环境必须先确认 downgrade guard 允许无损回退并执行
Alembic downgrade；如果已有多 owner references，不能直接回退代码或强行折叠所有权。

## P2-1：跨表 tenant 一致性约束

### 阶段判断与实现

- 起始 SHA：`397c5ccffa8bc1521e71b421785067f7aeac6d4d`；
- 状态：`LOCAL_AND_REMOTE_CONTRACT_VERIFIED / FORMAL_GATE_NOT_RUN`；
- 没有给所有子表机械复制 tenant，只加固同一行已经保存多份归属/父链事实的关系；
- 新增 `20260802_0010`，给 Dataset Version 回填 tenant，并用复合 FK 绑定
  Dataset/Artifact/Version/Run/API Key/Human Review；
- Case Result 与 Human Review Task 用 `(job_id, run_id)` 保证同一 Job/Run lineage；
- upgrade guard 遇到旧数据矛盾时事务失败，不自动重归属；downgrade 恢复旧单列 FK；
- `audit_events` 多态字符串、只有单父链的表和 `case_id` 内容一致性不在本项内；没有 RLS。

### 本地证据

| 检查 | 结果 | 状态 |
|---|---|---|
| ORM/query/migration 定向 | 19 passed；migration 合并 4 passed | `VERIFIED` |
| 非 integration 全量 | 429 passed，8 deselected | `VERIFIED` |
| Ruff format/lint | 241 files / All checks passed | `VERIFIED` |
| strict mypy | 116 source files | `VERIFIED` |
| uv lock | 70 packages resolved | `VERIFIED` |
| 新 PostgreSQL constraint test | 本机 1 skipped | `NOT_RUN_LOCAL` |
| GitHub Actions Run #15 | 两个 job、constraint integration、migration round-trip、image、Compose success | `VERIFIED` |
| 正式 500-case/32-arm | 未运行 | `NOT_RUN` |

完整逐步记录见
[`p2_1_cross_table_tenant_consistency_log.md`](p2_1_cross_table_tenant_consistency_log.md)。普通
CI 即使成功也只证明列出的 schema/integration/Compose 合同，不等于容量、RLS、生产安全
或正式 Gate 通过。

远端证据绑定 head `87d85d0906ba3c42e2caf5185d5b034a6cd5f322`：
[GitHub Actions Run #15](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30729735398)
为 `completed / success`，`quality-and-integration` 与 `compose-smoke` 均成功；新 constraint
integration 和实际 `0010→0009→0010` 也明确执行成功。正式 Gate 继续 `NOT_RUN`。
