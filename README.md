# AI EvalOps Platform

多租户异步 AI 评测与任务编排平台。当前仓库完成 **Phase 0 工程底座** 与 **Phase 1 身份和数据集**；Run、Job 和任务执行仍未实现。

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

Phase 1 已建立：

- tenant 与只显示一次的 scrypt API Key；
- revoked、expired、disabled tenant 和认证并发状态复核；
- Principal 服务端派生与统一 401；
- tenant-scoped Dataset create/get；
- 有界 UTF-8 JSONL 校验与不可变 Dataset Version；
- tenant-owned artifact 元数据与 SHA-256 内容寻址物理存储；
- 原子发布、物理去重、落盘摘要确认和临时文件清理；
- Phase 1 Alembic migration、运维脚本与真实 PostgreSQL 集成测试合同。

Phase 2 已建立：

- canonical Run request hash；
- tenant-scoped Idempotency-Key replay 与 payload conflict；
- 数据库唯一约束保护的并发创建路径；
- 可复现 target/evaluator/dataset hash 与版本绑定；
- 一个 case 一个 queued Job，并保存不可变 case payload snapshot；
- `POST /api/v1/runs` 与 `GET /api/v1/runs/{run_id}`；
- Phase 2 Alembic migration 与真实 PostgreSQL 并发测试合同。

Worker 和 Reaper 当前仍只维持进程生命周期，并明确记录 `capability=lifecycle_only`。Jobs 已能初始化，但它们尚不会领取或回收任务。

## 架构骨架

```text
Client
  |
  v
FastAPI API
     |
     +---- Bearer API Key ---- tenant Principal
     |                              |
     |                              +---- Dataset / immutable version ---- PostgreSQL
     |                                                       |
     |                                                       +---- artifact metadata
     |                                                               |
     |                                                               +---- SHA-256 local storage
     |
     +---- readiness ---- PostgreSQL / Redis / artifact directory / Alembic
     +---- structured JSON logs + request_id + tenant context

Worker process ---- lifecycle only
Reaper process ---- lifecycle only
```

PostgreSQL 将是后续领域状态的最终事实来源。Redis 只承担可丢失的实时能力，不能决定最终 Run/Job 结果。

更详细的阶段边界见 [项目范围](docs/00_project_scope.md)、[架构说明](docs/01_architecture.md)、[Phase 1 领域模型](docs/02_domain_model.md)和[安全边界](docs/08_security_boundaries.md)。

## 快速启动

### 本地 Python

前置条件：uv 和 Python 3.12。uv 可以自动安装缺失的 Python 3.12。

```bash
uv python install 3.12
uv sync --locked --all-groups
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload \
  --loop app.core.event_loop:create_psycopg_compatible_event_loop
```

上述 Alembic 和 readiness 命令要求 `.env` 指向真实 PostgreSQL/Redis。只访问 liveness 不会主动连接外部服务：

Uvicorn 显式使用项目的 Selector loop factory，是因为 psycopg async 在 Windows 不兼容系统默认的 Proactor loop。Alembic、CLI、运维脚本和 async pytest 也使用同一合同，避免“测试能跑、真实入口不能连接”的差异。

```bash
curl http://127.0.0.1:8000/health/live
```

预期：

```json
{"status":"alive"}
```

创建开发 tenant/API Key（明文只在成功提交后显示一次）：

```bash
uv run python -m scripts.create_dev_api_key \
  --tenant-slug demo \
  --tenant-name "Demo tenant" \
  --key-name local
```

撤销时只传安全前缀，不要把完整密钥放入命令历史：

```bash
uv run python -m scripts.revoke_api_key evk_001122334455
```

用返回的密钥创建 dataset 并上传 version：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/datasets \
  -H "Authorization: Bearer $EVALOPS_DEMO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"rag-regression","description":"Regression cases"}'

curl -X POST http://127.0.0.1:8000/api/v1/datasets/<dataset-id>/versions \
  -H "Authorization: Bearer $EVALOPS_DEMO_API_KEY" \
  -F "file=@cases.jsonl;type=application/x-ndjson"
```

不要把真实 API Key 写入 `.env.example`、源码、日志或 shell 脚本。上面的环境变量名只是调用示例。

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

Dataset 默认限制为 10 MiB 文件、10,000 个 case、1 MiB 单行，可分别通过 `EVALOPS_DATASET_MAX_FILE_BYTES`、`EVALOPS_DATASET_MAX_CASES` 和 `EVALOPS_DATASET_MAX_LINE_BYTES` 下调或在受控范围内调整。

## 测试与质量命令

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run mypy scripts
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

Phase 1 migration 创建五张领域表：

- `tenants`；
- `api_keys`（只含 prefix 与 scrypt hash，不含明文）；
- `datasets`；
- `artifacts`（tenant-owned 元数据）；
- `dataset_versions`（`dataset_id + version` 和 `dataset_id + sha256` 唯一）。

Phase 2 migration 新增：

- `evaluation_runs`（`tenant_id + idempotency_key` 唯一）；
- `evaluation_jobs`（`run_id + case_id` 唯一，保存不可变 case payload snapshot）。

物理 artifact 可按 SHA-256 跨 tenant 复用，但数据库元数据保留 tenant 所有权。所有已实现的 dataset/version 查询同时过滤服务端 tenant 与资源 ID；当前采用应用层隔离，尚未启用 PostgreSQL RLS。

Run/Job 状态枚举和持久化字段已经存在，显式合法转换状态机将在 Phase 3 实现。

## Worker、崩溃恢复与幂等

- Worker 当前不领取任务；
- Reaper 当前不扫描 lease；
- `SKIP LOCKED`、lease、heartbeat、retry、crash recovery 和 cooperative cancellation 均未实现；
- Run 创建已使用 canonical request hash、Idempotency-Key 和 PostgreSQL 唯一约束；
- 相同 key/请求返回同一 Run，不同请求返回 409；
- 真实 PostgreSQL 并发合同存在，但本机因无数据库而 skipped。

因此当前仓库能证明幂等代码/数据库合同，但不能证明本机真实并发成功，也不能证明 at-least-once 执行或崩溃恢复。

## 实验结果

Phase 0–2 的本地命令、RED/GREEN 证据和环境限制分别记录在 [Phase 0 日志](docs/phase_0_execution_log.md)、[Phase 1 日志](docs/phase_1_execution_log.md)和 [Phase 2 日志](docs/phase_2_execution_log.md)。幂等细节见 [Run 幂等合同](docs/04_idempotency_contract.md)，阶段汇总见 [工程日志](docs/engineering_journal.md)。

不得把跳过的集成测试或未运行的 Docker 命令写成通过。

2026-07-29 Phase 2 本机阶段结果：

| 检查 | 结果 |
|---|---|
| Python / uv | CPython 3.12.13 / uv 0.11.32 |
| lock | `uv lock --check` 通过；48 packages |
| format / lint | Phase 2 文件已格式化；All checks passed |
| mypy | app 38 files，无问题 |
| pytest 非集成 | 87 passed，3 deselected |
| Phase 2 PostgreSQL integration | 1 skipped；本机无 migrated real PostgreSQL |
| Alembic | 唯一 head `20260729_0003` 与 offline PostgreSQL SQL 通过 |
| Compose YAML / CI YAML | PyYAML 静态解析通过 |
| Docker build / Compose up | 未运行；`docker --version` 与 `docker compose version` 均为 CommandNotFound |
| GitHub Actions | 未运行；没有 push |

## 当前限制

- tenant 隔离依赖应用层查询约束，尚无 PostgreSQL RLS；
- API Key 认证尚无限流/容量验证，不声称抵御 DoS；
- 本地 artifact storage 不适合多 API 主机共享，尚无 artifact GC；
- JSONL 第一版有界读入内存，不是流式 parser；
- Run 目前只有 create/get；case 结果、取消、SSE 与比较尚未实现；
- 没有任务队列、Worker 业务、Reaper 业务或取消；
- 没有 Target/Evaluator；
- 没有 SSE、运行比较、人工评审、Prometheus 指标或 OpenTelemetry trace；
- readiness 表示依赖当前可用，不等于系统通过生产可靠性或安全认证。

## 面试展示路径（Phase 2）

1. 解释 API Key 为什么只保存版本化 scrypt hash，以及 unknown prefix 为什么执行 dummy hash；
2. 展示 Principal 如何从服务端 tenant 关联派生，请求体 `tenant_id` 如何被拒绝；
3. 展示 dataset/version SQL 如何强制 tenant 条件，并让跨 tenant 与不存在共享 404；
4. 展示 JSONL 的有界读取、逐行错误定位、case ID 唯一和敏感内容不回显；
5. 展示 artifact 的 SHA 路径、临时文件、fsync、发布前摘要确认、硬链接原子发布与物理去重；
6. 展示 dataset 行锁如何串行化 version 分配，以及为何验证/落盘不放进长数据库事务；
7. 展示真实 PostgreSQL 集成合同与“本机 skip 不算通过”的证据；
8. 说明 Worker/Reaper、任务执行与崩溃恢复为何仍严格留在后续阶段。
9. 展示 canonical request hash 为什么忽略 object key 顺序但保留数组顺序。
10. 展示首次幂等查询、数据库唯一约束和冲突后 hash 复核如何共同处理并发。
