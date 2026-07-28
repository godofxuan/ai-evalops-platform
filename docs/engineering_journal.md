# Engineering Journal

本文件保留阶段级结论；详细操作证据见同阶段 execution log。任何未运行的验证必须标记为“未运行”，不得推断为通过。

## 2026-07-28 — Phase 0：仓库初始化（完成）

### 基本信息

- 日期：2026-07-28
- 起始 SHA：无；起始目录为空且不是 Git 仓库
- 结束分支：`main`
- 目标：建立 Python 3.12、uv、FastAPI、配置、结构化日志、健康检查、PostgreSQL、Redis、Alembic、Docker 和 CI 基础

### 问题与根因

- 问题：空目录没有可执行、可测试、可迁移或可部署的工程底座。
- 根因：项目尚未初始化；本机只有 Python 3.13/3.14/3.11，没有要求的 3.12；uv、Docker 和 Compose 不在 PATH。
- 环境附加问题：
  - PowerShell 第一次按错误编码读取 UTF-8 需求，中文乱码；
  - Microsoft Store Python 3.13 无法创建工具 venv；
  - pytest 默认导入模式不能同时收集两个同名测试文件；
  - Git sandbox 所有者与当前命令用户不同，触发 dubious ownership；
  - PTY 中的 Uvicorn smoke 进程没有响应 Ctrl+C。

### 指令适配性判断

- “现在只执行 Phase 0”是合适边界，因此没有创建 tenant、dataset、Run、Job 或用户后续亲自实现的核心模块。
- “每一步详细记录”已拆成阶段工程日志和逐步 execution log，避免只存在于聊天。
- “先测试”通过多个垂直 RED→GREEN 切片执行；没有一次批量写完所有测试和实现。
- “Docker 验证”是合理验收，但安装 Docker Desktop 会涉及系统级 GUI/虚拟化配置，因此本阶段只实际运行命令并记录工具缺失，把真实验证交给具备 Docker 的机器和 CI。
- Worker/Reaper 必须出现在 Compose，但业务属于后续阶段，因此只提供明确标记 `lifecycle_only` 的进程入口。

### 设计

- 单仓库、多进程骨架：API、Worker、Reaper 共用代码和镜像。
- FastAPI app factory + lifespan 管理异步 PostgreSQL/Redis 客户端。
- `GET /health/live` 不访问依赖；`GET /health/ready` 并发检查 PostgreSQL、Redis、artifact 目录和 Alembic revision。
- readiness 只返回稳定错误码，不回显底层异常文本。
- JSON 结构化应用日志绑定 request ID，并递归屏蔽常见敏感字段。
- Alembic 只创建空 revision 基线，不提前创建后续领域表。
- 集成测试只接受真实 PostgreSQL/Redis；无服务时明确 skip，不使用 SQLite。
- Docker 镜像固定 Python/uv 版本并以 UID/GID 10001 非 root 运行。
- Compose 等待 PostgreSQL/Redis healthy 和 migration completed 后再启动应用进程。

### 实际新增或修改文件

本阶段最终跟踪 40 个文件，按责任分组如下：

```text
工程规则与文档
  .gitattributes
  .gitignore
  README.md
  docs/00_project_scope.md
  docs/01_architecture.md
  docs/engineering_journal.md
  docs/phase_0_execution_log.md

Python 与配置
  .env.example
  .python-version
  pyproject.toml
  uv.lock

应用
  app/__init__.py
  app/main.py
  app/cli.py
  app/api/__init__.py
  app/api/middleware.py
  app/api/routes_health.py
  app/core/__init__.py
  app/core/config.py
  app/core/logging.py
  app/health/__init__.py
  app/health/service.py
  app/persistence/__init__.py
  app/persistence/database.py
  app/persistence/redis.py

数据库迁移
  alembic.ini
  alembic/env.py
  alembic/script.py.mako
  alembic/versions/20260728_0001_baseline.py

测试
  tests/api/test_health.py
  tests/integration/test_readiness.py
  tests/unit/test_cli.py
  tests/unit/test_config.py
  tests/unit/test_logging.py
  tests/unit/test_readiness.py

容器与 CI
  .dockerignore
  Dockerfile
  deploy/compose.yaml
  .github/workflows/ci.yml

运行目录占位
  data/artifacts/.gitkeep
```

### RED 测试和失败记录

- `app.main` 不存在：liveness 测试收集失败。
- `app.health` 不存在：readiness 成功合同收集失败。
- `app.core.config` 不存在：配置/SecretStr 测试收集失败。
- `CompositeReadinessProbe` 不存在：异常脱敏测试收集失败。
- artifact 探测函数不存在：目录写入测试收集失败。
- `app.core.logging` 不存在：结构化日志测试收集失败。
- response 缠少 `X-Request-ID`：HTTP 测试断言失败。
- 真实基础设施工厂不存在：集成合同收集失败。
- `app.cli` 不存在：Worker 入口测试收集失败。
- 实现后首次全量收集失败：unit/integration 两个 `test_readiness.py` 在 pytest 默认模式下冲突。
- 静态检查首次失败：13 个文件需格式化、3 个导入顺序、2 个 async pathlib、1 个 Redis 返回类型问题。
- staged whitespace 检查多次发现末尾空行并在后续提交前修复。

完整命令和原始关键结果见 `docs/phase_0_execution_log.md`。

### 验证结果

| 验证 | 结果 |
|---|---|
| Python | uv 管理的 CPython 3.12.13 |
| uv | 0.11.32 |
| 依赖锁 | 47 个包解析；`uv lock --check` 通过 |
| Ruff format | 27 files already formatted |
| Ruff lint | All checks passed |
| mypy | 14 个应用文件，0 issues |
| pytest 全量 | 10 collected；9 passed；1 skipped |
| 集成测试 | 本机 skipped：未设置真实 PostgreSQL/Redis |
| Alembic head | `20260728_0001 (head)` |
| Alembic offline SQL | 成功生成 version table 和 baseline revision SQL |
| YAML | Compose 与 GitHub Actions 均可由 YAML parser 解析 |
| CLI | Worker/Reaper `--check` 均输出 `lifecycle_only` |
| Uvicorn liveness | 独立进程 HTTP 200，含 `X-Request-ID` |
| Uvicorn readiness | 无本地依赖时 HTTP 503；artifact ok；DB/Redis/migration 稳定错误码 |
| Docker Compose | 未运行：本机没有 `docker` 命令 |
| Docker build | 未运行：本机没有 `docker` 命令 |
| GitHub Actions | 未运行：仓库未 push；工作流已静态解析 |

### 当前实现能够证明

- Python 3.12 环境可以解析、锁定和运行项目依赖。
- API 的 liveness、readiness HTTP 合同和 request ID 行为在 ASGI 测试及独立 Uvicorn 进程中成立。
- readiness 聚合会并发限制单项超时，并把异常文本转换为稳定错误码。
- artifact 探测执行真实写入、flush、`fsync` 和清理。
- 配置对象与结构化日志对已知敏感字段有脱敏机制。
- Alembic baseline 脚本可以被加载并生成 PostgreSQL offline SQL。

### 当前实现不能证明

- 真实 PostgreSQL/Redis readiness 在本机通过；
- Alembic migration 已在真实 PostgreSQL 应用；
- Docker 镜像能构建、Compose 拓扑能启动；
- GitHub Actions 已执行；
- 租户隔离、幂等、任务领取、租约、心跳、重试、崩溃恢复或取消；
- 生产可靠性、安全认证或 exactly-once 执行；
- structlog 按字段名脱敏能识别被错误放进普通字符串字段的秘密；
- readiness 的瞬时成功代表持续可用。

### 未解决问题

- 需要在安装 Docker 的环境运行完整 Compose smoke，并保留成功或失败日志。
- 需要由 CI 首次执行真实 PostgreSQL/Redis 集成测试。
- Uvicorn 自身的启动/access log 仍使用其默认格式；应用请求日志是 JSON。后续可统一第三方 logger 配置。
- artifact 探测的线程在极端文件系统阻塞时不能被 asyncio timeout 强行终止，只能让 HTTP 检查超时返回。
- 目前使用开发默认数据库密码；生产部署必须由秘密管理机制注入，不能沿用默认值。

### 为什么没有采用其他方案

- 未用 SQLite：不能证明 PostgreSQL 行锁、事务和后续 `SKIP LOCKED`。
- 未提前创建领域表：避免在相应行为合同之前固化模型。
- 未用 Celery/Kafka/Kubernetes/微服务：Phase 0 不需要，且会隐藏后续学习核心。
- 未用 Redis 保存最终状态：它不是事实来源。
- 未安装 Docker Desktop：这是系统级变更，不是仓库内正常实现步骤。
- 未在日志中记录原始异常文本：优先防止 readiness 响应或日志泄露连接秘密；后续可记录安全的异常类型/指纹。

### 应亲自理解的代码

1. `app/main.py`：app factory、lifespan、资源创建与关闭顺序。
2. `app/health/service.py`：并发探测、超时、错误码、Alembic current/head 比较。
3. `app/api/middleware.py`：纯 ASGI request ID 和结构化请求日志。
4. `app/core/logging.py`：标准库 logging 与 structlog 的组合及脱敏边界。
5. `alembic/env.py`：异步 SQLAlchemy 如何进入 Alembic 同步 migration context。
6. `tests/integration/test_readiness.py`：fake 合同与真实依赖证据的区别。
7. `deploy/compose.yaml`：healthy、completed 和 started 的不同语义。

### 面试官可能追问

- liveness 为什么不能检查数据库？
- readiness 失败是否应该让正在执行的 Worker 停止？
- Redis 不可用时 readiness 应该 503 还是降级为 ready？
- 为什么 migration head 检查与 PostgreSQL ping 分开？
- `asyncio.wait_for` 超时后数据库连接和线程文件操作分别会怎样？
- request ID 为什么允许部分客户端值，又为什么限制字符和长度？
- SecretStr 与日志脱敏分别解决什么问题，分别有哪些盲区？
- 空 baseline migration 有什么价值？
- 为什么 CI 既有 service containers 又有 Compose smoke？

### 提交

- `dddb98b docs: define phase 0 engineering contract`
- `8523094 chore: initialize project tooling`
- `2a51a30 test(health): define phase 0 runtime contracts`
- `8cf1b3e feat(health): implement phase 0 runtime foundation`
- `17c9726 chore: add container and ci foundation`
- 最终 README/日志提交：见本阶段完成后的最新 `git log`

## 2026-07-29 — Phase 1：身份、数据集与 Artifact（完成）

### 基本信息

- 日期：2026-07-29
- 起始 SHA：`f574cbe3c3836fc91188de1a52392ced9cc89924`
- 阶段状态：仓库内实现和本机可执行验收完成；真实服务与 Docker 验证明确未完成
- 目标：实现 API Key、服务端 tenant principal、dataset 元信息、immutable JSONL version 和本地 content-addressed artifact
- 明确不做：Run/Job、Worker 领任务、Reaper、Redis 队列、幂等提交、崩溃恢复、取消和 SSE

### 问题与根因

- Phase 0 没有身份入口，任何未来业务资源都缺少可信 tenant 来源。
- 没有 dataset/version 领域模型，评测输入不能稳定引用，也无法证明输入不可变。
- 没有 artifact 所有权和物理内容分层，同内容复用、tenant 隔离与磁盘安全边界均未定义。
- 根因不是 Phase 0 遗漏，而是阶段拆分：Phase 0 有意只交付工程底座，本阶段才引入首批领域表和授权链。

### 指令适配性判断

- “API Key 只显示一次、数据库只存 hash”合理；采用带版本与参数的 scrypt 编码，不使用可离线直接反查的裸 SHA-256。
- “所有业务资源 tenant 隔离”合理；tenant 只从认证 Principal 派生，请求体不能接受 `tenant_id`。
- “跨 tenant 返回 404”合理；避免向攻击者证明目标资源存在。
- “immutable version”合理；相同 dataset 的相同 SHA 返回 409，不覆盖历史版本。
- “本地 artifact 物理去重”合理，但必须与 tenant-owned 数据库记录分层，否则全局 metadata 会破坏授权归属。
- “短事务”合理；JSONL 解析和磁盘 fsync 放在事务外，只有重新授权、行锁、artifact metadata upsert 和 version insert 位于写事务。
- “真实 PostgreSQL 集成测试”合理；本机没有服务时只能 skip，禁止用 SQLite 伪造通过。
- “Docker 验证”合理；本机没有 Docker，安装 Desktop 属于系统级变化，因此只保留真实命令失败与 YAML 静态解析结果。

### 核心设计

- API Key 格式为 `evk_<12 hex prefix>_<secret>`；prefix 用于候选查询，secret 以随机 salt 的 scrypt 校验。
- malformed/unknown key 执行 dummy scrypt；所有认证失败使用相同 401 body。
- 认证成功前最后一步是条件 UPDATE，重新检查 key active、未过期和 tenant active，关闭撤销竞态窗口。
- 所有 dataset/version SQL 同时包含 tenant 与资源 ID；跨 tenant 与不存在共享 404。
- JSONL 使用严格 UTF-8、一行一个 object、必填字段、case ID 唯一，以及文件/行数/单行三层上限。
- artifact 物理路径只由服务端 SHA-256 派生；临时文件 flush/fsync 后重新计算摘要，再以 create-only 硬链接原子发布。
- artifact metadata 按 tenant 拥有；不同 tenant 可以指向同一物理摘要路径。
- 同一 dataset 的 version 分配以 tenant-scoped `SELECT ... FOR UPDATE` 串行化，数据库唯一约束作为最后防线。

### 实际文件范围

主要新增：

- `app/auth/`：密钥格式、hash、Principal、策略、SQLAlchemy repository 和 FastAPI dependency；
- `app/domain/`：Phase 1 状态与 artifact 类型；
- `app/datasets/`：schema、JSONL validation 和 SQLAlchemy service；
- `app/artifacts/`：本地内容寻址 storage；
- `app/api/errors.py`、`app/api/routes_datasets.py`：HTTP 合同与错误映射；
- `app/persistence/orm_models.py`：五张 Phase 1 ORM 表；
- `alembic/versions/20260729_0002_identity_datasets.py`：Phase 1 migration；
- `app/core/event_loop.py`：psycopg-compatible Selector loop；
- `scripts/`：开发 API Key 创建与撤销；
- `docs/02_domain_model.md`、`docs/08_security_boundaries.md`、`docs/phase_1_execution_log.md`；
- API、unit 和 real-service integration tests。

主要修改：

- app factory、数据库 session factory、Alembic env、CLI、Settings 与 `.env.example`；
- `pyproject.toml`/`uv.lock`，增加 multipart 支持；
- Dockerfile、Compose 与 CI；
- README 与本工程日志。

### RED→GREEN 与实现偏差

完整逐步证据见 `docs/phase_1_execution_log.md`。关键 RED 包括：

- `app.auth`、`app.datasets`、`app.artifacts` 和 ORM 模块不存在；
- revoked、expired、disabled tenant 最初均被错误放行；
- 文件/行数/单行、空文件/空行、UTF-8、JSON、字段 schema 和重复 case ID 最初逐项失败；
- artifact 已有内容损坏、临时内容变化和摘要目录符号链接最初缺少保护；
- 初版 artifact ORM 丢失原始需求中的 tenant/type/media/byte size，回读附件后先改测试再纠正模型；
- 跨 tenant version upload 最初虽返回 404，却已写物理 artifact；增加“storage 调用次数为 0”测试后调整顺序；
- Windows pytest 的默认 Proactor loop 不满足 psycopg async 合同，增加统一 Selector loop 后转绿。

记录的 TDD 粒度偏差：

- artifact 第一个实现提前包含顺序复用和 `finally` 清理，后续两条测试首次即 GREEN；日志如实标为回归测试，没有改写成 RED。

### 实施中遇到的问题

1. Alembic constraint 显式名称与 naming convention 重复加前缀；改成短语义名后 offline DDL 可读且一致。
2. 运维脚本误用不存在的 `generated.key_prefix`；mypy 捕获后改为 `generated.prefix`。
3. 在线 Alembic 首先暴露 Windows Proactor/psycopg 不兼容；统一 Selector loop 后，错误推进到真实的 PostgreSQL `ConnectionTimeout`。
4. 一次 uv 命令漏设项目缓存目录，沙箱拒绝用户级缓存；恢复 `.uv-cache` 后通过。
5. 旧 `.pytest_cache` 当前身份无法访问；不提权、不删除，最终禁用 cache provider。
6. 两个 pytest 进程并发共享 `.pytest-tmp`，产生 10 个 setup `PermissionError`；改为独立 basetemp 串行重跑后全部正常。
7. 首次 YAML Python one-liner 因 PowerShell 双层引号报 SyntaxError；简化字符串构造后两个 YAML 均成功解析。
8. `Invoke-WebRequest` 在本机触发自身 NullReferenceException；改用 `curl.exe` 读取原始响应，服务返回正常。
9. PTY Ctrl+C 没有退出 Uvicorn；只停止本次启动的明确 PID，没有批量终止进程。

### 最终验证结果

| 检查 | 结果 |
|---|---|
| Python / uv | CPython 3.12.13 / uv 0.11.32 |
| `uv lock --check` | 通过；48 packages |
| Ruff format | 64 files already formatted |
| Ruff lint | All checks passed |
| mypy app | 32 source files，无问题 |
| mypy scripts | 3 source files，无问题 |
| pytest 非集成 | 71 passed，2 deselected |
| pytest 全量 | 71 passed，2 integration skipped |
| Alembic head | `20260729_0002 (head)` |
| Alembic history/offline SQL | 通过；五张 Phase 1 表的 PostgreSQL DDL 已生成 |
| Alembic online current | 未通过；Selector loop 正常，连接真实 PostgreSQL 超时 |
| Uvicorn smoke | HTTP 200、UUID `x-request-id`、四条 Phase 1 OpenAPI 路由 |
| Compose / CI YAML | PyYAML 静态解析通过 |
| Docker / Compose | 未运行；本机没有 `docker` 命令 |
| GitHub Actions | 未运行；没有 push |

### 当前实现能够证明

- API Key 明文不会进入 ORM schema，hash 可验证且失败类型对外一致；
- revoked、expired、disabled tenant 和最终条件更新失败不能生成 Principal；
- 客户端不能指定 tenant，已实现的 dataset/version 查询都受 tenant 约束；
- JSONL 的第一版严格格式和资源上限可重复验证；
- dataset version 只追加、不覆盖，重复 SHA 被拒绝；
- artifact 路径由服务端摘要决定，发布失败会清理临时文件，重复内容可复用；
- app factory 能在自定义 Selector loop 下启动，Phase 1 路由进入 OpenAPI；
- migration revision 链与 PostgreSQL offline DDL 一致。

### 当前实现不能证明

- migration 已在真实 PostgreSQL 成功 apply/rollback；
- 真实 PostgreSQL 上的行锁、唯一冲突和 tenant integration 全部动态通过；
- Redis readiness 的本轮真实成功路径；
- Docker 镜像可构建、Compose 拓扑可启动；
- CI 在远端通过；
- 多 API 主机共享本地 artifact storage；
- 限流、RLS、密钥轮换、完整管理员审计或生产安全认证；
- at-least-once、幂等结果、lease、heartbeat、重试、取消或崩溃恢复。

### 为什么没有采用其他方案

- 未用裸 SHA-256 存 API Key：离线泄漏后试探成本过低。
- 未接受请求体 tenant ID：会把授权边界交给不可信客户端。
- 未用 SQLite 替代 PostgreSQL：无法验证 PostgreSQL UUID、ON CONFLICT、行锁与并发语义。
- 未把文件解析/fsync 放进数据库事务：会放大锁持有时间。
- 未把 artifact metadata 做成全局记录：会丢失 tenant 所有权。
- 未启用 PostgreSQL RLS：当前先把应用层查询约束做成显式、可测试合同；RLS 是后续 defense-in-depth。
- 未提前创建 Run/Job：用户要求严格阶段化，本阶段完成后必须停止。

### 应亲自理解的代码

1. `app/auth/api_keys.py`：版本化 scrypt 编码、salt、常量时间比较和 dummy hash。
2. `app/auth/service.py` 与 `repository.py`：认证决策和撤销竞态复核如何分层。
3. `app/datasets/validation.py`：为什么先执行字节上限，再做 UTF-8/JSON/schema。
4. `app/datasets/service.py`：事务外校验/落盘与事务内重新授权/锁行的顺序。
5. `app/artifacts/storage.py`：同目录临时文件、fsync、重算摘要和 create-only 发布。
6. `app/persistence/orm_models.py` 与 Phase 1 migration：应用约束和数据库最后防线。
7. `app/core/event_loop.py`：Windows psycopg 为什么需要 Selector。
8. `tests/integration/test_identity_and_datasets.py`：真实服务合同能证明什么、skip 又不能证明什么。

### 提交

- `aca08ae docs: define phase 1 domain and security contracts`
- `8d20657 feat(auth): add tenant api key identity and schema`
- `96d8e46 feat(datasets): add immutable jsonl dataset versions`
- `16211c7 chore: add phase 1 runtime and operator tooling`
- 最终 README/日志提交：以本阶段完成后的最新 `git log` 为准
- 未 push
