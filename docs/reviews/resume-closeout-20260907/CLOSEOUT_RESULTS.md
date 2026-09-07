# 2026-09-07 简历发布收口

结论：**READY_WITH_LIMITS**。可展示固定合成评测，以及精确新 CODE 的真实数据库/Worker/报告工程验收；没有把它升级为正式 A/B、人评、生产资格或扩容通过。新用户现场 durable 教程仍是 NEEDS_REGISTERED_TARGET。

NEW_CODE_SHA：c5dbeecaf5d06ba2bbae7f7bcb4b7a7678911997。[CODE CI 34135369898](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34135369898) attempt 1 已 completed/success，两项 job 均成功。实际下载 product-ci-evidence-34135369898-1，ZIP SHA256 b3d62ac1539f39add6ad705317bece08811b21e2e3880aedabbe834d0761cc99，与 GitHub artifact digest 相同。不是借用历史 CI。

运行源码指纹：5e77c77373da893785c5105f3a94b116fb7ed32bff0e5be564bbe2a3c277697a，覆盖 485 个源码、测试、迁移、锁、策略、部署和 CI 文件。完整 git archive 包含 13015 个提交文件，保留旧校验依赖的历史公开证据，但不把生成报告纳入运行源码指纹。NEW_DOC_SHA 与它自己的 CI 放在仓库外 FINAL_RECEIPT.json；不为自引用再提交一轮文档。

机器摘要见 [PUBLIC_SUMMARY](PUBLIC_SUMMARY.json)，实际 CI 身份/各集合数量见 [CI_CODE_IDENTITY](CI_CODE_IDENTITY.json)，48 个关键测试 ID 均 PASSED，见 [CI_KEY_TESTS](CI_KEY_TESTS.json)。公开候选投影位于 public/qa 与 public/agent；它们来自同一次冻结私有结果，不再次调用目标。

## 固定边界与根因

仅 godofxuan/ai-evalops-platform；独立 worktree 从 DOC b122a6d7394146422c8c153e33531f81241c8280 创建，已审 CODE abfab98056e5526af505551ebde9618b94698f3a。CODE→DOC 13 个变更仅说明/公开制品，运行源码未变化。原工作区、RAG、main、历史运行与原审计 ZIP 不修改。

| 项目 | 修改与对应证据 | 当前范围 |
| --- | --- | --- |
| F1 | observation_contract 常量，ProviderResult.from_target 前置约束；fixture 转安全目标错误；test_observation_contract 中 CLI/实际 HTTP/worker 边界 | 本机与精确 CODE CI 均通过；真实 PG 中 QA/Agent 超长观测各保留失败题并复算失败报告 |
| F2 | validate_terminal_pair、artifact/flat 共享映射、terminal_matches_expected；缺粗态为证据不足；旧粗态兼容 | 120 题旧错误 DEMO_PASS 已复现；新代码 local/HTTP/worker/真实 PG/私有复算拒绝冲突 |
| F3 | local CLI 输出 LOCAL_PRIVATE_STRUCTURE_ONLY/reported_quality_status；public 仅投影；durable 真实复算 | 语义篡改与普通摘要重算反例已测试，local 不伪称质量复算 |
| F4 | prepare_product_client_demo + SDK 既有数据集 API；自动捕获真实 UUID/双摘要；完整教程与简历答辩 | 准备助手已进入实际 create_app/鉴权/PG 集成；本机新用户现场仍 NEEDS_REGISTERED_TARGET，未部署 |
| F5 | always 留存脱敏 JUnit、白名单身份与阶段，加入失败 annotation | 正反例通过；已下载并验证新 CODE 的真实 artifact、JUnit 与三条故障阶段 |

共享模型仍沿用原 schema；**执行 CODE SHA 是本次语义修正的版本身份**。没有另造一套 evaluator ID。合法旧粗态继续读取；非法旧快照/已发布 private result 在当前代码返回 evidence_invalid_for_current_code，经现有 API 安全错误边界转 422；不回显答案、不原地修库、不重新发布历史报告。旧材料只能按旧 SHA 审阅，不能宣称符合本轮修正。

## 已发生的过程与非通过记录

使用 Python 3.12.13、uv locked all-groups；锁 SHA256 1a83041db8aae7ac85020405733e1638efa89ae1f4fc8618184b9864f54ffee6。跨盘硬链接不可用时 uv 复制安装，未改依赖。
三份审计探针在干净 DOC 基线实际运行：超长观测后段失败；终态冲突通过；local 语义修改后重 hash 仍接受。探针退出 0 只是诊断脚本运行完，不是系统通过。
先失败再修：F1 CLI 2 failed→2 passed；F2 完整 gate 1 failed→共享 21 passed；旧非法快照 2 failed→24 passed；F3 旧文本输出 2 failed→6 passed。集合重叠，不能相加。
补充缺失终态 fixture 时发现旧行为 DEMO_FAIL，应为 INSUFFICIENT_EVIDENCE，已修；新增本地真实 TCP、派生分数重 hash 与旧私有安全错误，合并针对集 44 passed。
F4 初次测试错误只写 1 题，被既有至少 2 题约束拒绝；这是测试准备错误，不算产品 bug。改为 2 题后观察助手未实现，再实现，客户端相关集合 21 passed。
格式与新 dict 推导类型问题在预验收阶段修正，不降低断言；完整验收开始后最多两轮本任务内修正。

第一次全量本机验收实际为 1217 passed / 1 failed / 1 skipped（381.54 秒）。唯一失败是 test_invalid_agent_terminal_is_a_safe_response_error：共享校验把旧非法粗态的安全错误码从 target_agent_observation_invalid 改成了新码。第 1 轮限定修正采用 InvalidCoarseTerminalError 区分旧类别，保留旧错误码，不删旧断言、不放宽终态约束。未知细态/冲突仍用 target_agent_terminal_invalid。跳过是 Windows 当前权限无法创建符号链接（1314），需由精确 Linux CI 验证，不能计本机通过。

## 验证等级

第 1 轮兼容修正后的完整本机验收：1218 passed / 1 skipped / 40 deselected，376.52 秒，正常项目配置。唯一 skip 仍为 Windows symlink 权限 1314；40 项 integration 明确未在本机运行。ruff format 652 文件、lint、mypy 226 源文件、uv lock --check 与旧证据/scorecard 检查均成功。详细命令、开始结束时间、dirty 源码摘要和 JUnit 保留在外部交付日志；这些不是新提交 CI 的替代品。

- LOCAL_PRIVATE_STRUCTURE_ONLY：local 文件/结构/摘要绑定；不重算质量，reported 状态可能被同时重写普通摘要。
- PUBLIC_PROJECTION_ONLY：公开允许字段及派生内容，不检查私有观测。
- PRIVATE_SOURCE_REQUIRED：库级私有单报告缺原始输入，未复算；不是完整私有包通过。
- PRIVATE_RECOMPUTED：原始输入 + 持久结果快照 + 共享聚合器复算一致，仍不是来源认证。
- 测试用真实本地 TCP 不等于公网 TLS；DNS/peer 只在 tests 注入。
- HUMAN_REVIEW=NEEDS_HUMAN，FORMAL_AB=NOT_EVALUATED，PRODUCTION=NOT_EVALUATED；保留历史 NEGATIVE_SCALING。

## 演示与材料

固定 CODE 的本机发布候选每套只运行一次：QA execution_id=23e92cc1-f26f-427b-b24d-f1da86117b11、Agent execution_id=80f17f94-447e-448e-8866-7f026685b871，均 120 题、DEMO_PASS、退出 0、SYNTHETIC_FIXTURE。QA 超长和 Agent 冲突两个独立失败演示各 2 题，均 EXECUTION_FAILED、退出 3、一个不重试错误，完整失败包保留。没有修改所选 gold/policy；没有择优重跑。既有 CI 自带的 QA 自检保留为 CI 测试，不拿它替换发布候选。

本机助手实际返回 NEEDS_REGISTERED_TARGET、remote_mutations=0；raw SHA=563a5063ae06efcd8b4a49729bf3621887b9876ffe34bc66bf41c0b6b2bb916c，normalized SHA=c219841d4920c42c1b878a9ecbb0564ef6fb32d2d71aff63808a1905a6fda243。未伪造服务/目标 ID 或执行成功。

CODE CI 实际结果是 1219 项非集成 + 40 项集成，全部无失败、无跳过。持久产品入口 test_real_postgres_pair_idempotency_and_hidden_tenant_boundary 用时 20.544 秒；包含真实应用/鉴权、原子双组、同键重放、跨租户、真实 PostgreSQL、结果发布、客户端准备助手、取消/截止/预算及 OS 子进程 kill 后恢复。三条新故障阶段均为 4 Jobs / 1 failed / 3 accepted / 每题 attempt 1 / private_recomputed=true；并检验派生状态普通重 hash 后仍被拒绝。单元集合另验证派生分数篡改被复算拒绝。客户端协议在真实 loopback HTTP 子进程测试中验证，但这个服务是 API fixture；集成客户端是 ASGI transport，目标 DNS/public peer 是测试替代，不能称为完整生产公网 TLS 演示。

停止开发：F1–F5 在上述范围完成。外部剩余仅为操作者提供合法注册测试目标与实例（若需要现场 durable 演示）；人评、正式 A/B、生产与新性能测试不属于本轮后续默认工作。DOC 自身 CI 与最终 ZIP 重读摘要见外部回执。

[DEMO_GUIDE](DEMO_GUIDE.md) 覆盖 API 提交前全过程、真实 ID 捕获、同键重放、独立客户端恢复、私有导出和离线验证；[RESUME_AND_DEFENSE](RESUME_AND_DEFENSE.md) 已写完整。缺少合法注册目标/本机 PostgreSQL 时，不能把测试 API 夹具说成新用户 durable 现场已走通。最终 ZIP/身份/CI 以包外回执为准，避免自引用和无限文档提交。
