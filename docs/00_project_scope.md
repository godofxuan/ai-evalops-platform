# AI EvalOps Platform：项目范围与阶段合同

## 1. 业务问题

AI EvalOps Platform（多租户异步 AI 评测与任务编排平台）用于把只能在本地运行的 AI 评测脚本，逐步改造成可提交、排队、执行、恢复、取消、观察、比较和审计的后端平台。

本仓库不复制现有 Enterprise Agentic RAG 的检索或 Agent 逻辑。未来平台只会把外部 RAG API 当作被测目标。

## 2. 第一版系统语义

第一版最终要实现的正确语义是：

```text
at-least-once job execution
+ idempotent result persistence
+ lease-based crash recovery
```

这不等同于 exactly-once execution，也不承诺“零重复”或“生产级”。

## 3. 分阶段边界

项目必须逐阶段完成。每个阶段都执行以下闭环：

1. 检查仓库和环境；
2. 定义本阶段问题、接口与验收合同；
3. 列出文件变更；
4. 以一条可观察行为为单位执行 RED → GREEN；
5. 运行目标测试和相关回归；
6. 记录失败、修复、证据和仍未知的部分；
7. 创建小提交；
8. 输出学习要点；
9. 停止并等待用户确认。

禁止自动连续完成所有阶段，禁止未经允许 push。

## 4. Phase 0：仓库初始化

### 4.1 要解决的问题

后续的多租户、异步任务和并发实验都依赖一个一致的工程底座。Phase 0 只回答以下问题：

- 项目能否锁定 Python 3.12 和依赖；
- API 进程能否启动并提供存活检查；
- 系统能否明确判断 PostgreSQL、Redis、artifact 目录和数据库迁移是否就绪；
- API、Worker 和 Reaper 是否具有清晰但不冒充业务已完成的进程入口；
- 本地、容器和 CI 是否使用一致命令；
- 失败验证和环境限制能否被长期保留。

### 4.2 设计合同

- Python 版本固定为 `>=3.12,<3.13`。
- 使用 uv 维护跨平台锁文件，所有自动化命令使用 `uv run` 或 `uv sync --locked`。
- FastAPI 应用通过工厂函数创建，便于测试注入，并使用 lifespan 管理资源。
- `GET /health/live` 只证明 API 进程能响应，不访问外部依赖。
- `GET /health/ready` 检查 PostgreSQL、Redis、artifact 目录和 Alembic revision。
- readiness 的失败响应只暴露组件和稳定错误码，不回显数据库密码、Redis 密码或底层异常文本。
- PostgreSQL 是未来持久状态的事实来源；Redis 在 Phase 0 只作为依赖被探测。
- API、Worker、Reaper 共用同一个镜像；Phase 0 的 Worker/Reaper 入口只维护进程生命周期，不领取或回收任务。
- Docker 镜像使用 Python 3.12、锁定依赖并以非 root 用户运行。
- 集成测试只使用真实 PostgreSQL 和 Redis；不以 SQLite 替代。

### 4.3 Phase 0 验收标准

1. `uv lock --check` 或等价锁文件校验通过。
2. Ruff 格式和 lint 通过。
3. mypy 严格类型检查通过。
4. 单元/API 测试通过。
5. `GET /health/live` 返回 HTTP 200 和稳定响应合同。
6. readiness 全部依赖正常时返回 200；任一关键检查失败时返回 503。
7. 真实 PostgreSQL/Redis 的 readiness 集成测试存在，并在具备服务的环境中通过。
8. Alembic 可以升级到当前 head。
9. Dockerfile 满足 Python 3.12、锁文件和非 root 运行约束。
10. Compose 包含 API、Worker、Reaper、PostgreSQL、Redis，并配置依赖健康检查。
11. CI 包含锁文件、lint、格式、类型、测试、受控集成测试和镜像构建。
12. 所有实际执行、失败和未执行验证都写入日志。

### 4.4 Phase 0 明确不实现

- tenant 与 API Key；
- dataset 与 immutable dataset version；
- Run、Job 和状态机；
- Idempotency-Key；
- `SKIP LOCKED`、lease、heartbeat 和 attempt；
- Target 与 Evaluator；
- retry、Reaper 的回收业务和 cooperative cancellation；
- Redis 事件、SSE、Run 比较；
- Artifact 内容寻址写入；
- 人工评审、业务指标、追踪和负载实验。

### 4.5 计划文件

以下是写测试前的文件计划。实施中如果调整，必须在 execution log 说明原因：

```text
.github/workflows/ci.yml
.dockerignore
.env.example
.gitattributes
.gitignore
.python-version
Dockerfile
README.md
alembic.ini
alembic/
  env.py
  script.py.mako
  versions/20260728_0001_baseline.py
app/
  __init__.py
  main.py
  api/
    __init__.py
    middleware.py
    routes_health.py
  core/
    __init__.py
    config.py
    logging.py
  health/
    __init__.py
    service.py
  persistence/
    __init__.py
    database.py
    redis.py
  cli.py
data/artifacts/.gitkeep
deploy/compose.yaml
docs/
  00_project_scope.md
  01_architecture.md
  engineering_journal.md
  phase_0_execution_log.md
pyproject.toml
tests/
  conftest.py
  api/test_health.py
  integration/test_readiness.py
  unit/test_logging.py
uv.lock
```

没有预建后续阶段的空模块。`app/persistence/redis.py` 是在实现前明确加入计划的基础设施客户端，与数据库客户端并列；它不包含 Phase 6 的事件能力。`app/cli.py` 只提供 Worker/Reaper 生命周期骨架，避免提前修改后续由用户亲自实现的 `app/jobs/reaper.py`。

## 5. 逐步记录规范

每个阶段同时维护：

- `docs/engineering_journal.md`：适合回顾和面试复盘的阶段摘要；
- `docs/phase_<n>_execution_log.md`：按实际顺序记录命令、预期、结果、问题、判断和效果。

记录的是可验证的工程依据与取舍，不把未运行的检查写成通过，也不删除负面结果。
