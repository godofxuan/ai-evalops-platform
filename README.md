# AI EvalOps Platform

多租户异步 AI 评测与任务编排平台。当前仓库已完成 Phase 0–9：工程底座、身份与不可变
数据集、异步评测与恢复、实时事件、结果比较、双人盲评，以及可观测性与可复现实验入口。

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
- tenant-owned artifact reference 与全局 SHA-256 content blob 分层；
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

Phase 3 已建立：

- Run/Job 显式状态机和强制 reason/actor；
- `FOR UPDATE OF evaluation_jobs SKIP LOCKED` 并发领取；
- 短事务内状态、lease、version、Attempt 与审计写入；
- owner/version/live-expiry 保护的心跳条件更新；
- 10 Worker 真实 PostgreSQL 并发测试合同。

Phase 4 已建立：

- deterministic MockTarget，以及由操作员 Registry 管理、固定公网 IP 连接并校验实际 peer 的
  HTTPRAGTarget；
- ExecutionEvaluator 与明确标为 lexical 的 BasicAnswerEvaluator；
- Worker 的 claim → Target → Evaluator → result 成功流水线；
- lease owner/version/expiry fencing 的 CaseResult 提交；
- Job/Attempt/Result/Audit/Run counter 同事务更新。

Phase 5 已建立：

- transient/permanent/cancelled 失败分类与有界指数退避；
- 执行 Target 期间的周期 heartbeat 与 cooperative cancellation；
- lease-fenced 失败提交和 Reaper 过期租约回收；
- queued/retry_wait 直接取消、running 转 cancelling 的幂等取消 API；
- 基于数据库真实 Job 状态重算的 Run counter/status 聚合；
- 可直接运行的 Worker/Reaper CLI 循环。

Phase 6 已建立：

- tenant/run scoped Redis Pub/Sub 实时事件；
- 鉴权后先读取 PostgreSQL snapshot 的 SSE；
- heartbeat、跨 tenant 消息复核与客户端断开清理；
- Redis publish 故障不影响 Worker durable path；
- Redis subscriber 故障转 PostgreSQL polling。

Phase 7 已建立：

- tenant-scoped keyset cursor case 查询、筛选和 metric 排序；
- 明确定义分母和 percentile 算法的聚合指标；
- RunMetric 持久化与 Run GET 指标摘要；
- metrics、failure cases、summary report JSON artifact；
- 同 Dataset Version 比较与跨版本 intersection warning/diff。

Phase 8 已建立：

- 默认关闭、服务端派生的 human reviewer credential 权限；
- deterministic sample 与不含 machine metric 的 blind packet；
- 两个不同 reviewer 的 immutable submission；
- Task row lock 保护的 agreed/disputed 转换；
- 第三 reviewer adjudication；
- agreement、Cohen’s kappa 与 human review packet artifact。

Phase 9 已建立：

- API/Worker/Reaper 独立 Prometheus registry 与低基数指标；
- API `/metrics`、Worker 9101、Reaper 9102 抓取入口；
- API request、Run 创建、claim、Target、Evaluator、result、Reaper、SSE 业务 span；
- W3C `traceparent` API 延续、Run 来源 carrier 持久化，以及 Worker/Reaper 异步 Span Link；
- question/answer/evidence/credential 等敏感字段脱敏；
- Redis/数据库单轮故障、SSE 断连和观测资源生命周期回归；
- 20 个并发幂等请求、10 Worker/100 Jobs、2 Reaper 的真实 PostgreSQL 测试合同；
- 500-case 1/2/4/8 Worker、故障注入、幂等并发和 Run diff 实验脚本；
- 架构图、面试问题和不夸大证据的简历材料。

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

Worker ---- claim → heartbeat → Target → Evaluator → fenced result/failure
Reaper ---- expired lease → retry_wait / failed / cancelled
```

PostgreSQL 是领域状态的最终事实来源。Redis 只承担可丢失的实时通知，不能决定最终
Run/Job 结果。SSE 重连首先读取 PostgreSQL，而不是假设 Pub/Sub 可以回放。

更详细的阶段边界见 [项目范围](docs/00_project_scope.md)、[架构说明](docs/01_architecture.md)、
[完整架构图](docs/architecture_diagram.md)、[Phase 1 领域模型](docs/02_domain_model.md)和
[安全边界](docs/08_security_boundaries.md)。

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

Human Review Task creator 与 reviewer 是两个默认关闭的独立权限。建议分别创建 credential：

```bash
uv run python -m scripts.create_dev_api_key \
  --tenant-slug demo \
  --key-name review-operator \
  --review-task-creator

uv run python -m scripts.create_dev_api_key \
  --tenant-slug demo \
  --key-name reviewer-a \
  --human-reviewer
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

Compose 会启动 PostgreSQL、Redis、一次性 migration、API、Worker 和 Reaper。默认开发端口只绑定到 `127.0.0.1`。

六个服务都显式使用非 root 用户、只读镜像根文件系统、`cap_drop: ALL` 与
`no-new-privileges`，并设置 CPU、内存和 PID 上限。需要写入的目录只通过命名 volume 或有界
tmpfs 开放：PostgreSQL/Redis 写各自数据卷，API/Worker 写 artifact 卷；migrate/Reaper 不挂载
artifact 卷。CI 还会用 `docker inspect` 验证 Docker 的有效 HostConfig，而不只解析 YAML。

默认 limit 是开发/CI containment，不是生产容量结论。可通过 `.env.example` 中的
`EVALOPS_APP_*`、`EVALOPS_POSTGRES_*` 和 `EVALOPS_REDIS_*` 调整；修改前应使用真实负载观察
OOM、CPU throttling、PID 和尾延迟。升级基础镜像或改用 host bind mount 后必须重跑 fresh-volume
Compose smoke，并确认宿主目录 ownership。

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

数据库、Redis URL 和 OTLP headers 使用 Pydantic `SecretStr`。日志处理器还会对
`api_key`、`authorization`、`database_url`、`redis_url`、`password`、`secret`、
`token`、`question`、`expected_answer`、`answer`、`response`、`evidence`、`trace`
等字段递归脱敏。脱敏依赖正确字段命名，不能识别被错误放入普通文本字段的任意秘密。

Dataset 默认限制为 10 MiB 文件、10,000 个 case、1 MiB 单行，可分别通过 `EVALOPS_DATASET_MAX_FILE_BYTES`、`EVALOPS_DATASET_MAX_CASES` 和 `EVALOPS_DATASET_MAX_LINE_BYTES` 下调或在受控范围内调整。

### HTTP Target Registry

HTTP Target 不是由 tenant 自由提交 URL。操作员通过
`EVALOPS_HTTP_TARGET_REGISTRY` 维护版本化 Registry，例如在 `.env` 中写入：

```dotenv
EVALOPS_HTTP_TARGET_REGISTRY={"rag-production":{"version":"rag-v1","config":{"base_url":"https://rag.example.com","endpoint":"/v1/query","auth_env_var":"RAG_PRODUCTION_BEARER_TOKEN"}}}
```

tenant 创建 Run 时只提交 Registry ID，并让请求版本与 Registry 版本精确一致：

```json
{
  "target": {
    "type": "http_rag",
    "version": "rag-v1",
    "config": {"target_id": "rag-production"}
  }
}
```

Registry 不接受 `target_id`、`allowed_hosts`、重定向开关或明文认证值；平台从
`base_url` 派生精确 hostname，并把经过验证的执行配置冻结到 Run。Registry 中只保存
`auth_env_var` 名称，真实 token 必须通过部署系统单独注入 Worker 进程；不要把 token 放进
Registry JSON、源码、镜像或日志。除纯凭证轮换外，操作员修改执行配置时必须同步提升
Registry version；平台会保存配置 hash，但无法替操作员推断版本命名是否诚实。

HTTP Target 仅允许 HTTPS 443、无 userinfo/query/fragment 的 base URL 和无 authority 的绝对
endpoint；不跟随重定向。hostname 必须是 ASCII，IDN 由 operator 显式写成规范化 punycode。
每次执行会解析全部 A/AAAA 地址，只接受原生公网地址，选择其中一个
数值 IP 建连，同时保留原 hostname 的 Host 与 TLS SNI，并在读取正文前核对实际 peer。生产部署
仍必须叠加网络 egress policy；这套应用层边界不能被描述为“完全消除 SSRF”。内部测试目标使用
MockTarget，不要把私网服务加入 HTTP Registry。

## 指标、Trace 与实验

```bash
curl http://127.0.0.1:8000/metrics
```

Prometheus 指标不使用 tenant/run/job/attempt ID 标签；这些高基数字段只进入日志和 trace。
API 抓取会从 PostgreSQL 刷新 queue/running/heartbeat Gauge。Worker/Reaper 分别在
Compose 内部端口 9101/9102 暴露自己的 counter/histogram。

配置 `EVALOPS_OTEL_EXPORTER_OTLP_ENDPOINT` 后，API、Worker 和 Reaper 使用 OTLP/HTTP
向 Collector 导出 span。未配置 endpoint 时仍生成本进程 trace ID，但没有后端持久化，
不能声称已经具备生产 trace 查询。

可复现实验：

```bash
uv run python -m scripts.run_concurrency_test
uv run python -m scripts.run_load_test
uv run python -m scripts.run_comparison_experiment
uv run python -m scripts.run_failure_scenarios --allow-service-disruption
```

Gate 1 prepared manifest schema v5 会冻结 result schema v3、expected arm plan 和不可弱化的
quality policy。最终 aggregate 自动将客观质量标为 `VERIFIED`、`FAILED` 或 `UNKNOWN`；只有完整
有效时才标记 `READY_FOR_HUMAN_REVIEW`。adoption 始终由人决定，工具不会自动选择或修改 Worker
数。`--confirm-quality-gate` / `--confirm-adoption-gate` 只是授权开始正式运行，不能代替结果
检查或用户拥有的性能阈值。

实验密钥从 `EVALOPS_EXPERIMENT_API_KEY` 读取。failure 脚本会 stop/kill 开发 Compose
服务，只能在独占开发环境执行。结果默认写入 `docs/results/` 且拒绝覆盖。完整合同见
[可观测性与实验](docs/12_observability_and_experiments.md)和
[故障矩阵](docs/13_failure_injection_matrix.md)。

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

Phase 1 migration 最初创建五张领域表：

- `tenants`；
- `api_keys`（只含 prefix 与 scrypt hash，不含明文）；
- `datasets`；
- `artifacts`（当时的一体化 tenant/物理元数据，已由 P1-7 migration 迁移）；
- `dataset_versions`（`dataset_id + version` 和 `dataset_id + sha256` 唯一）。

Phase 2 migration 新增：

- `evaluation_runs`（`tenant_id + idempotency_key` 唯一）；
- `evaluation_jobs`（`run_id + case_id` 唯一，保存不可变 case payload snapshot）。

Phase 3 migration 新增：

- `job_attempts`（`job_id + attempt_number` 唯一）；
- `audit_events`（tenant-owned 状态转换审计）。

Phase 4 migration 新增：

- `evaluation_runs.evaluator_type`；
- `case_results`（Job 唯一且 Run/case 唯一）。

Phase 7 migration 新增：

- `artifacts.run_id` 与报告类型；
- `run_metrics`（`run_id + metric_name` 唯一）。

Phase 8 migration 新增：

- `api_keys.can_review`（默认 false）；
- `human_review_tasks`；
- `human_review_submissions`；
- `human_review_adjudications`。

P1-7 migration `20260802_0009`：

- 用 `artifact_blobs` 保存全局 SHA-256、大小和物理相对路径；
- 用 `artifact_references` 保存 reference UUID、tenant、可选 Run、artifact type 和 media type；
- 保留旧 Artifact UUID，并把 `dataset_versions.artifact_id` 无损切到 reference；
- 同 tenant 的不同 Run 和不同 tenant 都可以分别拥有同一 blob，授权不再由物理去重键决定。

P2-1 migration `20260802_0010`：

- 给 `dataset_versions` 增加由 Dataset 派生的非空 `tenant_id`；
- 用包含 tenant 的复合外键约束 Dataset、Artifact Reference、Dataset Version、Run、
  API Key 与人工复核记录必须属于同一租户；
- 用 `(job_id, run_id)` 复合外键约束 Case Result 和 Human Review Task 必须引用同一条
  Job/Run 父链；
- upgrade 在加约束前检查历史矛盾并失败关闭，不会擅自改写归属；downgrade 恢复旧单列
  外键并移除可派生的 Dataset Version tenant 列。

P2-2 migration `20260802_0011`：

- 新增默认 false 的 `api_keys.can_create_review_tasks`；
- 普通 key 和 reviewer-only key 都不能创建/扩展 Human Review Task；
- creator-only key 可以创建 Task，但不会因此获得 list/submit/adjudicate reviewer 权限；
- 权限只从数据库认证记录进入 Principal，请求 body/query/header 不能自我提权。

P2-3 migration `20260802_0012`：

- `evaluation_runs.origin_traceparent` 保存首次创建 Run 的平台 `run.create` span carrier；
- 每次 Worker attempt 保持独立 root trace，通过 Span Link 指向 Run 创建 span；
- Reaper batch 保持独立，每个 recovered Job 产生自己的 linked root span；
- 历史 Run、禁用 telemetry 和 malformed carrier 安全退化为无 Link，不影响业务状态；
- 只保存 W3C `traceparent`，不持久化 baggage、tracestate、凭据或请求内容。

所有已实现的 dataset/version 和 artifact reference 读取先过滤服务端 tenant 与资源 ID，再
解析 blob。跨表复合外键提供数据库纵深防御，但当前仍未启用 PostgreSQL RLS；两者不是
同一种隔离机制。

Run/Job 状态转换由两个纯领域状态机集中校验，图和审计规则见
[状态机合同](docs/03_state_machines.md)。

实时事件和故障降级合同见 [SSE 合同](docs/07_realtime_events.md)。
结果、指标和比较语义见 [结果分析合同](docs/10_results_metrics_and_comparison.md)。
人工评审信任和盲化边界见 [人工评审合同](docs/11_human_review.md)。

## Worker、崩溃恢复与幂等

- Worker CLI 已运行 claim、执行期 heartbeat、Target、Evaluator 与 fenced commit 循环；
- Reaper 使用 `SKIP LOCKED` 小批量扫描并回收过期 lease；
- transient failure 使用带 jitter 的有界指数退避，permanent failure 不重试；
- cooperative cancellation 由 heartbeat 观察，陈旧 Worker 不能提交结果或失败；
- Run 创建已使用 canonical request hash、Idempotency-Key 和 PostgreSQL 唯一约束；
- 相同 key/请求返回同一 Run，不同请求返回 409；
- 真实 PostgreSQL 并发合同存在，但本机因无数据库而 skipped。

因此当前仓库能证明幂等与租约的代码/SQL 合同，但本机无 PostgreSQL，不能证明真实行锁并发
成功；成功、失败、重试、Reaper 与取消已有代码合同，但本机仍不能给出真实服务下
at-least-once 执行和崩溃恢复的实验结论。

## 实验结果

Phase 0–9 的本地命令、RED/GREEN 证据和环境限制分别记录在
[Phase 0 日志](docs/phase_0_execution_log.md)、[Phase 1 日志](docs/phase_1_execution_log.md)、
[Phase 2 日志](docs/phase_2_execution_log.md)和
[Phase 3 日志](docs/phase_3_execution_log.md)和
[Phase 4 日志](docs/phase_4_execution_log.md)和
[Phase 5 日志](docs/phase_5_execution_log.md)和
[Phase 6 日志](docs/phase_6_execution_log.md)和
[Phase 7 日志](docs/phase_7_execution_log.md)和
[Phase 8 日志](docs/phase_8_execution_log.md)和
[Phase 9 日志](docs/phase_9_execution_log.md)。幂等细节见
[Run 幂等合同](docs/04_idempotency_contract.md)，领取细节见
[Worker 租约合同](docs/05_worker_lease_contract.md)，阶段汇总见
[工程日志](docs/engineering_journal.md)。
Target 与自动指标边界见 [评测语义](docs/09_evaluation_semantics.md)。
重试、回收和取消语义见 [恢复合同](docs/06_retry_and_cancellation.md)。

P1-6 operator Registry、DNS rebinding 与实际 peer 加固的逐条判断、RED/GREEN、环境问题和
残余风险见 [HTTP Target 安全加固记录](docs/reviews/p1_6_http_target_security_log.md)。
Gate 1 自动质量检查、人工采纳边界、schema 升级和旧证据影响见
[P2-5 Gate 自动化记录](docs/reviews/p2_5_gate_automation_log.md)。

不得把跳过的集成测试或未运行的 Docker 命令写成通过。

2026-07-29 Phase 8 本机阶段结果：

| 检查 | 结果 |
|---|---|
| Python / uv | CPython 3.12.13 / uv 0.11.32 |
| lock | `uv lock --check` 通过 |
| format / lint | Phase 8 文件已格式化；All checks passed |
| mypy | app 86 files，无问题 |
| pytest 非集成 | 210 passed，6 deselected |
| Phase 8 PostgreSQL review contract | 1 skipped；本机未启用 migrated PostgreSQL |
| Alembic | 唯一 head `20260729_0007`；offline PostgreSQL SQL 通过 |
| Compose YAML / CI YAML | PyYAML 静态解析通过 |
| Docker build / Compose up | 未运行；`docker --version` 与 `docker compose version` 均为 CommandNotFound |
| GitHub Actions | 未运行；没有 push |

2026-07-29 Phase 9 当前验证结果（本机 + GitHub CI）：

| 检查 | 结果 |
|---|---|
| Python / uv | CPython 3.12.13 / uv 0.11.32 |
| observability deps | OpenTelemetry SDK 1.44.0 / Prometheus Client 0.26.0 |
| lock | `uv lock --check` 通过；60 packages |
| format / lint | 199 files already formatted；All checks passed |
| mypy | app + scripts + integration/concurrency tests，103 source files，无问题 |
| pytest 非集成 | 235 passed，6 deselected |
| 真实 PostgreSQL/Redis contracts | 本机 6 skipped；GitHub Actions 6 passed |
| Alembic | 唯一 head `20260729_0008`；offline SQL 与 CI 真实 PostgreSQL migration 通过 |
| Docker image / Compose smoke | 本机无 Docker；GitHub Actions build、迁移、API/Worker/Reaper 启动和 readiness 通过 |
| 500-case / 1/2/4/8 Worker | NOT-RUN；Docker/Compose 均为 CommandNotFound |
| fault/container comparison 实验 | NOT-RUN；没有运行栈 |
| GitHub Actions | [Run #7](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30425559361) 两个 job 均通过 |

未执行实验的完整清单见
[Phase 9 环境与阻塞](docs/results/phase_9_environment_and_blockers.md)。本 README 不提供
吞吐/p50/p95 数字，因为本机没有产生这些证据。

## 当前限制

- tenant 隔离依赖应用层查询约束，尚无 PostgreSQL RLS；
- API Key 认证尚无限流/容量验证，不声称抵御 DoS；
- 本地 artifact storage 不适合多 API 主机共享，数据库提交与文件删除也不是跨系统原子事务；
- JSONL 第一版有界读入内存，不是流式 parser；
- Run API 已有 create/get/cancel/SSE/cases/metrics/artifacts/compare；
- Worker/Reaper 是第一版轮询循环，尚无优雅的数据库断线重连策略；
- HTTP Target 已固定经过验证的数值公网 IP，并在读取正文前校验实际 peer；仍依赖当前
  HTTPX/HTTPCore transport 元数据合同和部署级 egress 控制，不声称完全消除 SSRF；
- 已有 Prometheus 指标和 OpenTelemetry SDK span，但本机未配置 Prometheus/Collector；
- API 与 Worker/Reaper 刻意保持不同 trace，并用持久化 Run carrier 建立 Span Link；尚无真实
  Collector/backend 查询、采样、保留和多副本导出证据；
- 多 Worker 指标要求 Prometheus 抓取每一个副本，尚未验证 service discovery/告警；
- Gate 1 能自动检查客观质量和 expected-arm 完整性，但没有用户数值 performance policy；
  `READY_FOR_HUMAN_REVIEW` 不等于 adoption，正式 500-case/32-arm 仍未运行；
- can_review 是管理员凭据信任边界，不是自然人/反自动化身份认证；
- can_create_review_tasks 与 can_review 独立且都默认关闭；当前仍不是通用 RBAC/scope 系统；
- review deterministic sampling 会读入全部成功候选，尚无大 Run sampling 容量证据；
- 任意 JSONB metric 排序没有表达式索引，尚无大 Run query plan/容量证据；
- artifact 支持已知 SHA 的无引用清理，但尚无定时全盘扫描/对象存储生命周期 GC；
- SSE fallback 尚未做大量长连接容量测试，Pub/Sub 不提供历史回放；
- readiness 表示依赖当前可用，不等于系统通过生产可靠性或安全认证。

## 面试展示路径（Phase 9）

1. 解释 API Key 为什么只保存版本化 scrypt hash，以及 unknown prefix 为什么执行 dummy hash；
2. 展示 Principal 如何从服务端 tenant 关联派生，请求体 `tenant_id` 如何被拒绝；
3. 展示 dataset/version SQL 如何强制 tenant 条件，并让跨 tenant 与不存在共享 404；
4. 展示 JSONL 的有界读取、逐行错误定位、case ID 唯一和敏感内容不回显；
5. 展示 artifact 的 SHA 路径、临时文件、fsync、发布前摘要确认、硬链接原子发布与物理去重；
6. 展示 dataset 行锁如何串行化 version 分配，以及为何验证/落盘不放进长数据库事务；
7. 展示真实 PostgreSQL 集成合同与“本机 skip 不算通过”的证据；
8. 展示 Worker/Reaper 如何共享 lease fencing、锁顺序和数据库最终事实来源。
9. 展示 canonical request hash 为什么忽略 object key 顺序但保留数组顺序。
10. 展示首次幂等查询、数据库唯一约束和冲突后 hash 复核如何共同处理并发。
11. 展示 `SKIP LOCKED` 领取、owner/version 心跳 fencing 与短事务边界。
12. 展示 Target 成功后为何仍需再次校验 lease 才能写唯一 CaseResult。
13. 解释 `lexical_*` 指标为什么不能称为语义准确率。
14. 展示 operator Registry、数值 IP 固定、Host/SNI 保留和 peer 校验如何收紧 DNS 重绑定窗口，
    以及为什么仍需网络 egress policy。
15. 解释失败分类、指数退避+jitter，以及未知内部错误为何只保存安全摘要。
16. 展示取消如何从 running 进入 cancelling，并由 heartbeat 驱动协作式停止。
17. 展示 Reaper 如何把过期 Attempt 标成 `lease_expired`，再决定重试、失败或取消。
18. 解释为什么 PostgreSQL snapshot 必须先于 Redis 订阅，以及断线窗口意味着什么。
19. 展示 Redis publish 失败为何不会改变已提交 Job，并如何退化为 PostgreSQL polling。
20. 展示 heartbeat 后结果提交必须使用最新 lease version 的回归测试。
21. 解释 keyset cursor 为什么绑定 query contract，以及为什么它仍不是授权凭据。
22. 展示 bool/NaN 为什么不能进入自动指标，p95 采用哪种插值定义。
23. 展示跨 Dataset Version 比较为何只对 case_id 交集做 diff。
24. 展示 Alembic `op.f` 如何避免 naming convention 重写已有约束名。
25. 解释 can_review 能防什么，以及为什么不能声称它证明了“操作者一定是真人”。
26. 展示 candidate SQL、own-submission join 和 packet artifact 的三层盲化。
27. 展示为什么 task/reviewer unique 仍需要 Task `FOR UPDATE`。
28. 解释 observed/expected agreement、kappa 和单类别分母为零。
29. 展示为什么 tenant/run/job ID 进入 trace/log 而不是 Prometheus label。
30. 展示 API 如何延续 W3C traceparent，以及为什么 Worker 用新 trace + Span Link，而不是
    继续一个跨排队/retry 的超大 parent-child trace。
31. 展示 SSE 观测包装曾如何破坏 async generator close，并如何用 `aclosing` 修复。
32. 展示 500-case、幂等、故障和 comparison 脚本如何拒绝覆盖负面结果。
33. 明确区分本机 235 passed、CI 6 个真实服务合同 passed 和 NOT-RUN 容量实验，拒绝把
    合同当成性能实测结果。
