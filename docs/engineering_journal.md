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

## 2026-07-29 — Phase 2：Run 与幂等（完成）

### 基本信息

- 起始 SHA：`9a8234073a61e81928d0c6b2c684d55a4d547d53`
- 目标：创建可复现 Evaluation Run、canonical request hash、Idempotency-Key、每 case 一个 Job，以及 tenant-scoped Run 查询
- 新授权：用户明确要求连续完成全部剩余阶段，因此不再在每个 Phase 停止；仍逐阶段记录和提交

### 问题与根因

- 客户端/代理可能重复提交，若每次都创建 Run，会重复初始化 Jobs 和未来费用。
- 单纯“先查再插”存在并发竞态。
- Dataset Version 只保存原始 JSONL artifact，Worker 后续若逐 Job 扫描整文件会产生平方级重复工作。

### 设计

- Pydantic 验证后的请求做 canonical JSON + SHA-256。
- 幂等作用域当前为 `(tenant_id, evaluation-runs endpoint, idempotency_key)`；endpoint 由独立表隐式提供。
- 首次 SELECT 只做快速 replay；数据库唯一约束提供最终并发保护。
- 同 key 同 hash 返回原 Run；同 key 不同 hash 返回固定 409。
- Run 和全部 Jobs 在同一短事务提交；artifact 读取/JSONL 解析在事务外。
- Job 保存不可变 case payload JSON snapshot，仍保留 dataset artifact/hash 作为审计来源。

### 关键失败与修正

- Run 路由缺失：POST header 测试先得到 404。
- `RunCreate strict=True` 拒绝正常 JSON UUID 字符串：放宽外层 UUID 解析，保留 extra forbid 和组件 strict。
- ORM 首版遗漏原始字段清单中的 `dataset_hash`：回读要求后先加 RED 再补列。
- Artifact 没有安全读取接口：增加只按 64 位 canonical SHA 派生路径、读取后重算摘要。
- ValidatedJSONL 只有计数：增加已验证 case tuple，避免二次解析。
- replay 与 conflict 分支依次从显式未实现转为 GREEN。
- 并发 winner 返回后最初没有再次比较 hash：测试得到 `DID NOT RAISE`，增加第二次比较。
- 无效 max_attempts 最初先读取 dataset：调整为幂等快速路径后、I/O 前校验。
- 409、404、invalid evaluator 最初分别表现为 500/未处理异常：增加稳定 HTTP 映射。
- Ruff 最终发现 3 个纯 import 排序问题，自动安全修复后通过。

### 数据库

- 新增 `evaluation_runs`：
  - tenant、dataset version/hash、request hash；
  - target/evaluator config/hash/version；
  - idempotency key；
  -聚合计数、时间、created_by 和 optimistic version。
- 新增 `evaluation_jobs`：
  - run/case 唯一；
  - case payload snapshot；
  - queued/running/retry/terminal 状态字段；
  - attempt、lease、heartbeat、错误、取消和 version；
  - Phase 3 领取与 lease 所需索引。
- Alembic head：`20260729_0003`；offline PostgreSQL DDL 通过。

### 验证

| 检查 | 结果 |
|---|---|
| Phase 2 目标测试 | 45 passed |
| 全仓非集成回归 | 87 passed，3 deselected |
| PostgreSQL 并发合同 | 1 skipped；本机无 migrated real PostgreSQL |
| Ruff | All checks passed |
| mypy app | 38 source files，无问题 |
| Alembic | head/offline SQL 通过 |

### 能够与不能证明

能够证明：

- object key 顺序不影响 request hash；
- replay 不读取 artifact、不重新创建 Jobs；
- 同 key 不同请求冲突；
- repository SQL 包含 tenant 边界；
- Run/Jobs 事务结构和数据库约束存在；
- Run HTTP create/get 与稳定错误合同成立。

不能证明：

- 本机真实 PostgreSQL 并发请求只创建一个 Run；
- Worker 已领取或执行 Job；
- exactly-once 或不重复计费；
- API 响应丢失的真实网络实验。

### 提交

- `79b09d4 feat(run): implement idempotent run creation`
- 文档提交：以本阶段完成后的最新 `git log` 为准
- 未 push

## 2026-07-29 — Phase 3：Worker 领取、租约与心跳（完成）

### 基本信息

- 起始 SHA：`ffff1e4`
- 实现提交：`e712f8a`
- 目标：显式 Run/Job 状态机、PostgreSQL `SKIP LOCKED` 领取、lease、heartbeat、
  JobAttempt 与审计事件。

### 问题与根因

- 只有状态枚举和 lease 字段，没有集中转换规则，各 service 未来可能写出非法状态。
- 没有领取事务时，多个 Worker 会读到同一个 queued Job。
- 只写 owner 而不写 expiry/version，旧 Worker 可在失去执行权后继续覆盖新世代。
- 没有 Attempt 和审计表时，重试历史、错误分类、操作者和转换原因不可追踪。

### 设计与修改

- 新增纯函数显式状态机，强制 reason/actor。
- PostgreSQL 候选查询采用 `FOR UPDATE OF evaluation_jobs SKIP LOCKED`，固定优先级与
  创建时间顺序。
- 领取、状态改变、lease、version、Attempt、审计和首次 Run 启动在短事务内提交。
- 网络/模型执行明确放在事务之外。
- 心跳使用 owner + expected version + running + live expiry 的条件更新，并返回新 version。
- 新增 migration `20260729_0004`、真实 PostgreSQL 并发合同、状态与租约设计文档。

### 关键失败与修正

- Job/Run/clock/jobs 模块均由导入失败开始，证明 RED 来自能力缺失。
- 状态表驱动扩展分别出现 10 和 9 个失败，随后只补需求允许边。
- ORM 导入 `AuditEvent` 失败后补表和约束。
- Ruff 首轮发现 4 个未使用导入，删除后通过。
- 真实 PostgreSQL 并发测试因本机没有服务而 skip；未改用 SQLite，也未把 skip 写成通过。

### 验证

| 检查 | 结果 |
|---|---|
| Phase 3 目标测试 | 45 passed，1 skipped |
| 非集成全量回归 | 127 passed，4 deselected |
| Ruff | All checks passed |
| mypy app | 45 source files，无问题 |
| Alembic | 唯一 head `20260729_0004`，offline SQL 通过 |
| 真实 PostgreSQL 并发 | 本机 skipped |

### 未解决与方案取舍

- 真实行锁行为仍需 CI/Compose 证据。
- Worker 尚未调用 Target/Evaluator；Reaper、retry、cancel 尚未实现。
- 没采用 Celery、Redis 锁、SQLite 或长事务；原因分别是隐藏核心机制、事实源错误、
  语义不等价和持锁风险。
- 当前不声称 exactly-once、生产级或已通过安全认证。

完整命令、RED/GREEN 过程、学习点和面试追问见
`docs/phase_3_execution_log.md`、`docs/03_state_machines.md` 与
`docs/05_worker_lease_contract.md`。

## 2026-07-29 — Phase 4：Target、Evaluator 与 CaseResult（完成）

### 基本信息

- 起始 SHA：`133a635`
- 实现提交：`e1ac1e2`
- 目标：可复现 Mock、受约束 HTTP RAG adapter、两类自动 evaluator、Worker 成功链和
  lease-fenced 最终结果。

### 问题与根因

- Job 领取后没有可执行的 Target/Evaluator 合同。
- 外部请求不能持有数据库锁，但事务外执行后 lease 可能已经过期。
- 仅靠 CaseResult 唯一约束不能阻止旧 Worker 改 Job/Attempt。
- HTTP Target 引入 SSRF、认证持久化和敏感响应泄露风险。
- 原 Run 模型没有 evaluator type，Worker 不能从版本或任意 JSON 稳定选择实现。
- 词法启发式若命名为“准确率”，会产生不受证据支持的评测结论。

### 设计与修改

- 新增 evaluation domain DTO、Target/Evaluator protocols 与 factory。
- MockTarget 由配置/metadata 确定性驱动；测试用 fake sleeper。
- HTTPRAGTarget 采用 HTTPS、精确 hostname allowlist、相对 endpoint、DNS 公网检查和
  环境变量认证引用。
- ExecutionEvaluator 记录运行事实；BasicAnswerEvaluator 只输出 `lexical_*` 指标。
- Result committer 在同一短事务检查 lease fencing、完成 Job/Attempt、写唯一 CaseResult、
  审计和 Run 成功计数。
- 新增显式 `evaluator_type` 和 migration `20260729_0005`。
- Run 创建在 artifact I/O 前验证 supported component 与安全配置。

### 关键失败与修正

- 首轮 7 组测试均因模块/CaseResult 缺失而 RED。
- 首次实现后 19 passed、1 failed：测试替身属性覆盖同名 `claim()` 方法；重命名后 20 passed。
- 组件输入补测因 `InvalidTargetConfigurationError` 缺失而 RED；加入 service/API 稳定 422。
- Ruff 首轮 6 项为两个长行和四个不必要 `getattr`；机械修正后通过。
- 真实 PostgreSQL 唯一结果与旧 lease 提交合同本机 skip，未用 SQLite 替代。

### 验证

| 检查 | 结果 |
|---|---|
| Phase 4 目标 | 20 passed，1 skipped |
| 非集成全量回归 | 145 passed，4 deselected |
| Ruff | All checks passed |
| mypy app | 57 source files，无问题 |
| Alembic | head `20260729_0005`，offline SQL 通过 |
| 真实 PostgreSQL result race | 本机 skipped |

### 未解决与方案取舍

- 执行期间的持续心跳、失败持久化、retry、Reaper 和 cancel 属于 Phase 5。
- SSRF 仍有 DNS check/connect TOCTOU，需 egress proxy 或固定地址 transport 进一步收紧。
- 没采用 LLM judge、任意 URL、明文认证配置或长数据库事务。
- 当前不声称 semantic accuracy、exactly-once、生产级或安全认证。

完整过程见 `docs/phase_4_execution_log.md` 与 `docs/09_evaluation_semantics.md`。

## 2026-07-29 — Phase 5：重试、Reaper 与取消（完成）

### 基本信息

- 起始 SHA：`e328933`
- 实现提交：`b7f3de5`
- 目标：失败路径、backoff+jitter、执行期 heartbeat、lease recovery、统一 Run 聚合、
  cooperative cancellation 和 operational CLI。

### 问题与根因

- Phase 4 的异常会让 Job 留在 running，没有 Attempt 完成或重试安排。
- Target 执行可能超过 lease，需要持续 heartbeat 并传递最新 fencing version。
- Worker 崩溃后没有 Reaper，Job 永久占用。
- Run counter 自增不能在所有并发/崩溃路径保持一致。
- 取消没有数据库事务和 Worker 安全检查点。

### 设计与修改

- 显式 `FailureClassification` 与可注入 RandomSource 的指数退避+jitter。
- 成功/失败使用相同 lease fencing；失败事务决定 retry_wait/failed/cancelled。
- Heartbeat runner 在 coroutine 执行期间更新版本并观察取消。
- Reaper 使用 expired 条件、Job `SKIP LOCKED`、Attempt lease_expired 和统一审计。
- Run 聚合在 Run lock 下重新 group-by Job 状态并覆盖 counters。
- tenant-scoped cancellation API；queued/retry_wait 直接终止，running 协作取消。
- Worker/Reaper CLI 接入真实循环、`--once` 与安全日志。

### 关键失败与修正

- 五个策略/回收模块全部从导入 RED 开始。
- heartbeat 合同扩展到 cancelling 后，一条旧断言失败；更新为新协作取消合同。
- 第二组 failure module 从导入 RED 开始。
- 测试期间识别到 running cancel 若递增 lease version 会让当前 Worker 无法读取取消，故把
  version 明确解释为 lease generation；取消信号不换代。
- mypy 发现 backoff 表达式 Any，改用 `math.pow` 固定 float。
- Ruff 发现 try/except/pass 风格，改用 suppress。

### 验证

| 检查 | 结果 |
|---|---|
| 非集成全量 | 181 passed，4 deselected |
| 真实 PostgreSQL 合同 | 2 skipped |
| Ruff | All checks passed |
| mypy app | 65 source files，无问题 |
| Alembic | Phase 5 无 schema 变更，head 保持 `20260729_0005` |
| Docker/Compose | 未运行；本机无 docker |

### 未解决与方案取舍

- 没有用 tenacity/Celery/Redis delayed queue 隐藏 retry 与事实状态。
- PostgreSQL 短暂故障目前由循环捕获并继续，但没有独立指数退避/circuit breaker。
- 真正的多 Reaper、取消/完成 race 和 crash takeover 要等 CI/Compose 证据。
- 不承诺 exactly-once、远端请求撤销、零重复费用或生产级。

完整过程见 `docs/phase_5_execution_log.md` 与 `docs/06_retry_and_cancellation.md`。

## 2026-07-29 — Phase 6：Redis 实时事件与 SSE（完成）

### 基本信息

- 起始 SHA：`a130779`
- 实现提交：`1293836`
- 目标：PostgreSQL snapshot-first SSE、best-effort Redis Pub/Sub、断线资源清理与故障降级。

### 判断与实现

- Redis Pub/Sub 是 at-most-once，因此只作为通知层，不能成为 Run/Job 最终事实来源。
- SSE 在 response start 前做 tenant-scoped Run 查询，首帧固定为 snapshot。
- tenant/run 精确频道之外，subscriber 还复核消息 payload 内的 tenant/run。
- PubSub 每客户端独立创建，生成器关闭时 unsubscribe/aclose。
- Redis 订阅失败转为 PostgreSQL 周期快照；publish 失败不影响已提交的 Worker/Reaper/cancel。
- Worker/Reaper 只在数据库事务完成后发布状态通知。

### 过程中发现的问题

- 首轮 4 个测试模块因 `app.events` 不存在而 RED。
- 首次 GREEN 为 10 passed、1 failed：测试事件 UUID 每次重建不同，固定 fixture ID 后通过。
- 回归测试发现成功 Worker 在 heartbeat 后仍传初始 lease version；改为 LeaseRunner 返回的
  最新 version，避免合法结果被 fencing 拒绝。
- Ruff/mypy 分别发现兼容参数、import、空 except、变量窄化和 redis stub 问题，均做局部修正。

### 验证

| 检查 | 结果 |
|---|---|
| 非集成全量 | 191 passed，5 deselected |
| 真实 Redis 合同 | 1 skipped |
| Ruff | All checks passed |
| mypy app | 71 source files，无问题 |
| Alembic | 无 schema 变化；head `20260729_0005` |

### 未解决与取舍

- Pub/Sub 不支持历史重放，Last-Event-ID 不能恢复丢失通知；每次重连以 snapshot 重置。
- fallback 会增加 PostgreSQL 查询负载，尚未做大量 SSE 连接容量测试。
- 真实 Redis、多 API 节点、代理缓冲和断线风暴需要可用 Docker/CI 环境验证。
- 不声称 exactly-once event delivery 或生产级。

完整过程见 `docs/phase_6_execution_log.md` 与 `docs/07_realtime_events.md`。

## 2026-07-29 — Phase 7：指标、Artifact 与 Run 比较（完成）

### 基本信息

- 起始 SHA：`2b157b5`
- 实现提交：`437248c`
- 目标：case keyset API、指标重算/持久化、Run-owned JSON artifact、同/跨版本比较。

### 设计与修改

- cursor 绑定 sort/direction/metric/status/error，权限仍由 Principal + tenant SQL 决定。
- metric JSONB 仅 numeric cast，其余 NULLS LAST。
- rate 用全部 Job 为分母；latency/evaluator metric 只用有效成功结果。
- 新增 RunMetric 与 Artifact.run_id，migration head 0006。
- 三种 deterministic report 使用现有 SHA-256 content-addressed store。
- compare 的 delta 固定 right-left；不同 dataset version 发 warning，case diff 只取交集。
- Run GET 读取已持久化 metric value，详细分布由 metrics API 返回。

### 关键问题

- Alembic 已格式化约束名被 naming convention 再格式化；用 `op.f` 修正真实 DROP 名。
- `/runs/compare` 可能被动态 UUID 路由抢先匹配；调整 router 注册顺序。
- SQLAlchemy stubs、异构 payload 和 conditional predicate 触发 strict mypy；均做局部显式类型。
- 审查发现 RunRead.metrics 长期为空，补 RED 回归和 repository 加载。

### 验证

| 检查 | 结果 |
|---|---|
| 非集成全量 | 201 passed，5 deselected |
| 真实 PostgreSQL 扩展合同 | 1 skipped |
| Ruff | All checks passed |
| mypy app | 78 source files，无问题 |
| Alembic | head `20260729_0006`，offline SQL 通过 |

### 未解决与取舍

- 没有 arbitrary metric expression index 或真实 EXPLAIN 结果。
- content store 可能有无 metadata 引用的 orphan，需要未来 GC。
- 不同版本同 case_id 的语义一致性仍需内容 hash/人工约束。
- 没有统计显著性、置信区间或生产容量结论。

完整过程见 `docs/phase_7_execution_log.md` 与
`docs/10_results_metrics_and_comparison.md`。
