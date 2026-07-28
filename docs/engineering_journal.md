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
