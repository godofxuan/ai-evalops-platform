# P1-7 Artifact 内容去重与所有权分离：证据化实施日志

## 1. 阶段身份与边界

- 阶段：P1-7。
- 开始时间：2026-08-02（Asia/Shanghai）。
- 分支：`codex/gate1-evidence-hardening`。
- 开始 SHA：`ca2a893af24572445a6de4359d24f44c65350ee8`。
- 实现提交：`de1a44b659ea1edc88d97ab7aec0eccb41868240`。
- 工作区开始状态：clean，且本地分支与
  `origin/codex/gate1-evidence-hardening` 同步。
- 本阶段不运行正式 500-case/32-arm Gate 1，不改写历史实验，不把普通 CI 写成正式 Gate
  证据，也不声称系统已经通过生产容量认证。
- 本阶段允许新增 Alembic migration；禁止修改已经发布的 `0001`–`0008` migration。

## 2. 为什么 P1-7 适合现在处理

确认修改指令要求在 P1-1 至 P1-6 之后检查 Artifact 是否把物理内容去重与租户/Run
所有权耦合。检查结果不是风格偏好，而是可由当前约束和运行分支直接推出的实际完整性缺陷：

- `app/persistence/orm_models.py` 的 `Artifact` 同时含有 `tenant_id`、`run_id`、
  `artifact_type`，以及 `sha256`、`byte_size`、`storage_path`；
- 唯一约束是 `(tenant_id, artifact_type, sha256)`，没有 `run_id`；
- `app/results/service.py::_ensure_run_artifact` 和
  `app/reviews/service.py::_ensure_packet_artifact` 在唯一键冲突后读取旧行；如果旧行属于另一个
  Run，就抛出 `artifact metadata conflicts with Run ownership`；
- 因此，同一 tenant 的两个 Run 不能各自拥有指向相同内容的独立引用；物理去重规则错误地
  决定了所有权规则。

这是 P1 数据完整性与授权建模问题，并且需要数据库迁移。它不要求、也不适合通过放宽唯一键
或删除 `run_id` 校验来掩盖；那样只会让一个 reference 同时冒充多个 Run 的所有权。

## 3. 修改前六个问题的答案

### 3.1 一行是否同时表示 blob 和 Run 所有权

是。当前 `artifacts` 行同时保存物理 blob 事实与租户/Run 归属。

### 3.2 SHA-256 唯一约束作用域

`(tenant_id, artifact_type, sha256)`。它既不是全局 blob 唯一，也不能表达“同一内容、两个
不同 Run、两个独立 reference”。

### 3.3 两个 Run 引用相同内容时

- 同 tenant、同 artifact type：第二次 insert 被唯一键吞掉，随后因旧行 `run_id` 不同而
  报错；
- 不同 tenant：创建两条重复的物理元数据行，但两行可指向同一个内容寻址文件。

### 3.4 两个 tenant 拥有相同内容时

数据库创建两条 `artifacts` 行，磁盘只保留一份文件。跨 tenant 物理去重已经存在，但 blob
事实被重复保存，授权与存储仍在同一模型中。

### 3.5 删除一个 Run 时

`artifacts.run_id` 使用 `ON DELETE CASCADE`，因此该 Run 的 metadata 行会删除；应用没有同步
物理文件删除。它当前不会直接删除另一个 Run 使用的文件，但代价是没有 blob reference
count、没有最后引用判断，也没有可靠 orphan 清理。

### 3.6 内容去重与权限是否耦合

是。物理 SHA 去重所使用的唯一约束同时决定 reference 是否能创建；查询则直接用同一行的
`tenant_id`/`run_id` 做授权。两种职责没有独立约束。

## 4. 现有测试，以及为什么没有发现问题

- `tests/unit/persistence/test_orm_models.py` 明确断言旧的一体化列集合和
  `(tenant_id, artifact_type, sha256)` 唯一键，实际是在保护缺陷结构；
- `tests/integration/test_identity_and_datasets.py` 只验证两个 tenant 产生两条 metadata、共享
  一个 `storage_path` 和一个文件；没有同 tenant、两个 owner；
- `tests/integration/test_run_idempotency.py` 只为单个 Run 生成报告；报告 JSON 自带 `run_id`，
  因而两个 Run 的正常报告通常不会自然得到相同 SHA，无法触发根因；
- storage 单元测试只验证硬链接发布、摘要校验与物理复用，不接触数据库 reference；
- 没有 reference 删除 API/服务测试，没有“最后 reference”判断，也没有 DB/file 不一致测试。

## 5. 冻结的最小数据合同

### 5.1 `artifact_blobs`

只保存全局、内容寻址的物理事实：

- `sha256`：主键；
- `byte_size`；
- `storage_path`；
- `created_at`。

### 5.2 `artifact_references`

只保存授权与业务引用：

- `id`：沿用旧 Artifact UUID，使现有 API 的 `artifact_id` 不变；
- `blob_sha256`：引用全局 blob；
- `tenant_id`；
- 可选 `run_id`；
- `artifact_type`；
- `media_type`；
- `created_at`。

`dataset_versions.artifact_id` 保留字段名和 UUID，但 FK 改为 `artifact_references.id`。这样不
改变已发布 Dataset Version 响应，也避免同时在两张表保存互相重复的
`dataset_version_id`/`artifact_id`。对 Dataset Version 而言，反向 FK 已经精确表达其
reference 所有权；再在 reference 中加 `dataset_version_id` 会制造循环插入和双重事实来源。

### 5.3 为什么 `media_type` 放在 reference

确认修改指令给出的结构是“优先设计”，不是要求无条件照抄。当前真实集成合同允许同一 JSONL
字节分别以 `application/x-ndjson` 和 `application/jsonl` 上传，而 SHA-256 相同。
`media_type` 不是由字节摘要唯一决定的物理事实；如果只放在全局 blob，第二个引用要么覆盖第
一个，要么被错误判定为内容冲突。因此把它保留在 reference 是必要的规范化修正，不是扩展
功能。

### 5.4 Reference 唯一性

- Run-owned reference 使用
  `(tenant_id, run_id, artifact_type, blob_sha256)` 唯一，确保同一 Run 的相同产物重试幂等；
- 不同 Run 可以引用同一 blob；
- Dataset Version 自身已有 `(dataset_id, sha256)` 唯一约束，Dataset reference 不再用全
  tenant 的 SHA 唯一键错误合并不同 Dataset 的所有权。

## 6. Migration、backfill 与 rollback 方案

计划新增 `20260802_0009`：

1. 创建 `artifact_blobs` 和 `artifact_references`；
2. 在复制前检查同一 SHA 是否出现互相冲突的 `byte_size` 或 `storage_path`，发现冲突就使
   migration 失败，而不是任意选一行；
3. 按 SHA 折叠旧物理元数据到 blob；
4. 保留旧 Artifact UUID，把每个旧行一对一复制成 reference；
5. 把 `dataset_versions.artifact_id` FK 切到 references；
6. 删除旧 `artifacts` 表；
7. 不读取、不覆盖也不删除任何物理 artifact 文件。

旧唯一键已经保证同一 `(tenant, type, sha)` 没有重复行；跨 tenant/type 的相同 SHA 在 blob
backfill 中合并，reference 不合并。旧库里已经缺失的物理文件不会被 migration 伪装成正常，
后续读取仍必须摘要校验并 fail closed。

Downgrade 只有在数据仍可由旧模型无损表达时才允许：如果升级后已经出现同 tenant/type/sha
但属于不同 Run 的多个 reference，downgrade 必须明确失败并要求先处理这些新语义数据，不能
静默丢弃 owner。可无损时重建旧表、复制相同 UUID 和 blob 元数据、切回 FK，再删除新表。

## 7. 计划按纵向 TDD 增加的行为

每次只做一个 RED→GREEN，不批量写完全部测试再实现：

1. ORM metadata 明确分成 blob/reference，Dataset FK 指向 reference；
2. 同 tenant 的两个 Run 可拥有相同 SHA 的两个 reference，但只有一个 blob；
3. 不同 tenant 可拥有相同 SHA 的两个 reference，但只有一个 blob；
4. 同 owner/相同 SHA 的并发写幂等，不产生重复 blob/reference；
5. tenant-scoped 读取只能通过 reference，跨 tenant 与不存在返回相同结果；
6. 删除一个 reference 不影响另一个 reference 和物理文件；
7. 删除最后一个 reference 后清理 blob metadata 与物理文件；
8. DB reference 指向缺失文件时读取 fail closed；
9. 文件写入成功但 DB reference 事务失败时，不伪造 reference，并由安全的 orphan 路径处理。

## 8. 兼容性和 Gate 证据判断

- 需要 migration；不改历史 migration。
- API 的 `artifact_id`、Run artifact 响应字段和 Dataset Version schema 不升级。
- 已有 UUID、tenant、run、artifact type、created_at 全量保留；SHA/大小/路径转入 blob。
- Gate 1 prepared bundle 与正式 evidence 目录不是应用 `artifact_root` 数据库模型，不因本迁移
  失效；本阶段也不会覆盖任何历史 bundle。
- 普通 CI 的 migration/integration 只能证明新 schema 与已列测试合同，不等于正式 Gate 1。
- 本地 content store 仍不是多主机对象存储；并发删除与未来多 API 实例需要单独的分布式
  协调/对象存储生命周期合同，不能在本阶段夸大为已解决。

## 9. 实施流水

后续每个 RED、GREEN、遇到的失败、根因、修改和验证证据继续追加在本节，不覆盖前述审计。

### 9.1 Tracer 1：ORM 职责分离

先把 `tests/unit/persistence/test_orm_models.py` 改成只接受
`ArtifactBlob`/`ArtifactReference` 两张表，并要求 `DatasetVersion.artifact_id` 指向
reference。

第一次运行：测试收集 RED，`ImportError: cannot import name 'ArtifactBlob'`。这证明新测试确实
拒绝旧的一体化模型，不是先实现后补一个必过断言。

最小 GREEN：

- 新增 `ArtifactBlob`，只含 SHA、大小、物理相对路径和创建时间；
- 新增 `ArtifactReference`，只含引用 UUID、blob FK、tenant/Run/type/media type 和创建时间；
- Run-owned 幂等键改为 `(tenant_id, run_id, artifact_type, blob_sha256)`；
- Dataset Version FK 改指 reference；
- 将非原生 `artifact_type` 的 ORM 长度显式固定为 32，和已发布 `0008` 的安全宽度一致；
- 暂时保留源码级 `Artifact = ArtifactReference` alias，避免在同一个 tracer 中同时改全部调用
  点；该 alias 不会重新创建 `artifacts` 表。

第一次 GREEN 运行仍有 1 个失败：旧的 Dataset constraint 测试还单独写死
`artifacts.id`。这不是产品实现失败，而是同一测试文件中遗漏更新的一条旧合同；把它改成
`artifact_references.id` 后再次运行：`9 passed`。

Pytest 仍报告仓库 `.pytest_cache` 无写权限的既有环境 warning；测试主体实际执行并通过，
本阶段没有放宽权限或改变 pytest 合同来隐藏 warning。

### 9.2 Tracer 2：新增 migration，而不是改历史 migration

新增离线 SQL 测试，第一次 RED 明确显示 Alembic head 仍是 `20260729_0008`，输出中不存在
`CREATE TABLE artifact_blobs`。随后新增 `20260802_0009_artifact_blobs_references.py`：

- upgrade 创建 blobs/references；
- backfill 前检查同 SHA 的大小/路径冲突和 artifact type/Run owner scope 冲突；
- blob 按 SHA 聚合，reference 保留每个旧 UUID；
- Dataset Version FK 在复制完成后切换；
- 最后才删除旧表，整个 PostgreSQL DDL/DML 处于 Alembic transaction；
- downgrade 在旧唯一键无法表示多个 owner 时主动抛错。

离线 upgrade 测试从 RED 变为 GREEN；新增 downgrade SQL 合同后，两项均通过。又直接运行
Alembic 离线命令检查生成 SQL，确认 constraint 名、FK 切换、backfill、旧表删除以及受保护
downgrade 都实际出现，而不是只检查 Python 文件字符串。

### 9.3 Tracer 3：Dataset 读取先授权 reference，再读取 blob

ORM 拆分后，原有 Run repository 测试真实暴露 `Artifact.sha256` 已不存在的 RED。将测试合同改为
必须同时出现 `JOIN artifact_references`、`JOIN artifact_blobs` 和 reference tenant 条件；实现只
修改 Dataset Version source 查询，最终 `2 passed`。

### 9.4 Tracer 4：统一注册 blob 与 reference

新增 `app/artifacts/repository.py`，把三个调用点原本各自实现的 upsert 集中为：

1. 全局 blob 以 SHA `ON CONFLICT DO NOTHING`；
2. 回读并比较 byte size/storage path，冲突失败关闭；
3. Dataset 每个 Version 创建独立 reference；
4. Run-owned reference 用 owner/type/blob 唯一键并发幂等；
5. 相同 owner 的已有 reference 还要校验 media type。

Dataset、Result report 和 Human Review packet 都改用同一注册函数。Result API 响应仍返回原字段，
SHA/大小来自刚刚经过 store 校验的 `StoredArtifact`，reference ID 和 created_at 来自数据库。
这一阶段没有更改 HTTP schema。

### 9.5 Tracer 5：reference-scoped 读取与删除

新增 reference query RED，最初因 `app.artifacts.repository` 不存在而在收集阶段失败；最小 GREEN
只提供 tenant/reference/Run 过滤后 join blob 的 statement。

随后按一个行为一个循环加入：

- 物理删除：RED 为 `LocalArtifactStore` 没有 `delete_bytes`，GREEN 后 storage `8 passed`；
- 删除共享 reference：RED 为 access service 没有 `delete_reference`，GREEN 只删除 DB
  reference，不碰物理文件；
- 删除最后 reference：RED 为预期 SHA 未传给 store，GREEN 才加入物理清理；
- 已知 orphan：RED 为没有 `collect_orphan_blob`，GREEN 要求数据库先 claim“无 reference”，再
  删除经过 SHA 校验的文件。

Access service 单元合同最终 `5 passed`。按 SHA 的 orphan 方法是内部维护能力，没有增加客户端
可调用的“按 SHA 绕过所有权”路由。

### 9.6 Tracer 6：真实 PostgreSQL 生命周期合同

新增 `tests/integration/test_artifact_references.py` 并作为独立 GitHub CI step。它在同一个真实
PostgreSQL 合同中覆盖：

- 同 tenant 两个 Run 注册相同 content；
- 不同 tenant 注册相同 content；
- 相同 owner 的并发重试；
- 三个 owner 只有一个 blob、三个 references；
- 跨 tenant、错误 Run、以及省略 Run 的读取失败且不触碰 blob；
- 逐个删除 reference，前两个不删共享文件，最后一个清理；
- DB reference 存在但物理文件缺失时摘要读取失败关闭；
- 文件已写、reference 事务回滚后，数据库没有伪造 reference，并可由已知 orphan 维护路径清理。

本机没有启用真实 PostgreSQL，测试结果是明确的 `1 skipped`。它已经接入 CI，只有远端真实
migration/数据库运行成功后才能记为 passed。

### 9.7 适配既有真实服务测试

原 concurrency/human review/dataset/run integration fixture 都直接创建旧 `Artifact` 行。将它们
改为显式创建 blob/reference，并把 teardown 改成：

1. 先清除引用者（Run/Dataset Version）；
2. 删除测试 tenant references；
3. 只在 `NOT EXISTS(reference)` 时删除测试 blobs。

这样 teardown 也不会因为相同 SHA 而误删另一个 owner 仍使用的 metadata。

### 9.8 提交前审阅发现并修复 Run scope 绕过

第一次实现把 `run_id` 设为可选以同时支持 Dataset reference，但查询在 `run_id=None` 时没有
增加 Run 条件。同 tenant 调用者如果知道 Run artifact reference UUID，就可能通过省略 Run
绕过 owner scope。

新增 SQL RED，确认生成语句没有 `artifact_references.run_id IS NULL`。修复后：

- 传 Run 必须精确匹配；
- 不传 Run 只允许 `run_id IS NULL` 的 Dataset reference；
- delete 使用同一个 scope 规则；
- 数据库增加 owner-scope CHECK：`dataset_source` 必须没有 Run，其余当前 artifact type 必须有
  Run；
- 注册函数在任何 SQL/I/O 前做同样校验；
- migration backfill 遇到旧数据违反该形状时失败，不悄悄迁移成可绕过的 reference。

这轮 RED→GREEN 后 repository/service 定向合同 `7 passed`，ORM/migration/repository 合同
`13 passed`。

### 9.9 第一次全量验证与命令问题

第一次全量非 integration 命令设置了 180 秒外层上限。它在约 79% 时被外层以 exit 124
终止，已输出部分没有失败，但不能算完整通过。没有缩小测试范围，而是用同一命令和足够上限
重跑：当时结果为 `421 passed, 7 deselected`，耗时约 183 秒。

随后提交前审阅又加入 Run scope 和 owner-scope 回归，因此该 421 数字只是中间证据，最终数字
必须在最新代码上重新生成后再填写。中间静态结果为：Ruff format 237 files、Ruff lint passed、
mypy 115 source files、uv lock 70 packages、`git diff --check` passed；最终提交前也必须重跑。

### 9.10 最新代码的最终本地验证

在 Run scope、owner-scope CHECK、文档和安全 teardown 全部完成后，从头重跑：

| 验证 | 结果 |
|---|---|
| P1-7 相关定向单元/API 回归 | `61 passed` |
| 最新完整非 integration | `424 passed, 7 deselected` |
| 新 PostgreSQL integration 本机收集 | `1 skipped`，原因是未设置真实服务合同 |
| Ruff format | `237 files already formatted` |
| Ruff lint | `All checks passed` |
| mypy | `115 source files`，无问题 |
| uv lock | `70 packages`，lock check 通过 |
| Alembic offline upgrade/downgrade | `2 passed`，实际 SQL 另行筛查通过 |
| `git diff --check` | 通过 |

`.pytest_cache` 无写权限 warning 仍存在；它没有改变测试退出码，也没有通过修改权限或 pytest
配置规避。真实 PostgreSQL concurrency/migration 仍必须等待 GitHub CI，当前不能写成 passed。

### 9.11 本地实现提交

在确认 staged diff 只包含 P1-7 的 migration、生产调用点、测试、CI step 与当前合同文档后，
执行 `git diff --cached --check` 通过，并创建：

```text
de1a44b fix(artifacts): separate blobs from tenant references
```

详细实施日志没有混入实现提交，留在后续独立 docs commit；这样代码回滚和审计记录可以分别
审阅。当前尚未 push，GitHub PostgreSQL/Compose 结果仍未知。
