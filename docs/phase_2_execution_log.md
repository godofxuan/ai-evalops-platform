# Phase 2 逐步执行日志

## 记录规则

每步记录目标、设计判断、RED、实现、GREEN、问题、修正、效果和仍未知边界。首次即 GREEN、环境失败和 skip 均如实保留。

## P2-001 — 连续阶段授权与预检

- 日期：2026-07-29
- 起始 SHA：`9a8234073a61e81928d0c6b2c684d55a4d547d53`
- 用户新指令：“不要停，继续做下去，都做完。”
- 判断：该指令比原附件的“每阶段停止”和“第一轮部分模块由用户实现”更新且更直接，因此授权连续完成 Phase 2–9 和实现核心学习模块；仍不授权 push。
- 操作：重新完整读取 TDD 技能、原始附件、Phase 0/1 范围与架构文档；检查 Git、ORM、dataset service、app factory、错误映射和 CI。
- 实际：工作区干净；Phase 1 head 正确；Docker/PostgreSQL/Redis 仍不可用。
- 效果：以附件 Phase 2–9 的公开行为作为已批准合同，不再逐阶段请求确认。

## P2-002 — Phase 2 设计与文件计划

- 目标：实现 Run 创建、request hash、Idempotency-Key、Job 初始化与 Run 查询。
- 核心判断：
  - 幂等最终保护必须是 PostgreSQL 唯一约束；
  - 首次 SELECT 只用于快速 replay；
  - JSONL/artifact I/O 放在事务外；
  - Run 与所有 Jobs 在一个事务中提交；
  - Job 保存不可变 case payload snapshot，避免 Phase 3/4 每次执行扫描全文件；
  - endpoint 作用域当前由 `evaluation_runs` 表隐式提供。
- 计划新增：
  - `app/runs/`；
  - `app/api/routes_runs.py`；
  - `alembic/versions/20260729_0003_runs_jobs.py`；
  - Run API/unit/integration tests；
  - `docs/04_idempotency_contract.md` 和本日志。
- 计划修改：enums、ORM、app factory、artifact reader、JSONL validated result、README 与工程日志。

## P2-003 — Canonical request hash RED→GREEN

- 测试：两个语义相同但 object key 顺序不同的 payload 应产生相同 SHA-256。
- RED：`ModuleNotFoundError: No module named 'app.runs'`。
- 最小实现：稳定 `json.dumps`（sort keys、紧凑分隔、Unicode、拒绝 NaN）后计算 UTF-8 SHA-256。
- GREEN：`1 passed`。
- 边界：数组顺序保留；hash 不承担秘密加密功能。

## P2-004 — Idempotency-Key HTTP tracer 与 UUID strict 问题

- 测试 1：缺少 header 应为统一 422。
- RED：Run 路由不存在，实际 404。
- 实现：Run schema、service protocol、POST router、header 长度/字符约束和 main 注册。
- GREEN：缺 header 返回 422。
- 测试 2：有效请求应把 Principal、key、schema 交给 fake service。
- 预期：路由已经包含 service 调用，可能首次即 GREEN。
- 实际：首次 422。
- 根因：`RunCreate` 全局 strict 模式拒绝 FastAPI 解码后的 UUID 字符串；正常 JSON 无法表达 Python UUID 对象。
- 修正：外层保留 `extra="forbid"`，允许标准 UUID JSON 解析；组件 schema 保留 strict。
- GREEN：`2 passed`。

## P2-005 — Run/Job ORM 与漏失 dataset_hash

- 测试：Phase 2 元数据必须新增两表；Run tenant/key 唯一；Job run/case 唯一；Job 有 payload JSON。
- RED：`EvaluationRun`/`EvaluationJob` import 不存在。
- 实现：Run/Job 状态枚举、两张 ORM 表、检查约束、外键、唯一约束和领取/lease 索引。
- GREEN：ORM `5 passed`。
- 复核原始附件后发现 `evaluation_runs.dataset_hash` 被漏写。
- 新 RED：断言字段存在，实际失败。
- 修正：新增 64 位不可空 `dataset_hash`，service/repository/migration 同步保存。
- GREEN：ORM `5 passed`。

## P2-006 — Artifact 读取与结构化 validated cases

- 读取测试：写入后按服务端摘要读取并重新校验。
- RED：`LocalArtifactStore` 没有 `get_bytes`。
- 实现：
  - 只接受 64 位小写十六进制；
  - 由摘要派生路径；
  - 拒绝符号链接目录/文件；
  - 读取后重算 SHA。
- GREEN：artifact `7 passed`。
- 路径穿越拒绝逻辑在同一最小安全接口中提前实现，后续回归测试首次应为 GREEN。
- JSONL 测试：ValidatedJSONL 应返回已校验 case tuple 和 extra fields。
- RED：没有 `cases` 属性。
- 实现：复用已经 Pydantic 校验成功的对象；不二次解析；case_id 最大 200，与 Job 列一致。
- GREEN：validation `19 passed`。

## P2-007 — 首次 Run 创建 service tracer

- 测试：tenant-scoped source、artifact SHA 读取、两个 case 快照、created_by、dataset/target/evaluator hash、max_attempts 必须交给 repository。
- RED：`app.runs.repository` 不存在。
- 实现：`DatasetVersionSource`、`NewRun`、`RunSnapshot`、repository protocol 与 service 首次创建路径。
- 测试数据问题：最初使用固定 `"a"*64` 作为 artifact SHA，与内容不一致；正确实现应拒绝。测试改为对 bytes 计算真实 SHA。
- GREEN：`1 passed`。
- 边界：此时 replay 分支仍显式 `NotImplementedError`，未冒充完成。

## P2-008 — Replay、payload conflict 与并发胜者复核

- 相同请求 replay RED：命中显式 `NotImplementedError`。
- 实现：existing request hash 相同直接返回 snapshot，不读 artifact、不创建 Jobs。
- GREEN：`2 passed`。
- 同 key 不同 request RED：缺少 `IdempotencyConflictError`，收集失败。
- 实现：固定领域异常；不携带请求/hash 内容。
- GREEN：`3 passed`。
- 并发窗口 RED：首次查询为空，但 `create_or_replay` 返回不同 hash 的胜者；service 未再次检查，`DID NOT RAISE`。
- 实现：repository 返回后再次比较 request hash。
- GREEN：`4 passed`。
- 效果：覆盖“开始前已有”和“插入时竞争”两个冲突入口。

## P2-009 — Repository tenant SQL 与事务

- RED：三个 SQL builder 不存在。
- 实现：
  - tenant + key 幂等查询；
  - tenant + run id 查询；
  - DatasetVersion → Dataset → Artifact tenant 链；
  - 单事务 flush Run 并加入全部 Jobs；
  - 只识别指定幂等唯一约束；
  - 冲突 rollback 后回读胜者。
- GREEN：PostgreSQL dialect SQL 测试 `2 passed`。
- 边界：SQL 编译不证明真实并发，另建 integration contract。

## P2-010 — Run GET 与稳定错误映射

- GET RED：路由不存在，404。
- 实现：`GET /api/v1/runs/{run_id}`，Principal 传给 service。
- GREEN：API `3 passed`。
- 409 RED：领域冲突未处理，实际 500。
- 实现：固定 `idempotency_conflict` 409。
- GREEN：API `4 passed`。
- Run 404 RED：`RunNotFoundError` 未处理并穿透测试客户端。
- 实现：Run 与 dataset-version source 不存在共享固定 404。
- GREEN：API `5 passed`。
- evaluator config RED：无效 `max_attempts` 先触发 dataset I/O。
- 修正：幂等快速查询后、dataset I/O 前校验 1–10 的非 bool 整数。
- GREEN：service `5 passed`。
- evaluator HTTP RED：未处理异常返回 500。
- 实现：固定 `invalid_evaluator_config` 422，不回显 config。
- GREEN：API `6 passed`。

## P2-011 — Runtime wiring 与 migration

- app lifespan 使用共享 session factory/artifact store 构造 `SQLAlchemyRunRepository` 和 `SQLAlchemyRunService`。
- migration `0003` 创建 evaluation_runs/evaluation_jobs、JSONB 配置、状态 check、tenant/idempotency 唯一、run/case 唯一和候选/lease 索引。
- `alembic heads`：`20260729_0003 (head)`。
- `alembic upgrade head --sql`：成功生成 PostgreSQL DDL。
- 边界：本机没有 PostgreSQL，未执行 online migration。

## P2-012 — 静态检查问题

- `mypy app`：38 source files 首次通过。
- Alembic head/offline：首次通过。
- Ruff：3 个 import 排序问题，分别在 main、ORM 和 test service。
- 判断：纯机械排序，不改变行为；使用 `ruff check --fix` 修复。
- 结果：Ruff All checks passed。

## P2-013 — PostgreSQL 并发合同与回归

- integration contract：
  - 两个并发相同请求；
  - 返回同一 run_id；
  - 数据库一个 Run、两个 Jobs；
  - 同 key 不同 target version 返回 409；
  - tenant B 查询 tenant A Run 返回 404；
  - 精确清理测试 UUID。
- 本机结果：`1 skipped`，原因是缺少 migrated real PostgreSQL。
- Phase 2 目标集合：`45 passed`。
- 全仓非集成回归：`87 passed, 3 deselected in 3.94s`。
- 临时目录：三个本轮 basetemp 在绝对路径/仓库边界校验后删除。

## P2-014 — 提交与结论

- 实现提交：`79b09d4 feat(run): implement idempotent run creation`
- 提交前 `git diff --cached --check` 通过。
- 未 push。
- Phase 2 能证明仓库内幂等合同、事务结构和 API 语义；不能证明本机真实 PostgreSQL 并发成功。
- Phase 3 将实现显式状态机、SKIP LOCKED、lease、heartbeat 和 attempts；本次按用户连续授权直接进入。
