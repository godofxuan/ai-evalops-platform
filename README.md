# AI EvalOps Platform

多租户异步 AI 评测与任务编排平台。当前仓库只完成 **Phase 0 工程底座**，尚未实现租户、数据集、Run、Job 或任务执行。

## 业务问题

本项目要把只能本地运行的 RAG/Agent/大模型评测脚本，逐步改造成可提交、排队、执行、重试、恢复、取消、观察、比较和审计的后端平台。它不会复制现有 RAG 的检索或 Agent 代码；未来只通过 HTTP 把外部 RAG 当作被测目标。

第一版最终目标语义是：

```text
at-least-once job execution
+ idempotent result persistence
+ lease-based crash recovery
```

不是 exactly-once execution，也不承诺零重复或“生产级”。

## 当前实现

Phase 0 已建立：

- Python 3.12 + uv 锁文件；
- FastAPI app factory；
- JSON 结构化日志和按敏感字段名递归脱敏；
- request ID 响应头与日志上下文；
- liveness 与 readiness；
- PostgreSQL、Redis、artifact 目录和 Alembic revision 探测；
- Alembic 空基线迁移；
- API、Worker、Reaper 进程骨架；
- 单元/API/真实服务集成测试合同；
- 非 root Docker 镜像、完整 Compose 拓扑和 CI 基础。

Worker 和 Reaper 在 Phase 0 只维持进程生命周期，并明确记录 `capability=lifecycle_only`。它们不会领取或回收任务。

## 架构骨架

```text
Client
  |
  v
FastAPI API ---- readiness ---- PostgreSQL
     |               +-------- Redis
     |               +-------- artifact directory
     |               +-------- Alembic revision
     |
     +---- structured JSON logs + request_id

Worker process ---- lifecycle only
Reaper process ---- lifecycle only
```

PostgreSQL 将是后续领域状态的最终事实来源。Redis 只承担可丢失的实时能力，不能决定最终 Run/Job 结果。

更详细的阶段边界见 [项目范围](docs/00_project_scope.md) 和 [架构说明](docs/01_architecture.md)。

## 快速启动

### 本地 Python

前置条件：uv 和 Python 3.12。uv 可以自动安装缺失的 Python 3.12。

```bash
uv python install 3.12
uv sync --locked --all-groups
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

上述 Alembic 和 readiness 命令要求 `.env` 指向真实 PostgreSQL/Redis。只访问 liveness 不会主动连接外部服务：

```bash
curl http://127.0.0.1:8000/health/live
```

预期：

```json
{"status":"alive"}
```

### Docker Compose

```bash
docker compose -f deploy/compose.yaml up --build --wait
curl http://127.0.0.1:8000/health/ready
```

Compose 会启动 PostgreSQL、Redis、一次性 migration、API、Worker 骨架和 Reaper 骨架。默认开发端口只绑定到 `127.0.0.1`。

停止并删除开发数据卷：

```bash
docker compose -f deploy/compose.yaml down --volumes
```

这会删除 Compose 管理的开发数据库、Redis 和 artifact 卷，不应在需要保留这些开发数据时执行。

## 健康检查合同

`GET /health/live`

- 只证明 API 进程可响应；
- 不访问 PostgreSQL、Redis 或文件系统；
- 返回 HTTP 200。

`GET /health/ready`

- 并发检查 PostgreSQL `SELECT 1`；
- 检查 Redis `PING`；
- 对 artifact 目录执行临时写入、flush、`fsync` 和清理；
- 比较数据库 current revisions 与代码 Alembic heads；
- 全部正常返回 200；
- 任一失败返回 503 和稳定错误码；
- 不回显底层异常、连接串或密码。

## 配置

所有配置使用 `EVALOPS_` 前缀。示例见 `.env.example`。

数据库和 Redis URL 使用 Pydantic `SecretStr`，日志处理器还会对 `api_key`、`authorization`、`database_url`、`redis_url`、`password`、`secret`、`token` 等字段递归脱敏。脱敏依赖正确字段命名，不能识别被错误放入普通文本字段的任意秘密。

## 测试与质量命令

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run pytest -m "not integration"
```

真实服务集成测试：

```bash
EVALOPS_RUN_INTEGRATION=1 uv run pytest -m integration
```

在 PowerShell 中：

```powershell
$env:EVALOPS_RUN_INTEGRATION = "1"
uv run pytest -m integration
```

集成测试禁止用 SQLite 代替 PostgreSQL。CI 会启动真实 PostgreSQL 和 Redis、执行 migration 后再运行它。

## 数据模型与状态机

Phase 0 只有 Alembic revision 基线，没有领域表。tenant、API Key、dataset、Run、Job、attempt、result 等表会在相应阶段通过行为合同和测试加入。

Run/Job 显式状态机尚未实现。`app/domain/job_state_machine.py` 是用户后续亲自实现的学习模块，Phase 0 没有提前创建或填充它。

## Worker、崩溃恢复与幂等

- Worker 当前不领取任务；
- Reaper 当前不扫描 lease；
- `SKIP LOCKED`、lease、heartbeat、retry、crash recovery 和 cooperative cancellation 均未实现；
- Idempotency-Key 和幂等结果持久化尚未实现。

因此当前仓库不能证明 at-least-once 执行、崩溃恢复或并发幂等；这些只是后续目标。

## 实验结果

Phase 0 的本地命令、RED/GREEN 证据和环境限制记录在 [逐步执行日志](docs/phase_0_execution_log.md)。阶段汇总见 [工程日志](docs/engineering_journal.md)。

不得把跳过的集成测试或未运行的 Docker 命令写成通过。

2026-07-28 本机结果：

| 检查 | 结果 |
|---|---|
| Python / uv | CPython 3.12.13 / uv 0.11.32 |
| lock / format / lint / mypy | 全部通过 |
| pytest | 9 passed，1 integration skipped |
| Alembic | head 与 offline SQL 生成通过 |
| 独立 Uvicorn liveness | HTTP 200，含 request ID |
| 无依赖时 readiness | HTTP 503，稳定错误码，无连接串 |
| Compose YAML / CI YAML | 静态解析通过 |
| Docker build / Compose up | 未运行；本机无 `docker` 命令 |
| GitHub Actions | 未运行；没有 push |

## 当前限制

- 没有身份认证和多租户隔离；
- 没有数据集上传或 immutable version；
- 没有 Run/Job API；
- 没有任务队列、Worker 业务、Reaper 业务或取消；
- 没有 Target/Evaluator；
- 没有 SSE、运行比较、人工评审、Prometheus 指标或 OpenTelemetry trace；
- readiness 表示依赖当前可用，不等于系统通过生产可靠性或安全认证。

## 面试展示路径（Phase 0）

1. 解释 liveness 与 readiness 为什么必须分开；
2. 展示 readiness 如何并发探测四个依赖、限制超时并隐藏异常细节；
3. 展示 lifespan 如何创建和关闭异步客户端；
4. 展示为什么 Alembic 只有空基线而没有提前创建领域表；
5. 展示 JSON 日志、request ID 和脱敏边界；
6. 展示真实 PostgreSQL/Redis 集成测试与“本机跳过不算通过”的证据；
7. 说明 Worker/Reaper 为什么只是诚实的生命周期骨架。
