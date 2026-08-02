# P2-1 跨表租户一致性约束：证据化实施日志

## 1. 阶段身份与边界

- 阶段：P2-1，跨表 tenant 一致性约束。
- 开始日期：2026-08-02（Asia/Shanghai）。
- 分支：`codex/gate1-evidence-hardening`。
- 起始 SHA：`397c5ccffa8bc1521e71b421785067f7aeac6d4d`。
- 起始状态：工作区 clean，本地与
  `origin/codex/gate1-evidence-hardening` 的 ahead/behind 为 `0/0`。
- 前置阶段：P1-7 已由本地回归和 GitHub Actions run
  `30728552043` 验证成功。
- 本阶段不运行正式 500-case/32-arm Gate 1，不把普通 CI 写成正式 Gate
  证据，不创建 PR，也不合并分支。

## 2. 指令是否适合现在执行

确认修改指令把“跨表 tenant 一致性约束”列为 P2 的第一项。该项适合现在执行，
原因不是为了统一代码风格，而是当前数据库确实允许应用正常路径不会主动产生、但手工
SQL、迁移脚本、未来漏写过滤条件或错误服务实现仍可能产生的所有权矛盾：

1. `dataset_versions` 同时引用 tenant-owned `datasets` 和
   `artifact_references`，自身却没有可用于复合外键的 `tenant_id`；两端可以来自不同租户。
2. `evaluation_runs.tenant_id` 可以与其 Dataset Version 的派生租户、或
   `created_by` API Key 的租户不一致。
3. Run-owned `artifact_references` 可以把 tenant A 写在 reference 上，同时引用 tenant B
   的 Run。
4. 人工复核 task、submission、adjudication 都冗余保存 `tenant_id` 和父 ID，普通单列
   FK 只证明两端分别存在，不证明它们来自同一租户。
5. `case_results` 和 `human_review_tasks` 同时保存 `job_id` 与 `run_id`，数据库不证明该
   Job 确实属于该 Run。它虽然不是新增 tenant 列的问题，但直接决定父链是否能可靠传递
   tenant 归属，因此属于同一个完整性边界。

应用服务目前大多从已认证 principal 派生 tenant，并使用 tenant-scoped 查询，所以这是
数据库纵深防御缺口，不是已观察到的 HTTP 越权证据。不能因此声称现有 API 已被利用，
也不能因为正常路径安全就继续让数据库接受矛盾数据。

## 3. 不采用的机械方案

### 3.1 不给所有子表复制 `tenant_id`

`evaluation_jobs`、`job_attempts`、`run_metrics` 等表只有一条不可歧义的父链。给它们复制
tenant 会新增写入负担和新的不一致面，却没有消除现有冗余字段矛盾。本阶段只处理已经
存在多份所有权/父链事实的表。

### 3.2 不约束多态审计字符串

`audit_events.resource_type/resource_id` 是有意设计的多态审计引用，`actor_id` 也允许表示
非 API Key actor。普通 FK 无法在不重构审计模型的情况下可靠表达它们。本阶段继续依靠
`audit_events.tenant_id -> tenants.id`，不伪造一个只覆盖部分事件的约束。

### 3.3 暂不把 `case_id` 纳入复合外键

`case_results` 和 `human_review_tasks` 还复制了 `case_id`。校验 case 是否相同属于更广的
结果谱系合同，而本项明确要求 tenant 一致性。当前最小改动用 `(job_id, run_id)` 保证
Job/Run 所有权链，不同时扩大到 case 内容语义；该剩余项会明确记录，而不是暗示已解决。

## 4. 冻结的最小数据合同

父表增加为复合 FK 提供依据的候选唯一键：

- `api_keys(id, tenant_id)`；
- `datasets(id, tenant_id)`；
- `artifact_references(id, tenant_id)`；
- `dataset_versions(id, tenant_id)`；
- `evaluation_runs(id, tenant_id)`；
- `evaluation_jobs(id, run_id)`；
- `human_review_tasks(id, tenant_id)`。

`dataset_versions` 新增非空 `tenant_id`，其值由 `datasets.tenant_id` 派生。需要数据库证明
的复合关系是：

- Dataset Version 的 `(dataset_id, tenant_id)` 指向同一 Dataset；
- Dataset Version 的 `(artifact_id, tenant_id)` 指向同租户 Artifact Reference；
- Run 的 `(dataset_version_id, tenant_id)` 指向同租户 Dataset Version；
- Run 的 `(created_by, tenant_id)` 指向同租户 API Key；
- Run-owned Artifact Reference 的 `(run_id, tenant_id)` 指向同租户 Run；其中
  `run_id IS NULL` 的 Dataset source 继续由现有 owner-scope CHECK 处理；
- Case Result 的 `(job_id, run_id)` 指向同一 Evaluation Job；
- Human Review Task 的 Run、Job、creator 分别与 task 的 tenant/Run 链一致；
- Submission/Adjudication 的 task 和 reviewer/adjudicator 都与该行 tenant 一致。

现有直接 `tenant_id -> tenants.id` 外键保留，用于明确根所有权和原有级联删除语义。
被复合关系完整替代的单列父 FK 会移除，避免两套重复父约束。

## 5. 迁移、历史数据与回滚判断

计划新增 `20260802_0010_cross_table_tenant_consistency.py`，不修改已发布的历史 migration。
升级步骤：

1. 给 `dataset_versions` 添加暂时可空的 `tenant_id`。
2. 在变更约束前逐类检查 Dataset/Artifact、Run/Dataset、Run/creator、Artifact/Run、
   Result/Job/Run 及人工复核链。如果发现矛盾就抛出带类别的异常，停止整个事务；不能
   在没有业务证据时任意选择一方作为“正确租户”。
3. 从 Dataset 回填 Dataset Version tenant，然后设为 `NOT NULL`。
4. 添加父候选唯一键，替换相应单列 FK 为复合 FK。
5. 保留现有业务 UUID、时间、状态与内容，不读写 artifact 文件。

降级会先恢复旧单列 FK，再移除复合 FK、候选唯一键和 Dataset Version 的冗余 tenant
列。该列始终可由 Dataset 派生，约束加固也没有创造旧结构无法表示的新业务实体，因此
降级不会删除业务行。不过，降级会重新允许未来写入不一致数据，这是回到旧版本合同的
必然后果。

## 6. TDD tracer 计划

每个 tracer 都先运行一个能说明缺失合同的 RED，再做最小 GREEN：

1. Dataset/Artifact/Run 数据来源租户链；
2. API Key 与 Run/人工复核 actor 租户链；
3. Case Result 和 Human Review Task 的 Job/Run 父链；
4. 生产写入点与现有测试 fixture 补齐 Dataset Version tenant；
5. Alembic 离线 upgrade/downgrade 合同；
6. 真实 PostgreSQL 拒绝跨租户和跨 Run 插入；
7. 定向回归、全量非集成回归、静态检查、真实 CI 和 Compose。

## 7. 实施流水

后续每次 RED/GREEN、遇到的问题、根因、采取的修改和验证结果都追加在本节，不覆盖前述
审计判断。

### 7.1 Tracer 1 RED：Dataset/Artifact/Run 来源链

先在 ORM metadata 测试中要求：

- `dataset_versions.tenant_id` 存在且非空；
- Dataset、Artifact Reference、Dataset Version、Run 都有 `(id, tenant_id)` 候选唯一键；
- Dataset Version 的 Dataset/Artifact 两端、Run 的 Dataset Version、Artifact Reference 的
  可选 Run 都使用包含 tenant 的复合 FK。

第一次定向运行结果：`1 failed`。失败点是
`"tenant_id" in DatasetVersion.__table__.columns`，当前列集没有该列。这个失败准确指向
跨表归属无法被复合 FK 表达的根缺口。pytest 同时报告既有 `.pytest_cache` 无写权限
warning，但测试已正常收集、执行并因业务断言失败，warning 不是 RED 原因。

### 7.2 Tracer 1 最小 GREEN 实现

本轮只修改来源链 ORM：

- 给 Dataset、Artifact Reference、Dataset Version、Run 增加明确命名的
  `(id, tenant_id)` 候选唯一键；
- 给 Dataset Version 增加非空 tenant 列；
- 用 Dataset/Artifact + tenant 复合 FK 替换 Dataset Version 原单列 FK；
- 用 Dataset Version + tenant 复合 FK 替换 Run 原单列 Dataset Version FK；
- 用 Run + tenant 复合 FK 替换 Artifact Reference 原单列 Run FK；
- Dataset source 的 `run_id=NULL` 继续采用 PostgreSQL 默认 `MATCH SIMPLE`，因此不会错误
  要求 Dataset artifact 必须属于 Run，现有 owner-scope CHECK 仍负责区分两类 owner。

没有在此 tracer 顺手修改 API Key、人工复核或 Job/Run 关系，以保持一次只验证一个所有权
切片。

第二次运行同一定向测试：`1 passed`。这证明新增列、候选唯一键和四条来源链复合 FK 已
进入 SQLAlchemy metadata。`.pytest_cache` warning 仍在，但不影响退出码。该 GREEN
尚未覆盖数据库 migration 和生产构造器，因此不能写成 P2-1 已完成。

### 7.3 Tracer 2 RED：API Key actor 与记录 tenant

下一条测试要求 API Key 和 Human Review Task 提供 `(id, tenant_id)` 候选唯一键，并
要求 Run creator、Task creator、Task Run、Submission reviewer、Adjudication
adjudicator 及其各自 Task 都通过复合 FK 与行内 tenant 绑定。先写测试、运行并记录失败，
再修改这些模型。

第一次运行结果：`1 failed`。首个失败断言是 API Key metadata 不包含
`(id, tenant_id)` 唯一键，当前仅有 `key_prefix` 唯一键。主键 `id` 在逻辑上当然也能
推出组合唯一，但 PostgreSQL 的复合 FK 需要被引用列组有明确的唯一/主键约束，不能把
两个独立事实假定为一条可引用候选键。因此新增冗余候选唯一键是数据库表达同租户 actor
关系的必要成本。

### 7.4 Tracer 2 最小 GREEN 实现

- API Key 和 Human Review Task 新增 `(id, tenant_id)` 候选唯一键；
- Run 的 `(created_by, tenant_id)` 改为引用同租户 API Key；
- Human Review Task 的 `(run_id, tenant_id)` 与 `(created_by, tenant_id)` 分别引用
  同租户 Run 和 API Key；
- Submission 的 task/reviewer 与 Adjudication 的 task/adjudicator 都改为包含 tenant 的
  复合 FK；
- 现有每张人工复核表的直接 `tenant_id -> tenants.id` FK 保留；
- Task 的 `job_id` 暂时仍是单列 FK，等待下一 tracer 用独立 RED 证明 Job/Run 缺口。

第二次运行 actor 定向测试：`1 passed`。它证明 SQLAlchemy metadata 已能表达所有列出的
actor/task tenant 复合关系；仍未验证 migration 和真实 PostgreSQL。

### 7.5 Tracer 3 RED：Job/Run 父链

新增 metadata 测试要求 Evaluation Job 提供 `(id, run_id)` 候选唯一键，并要求 Case
Result 与 Human Review Task 的 `(job_id, run_id)` 指向同一 Evaluation Job。这样 task
tenant 先由 task→Run 复合 FK 确认，再由 task→Job/Run 复合 FK 把 Job 纳入同一条归属链。

第一次运行结果：`1 failed`。Evaluation Job 当前只有 `(run_id, case_id)` 业务唯一键，没有
可供 `(job_id, run_id)` FK 引用的候选唯一键。虽然 `id` 主键在逻辑上让组合必然唯一，
仍需显式的复合唯一约束供 PostgreSQL 引用。

### 7.6 Tracer 3 最小 GREEN 实现

- Evaluation Job 新增 `(id, run_id)` 候选唯一键；
- Case Result 移除分别指向 Job 和 Run 的两条单列 FK，改为一条
  `(job_id, run_id) -> evaluation_jobs(id, run_id)` 复合 FK；Job 已通过自己的 `run_id`
  指向 Run，因此不再保留一条只能证明 Run 单独存在的冗余 FK；
- Human Review Task 的单列 Job FK 改为同样的 Job/Run 复合 FK；Task→Run+tenant 复合 FK
  仍负责 tenant 一致性；
- 两条新 FK 都保留 `ON DELETE CASCADE`，删除 Job/Run 时仍会清理依赖记录。

定向运行 Tracer 3：`1 passed`。

### 7.7 ORM 合同文件回归与旧断言修正

运行整个 `test_orm_models.py` 得到 `4 failed, 8 passed`。四项失败都来自旧合同：

1. Artifact Reference、Run 和三张人工复核表的旧断言要求 `tenant_id` 的 FK target 集合
   **只能**包含 `tenants.id`；复合 FK 正确地让同一列还指向父记录的 `tenant_id`。
2. Case Result 的旧断言要求 `run_id -> evaluation_runs.id`；新合同已用
   `(job_id, run_id) -> evaluation_jobs(id, run_id)` 取代这条无法验证 Job/Run 相互归属的
   单列 FK。

修正方式不是删除校验：根租户断言改为明确要求 target 集合中仍包含 `tenants.id`，完整
复合关系由新增的 `foreign_key_specs` 断言精确校验；Case Result 则明确要求 `run_id`
对应 `evaluation_jobs.run_id`。这样同时保护根 tenant FK 和新父链，而不会把“额外 FK”
误报为失败。

修正后 ORM 合同文件：`12 passed`。

### 7.8 Tracer 4 RED：Dataset Version 生产读写使用 tenant

仅让数据库列存在还不够。读取单个 Dataset Version 的 statement 原本只通过 Dataset join
过滤 tenant。复合 FK 生效后这条 join 已足以推出相同 tenant，但直接过滤新增列可以让
查询本身显式表达服务端边界，并防止 migration 前/约束临时失效环境中的意外扩大。
因此先给现有 SQL 编译测试增加 `dataset_versions.tenant_id = principal.tenant_id` 断言。

第一次运行结果：`1 failed`。编译后的 SELECT 列表因为 ORM 新列已包含
`dataset_versions.tenant_id`，但 WHERE 只有 `datasets.tenant_id`；失败证明断言检查的是
过滤语义，不是字符串偶然出现。

### 7.9 Tracer 4 最小 GREEN 实现

- `build_get_dataset_version_statement` 同时过滤 Dataset Version 和 Dataset 的 tenant；
- 创建版本时从已认证 `principal.tenant_id` 写入新列；
- duplicate-SHA 与 next-version 查询也加入同一 tenant 条件，使同一方法内所有版本访问
  都显式使用相同边界；
- concurrency job claiming、artifact reference、human review 三个真实 PostgreSQL fixture
  的直接 DatasetVersion 构造补齐 tenant；
- `DatasetVersionRead` 不暴露该内部冗余列，因此 HTTP 响应契约不变。

定向读取测试转为 `1 passed`。随后用全仓搜索确认仅有的 4 个 DatasetVersion 构造点
（1 个生产服务、3 个 PostgreSQL/concurrency fixture）都已传入 tenant，没有遗漏的
直接构造器。

### 7.10 Tracer 5 RED：Alembic upgrade 合同

新增离线 SQL 测试，要求 Alembic head 包含：

- Dataset Version tenant nullable-add、回填与 `NOT NULL`；
- 可识别类别的历史数据一致性 guard；
- 关键父候选唯一键；
- Artifact、Dataset/Version/Run、actor、Result/Job/Run 及人工复核链的复合 FK。

使用离线 SQL 是为了让本地没有 PostgreSQL 时仍能验证 migration 结构；真实执行行为会在
后续 integration/CI 验证，二者不能互相替代。

第一次运行结果：`1 failed`。Alembic 离线输出最终只更新到 `20260802_0009`，完全没有
`ALTER TABLE dataset_versions ADD COLUMN tenant_id UUID`，证明测试确实拒绝旧 head。

### 7.11 Tracer 5 upgrade 最小实现

新增 `20260802_0010_cross_table_tenant_consistency.py`，upgrade 顺序为：先添加可空列，
再用一个事务内 PostgreSQL `DO` block 分类别检查全部已冻结关系，随后回填并设为非空，
最后创建父候选唯一键并替换 FK。历史数据检查发现矛盾会中止整个 migration，保留原库；
没有依据时不自动选择 Dataset tenant、Run tenant 或 actor tenant 中的任何一方。

本轮暂不实现 downgrade，以便下一条 downgrade 测试能够先 RED；这不是准备提交的最终
状态。

第一次运行 upgrade 实现没有 GREEN，而是在 Alembic 编译到 Run→DatasetVersion FK 时
抛出 `IdentifierError`：显式名称长度 64，超过 PostgreSQL identifier 上限 63。这个问题
在离线测试阶段被捕获，说明离线 SQL 验证确实能在进入真实数据库前发现 DDL 兼容错误。

没有只缩短第一个报错名。对 ORM、migration 和测试中的所有新 FK/UQ 名称做长度清单，
发现 3 个超过 63 字符、1 个恰好 63。统一将 5 个较长的人工复核/Run tenant 约束缩短为
`fk_<table>_<role>_tenant` 形式。列组和目标表仍完整出现在 DDL 中，名字只负责稳定识别；
缩短后避免 PostgreSQL 拒绝、自动截断或未来名称碰撞。

修正后 upgrade 离线合同：`1 passed`。

### 7.12 Tracer 5 downgrade RED

新增离线 downgrade 测试，要求 `0010:0009`：

- 恢复 P2-1 前全部单列父 FK 及其原 `ON DELETE` 语义；
- 删除 7 个只为复合 FK 提供引用依据的候选唯一键；
- 最后删除 `dataset_versions.tenant_id`。

顺序很重要：必须先移除引用新候选键/新列的复合 FK，再恢复旧 FK，最后才可删除唯一键
和列，不能让 downgrade 在中途留下无法执行的依赖。

第一次运行结果：`1 failed`。离线输出只有 Alembic version 从 `0010` 回到 `0009`，没有
任何 FK/column DDL，准确证明空 downgrade 不满足可回滚合同。

### 7.13 Tracer 5 downgrade 最小实现

实现严格依赖顺序：

1. 删除 13 条 P2-1 复合 FK；
2. 恢复 14 条旧单列 FK（Case Result 从一条复合 FK 恢复为 Job 和 Run 两条）；
3. 删除 7 个候选唯一键；
4. 最后删除 Dataset Version tenant 列。

恢复时逐条沿用 `0009` 之前的 constraint 名和 `ON DELETE CASCADE/RESTRICT`，使旧应用与
旧 migration metadata 能重新识别数据库结构。

实现后 upgrade/downgrade 离线合同合并运行：`2 passed`。

### 7.14 真实 PostgreSQL 约束测试与 CI 路由

新增 `tests/integration/test_tenant_consistency_constraints.py`。测试先创建 tenant A/B 的
完整合法 Dataset→Version→Run→Job→Review Task 图，再逐笔尝试 13 类非法关联。每次插入
都在独立事务中 flush，并检查 psycopg 返回的**准确 constraint name**，因此不仅要求“某个
错误发生”，还证明预期数据库边界负责拒绝：

- Dataset Version 的 Dataset tenant 与 Artifact tenant 各自错配；
- Run 的 Dataset Version 与 creator tenant 各自错配；
- Run-owned Artifact Reference 指向另一 tenant 的 Run；
- Case Result 的 Job 与 Run 不同源；
- Review Task 的 Run tenant、Job/Run、creator tenant 分别错配；
- Submission 的 Task tenant、reviewer tenant 分别错配；
- Adjudication 的 Task tenant、adjudicator tenant 分别错配。

本地没有真实 PostgreSQL 时测试会明确 skip，不会用 SQLite 冒充 PostgreSQL 复合 FK
证据。CI 新增独立步骤和 JUnit 文件，并把该文件加入统一失败 annotation，便于直接定位
具体 constraint。

首次并行运行定向 pytest、format 与 lint 时，Ruff 报告 `0010` 的 3 条 guard 文本源代码行
超过 100 字符。SQL 类别本身没有变化；把消息从冗长的
`tenant consistency check failed: human-review ...` 缩短为仍可识别的
`tenant check failed: review ...`，并同步离线 SQL 断言。因为并行任务有一项失败时没有
完整返回其余输出，不能把那次运行未显示的项目记录为通过，必须重新执行。

重新执行结果：

- 新 PostgreSQL integration：本地 `1 skipped`，原因是未设置真实服务开关；
- ORM/migration/dataset 定向单元：`19 passed`；
- Ruff lint：通过；
- format check：3 个文件需机械格式化。

运行 Ruff formatter 后 3 个文件被重排；随后 format check 显示 10 个相关文件均已格式化，
lint 再次通过，定向 mypy 对 6 个 source file 无问题。

### 7.15 提交前结构审查与真实 migration round-trip

逐表打印 ORM 的 FK/UQ 名称、local columns 和 target columns，与 `0010` 对照，所有关系
一致。检查已有 concurrency/integration 的 finally cleanup：都先删除人工复核/Result、
Job、Run，再删除 Dataset Version、Reference、Blob、Dataset、Key、Tenant，没有发现会被
新 RESTRICT/CASCADE 关系阻断的旧顺序。

公开 README、领域模型和安全边界补充 P2-1，但明确区分：复合 FK 是写入完整性纵深防御，
不是会自动过滤 SELECT 的 PostgreSQL RLS。CI 除新增 13 类非法插入测试外，还在所有
integration 后实际执行 `alembic downgrade 20260802_0009` 再 `upgrade head`，用于验证
真实 PostgreSQL DDL、可派生 tenant 回填和回滚依赖顺序。

### 7.16 本地全量门禁

CI 同形非 integration 回归：收集 437 项，8 项 integration deselected，429 项全部通过，
耗时 233.59 秒。新增的 5 个非 integration 合同来自 ORM/查询和 migration
upgrade/downgrade 验收；不能把 deselected 的真实服务测试写成通过。

其余门禁：

- Ruff format：241 files already formatted；
- Ruff lint：All checks passed；
- strict mypy：116 source files，无问题；
- Artifact `0009` + tenant consistency `0010` 离线 migration 合同：`4 passed`；
- 新真实 PostgreSQL constraint integration：本机 `1 skipped`，等待 GitHub CI；
- `git diff --check`：无 whitespace error（最终提交前还会复查）；
- 正式 500-case/32-arm Gate 1：`NOT_RUN`。

lock check 首次使用 `uv lock --check` 失败，因为当前 PowerShell PATH 没有全局 `uv`；定位到
仓库 `.codex-tools/Scripts/uv.exe` 后，第二次又因用户级
`C:\Users\xuan\AppData\Local\uv\cache` 中既有文件无权限而失败。两次都发生在读取 lock
前，不能记成 lock 内容失败。把 `UV_CACHE_DIR` 指向仓库已忽略的工具缓存后第三次成功：
`Resolved 70 packages in 2ms`，`uv.lock` 没有修改。

## 8. 当前效果与剩余边界

已达到的效果：正常应用写入继续从 principal 派生 tenant；即使未来出现漏过滤的写入实现、
手工 SQL 或错误迁移，数据库也会拒绝测试覆盖的跨 tenant/跨 Run 父链。升级旧库时发现已有
矛盾会停止并保留原事务，不静默重归属。

仍未证明或刻意未处理：

- `case_id` 与 Job 的内容一致性没有纳入本项；
- 多态 `audit_events.resource_id/actor_id` 没有强行建立部分 FK；
- 只有单一父链的表没有复制 tenant；
- 没有 PostgreSQL RLS，读取仍必须显式 tenant-scoped；
- 本机没有执行真实 PostgreSQL constraint test、migration round-trip、Docker image 或
  Compose；等待 GitHub Actions 后才能提升远端普通 CI 证据状态；
- 普通 CI 通过也不等于正式 Gate 1、生产容量、灾难恢复或安全审计通过。
