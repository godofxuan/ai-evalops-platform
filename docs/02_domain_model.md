# Phase 1 领域模型与设计合同

## 1. 阶段问题

Phase 0 只能证明应用进程、依赖探测和工程工具可工作，还不能安全地区分调用者，也不能保存可复现的数据集版本。

Phase 1 只解决以下问题：

1. API Key 如何只显示一次，并且不以明文存入数据库；
2. tenant 如何由服务端身份派生，而不是由请求体决定；
3. 所有 dataset/version 查询如何强制携带 tenant 边界；
4. JSONL 如何在大小、行数、格式和 case ID 唯一性约束下被验证；
5. 原始数据如何以内容寻址、不可由用户指定路径的方式保存；
6. dataset version 如何不可变、可复现，并绑定 SHA-256 和 artifact。

本阶段不创建 Run、Job、幂等、Worker、lease、retry 或 SSE。

## 2. 公开 HTTP 合同

### 2.1 认证

```http
Authorization: Bearer evk_<12-hex-prefix>_<high-entropy-secret>
```

以下情况统一返回 HTTP 401 和相同错误码 `invalid_api_key`：

- header 缺失或 scheme 不是 Bearer；
- key 格式错误；
- prefix 不存在；
- hash 不匹配；
- key 已撤销或已过期；
- tenant 不是 active。

成功后服务端生成：

```text
Principal(
  tenant_id,
  api_key_id,
  key_prefix
)
```

请求体不得接受 `tenant_id`。

### 2.2 Dataset

```http
POST /api/v1/datasets
Content-Type: application/json
Authorization: Bearer <api-key>

{
  "name": "rag-regression",
  "description": "Regression cases"
}
```

返回 HTTP 201 和 dataset 元信息。

```http
POST /api/v1/datasets/{dataset_id}/versions
Content-Type: multipart/form-data
Authorization: Bearer <api-key>

file=<JSONL>
```

返回 HTTP 201 和不可变 version 元信息。

```http
GET /api/v1/datasets/{dataset_id}
GET /api/v1/datasets/{dataset_id}/versions/{version_id}
```

资源不存在和跨 tenant 访问都返回同一个 HTTP 404。

## 3. API Key 设计

### 3.1 格式与存储

完整 key：

```text
evk_<12 hexadecimal characters>_<urlsafe random secret>
```

数据库保存：

- `key_prefix`：用于定位候选记录和审计；
- `key_hash`：包含算法版本、scrypt 参数、随机 salt 和派生值；
- status、expires_at、last_used_at；
- 不保存完整 key。

哈希参数第一版固定为：

```text
scrypt n=16384, r=8, p=1, dklen=32, salt=16 bytes
```

验证使用 `hmac.compare_digest`。未知 prefix 仍执行一次 dummy scrypt，避免明显的“查不到立即返回”时序差。

### 3.2 替代方案

- 裸 SHA-256：未采用。计算过快，数据库泄露后缺乏 salt 和计算成本保护。
- HMAC-SHA-256 + server pepper：对高熵 API Key 是合理方案，验证更快；但引入 pepper 轮换和秘密管理合同。本阶段选择随机 salt 的 scrypt，减少额外部署秘密。
- Argon2id：合理且常用于凭证哈希；未采用是为了避免只为这一能力增加依赖。未来可用版本化编码平滑迁移。

风险：scrypt 会消耗 CPU/内存，攻击者可用无效 key 制造认证负载。API 层后续还需要限流和容量实验，当前不能声称抗 DoS。

## 4. Tenant 边界

- tenant ID 只从数据库中的 API Key 关联取得。
- Dataset create 使用 principal 的 tenant ID。
- Dataset/version read 和 upload 都以 `(tenant_id, resource_id)` 查询。
- 跨 tenant 返回 404。
- 第一版依赖应用层查询边界；PostgreSQL Row-Level Security 尚未启用。

应用层边界易于理解和测试，但风险是未来新增查询时遗漏 tenant 条件。集成测试和 repository/service 约束是第一道防线，RLS 可作为后续 defense-in-depth。

## 5. Dataset Version

每个 version 保存：

- dataset ID；
- 单调递增整数 version；
- schema version；
- 原始内容 SHA-256；
- case count；
- artifact ID；
- created_at。

唯一约束：

```text
(dataset_id, version)
(dataset_id, sha256)
```

上传时以 tenant 条件锁定 dataset 行，在短事务中重新检查 SHA 并分配下一个 version。已创建 version 没有 update/delete API。

## 6. JSONL 合同

每行至少包含：

```json
{
  "case_id": "case-001",
  "question": "...",
  "expected_answer": "...",
  "metadata": {}
}
```

第一版默认限制：

- 文件最大 10 MiB；
- 最多 10,000 行；
- 单行最大 1 MiB；
- UTF-8；
- 不允许空行；
- `case_id` 非空且文件内唯一；
- `question` 非空；
- `expected_answer` 必须存在；
- `metadata` 必须是 JSON object；
- 允许额外字段，因为原始需求使用“至少包含”。

第一版在读取 `max_bytes + 1` 后把有界内容保存在内存中，再验证和写 artifact。优点是事务外验证简单、失败无数据库副作用；限制是不能处理超大文件。未来需要流式 parser，但不能通过提高默认上限伪装成已解决。

## 7. Artifact

storage path 只能由 SHA-256 生成：

```text
<first-two-hex>/<full-sha256>
```

写入流程：

1. 在 artifact root 的临时目录创建文件；
2. 写入完整内容；
3. flush；
4. fsync；
5. 计算/确认 SHA-256；
6. 创建前两位目录；
7. 原子发布到最终路径；
8. finally 清理临时文件；
9. 数据库保存相对 storage path。

相同内容复用同一物理文件。数据库事务失败后可能留下无引用、但内容完整且地址正确的文件；后续需要 artifact GC。删除一个数据库记录时不能贸然删除共享内容文件。

物理文件与数据库所有权分开：

- 物理文件可因相同 SHA-256 被多个 tenant 复用；
- 每条 artifact 数据库记录必须带 `tenant_id`、`artifact_type`、`media_type`、`byte_size`；
- Phase 1 的类型为 `dataset_source`；
- `(tenant_id, artifact_type, sha256)` 唯一；
- `storage_path` 不做全局唯一约束，因为不同 tenant 的元数据记录可以安全指向同一内容寻址文件；
- `run_id` 等 Run 关联字段在 Phase 2/后续 Run 表存在时再通过迁移加入，不在 Phase 1 预埋无外键半成品列。

## 8. 当前能证明与不能证明

能证明：

- API Key 明文不进入 Phase 1 ORM 字段；
- 已知 key hash 使用随机 salt、scrypt 和常量时间 digest 比较；
- HTTP 请求体不能决定 tenant；
- 测试覆盖的 dataset 查询具有 tenant 边界；
- JSONL 与 artifact 合同在本地单元测试成立。

不能证明：

- 所有未来查询都不会遗漏 tenant；
- API Key 方案已通过安全审计或抗 DoS；
- 本机 PostgreSQL 并发/锁语义已经验证；
- artifact 存储适合多主机部署；
- dataset version 的存在等于评测结果可复现；Run 绑定属于 Phase 2。
