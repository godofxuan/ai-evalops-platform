# 2026-09-12 评测使用闭环：实施、问题与验证记录

## 为什么实施这些内容

用户要求把高星项目调研中值得学习的内容落实，并解决逻辑和操作问题。独立判断后保留三个目标：降低第一次使用门槛、解释评分的适用范围并能与人工意见对照、把失败与轨迹关联后进入完整回归。没有把“跟上时代”解释为安装五个平台、引入新模型或新增更多不可验证指标。

计划见 `docs/plans/evaluation-workflow-v1.md`，操作说明见 `docs/evaluation-workflow.md`。借鉴来源为官方接口与流程文档，代码为本项目独立实现。原发布 gate、gold 和历史负面结论不改。

## 工作树与运行环境

- 原工作区 `D:\文档\ai-evalops-platform` 保持原分支与内容。
- 在已有独立工作树 `C:\Users\xuan\AppData\Local\Temp\evalops-reliability-panels-20260912` 创建 `codex/evaluation-workflow-v1`，保留此前 reliability 的 12 个未提交文件。
- 基线 DOC HEAD：`6be5f971cc6b6d53d02bd026cf27473bc77785cc`。该 HEAD 是基线，不是本轮新实现的不可变身份。
- 使用已存在的 Python 3.12.13 环境。`uv sync --locked --all-groups --dry-run --offline` 核对 141 个已安装包，结果 Would make no changes。锁文件和依赖未改。
- Windows 沙箱辅助进程无法正常启动：只为本项目命令使用受审执行权限。Git safe.directory 仅命令级设置，没有更改全局配置。补丁更新也遇到相同 helper 故障，改为调用同一个 apply_patch 可执行入口，不使用 Python 或 shell 覆盖源码。

## 实施过程

| 改动 | 判断与原因 | 验证/效果 |
|---|---|---|
| `learning_workflow.py` | 复用现有运行器和聚合器，不新增执行后端；local 诊断也必须从冻结输入复算 | 原运行→私有文件→读取→重算通过；公开摘要不能冒充私有证据 |
| `learning_grading.py` | 代码注册的明确评分合同，区分封闭答案和 JSON 结构答案 | 返回 score/reason/limitations；非法 JSON 参考是输入问题；不改旧门槛 |
| 盲审及校准 | 避免先看机器结论影响标注；不伪造真人评价 | 隐藏 case/arm/分数；重复/未知/过期标签拒绝；缺失、UNSURE、null 分列；合成分层 |
| `trace_diagnostics.py` | 优先兼容开放轨迹结构，而不是绑定一种 Agent 框架 | 锁定 SDK 真实 span 经 OTLP 编码测试；过滤输入/输出、请求头和任意属性；部分轨迹不当完整 |
| `learning_analysis.py` | 报告不能只显示完整成功的 pair，否则执行失败题会消失 | 每题两臂全覆盖；缺观察/未知费用保留；症状不自动当根因；跨题复用 trace 标记歧义 |
| `learning_bundle.py` | 摘要完整不等于诊断正确，要能离线重建 | 重算 analysis/HTML/packet/focus，修改文件再重算哈希仍会被拒绝 |
| `evaluation_workflow.py` | 复用已有 JSON spec，增加统一入口 | init/demo/run/analyze/verify/calibrate/regressions/recover；默认公开，私有内容显式选择 |
| 完整回归题集 | 只复测失败子集会造成选择偏差 | 原题集字节不变，另加 focus；不改 gold，不重复挑成绩 |
| `tests/product_learning_support.py` | 单元快照不能取代真实持久化 | 接到已有 PostgreSQL/worker/回环 HTTP 集成后的 QA/Agent、正常/失败/取消报告；本机缺环境未验收 |

## 遇到的问题与处理

1. 首个来源切片先因模块不存在失败。实现后两个测试中一个直接比较 Pydantic 对象失败：存盘/读取后 union 类型选择不同，但 JSON 合同一致。改为检查实际 JSON 合同；重算器本身没有放宽。随后 2 passed。
2. 首个 Agent 诊断通过真实 fixture 执行和原 exporter 后生成所有两臂行，1 passed。没有把内存模型构造当成整个链路通过。
3. 构造 64 题较长响应，通过实际 CLI 执行发现复核包超限后源结果丢失。初始 `recovery-red.xml` 失败；修复后 `recovery-green.xml` 1 passed / 11.147 秒。后处理失败现为 EXECUTED_ANALYSIS_BLOCKED 并保留已接受观察和原题集，不要求重新调用目标。
4. 独立审查发现上一个修复仅覆盖诊断 writer，不覆盖最初源 exporter 或最后目录发布。增加持久故障捕获和完成标记；在真实演示执行后注入磁盘/发布失败，PRIVATE 保留原结果和题集，PUBLIC 仅保留公开投影；捕获写不完整时标 FAILED。恢复测试见 `test_workflow_recovery.py`。捕获恢复是离线重算，不认证来源。
5. durable 回归导出首次失败（`bundle-first.xml`: 1 failed / 7 passed）。原因不是缺证据，而是 durable 的 `result.input_snapshot` 设计上为空；真实冻结请求在外层 result snapshot。改从已验证的外层提取注册目标 request；不能臆造公网 URL 或伪装 local 配置。
6. 评分器最初把非法 JSON reference 和候选不一致混在一起。增加 INVALID_REFERENCE 与不可评分计数；下游不把它计为诊断答案错误。Agent 必需观察缺失时不生成完整的工具指标。
7. 旧 CLI 原本执行完目标才检查输出。在真实回环服务上，非空输出/已存在锁/写入失败/无效 SHA 的反例均在失败前产生 4 次请求；修复后均为 0。新/空目录仍可正常执行与导出；validate-only 不写文件。预检查锁会释放，因此没有宣称并发竞态完全消失。详见 `learning-grading-notes.md` 的追加记录。
8. 公开 writer API 的源码审查发现调用者可在 `WorkflowEvidence.source_files` 中构造路径穿越；CLI loader 已有限制但库接口不能依赖它。改为任何写入之前检查平面文件白名单；回归测试断言外部哨兵文件不变。未在真实用户目录执行危险复现。
9. 在最终自查中补齐 calibration/regressions 的显式私有选择、校准包重算验证，以及未处理的畸形文件/配置类型检查。只保存文件哈希不代替语义重建。
10. Ruff 指出长行、未使用导入和 async 测试中的路径解析；仅格式化/移动常量修正。最终全项目 lint 与严格 mypy 检查见下方最终记录，未通过忽略规则掩盖错误。

## 现有验证记录（集合重叠，不相加）

- 评分器新增 28 passed；连同复用 evaluator/agreement 测试 39 passed。
- OTLP adapter 61 passed，含 SDK 编码路径与保存投影重载约束。
- 组合评分/轨迹/来源/分析/CI 白名单：93 passed，11.58 秒。
- 故障恢复与当时 CLI 集合：12 passed，51.56 秒（后续又加入实际 recover/calibration 命令验证）。
- 旧 CLI 新增 17 passed / 2 Windows symlink 权限 skips；真实 junction 测试通过。
- 最终全量非集成：1401 passed / 3 skipped / 40 deselected，346.33 秒。3 个 skip 为 Windows 符号链接权限不足；40 个集成测试由本次选择条件排除，不是通过。
- 最终 Ruff format：686 files already formatted；Ruff check：All checks passed；严格 mypy：237 source files 无问题。原始日志在交付包 `checks/`，不能把前述重叠集合求和作测试总数。
- 本机实际执行持久化入口：1 skipped，原因 requires isolated migrated PostgreSQL。未发现可用 Docker/PostgreSQL 安装或已配置 WSL 发行版。该项未验收，不是绿色集成。
- 历史证据 manifest 复验通过，scorecard 仍为 portfolio READY_WITH_EXPLICIT_LIMITS / production NOT_VERIFIED / release NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED。没有改历史结论。

## 尚不能声称的内容

没有真人标签，没有付费模型 A/B，没有语义 judge 校准，没有 Phoenix/Langfuse 服务端联调，没有本轮真实数据库通过结果，没有新增远端 CI。SDK 兼容不是整个平台集成；本地重算不是服务器来源认证；大测试数量不是业务价值证明。

本轮实现的价值是提供可以真实操作的评测使用流程，以及防止重复花费、误判和证据丢失的工程约束。是否改变实际应用的上线决定，仍需要真实使用案例。交付后冻结功能，不默认继续扩展平台。

## 冻结代码后的实际操作验收

代码本地提交：`d0ced60cc64c19876fac10608b1c4cf54676e18c`，分支 `codex/evaluation-workflow-v1`。本轮全量回归的运行源码与该提交一致；随后只补交付说明，不修改运行代码或测试。历史 reliability 阶段的“12 文件待提交”是当时状态，现已随本次提交一并收口，并不代表仍有另一组未提交文件。

使用明确的该 CODE SHA 运行实际 CLI，所有以下命令退出 0：

| 操作 | 实际结果 | 不能据此声称 |
|---|---|---|
| Agent private demo + verify | 120 题 / 240 观察 / 0 缺失；原状态 DEMO_PASS；诊断重建通过 | 真实模型质量或生产 PASS |
| 导出 regressions | 全部 120 题保留，100 题有两臂诊断重点；candidate 新发现 0；题集 SHA256 `d6c10ec43c4f9194c3fc02ffaee2f7457adac0bf8510513761ac9134180d139b`，gold 未改 | 100 题都是 candidate 错误，或失败子集可代表总体 |
| 运行导出的完整配置 | 使用新 experiment ID，完整原题集执行，公开投影 DEMO_PASS | 通过反复跑选成绩；本轮没有做该选择 |
| 空白模板 calibrate + verify | 240 null / 0 paired；一致率与 kappa 为 null；HUMAN NOT_VERIFIED | 已完成人工标注或评分校准 |
| QA public demo | 只保存 manifest/result/report；PUBLIC_PROJECTION_ONLY | 公开摘要可重算私有原始观察 |

本轮新增讲解文件 `docs/evaluation-workflow-project-brief.md`，供用户理解架构、阅读演示和准备答辩。简历表述只引用可核验反例及测试，不补造生产吞吐、用户数或模型提升。

远端只读检查：`refs/heads/codex/evaluation-workflow-v1` 尚不存在。没有执行 push，没有新代码对应的远端 CI；本地绿色结果不替代远端 CI。交付状态为 **LOCAL_IMPLEMENTED_AND_DEMONSTRATED / EXTERNAL_VALIDATION_PENDING**。

## 标准轨迹端到端演示

补查发现原 Agent fixture 使用 `agent-baseline-000` 等非标准 trace ID，不能直接与 32 hex 的 OTLP 关联。没有修改历史 fixture 或原证据包。在交付演示目录生成派生副本，只替换 fixture `trace_id`、更新副本题集哈希与 experiment ID；逐值验证其他内容完全相同，包括 prompt/reference、预期工具与参数、预算、fixture 答案和门槛。policy 原始、复制、执行冻结哈希均为 `e2feb10ed831644f48b381bba044bfa1c4323c88492b1123519aaa55e244e60c`。

可复现 driver 使用锁定 SDK 产生 span，经标准 OTLP JSON 编码后，通过未修改的实际 `run --traces` 和 `verify` 命令。结果为 120 题、240/240 观察关联、480 个白名单投影 span、20 个合成 error span；两个 CLI 均退出 0。输入/输出、请求头、工具参数与错误消息中的隐私哨兵没有进入 projection/analysis。`REPORTED_TRACE_ONLY`、`UNPROVEN`、formal=false 保留。

这些 span 是合成 instrumentation，不是观察真实 Agent 内部行为；固定时间戳也不是性能测量。该演示证明开放协议序列化、实际观察关联、导出及离线重建路径，不能宣称 Phoenix/Langfuse 服务端已联调。driver、原始 OTLP、派生输入、完整 CLI stdout/stderr 与 summary 均随交付包 `demo/traced-fixture/` 保留；未将演示脚本混入已冻结运行代码。
