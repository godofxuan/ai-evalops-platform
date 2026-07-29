# Phase 7 逐步执行日志

日期：2026-07-29

起始提交：`2b157b5`

实现提交：`437248c`

## 1. 阶段前判断

原始要求包括 cursor 分页、status/error 筛选、metric 排序、聚合指标、artifact 和 Run 比较。
开始前作出以下判断：

- 不用大 OFFSET，优先 keyset；
- cursor 必须绑定筛选/排序合同，但不能承担授权；
- 指标从 PostgreSQL 当前事实重算，不做容易受 retry/cancel 影响的增量加法；
- 不同 Dataset Version 不能悄悄当作同一总体；
- artifact 路径只能由内容寻址存储返回；
- 自动指标和后续人工评审继续分表。

## 2. Tracer 1：指标聚合

RED：

```text
ModuleNotFoundError: No module named 'app.results'
```

GREEN 后明确：

- 全部 Job 是 rate denominator；
- 只有 success result 进入 latency；
- bool 不能因为是 int 子类而进入 evaluator metric；
- 非有限浮点忽略；
- p50/p95 线性插值。

目标结果：1 passed。

## 3. Tracer 2：纯 Run 比较

RED：`app.results.comparison` 不存在。

GREEN 后：

- warning 显式表示 dataset version 不同；
- case diff 只取 case_id 交集；
- 记录左右差集数量；
- only-left/right failure 与 changed metric/latency；
- delta 统一 right-left。

目标累计：2 passed。

## 4. Tracer 3：ORM 与 migration

先测试 RunMetric、Artifact.run_id、FK 和唯一约束，RED 为 RunMetric import 失败。

首次实现后遇到两个问题：

1. 测试把 `set(table.columns)` 当名称集合，实际得到 Column 对象；改用 `.columns.keys()`。
2. offline SQL 生成：

```text
DROP CONSTRAINT ck_artifacts_ck_artifacts_artifact_type
```

根因是 Alembic naming convention 对已有完整名称再次格式化。改成
`op.f("ck_artifacts_artifact_type")` 后，SQL 正确变为：

```text
DROP CONSTRAINT ck_artifacts_artifact_type
```

新增 migration `20260729_0006`：

- Artifact 可选 run_id FK/index；
- artifact type 扩展；
- RunMetric 表和 `(run_id, metric_name)` unique。

## 5. Tracer 4：Case API

先用 fake service 从公开 HTTP 接口验证 Principal、status、error、metric sort、direction 和
cursor page。RED 为 schema module 不存在，GREEN 后接口返回预期 page。

## 6. Tracer 5：Cursor

cursor 用 urlsafe base64 包装版本化 JSON。测试验证 round-trip，以及 metric_name 改变后旧
cursor 被拒绝。

没有对 cursor 做签名，因为它不是 authorization token；即使被修改，也只能进入严格解析和
参数化 SQL，tenant/run 条件不会来自 cursor。

## 7. Tracer 6：PostgreSQL keyset SQL

编译 PostgreSQL dialect SQL，验证：

- tenant_id 和 run_id；
- status/error filter；
- JSONB numeric type guard；
- NULLS LAST；
- limit+1；
- 无 OFFSET。

SQL target test GREEN 后，Ruff/mypy 指出 import 和 SQLAlchemy stub narrowing。处理方式：

- 局部把 InstrumentedAttribute cast 为 ColumnElement；
- 数据库 sort value 运行时确认 int/float；
- 不关闭 strict mypy。

## 8. Tracer 7：Metrics API

RED 为 DistributionRead/MetricsRead 不存在。GREEN 后：

- 当前 Job/CaseResult 重算；
- 同事务 delete/replace RunMetric；
- 返回完整 distribution；
- tenant-scoped absent/cross-tenant 共享 404。

## 9. Tracer 8：Compare API

RED 为 ChangedCaseRead 不存在。GREEN 后接入纯比较逻辑。

同时发现路由顺序风险：`/runs/compare` 若在 `/runs/{run_id}` 后注册，会由 UUID path 先捕获。
把 results router 注册在 runs router 前，保证静态 compare 路由优先。

## 10. Tracer 9：Artifact

RED 为 ArtifactRead 不存在。GREEN 后生成 metrics/failures/summary 三种 deterministic JSON。

实现问题：

- heterogeneous payload dict 被 mypy 推断为 object；
- inline conditional SQL predicate 被推断为 bool/ColumnElement union。

修正：

- 显式 `dict[ArtifactType, dict[str, Any]]`；
- 先构造 predicate 再传给 where；
- 抽取 RunMetric replace helper，两个入口共享。

## 11. Run GET 指标遗漏

审查发现 RunRead 虽有 `metrics` 字段，旧 `_to_run_read` 从未填充。新增 RED 回归测试后：

- RunSnapshot 增加默认 metrics；
- repository 在 tenant-scoped Run 查询后读取 RunMetric；
- Run API 返回已持久化简要 value。

## 12. 验证

| 检查 | 结果 |
|---|---|
| lock | 48 packages，`uv lock --check` 通过 |
| Phase 7 目标测试 | 24 passed |
| 非集成全量 | 201 passed，5 deselected |
| Ruff format/check | 通过 |
| mypy app | 78 source files，无问题 |
| Alembic | 唯一 head `20260729_0006`；offline SQL 通过 |
| 真实 PostgreSQL Phase 7 扩展合同 | 1 skipped；本机未启用 migrated PostgreSQL |

## 13. 达成效果

- tenant-scoped case cursor API；
- status/error filter、latency/metric sort；
- 明确定义的 aggregate metrics 与持久化；
- Run GET 指标摘要；
- 三类 Run-owned artifact；
- 同版本/跨版本 Run 比较和 case diff；
- migration/ORM/SQL/API/纯函数测试合同。

## 14. 尚未解决

- 没有真实数据库 query plan 和大数据容量证据；
- cursor 未签名，但它也不承担权限；如果未来包含敏感或计费状态，应改用 HMAC；
- metric sort 没有表达式索引，任意 metric 大 Run 可能排序昂贵；
- artifact 物理 orphan 需要 GC；
- case_id 相同不等于问题语义一定相同；
- 本机真实 PostgreSQL 测试 skipped，不能写成 passed；
- 不声称生产级、exactly-once 或统计显著性。
