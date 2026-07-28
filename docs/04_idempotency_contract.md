# Phase 2：Run 创建与幂等合同

## 1. 要解决的问题

创建一次 Evaluation Run 会同时创建一组 Jobs。客户端可能因为网络超时、代理重试或自身重试而重复发送请求；多个相同请求也可能并发到达。

平台必须保证：

- 相同 tenant、相同 endpoint、相同 Idempotency-Key、相同请求返回同一个 Run；
- 相同 key、不同请求明确冲突；
- 并发请求只创建一个 Run 和一组 Jobs；
- API 响应丢失后重试不会重复初始化 Jobs；
- Redis 不参与最终幂等判定。

这不是 exactly-once。客户端请求可以重复到达，数据库事务负责让持久化结果幂等。

## 2. 公共 HTTP 合同

```http
POST /api/v1/runs
Authorization: Bearer <api-key>
Idempotency-Key: create-rag-v1
Content-Type: application/json
```

`Idempotency-Key`：

- 必填；
- 1–128 字符；
- 只允许字母、数字、点、下划线、冒号和连字符；
- 不应包含 API Key、Token、问题文本或其他秘密。

首次创建和相同请求重放都返回：

```json
{
  "id": "<run-id>",
  "dataset_version_id": "<dataset-version-id>",
  "status": "queued",
  "total_jobs": 2,
  "succeeded_jobs": 0,
  "failed_jobs": 0,
  "cancelled_jobs": 0,
  "created_at": "...",
  "started_at": null,
  "finished_at": null,
  "metrics": {}
}
```

同 key 不同请求返回：

```json
{
  "error": {
    "code": "idempotency_conflict",
    "message": "This idempotency key was used for a different request."
  }
}
```

HTTP 409 不回显已有 request hash 或原请求配置。

## 3. 作用域

当前唯一约束：

```text
(tenant_id, idempotency_key)
```

Phase 2 只有 Run 创建使用幂等 key，因此 endpoint 作用域由 `evaluation_runs` 表隐式确定。未来若其他写接口也使用 Idempotency-Key，不能把它们直接塞入同一唯一键语义；应增加通用 idempotency record 的 endpoint 字段，或为各资源维持独立命名空间。

不同 tenant 可以使用相同 key，互不冲突。

## 4. Canonical request hash

request hash 来自 Pydantic 已验证请求的 JSON 表示：

1. UUID 规范化为标准字符串；
2. 缺省字段被展开；
3. `None` 被保留；
4. object key 递归按字典序输出；
5. 使用紧凑分隔符；
6. 保留 Unicode；
7. 拒绝 NaN/Infinity；
8. 对 UTF-8 bytes 计算 SHA-256。

因此 JSON object 的键顺序不影响 hash；数组顺序仍有语义，不能排序。

## 5. 创建流程

```text
Principal
  |
  +-- canonical request hash
  |
  +-- tenant + idempotency key 快速查询
        |
        +-- 已存在、hash 相同 -> 返回 snapshot
        +-- 已存在、hash 不同 -> 409
        +-- 不存在
              |
              +-- 校验 evaluator Job policy
              +-- tenant-scoped dataset version 查询
              +-- 按 SHA 读取并重新校验 artifact
              +-- 生成不可变 case payload snapshots
              +-- 单事务 INSERT Run + Jobs
                    |
                    +-- 成功 -> 返回新 Run
                    +-- 唯一冲突 -> 回读并再次比较 hash
```

首次快速查询不是并发保护，只是减少重复请求的 artifact I/O。真正的最终保护是 PostgreSQL 唯一约束。

## 6. 单事务边界

`evaluation_runs` 与该 Run 的全部 `evaluation_jobs` 在同一事务中创建：

- 先 flush Run，获得 run_id；
- 每个 case 创建一个 queued Job；
- 全部成功后才 commit；
- 任一 Job insert 失败则整个事务 rollback；
- 不会出现“Run 已存在但只初始化一部分 Jobs”的提交结果。

JSONL 读取、SHA 校验和结构解析发生在事务外，避免磁盘 I/O 延长数据库事务。

## 7. 并发语义

两个请求可能同时完成首次 SELECT，随后都尝试 INSERT：

- PostgreSQL 唯一约束只允许一个 `(tenant_id, idempotency_key)`；
- 失败方只在确认 constraint name 是幂等唯一约束时进入 replay 路径；
- 其他 IntegrityError 原样抛出，不能被误报为幂等成功；
- 失败事务 rollback 后重新查询胜者；
- service 再次比较 request hash；
- 相同则返回同一 run_id，不同则 409。

不能用“先 SELECT 再 INSERT”单独证明幂等，也不能只用 Redis lock。

## 8. 可复现性绑定

Run 保存：

- dataset_version_id；
- dataset_hash；
- target type/config/config hash/version；
- evaluator config/config hash/version；
- source commit；
- created_by API Key ID；
- canonical request hash。

每个 Job 保存该 dataset case 的不可变 JSON payload snapshot。这样 Worker 不需要为每个 Job 重新扫描整份 JSONL；原始 dataset artifact 和 hash 仍保留为审计来源。

## 9. Tenant 边界

- dataset version source 查询通过 Dataset join 强制 tenant；
- Artifact 记录也必须属于同一 tenant；
- Run 查询同时使用 tenant_id 和 run_id；
- 不存在与跨 tenant 都返回相同 404；
- 请求体禁止 `tenant_id`，tenant 只来自 Principal。

## 10. 当前能够证明

- canonical JSON object 键顺序不影响 request hash；
- 相同请求的 service replay 不读取 artifact、不创建 Jobs；
- 不同请求产生领域冲突；
- 插入竞态返回的胜者会被再次比较 hash；
- Run/Jobs 元数据和唯一约束存在；
- PostgreSQL SQL 中存在 tenant 条件；
- Run 与 Jobs 使用同一事务实现；
- 真实 PostgreSQL 并发测试合同存在并被 CI 收集。

## 11. 当前不能证明

- 本机真实 PostgreSQL 并发测试已通过；
- API 响应丢失、代理重试的网络级端到端实验；
- 计费系统幂等；
- Worker 已经领取或执行 Jobs；
- exactly-once execution。

## 12. 未采用方案

- Redis 分布式锁：Redis 不是最终事实来源，锁过期和网络分区会产生错误安全感。
- 只做应用层 SELECT：并发下两个请求都可能看不到记录。
- 把 artifact I/O 放入事务：会放大事务时长与连接占用。
- 每个 Job 执行时扫描 JSONL：实现简单但工作量随 `job_count × case_count` 放大。
- 保存客户端提供的 hash：客户端输入不可信，所有 hash 均由服务端计算。
