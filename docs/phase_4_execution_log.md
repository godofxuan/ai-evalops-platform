# Phase 4 逐步执行日志

## P4-001：问题、合同与文件计划

- 日期：2026-07-29
- 起始 SHA：`133a635`
- 目标：MockTarget、HTTPRAGTarget、ExecutionEvaluator、BasicAnswerEvaluator、
  Worker 成功执行链和 fenced CaseResult。
- 核心风险：
  - 外部请求慢且不可信，不能持有领取事务；
  - Target 成功后 lease 可能已经丢失；
  - 自动词法指标可能被误称为语义正确率；
  - HTTP Target 会引入 SSRF 和认证泄露；
  - 原 Run 模型缺少 evaluator type，Worker 无法选择适配器。
- 计划新增：evaluation domain、targets、evaluators、result committer、worker orchestrator、
  migration、unit/concurrency tests、语义文档。
- 计划修改：Run/NewRun/claim DTO、ORM、Run 输入校验、错误映射。

## P4-002：首批 RED

同时先写七组测试：

1. ExecutionEvaluator；
2. BasicAnswerEvaluator；
3. deterministic MockTarget；
4. HTTP mapping 与 SSRF；
5. result fencing SQL；
6. Worker 成功 pipeline；
7. CaseResult ORM。

收集阶段得到 7 个明确错误：

- 六组测试因 `app.domain.evaluation`、`app.jobs.results`、`app.workers` 不存在失败；
- ORM 因 `CaseResult` 不存在失败。

这证明 RED 来自 Phase 4 能力缺失，而不是断言写错。

## P4-003：领域合同与 Evaluator GREEN

- 新增不可变 `EvaluationCase`、`ExecutionContext`、`TokenUsage`、`TargetResult`、
  `EvaluationResult`。
- ExecutionEvaluator 记录运行事实。
- BasicAnswerEvaluator 使用显式 `lexical_*` 名称。
- 关键词覆盖只读取显式 `metadata.keywords`；无标签返回 `None`。
- 原因：从 expected answer 自动拆词并称为覆盖率会混淆标签与启发式。

## P4-004：MockTarget GREEN

- Pydantic extra-forbid 配置；
- fake sleeper 支持无真实 sleep 测试；
- 固定 response、tokens、delay；
- timeout/429/500/invalid-json/permanent/fail-until-attempt；
- case metadata 确定性覆盖；
- 执行前后取消检查。

目标测试确认前两次 503、第三次成功的故障注入完全由 attempt number 决定。

## P4-005：HTTPRAGTarget 与安全判断

- 仅 HTTPS；
- base hostname 必须精确 allowlist；
- endpoint 禁止 scheme/authority/query/fragment；
- 认证只允许环境变量引用，不保存明文；
- 请求前 DNS 解析全部地址并拒绝任何非公网地址；
- request/response 字段映射和 token usage；
- 超时、连接、HTTP、JSON 与结构错误转为稳定领域错误。

测试用 `httpx.MockTransport`，没有访问真实网络。输入案例覆盖 HTTP、localhost、绝对恶意
endpoint、直接 authentication 和私网 DNS。

限制：DNS 校验与实际连接之间仍有 TOCTOU；没有声称完全消除 SSRF。

## P4-006：Result 与 Worker pipeline

- CaseResult 唯一 `(job_id)` 及 `(run_id, case_id)`。
- 完成前 `SELECT ... FOR UPDATE OF evaluation_jobs` 同时检查 owner、expected version、
  live expiry、Run 和允许状态。
- 同一事务完成 Job、Attempt、CaseResult、AuditEvent 与 Run succeeded counter。
- Worker pipeline：claim → immutable case → Target → timeout boundary → Evaluator →
  fenced commit。
- 网络调用发生在数据库事务外。

首次目标 GREEN 运行结果为 `19 passed, 1 failed`。失败原因是测试替身
`SingleClaimer.__init__` 把属性也命名为 `claim`，覆盖同名方法，实际报
`TypeError: 'ClaimedJob' object is not callable`。只把属性改成 `claimed_job` 后，
`20 passed`。该失败属于测试装置错误，未修改生产逻辑。

## P4-007：补充 Run 组件校验 RED → GREEN

- 新测试要求 unsupported target/evaluator 在 artifact I/O 前失败。
- RED：`InvalidTargetConfigurationError` 尚不存在，收集失败。
- 实现：Run service 构造 Target/Evaluator 做纯配置验证，并转换成稳定 422 领域错误。
- API 新增 `invalid_target_config`，不回显配置或底层异常。
- GREEN：Run service、HTTP target、Run API 组合 `20 passed`。

## P4-008：模型偏差与迁移

- 原最低字段清单没有 `evaluator_type`，但有 `target_type`。
- 判断：只靠 evaluator version/config 无法选择实现；把 type 藏进 JSON 会制造隐式 schema。
- 修改：显式 evaluator_type 列，NewRun、repository 与 ClaimedJob 全链路传递。
- migration `20260729_0005`：
  - 历史行先回填 `execution`；
  - 立即移除 server default；
  - 新建 case_results 和唯一/检查/外键约束。
- `alembic heads`：`20260729_0005 (head)`。
- offline PostgreSQL SQL：通过。

## P4-009：并发合同

Phase 3 的真实 PostgreSQL 测试扩展为：

- 领取后心跳得到新 version；
- 用新 version 提交唯一结果；
- 同一 Worker 再用旧世代提交得到 LeaseLostError；
- 数据库只有一条 CaseResult。

本机结果：`1 skipped`，原因仍是没有 migrated real PostgreSQL。没有改用 SQLite。

## P4-010：静态检查与回归

- Ruff 首轮发现 6 项：
  - HTTP target 两个超长行；
  - Worker 测试四个常量 `getattr`。
- 修正：换行并让测试替身使用真实领域参数类型/显式属性。
- mypy：57 app source files，0 issues。
- Ruff：All checks passed。
- Phase 4 目标：`20 passed, 1 skipped`。
- 最终非集成回归：`145 passed, 4 deselected in 4.57s`。
- 真实 HTTP 未调用，Docker/Compose 未运行。

## P4-011：提交

- `e1ac1e2 feat(eval): add target evaluator and result pipeline`
- 提交前 `git diff --cached --check` 通过。
- 未 push。

## 为什么没采用其他方案

- LLM-as-a-judge：当前没有校准、人类标签和成本实验，会掩盖真正的执行系统目标。
- 词法指标命名为 accuracy：容易产生虚假结论，因此名称明确标注 lexical。
- 将认证 Token 放进 Run JSON：会持久化敏感值并进入 hash；改为环境变量引用。
- 任意 URL：SSRF 风险不可接受；采用 HTTPS + allowlist + DNS 公网检查。
- Target 成功后直接 INSERT：旧 Worker 可覆盖新世代；先锁定并 fence Job。
- 只依赖结果唯一约束：能防第二条结果，却不能证明提交者仍持有租约。

## 当前能证明

- Mock 故障可复现；
- HTTP mapping 与常见 SSRF 输入防线；
- 自动指标没有冒充语义正确率；
- 成功执行代码按 Target → Evaluator → fenced commit 分层；
- CaseResult 与 Attempt/Job 更新在一个事务设计中；
- 迁移与静态检查通过。

## 当前不能证明

- 本机真实 PostgreSQL 结果竞争；
- DNS 重绑定完全被消除；
- Worker CLI 已稳定长时运行或执行期间持续心跳；
- 失败已分类、重试或被 Reaper 回收；
- 真实 RAG 服务兼容、吞吐或费用；
- 生产级安全性。

## 建议亲自理解

1. `app/jobs/results.py`：为什么结果唯一约束与 lease fencing 都需要。
2. `app/targets/http_rag.py`：URL、DNS、认证与残余风险。
3. `app/evaluators/basic_answer.py`：指标命名如何避免过度声明。
4. `app/workers/worker.py`：为什么外部执行不放进数据库事务。
5. migration `0005`：evaluator type 回填后为何移除默认值。

## 面试官可能追问

- 唯一 CaseResult 是否等于 exactly-once？
- Target 已成功但结果提交被 fence 时，费用和副作用怎么办？
- 为什么 `cancelling → succeeded` 合法？
- DNS allowlist 为什么仍有重绑定风险？
- 为什么不把 bearer token 放进数据库加密保存？
- normalized exact match 能否作为答案准确率？
- Worker 执行超过 lease 时当前还缺什么？
