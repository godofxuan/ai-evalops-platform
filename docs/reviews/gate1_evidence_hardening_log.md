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
