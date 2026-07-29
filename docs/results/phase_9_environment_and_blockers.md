# Phase 9 本机验证结果与基础设施阻塞

记录时间：2026-07-29（Asia/Shanghai）

## 1. 环境

| 项目 | 实际值 |
|---|---|
| 工作目录 | `D:\文档\ai-evalops-platform` |
| Phase 9 起始提交 | `51a9ac4` |
| 可观测性实现提交 | `5af65ca` |
| 实验工具提交 | `36b2baf` |
| 失败证据保留修复 | `80ed75e` |
| uv 环境 Python | CPython 3.12.13 |
| 系统默认 Python | 3.13.5（项目命令没有使用它） |
| uv | 0.11.32 |
| OpenTelemetry SDK | 1.44.0 |
| Prometheus Client | 0.26.0 |
| Alembic head | `20260729_0007`（单一 head） |
| Docker CLI | 不存在，CommandNotFound |
| Docker Compose | 不存在，CommandNotFound |
| 本机 PostgreSQL/Redis | 未配置为本阶段真实测试服务 |

## 2. 已执行结果

| 命令/检查 | 结果 |
|---|---|
| 初始 Phase 9 RED | 4 个 collection error：缺少 `app.observability` 和 OpenTelemetry SDK |
| metrics/trace 第一轮 GREEN | 13 passed，2 failed |
| 修复日志测试与 SSE close 后 | 15 passed |
| Worker/durable observability 定向回归 | 10 passed |
| fault matrix、脚本与 MockTarget profile | 12 passed |
| `ruff format --check .` | 196 files already formatted |
| `ruff check .` | All checks passed |
| `mypy app scripts` | 96 source files，无问题 |
| 非集成全量 pytest | 230 passed，6 deselected |
| integration contract 命令 | 6 skipped，230 deselected |
| `uv lock --check` | 60 packages resolved，无变更 |
| load/failure script `--help` | 正常 |
| `alembic heads` | 单一 head `20260729_0007` |
| Alembic offline PostgreSQL SQL | 从 baseline 到 0007 全部生成并 COMMIT |

## 3. 本阶段真实遇到的问题

### 3.1 日志捕获器看不到正确输出

现象：API observability 测试中 stdout 已经出现 request_id/trace_id，但 `caplog.records`
为空。

根因：`create_app()` 调用 `configure_logging()`，它会按生产合同替换 root handlers；
pytest 的 caplog handler 被移除。

处理：测试改为捕获真实 JSON stdout，而不是改变生产日志初始化来迎合测试。

效果：验证的是用户真实会得到的 JSON 日志，并确认传入 traceparent 的 trace ID 被
延续。

### 3.2 SSE 外层观测包装破坏 close 传播

现象：增加 connection Gauge 后，既有 `subscriber.closed is True` 回归失败。

根因：外层 async generator 使用 `async for` 消费内层 generator，但外层被 `aclose`
时没有自动关闭内层。

第一次处理：为一层内层 generator 加 `aclosing`。

第二个问题：加入 `sse.connection` span 后又新增一层 helper generator，关闭传播再次
中断。

最终处理：去掉多余 helper 层，在 trace/no-trace 两条分支中都直接
`async with aclosing(stream)`。

效果：SSE 客户端断开时，Redis subscriber 关闭且 `sse_connections` 回到 0。这个问题
说明“观测代码”也能制造真实资源泄漏，必须保留原生命周期测试。

### 3.3 PostgreSQL Enum SQL 预期大小写错误

现象：durable Gauge SQL 测试预期 `QUEUED`，实际编译为 `queued`。

根因：项目枚举列的持久化值是小写 value。

处理：修正测试预期为真实 schema 值，没有修改生产 SQL 去匹配错误断言。

### 3.4 OpenTelemetry typing 导出位置

现象：运行时导入正常，但 strict mypy 报
`opentelemetry.sdk.trace.export` 未显式导出 `SpanProcessor`。

处理：按 1.44.0 的公开类型接口从 `opentelemetry.sdk.trace` 导入 `SpanProcessor`，
`BatchSpanProcessor` 仍从 export 模块导入。

### 3.5 比较实验无法用原 MockTarget 生成四种变化

现象：一个 Dataset 的 per-case `metadata.mock` 对左右 Run 都相同，无法同时制造
improvement/decline/new failure/recovery。

处理：先写 RED 测试，再给 MockTarget 增加有界 `profile`；case 可定义
`metadata.mock_profiles.left/right`。这只服务 deterministic 测试/实验，不进入真实
Target 实现。

效果：同一个 Dataset Version 能通过两个 Run target profile 产生可复现的四类 diff。

## 4. 未执行的真实实验

以下结果不是失败，也不是通过，而是 **NOT-RUN / SKIPPED-no-infra**：

| 实验 | 状态 | 阻塞 |
|---|---|---|
| 500 cases × 1 Worker | NOT-RUN | Docker/Compose 不存在 |
| 500 cases × 2 Workers | NOT-RUN | Docker/Compose 不存在 |
| 500 cases × 4 Workers | NOT-RUN | Docker/Compose 不存在 |
| 500 cases × 8 Workers | NOT-RUN | Docker/Compose 不存在 |
| 20 并发相同 Idempotency-Key（真实 PG） | SKIPPED | 无 migrated PostgreSQL |
| 10 Worker 竞争 100 Jobs | SKIPPED | 无 migrated PostgreSQL |
| 2 Reaper 并发回收 | SKIPPED | 无 migrated PostgreSQL |
| Worker kill + lease recovery | NOT-RUN | Docker/Compose 不存在 |
| Redis 容器中断与恢复 | NOT-RUN | Docker/Compose 不存在 |
| PostgreSQL 容器中断 | NOT-RUN | Docker/Compose 不存在 |
| cancel/result 真实竞态 | NOT-RUN | 无真实 PG/进程环境 |
| comparison 四 case 实验 | NOT-RUN | 无 API/Worker/PG/Redis 运行栈 |
| OTLP 导出到 Collector | NOT-RUN | 未配置 Collector |
| Prometheus 多副本抓取 | NOT-RUN | 未配置 Prometheus |

因此本文件没有吞吐、p50/p95、DB lock wait 或失败率数字。任何数字都会是伪造。

## 5. 在有 Docker 的机器上继续

```bash
docker compose -f deploy/compose.yaml up --build --wait
uv run python -m scripts.create_dev_api_key \
  --tenant-slug phase9 \
  --tenant-name "Phase 9 experiments" \
  --key-name experiment
```

把只显示一次的明文放入当前 shell，不要写入仓库：

```bash
export EVALOPS_EXPERIMENT_API_KEY='...'
```

依次运行，并为重跑指定新输出路径：

```bash
uv run python -m scripts.run_concurrency_test
uv run python -m scripts.run_load_test
uv run python -m scripts.run_comparison_experiment
uv run python -m scripts.run_failure_scenarios --allow-service-disruption
```

真实集成合同：

```bash
EVALOPS_RUN_INTEGRATION=1 uv run pytest -m integration
```

执行前确认这是独占开发环境。failure 脚本会 stop/kill Compose 服务。
