# P2-2 Human Review Task 创建权限：证据化实施日志

## 1. 阶段身份与边界

- 阶段：P2-2，Human Review Task 创建权限。
- 开始日期：2026-08-02（Asia/Shanghai）。
- 分支：`codex/gate1-evidence-hardening`。
- 起始 SHA：`687cf903ae75b849155ce8ca6855404587fe9f60`。
- 起始工作区：clean，本地与远端分支同步。
- P2-1 最终复验：[GitHub Actions Run #16](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30729880468)
  两个 job 均 `completed / success`。
- 本阶段不引入完整 RBAC/scope 系统，不运行正式 500-case/32-arm Gate 1，不创建 PR 或合并。

## 2. 原始行为与为什么现在适合处理

`POST /api/v1/runs/{run_id}/review-tasks` 调用
`SQLAlchemyReviewService.create_tasks()`。该方法会验证 Run tenant，却没有任何 capability
检查。因此任何同 tenant 的有效普通 API Key 都可以：

- 触发创建 Task；
- 通过增大 `sample_size` 扩展该 Run 的人工评审集合；
- 触发 human review packet artifact 写入；
- 成为 `human_review_tasks.created_by`。

这不是跨 tenant 读取漏洞：Run 仍按 principal tenant 查询。它是 tenant 内操作权限缺失，
会让普通 service/worker credential 执行本应由评审运营者决定的工作流动作。P2 顺序明确把
“Human Review Task 创建权限”排在跨表 tenant 一致性之后，因此现在处理适合且不越过顺序。

## 3. 为什么不能直接复用 `can_review`

现有 `can_review` 的合同是“真人 reviewer credential 可以 list/submit/adjudicate”。现有真实
集成测试还刻意使用 `can_review=false` 的独立 creator key 创建 Task，再由两个 reviewer 和
第三 adjudicator 操作。这表达了合理的职责分离：

- creator 决定/扩展评审 cohort；
- reviewer 只读取盲化 packet 并提交不可变标签；
- adjudicator 只解决两位 reviewer 的分歧。

若把创建权自动绑定到 `can_review`，所有 reviewer 都能扩大 sample，普通 creator 反而失去
合法路径；这会破坏现有职责模型，而不是修复它。因此冻结独立 capability：
`can_create_review_tasks`。

## 4. 最小权限合同

- `api_keys.can_create_review_tasks BOOLEAN NOT NULL DEFAULT false`；
- `APIKeyCandidate` 和 `Principal` 都携带该服务端派生字段，默认 false；
- 请求 body/query/header 不能设置或覆盖它；
- `create_tasks()` 的第一项动作是检查该字段，失败时不访问数据库、不写 artifact；
- reviewer-only、ordinary key 都返回 403；
- 403 使用独立错误码 `review_task_creator_required`，不能误报
  `human_reviewer_required`；
- 管理员 CLI 新增显式 `--review-task-creator`；可与 `--human-reviewer` 同时授予，但文档建议
  使用不同 credential；本阶段不强制互斥，因为指令没有要求组织级 separation-of-duty policy；
- P2-1 的 `(created_by, tenant_id)` FK 继续保证 creator 与 Task 同 tenant，但数据库 FK 不负责
  证明创建瞬间 capability 为 true，授权必须在服务入口检查。

## 5. Migration 与回滚

新增 `20260802_0011_review_task_creation_permission.py`，不修改历史 migration：

- upgrade 添加非空 boolean，server default false；现有 key 全部安全回填为无创建权；
- 不自动把已有 `can_review=true` key 提升为 creator；
- 不根据历史 `human_review_tasks.created_by` 反向提升 key，因为“过去创建过”不是管理员授权
  证据，而且旧系统允许所有 key 创建；
- downgrade 删除该列；业务 Task/API Key 行不删除。

默认拒绝会改变升级后的行为：过去能创建 Task 的普通 key 会得到 403，管理员必须显式创建
或配置 creator credential。这是本安全修复的预期兼容性变化，不能用自动宽松 backfill 消除。

## 6. TDD tracer 计划

1. reviewer-only key 在 DB 访问前不能创建 Task，且使用独立异常；
2. ORM/migration 默认 false 与 downgrade；
3. API Key candidate → Principal 的服务端权限传播；
4. CLI 显式创建 creator key；
5. 真实 PostgreSQL/HTTP：ordinary 和 reviewer-only 403，creator-only 201；
6. 定向、全量、静态、migration、CI 与 Compose 回归。

## 7. 实施流水

### 7.1 Tracer 1 RED：reviewer 不是 Task creator

先在 review service 单元测试中导入独立的
`ReviewTaskCreationPermissionError`，并使用 `can_review=true`、但没有创建权限的 Principal
调用 `create_tasks()`。测试要求在 `session_factory=None` 的情况下仍得到权限异常；若代码访问
数据库，就会以其他异常失败，从而证明检查顺序。

第一次运行结果：collection error。`app.reviews.service` 不存在
`ReviewTaskCreationPermissionError`，因此测试没有机会触碰数据库。这个 RED 证明旧模型没有
独立创建权限/异常，而不是某条已有 guard 的偶然失败。

### 7.2 Tracer 1 最小 GREEN

- `Principal.can_create_review_tasks` 新增，默认 false，保持所有未显式更新的测试/调用方
  fail closed；
- 新增 `ReviewTaskCreationPermissionError`；
- `create_tasks()` 在打开 session transaction 前调用 `_require_task_creator()`；
- reviewer-only Principal 因默认创建权 false 被拒绝，`session_factory=None` 不应被访问。

本轮尚未从数据库认证记录填充该字段，也未添加 HTTP handler；这两项留给后续 RED，不能把
当前 service 单元 GREEN 写成端到端权限已完成。

Tracer 1 第二次运行：`1 passed`。

### 7.3 Tracer 2 RED：ORM 默认拒绝

扩展现有 API Key metadata 测试，要求 `can_create_review_tasks` 存在、非空，且 Python default
与 server default 都是 false。双默认分别保护 ORM 构造和直接 SQL insert，不能只依赖某一
调用方记得传 false。

第一次运行：`1 failed`，字段集合缺少 `can_create_review_tasks`；旧 `can_review` 的存在没有
让测试误通过。

### 7.4 Tracer 2 ORM 最小 GREEN

在 `APIKey` 增加非空 Boolean，`default=False` 且 `server_default="false"`。没有修改
`can_review`，两种 capability 独立保存。

第二次运行：`1 passed`。

### 7.5 Tracer 2 migration upgrade RED

新增离线 Alembic 测试，要求 head 对 `api_keys` 执行
`ADD COLUMN can_create_review_tasks BOOLEAN DEFAULT false NOT NULL`。保留 server default，保证
旧行回填和未来直接 SQL insert 都默认拒绝；不生成任何 `UPDATE ... can_review` 或按历史 Task
creator 提权的 SQL。

第一次运行：`1 failed`，离线 SQL 最终 revision 是 `0010`，没有新增列。

### 7.6 Tracer 2 migration upgrade 最小 GREEN

新增 `20260802_0011_review_task_creation_permission.py`，upgrade 只添加 non-null Boolean 与
server default false。没有 data-dependent backfill；PostgreSQL 用默认值处理所有已有行。
`downgrade()` 暂时留空，只为下一条 downgrade 测试产生真实 RED，不是可提交终态。

upgrade 定向测试：`1 passed`。

### 7.7 Tracer 2 migration downgrade RED

要求 `0011:0010` 生成 `DROP COLUMN can_create_review_tasks`，并且 SQL 中不能出现
`DROP TABLE`。权限列可丢弃，但 API Key、Task 和评审历史必须保留。

第一次运行：`1 failed`，只有 Alembic version 更新，没有 `DROP COLUMN`。

### 7.8 Tracer 2 migration downgrade 最小 GREEN

`downgrade()` 只调用 `op.drop_column("api_keys", "can_create_review_tasks")`。没有删除或更新
任何 key/task/history 行。

合并运行 upgrade/downgrade：`2 passed`。

### 7.9 Tracer 3 RED：认证权限传播

修改 valid API Key 测试，让 `APIKeyCandidate.can_create_review_tasks=true`，并要求认证后的
Principal 同样为 true。普通/revoked/expired candidate 不传该字段，仍应由默认 false 保持
兼容和 fail closed。

第一次运行：`1 failed`，`APIKeyCandidate.__init__` 不接受新字段。

### 7.10 Tracer 3 最小 GREEN

- Candidate 新增默认 false 字段；
- `authenticate_api_key()` 显式复制到 Principal；
- `SQLAlchemyAPIKeyLookup` 从数据库 APIKey 行复制到 Candidate；
- 没有解析任何 request body/query/header 权限值。

认证定向测试：`1 passed`。

### 7.11 Tracer 4 RED：独立 HTTP 403

API 测试配置一个 `create_tasks()` 直接抛 `ReviewTaskCreationPermissionError` 的 fake service，
要求 POST 返回 403、code=`review_task_creator_required` 和明确的创建权限消息。当前应用只注册
reviewer permission handler，因此新异常不应被误映射或吞掉。

第一次运行：`1 failed`。异常从 ASGI app 冒泡，middleware 记录
`error_code=unhandled_exception`，没有返回 HTTP response。这证明新异常尚未进入错误边界。

### 7.12 Tracer 4 最小 GREEN

- `app.api.errors` 新增专用 handler；
- 只接受 `ReviewTaskCreationPermissionError`，返回 403；
- code=`review_task_creator_required`；
- message 明确是不能创建 Task；
- `create_app()` 注册新异常和 handler；原 `ReviewPermissionError` 的
  `human_reviewer_required` 完全保留。

HTTP 定向测试：`1 passed`。

### 7.13 Tracer 5 RED：管理员 CLI 显式授权

parser 测试分别解析默认参数和同时带 `--human-reviewer --review-task-creator` 的参数，要求
两个 flag 默认都 false、显式传入时各自为 true。允许同时传入不代表推荐同一操作者兼任；
它只避免在没有产品要求时擅自加入互斥政策。

第一次运行：`1 failed`，argparse 报 unknown `--review-task-creator` 并退出 2。

### 7.14 Tracer 5 最小 GREEN

- parser 新增独立 store-true flag；
- `create_key()` 新增默认 false 参数；
- 创建 ORM APIKey 时写入 `can_create_review_tasks`；
- `main()` 只从解析后的 `review_task_creator` 传值，不从 reviewer flag 推导。

parser 定向测试：`1 passed`。

### 7.15 Tracer 6：真实 PostgreSQL/HTTP 权限矩阵

扩展现有 blinded human review integration fixture：

- ordinary key：两权限都 false；
- creator key：`can_create_review_tasks=true`、`can_review=false`；
- reviewer/adjudicator keys：`can_review=true`、创建权限 false。

在 creator 成功调用前，ordinary 与 reviewer A 分别尝试创建，必须得到独立 403 code；随后
直接查询 PostgreSQL，Task 数和 human-review packet artifact 数都必须为 0。creator-only
再创建 2 个 Task 并产生 1 个 packet artifact；它随后提交 review 仍得到原
`human_reviewer_required`，证明两权限没有串联。

本机缺少真实 PostgreSQL 时该测试只会明确 skip；此前 service/auth/HTTP 的 RED 已驱动实现，
远端 CI 将执行完整真实路径。

### 7.16 文档与 CI migration 命名

README、领域模型、安全边界和 Human Review 合同分别记录：两权限默认关闭、服务端派生、
独立 403、CLI 授权方式和“最小 capability 不等于通用 RBAC”。CI 的实际 downgrade/re-upgrade
命令仍从当前 head 降到 `0009` 再升级，因此会覆盖 `0011`；step 名从仅 `P2-1` 改成
`P2 downgrade and re-upgrade`，避免名称落后于实际覆盖范围。

### 7.17 提交前补证：请求数据不能自我提权

最终审阅发现，认证单元测试已经证明 capability 来自数据库 Candidate，但 API 层还没有直接
锁定“客户端伪造字段不会覆盖 Principal”的合同。新增回归测试，让 reviewer-only Principal
同时在 JSON body、query 和 header 中提交值为 true 的创建权限，并把真实 review service 的
session factory 设为 `None`。结果仍是 403 `review_task_creator_required`；如果任一请求值能
覆盖 Principal，代码就会越过 guard 并尝试访问不存在的 session factory，测试会以其他异常
失败。这个测试是在核心 RED/GREEN 完成后的补充回归，不伪装成先于实现失败过的 RED。

首次运行新增测试即通过；同一轮 Ruff 报告两条同模块 import 未合并。该问题不影响运行语义，
但违反仓库 import 规范，因此合并 import 后重新执行格式、lint、类型和测试，全部通过。真实
PostgreSQL 用例中的 `ordinary_submit` 也改名为 `creator_submit`，避免把 creator-only key
误读为普通 key；这只是测试可读性调整，不改变合同。

### 7.18 完整本地验证

实现提交：`7aab279cdb95a2e1a615d6c982ffddee333db240`。

| 检查 | 结果 | 状态 |
|---|---|---|
| 权限/API/认证/ORM/migration/CLI 定向 | 31 passed | `VERIFIED` |
| Human Review 真实 PostgreSQL 合同 | 1 skipped：本机未设置真实服务开关 | `NOT_RUN_LOCAL` |
| 非 integration 全量 | 435 passed，8 deselected，264.60s | `VERIFIED` |
| Ruff format | 244 files already formatted | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | 108 source files，无问题 | `VERIFIED` |
| uv lock | 70 packages resolved | `VERIFIED` |
| Alembic topology | 唯一 head `20260802_0011` | `VERIFIED` |
| 全部离线 migration tests | 6 passed | `VERIFIED` |
| `git diff --check` / 暂存区检查 | 通过 | `VERIFIED` |
| 正式 500-case/32-arm Gate 1 | 未启动 | `NOT_RUN` |

本机没有启动 PostgreSQL/Redis，也没有 Docker CLI，因此不能把 integration 的 skip 写成通过。
真实 migration upgrade/downgrade、旧 key 默认拒绝、权限矩阵和 artifact 零副作用仍须由推送后
GitHub Actions 执行；在远端结果返回前，本阶段只能写
`LOCAL_CONTRACT_VERIFIED / REMOTE_PENDING`。

## 8. 达成效果、兼容性与残余边界

达成效果：

- 普通与 reviewer-only credential 在任何 DB/artifact I/O 前被拒绝；
- creator-only credential 可以决定 cohort，但不能读取/提交/裁决 reviewer 工作；
- 认证、ORM、migration、CLI、HTTP 错误和真实服务测试共享同一独立 capability；
- P2-1 creator tenant 复合 FK 继续提供数据库纵深防御；
- 客户端提交同名 body/query/header 值不能自我提权。

预期兼容性变化：升级后所有既有 key 的新字段都是 false。旧系统中曾能创建 Task 的普通 key
会改为 403，管理员必须显式创建带 `--review-task-creator` 的 credential。这是 fail-closed
安全修复，而不是回归；migration 不根据历史 creator 或 `can_review` 自动提权。

仍未解决：

- 两个 Boolean capability 不是通用 RBAC/scope、自然人认证或组织审批系统；
- CLI 只创建新 key，不在线修改旧 key；轮换/撤销仍由管理员流程负责；
- 数据库只能证明 `created_by` 与 Task 同 tenant，不能证明创建瞬间 capability 为 true；
- 本机未执行真实 PostgreSQL、Compose 或正式 Gate；远端普通 CI 即使成功也不等于生产安全、
  容量、RLS、exactly-once 或正式实验通过。

## 9. 回滚边界

纯代码仓库回滚入口：

```text
git revert 7aab279cdb95a2e1a615d6c982ffddee333db240
```

已经升级数据库时，不能先删除 migration 文件再尝试 downgrade。安全顺序是暂停相关实例与
Task 创建，用仍包含 `0011` 的当前 release 执行 `alembic downgrade 20260802_0010`，确认只
删除权限列，再部署 revert 后的代码。该 downgrade 不删除 API Key、Task 或 review history，
但会恢复“所有同 tenant 有效 key 都能创建 Task”的旧宽松行为，因此只能在明确接受安全退回时
执行。文档提交和远端 CI 证据将分别记录，不与本实现提交混淆。

## 10. 推送与远端真实服务证据

- 文档提交：`bbbf7a3995e770724ef79d715370ed9d771f38ca`；
- 推送分支：`codex/gate1-evidence-hardening`；
- 远端 Run：
  [GitHub Actions Run #17](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30730652470)；
- 绑定 head：`bbbf7a3995e770724ef79d715370ed9d771f38ca`；
- workflow：`completed / success`；
- `quality-and-integration`：`completed / success`；
- `compose-smoke`：`completed / success`。

公开 GitHub API 的 step 级结果明确显示：

| 远端 step | 结果 |
|---|---|
| Run tests without external services | `completed / success` |
| Apply migrations | `completed / success` |
| Integration - blinded human review | `completed / success` |
| Migration - P2 downgrade and re-upgrade | `completed / success` |
| Build application image | `completed / success` |
| Build the complete current topology | `completed / success` |
| Start and wait for PostgreSQL and Redis | `completed / success` |
| Apply migrations in the Compose topology | `completed / success` |
| Start API, Worker, and Reaper | `completed / success` |
| Verify readiness through the published API port | `completed / success` |

因此，`0011` 的真实 PostgreSQL upgrade、Human Review 权限矩阵、实际 downgrade/re-upgrade、
镜像构建和 Compose readiness 均从 `REMOTE_PENDING` 提升为 `VERIFIED`。当前阶段结论更新为
`LOCAL_AND_REMOTE_CONTRACT_VERIFIED / FORMAL_GATE_NOT_RUN`。

轮询时有两次本地 PowerShell 只读查询失败：把 `foreach (...) { ... }` 的输出直接接到
`Format-Table` 管道，解析器报告 empty pipe element。第一次修正了一个查询，第二个轮询模板
却重复使用了同类写法；最终统一改成先构造 `$Rows=@(...)` 再格式化。两次错误都发生在本地
公开 API 展示脚本中，没有修改仓库、没有取消/重跑 CI，也不代表远端 step 失败。保留这条记录
是为了避免以后把“证据读取工具失败”误写成“被验证系统失败”。

Run #17 是普通 CI 合同证据，不是正式 500-case/32-arm、容量、RLS、RBAC、灾难恢复或生产
安全验证。形式化 Gate 1 继续保持 `NOT_RUN`。
