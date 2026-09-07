# 2026-09-07 简历发布收口

本文件在实现提交时记录已发生的针对性验证；精确 CODE 候选、完整 CI 与最终决定将在后续纯证据 DOC 中补齐。不能把这里的待执行项当通过。

## 固定边界与根因

仅 godofxuan/ai-evalops-platform；独立 worktree 从 DOC b122a6d7394146422c8c153e33531f81241c8280 创建，已审 CODE abfab98056e5526af505551ebde9618b94698f3a。CODE→DOC 13 个变更仅说明/公开制品，运行源码未变化。原工作区、RAG、main、历史运行与原审计 ZIP 不修改。

| 项目 | 修改与对应证据 | 当前范围 |
| --- | --- | --- |
| F1 | observation_contract 常量，ProviderResult.from_target 前置约束；fixture 转安全目标错误；test_observation_contract 中 CLI/实际 HTTP/worker 边界 | 定向本机已通过；真实 PG 待精确新 CODE CI |
| F2 | validate_terminal_pair、artifact/flat 共享映射、terminal_matches_expected；缺粗态为证据不足；旧粗态兼容 | 120 题旧错误 DEMO_PASS 已复现，新代码拒绝；PG 待 CI |
| F3 | local CLI 输出 LOCAL_PRIVATE_STRUCTURE_ONLY/reported_quality_status；public 仅投影；durable 真实复算 | 语义篡改与普通摘要重算反例已测试，local 不伪称质量复算 |
| F4 | prepare_product_client_demo + SDK 既有数据集 API；自动捕获真实 UUID/双摘要；完整教程与简历答辩 | 小型 API 边界测试通过；本机 NEEDS_REGISTERED_TARGET |
| F5 | always 留存脱敏 JUnit、白名单身份与阶段，加入失败 annotation | 留存器正反例通过；真正新 CI/下载待候选提交 |

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

[DEMO_GUIDE](DEMO_GUIDE.md) 覆盖 API 提交前全过程、真实 ID 捕获、同键重放、独立客户端恢复、私有导出和离线验证；[RESUME_AND_DEFENSE](RESUME_AND_DEFENSE.md) 已写完整。缺少合法注册目标/本机 PostgreSQL 时，不能把测试 API 夹具说成新用户 durable 现场已走通。最终 ZIP/身份/CI 以包外回执为准，避免自引用和无限文档提交。
