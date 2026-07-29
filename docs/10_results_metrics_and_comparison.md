# 结果查询、指标、Artifact 与 Run 比较合同

## Case 查询

接口：

```text
GET /api/v1/runs/{run_id}/cases
```

支持：

- `limit`：1–200；
- `cursor`：opaque keyset cursor；
- `status`；
- `error_code`；
- `sort=case_id|latency|metric`；
- `metric_name`：只在 `sort=metric` 时允许；
- `direction=asc|desc`。

查询先用 `evaluation_runs.tenant_id + evaluation_jobs.run_id` 形成 tenant 边界，再做筛选。
不存在和跨 tenant 均返回统一 404。

cursor 内含版本、排序字段、方向、metric、status、error_code、最后值和 job_id。它是位置描述，
不是权限凭据；真正权限仍来自服务端 Principal 和 SQL tenant 条件。改变筛选/排序合同后复用
cursor 会返回 422。

没有 OFFSET。数值/metric 排序统一 `NULLS LAST`，同值以 job_id 升序稳定打破平局。
JSONB metric 只有 `jsonb_typeof(value)='number'` 才 cast 为 Float；bool、字符串、缺失指标都
按 NULL 处理，不会让一条脏数据炸掉整页。

## 聚合指标

聚合从 PostgreSQL 当前 Job/CaseResult 重算：

- completion rate = terminal jobs / all jobs；
- success rate = succeeded jobs / all jobs；
- failure rate = failed jobs / all jobs；
- cancellation rate = cancelled jobs / all jobs；
- latency 只统计成功且存在 CaseResult 的 case；
- evaluator metric 只统计成功结果里的有限 int/float，明确排除 bool、NaN 和 infinity。

p50/p95 使用线性插值：

```text
index = (n - 1) * probability
```

当 index 落在两个样本之间时按小数部分插值。选择它是为了让小样本行为明确且可测试；不得把
它与 PostgreSQL `percentile_disc` 或其他 nearest-rank 结果混称为同一算法。

`GET /api/v1/runs/{run_id}/metrics` 在同一事务内重算并替换该 Run 的 RunMetric。
`GET /runs/{id}` 返回已持久化的简要 metric value，详细 count/p50/p95 在 metrics API 返回。

## Artifact

接口：

```text
POST /api/v1/runs/{run_id}/artifacts
```

生成三个 deterministic JSON：

- `run_metrics`；
- `failure_cases`；
- `summary_report`。

payload 包含 schema_version 和 run_id。文件先进入现有 SHA-256 内容寻址存储；数据库 Artifact
随后保存 tenant_id、run_id、type、digest、size 和 server-derived storage path。响应不暴露
storage_path。

重复生成相同状态的报告会命中同一 metadata uniqueness；不同 Run 的 payload 含不同 run_id，
不会因为内容统计恰好相同而错误绑定到另一 Run。

文件系统写成功、数据库事务失败时可能留下未引用的内容寻址 blob。它不会被其他 tenant 自动
暴露，但需要未来 artifact GC 扫描“物理 digest - metadata digest”差集。第一版不通过删除
共享 digest 来模拟回滚。

## Run 比较

接口：

```text
GET /api/v1/runs/compare?left_run_id=...&right_run_id=...
```

两个 Run 都必须通过同一个服务端 tenant_id 查询。

返回：

- 左右 completion/success/failure/cancellation rate；
- 左右 mean/p50/p95 latency；
- evaluator metric summary 与总体 mean delta；
- 仅左失败、仅右失败；
- 两侧均有 case 但 metric/latency 变化的 case；
- intersection、left-only、right-only 数量。

所有 delta 方向固定：

```text
right - left
```

若 Dataset Version 不同：

- `warning=dataset_versions_differ`；
- 左右总体统计仍分别展示，不能说它们来自同一总体；
- case-level diff 只对相同 case_id 的交集计算；
- 明确报告两个差集数量。

当前以 case_id 判断交集；若不同版本复用了 case_id 却改变了问题语义，平台无法自动识别。
严谨实验还应结合 dataset hash、case 内容 hash 或业务审核。

## 能证明与不能证明

当前单元/API 测试能证明纯聚合、比较方向、query-bound cursor、tenant SQL、无 OFFSET、
numeric JSONB guard 和路由合同。

真实 PostgreSQL integration 合同覆盖两页 keyset、跨 tenant 404、指标、三类 artifact 和
compare；本机未启用 migrated PostgreSQL，结果为 skipped。因此不能声称真实数据库执行和
并发分页已在本机通过，也没有给出大 Run 的 query plan、索引选择或容量结果。
