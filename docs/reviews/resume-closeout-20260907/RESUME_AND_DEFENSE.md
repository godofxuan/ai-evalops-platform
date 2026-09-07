# AI EvalOps Platform：简历与答辩定稿

使用资格以同目录 CLOSEOUT_RESULTS.md 和交付 FINAL_RECEIPT.json 为准；材料描述项目实现，不捏造实习、线上业务、用户规模或收入。正式 A/B、人评和生产验证均不能写成已完成。

## 150 字内项目总述

AI EvalOps Platform 是面向 QA、RAG 和工具调用 Agent 的多租户异步评测后端。它把同题双版本比较转为可幂等提交、可恢复的后台任务，并将结果绑定输入、代码与执行尝试，输出分层验证的质量报告。平台负责可靠执行和可信证据，不实现被测模型或检索器。

## 简历正文（最多三条）

- 实现 PostgreSQL 原子双组实验与租户内幂等提交，将固定题集、策略及目标版本绑定到父实验和两组 Run；同键重放返回原任务，同键异参与越权访问被拒绝。
- 构建基于 lease、heartbeat、reaper 和 accepted-attempt fencing 的异步任务恢复链路，处理进程失联及迟到结果；明确区分数据库结果只接受一次与外部 HTTP 可能重复调用。
- 实现不可变报告发布及公共/私有证据分层验证；修复超长答案后段聚合失败和 Agent 终态冲突导致错误完成评分的问题，保留失败题，并通过原始输入与持久结果快照重算私有报告。

这里没有“质量提升百分比”“高并发生产吞吐”“exactly-once 调用”等未经核验数字。若最终回执 durable 为 NOT_RUN，前两条改为“实现并建立对应回归，真实数据库验收待完成”，不得省略限制。

## 约 90 秒介绍

这个项目解决的不是如何做出一个更聪明的 Agent，而是如何可信地比较两个版本。一次性脚本很容易在进程退出后丢状态、失败题被漏算，或者把校验文件 hash 当成质量验证。我把评测拆成控制面、执行面和证据面：控制面固定数据与策略，一次事务创建父实验和两组任务，使用租户内幂等键；执行面由 Worker 领取带租约的 Job，心跳延长租约，失联后由 Reaper 回收，提交时检查 attempt 和版本，拒绝旧结果；证据面保存被接受的观测，从冻结快照生成不可变报告。公共包只公开允许字段，私有包结合原始数据离线重算。

本轮独立审核发现两个实际问题：超长答案先被接收，直到聚合才触发长度错误；Agent 的 failed 和 answer 两个终态相互矛盾，却能拿到完成分数。我把约束前移到共享规范化入口，非法响应转成不重试的执行失败，既不吞题，也不误报输入错误。现阶段证据来自确定性合成用例及真实数据库测试，不是正式模型 A/B、人评或生产上线。扩容负收益的历史结果也保留，没有为了简历改成通过。

## 8–10 分钟演示路线

1. 0:00–1:00：展示 README 和本轮回执的 CODE/DOC、CI 与范围；说明 EvalOps 与 RAG 是独立项目，RAG 只是可选被测对象。
2. 1:00–2:30：打开包内 QA/Agent 已固定的 SYNTHETIC_FIXTURE 报告，展示同题、固定 policy、原始/规范化摘要与三个独立状态。避免现场重跑挑最好结果。
3. 2:30–4:00：有合法注册目标时，按 DEMO_GUIDE 提交并保存真实 ID，关闭一次客户端，再以原 ID get，并同键重放；否则明确展示 NEEDS_REGISTERED_TARGET，改看真实 CI 的持久化主流程与客户端协议测试，不能冒充现场全链路。
4. 4:00–5:30：运行 observation_contract 回归或展示其原始日志；超长答案要看到 EXECUTION_FAILED 和保留题数，终态矛盾不能出现完成分数或 DEMO_PASS。
5. 5:30–7:00：展示 durable 私有报告带原始输入的 PRIVATE_RECOMPUTED，以及修改派生分数并重新 hash 仍被拒绝的测试；local 仅结构校验。
6. 7:00–8:30：展示 process_recovery 代码中 kill、真实租约等待、reaper、迟到提交拒绝和已完成题不重做的断言；解释客户端退出不是 Worker 故障。
7. 8:30–9:30：主动说明外部重复调用、费用未知、缺题、人评待办、来源声明和 NEGATIVE_SCALING，结束演示，不承诺下一轮大功能。

## 十个面试追问与代码依据

### 1. 双组原子性到底包住什么？

SQLAlchemyProductExperimentRepository.create_or_replay 在同一数据库事务创建父实验、两组 Run 与 Jobs，并处理唯一幂等键冲突。目标 HTTP 调用和对象存储写入不在该数据库原子事务里；输入 artifact 可能先写入，引用/回收有自己的规则。不能说 PostgreSQL 事务覆盖外部世界。
依据：app/product_experiments/persistence.py::create_or_replay；app/product_experiments/submission.py::prepare_durable_experiment。

### 2. 同键异参和跨租户如何区别？

幂等键只在租户范围定位父实验，再比较 canonical request hash。同租户同键同请求重放原 ID；同键异参冲突。另一个租户不能借 dataset_version_id 或实验 UUID 绕过授权，隐藏资源返回 404，不靠“UUID 难猜”隔离。
依据：app/product_experiments/service.py、persistence.py::find_by_key/create_or_replay；tests/integration/test_product_experiment_persistence.py::exercise_authenticated_submission。

### 3. Worker 被杀之后靠什么恢复？

领取持有 lease/owner/version，运行中心跳续期。Reaper 仅回收真正过期任务，新的 attempt 接管。SQLAlchemyResultCommitter.commit_success 在事务内验证当前拥有权和 attempt，旧 Worker 的迟到结果不能覆盖新结果。
依据：app/jobs/claiming.py；app/jobs/heartbeat.py；app/jobs/reaper.py；app/jobs/results.py::commit_success；tests/product_process_recovery.py。

### 4. 这是不是 exactly-once？

不是外部调用 exactly-once。HTTP 已成功但结果提交前崩溃，平台无法知道对方副作用是否发生，接管可能再次调用。内部 accepted attempt 防止重复接纳结果，外部需要目标自身支持幂等协议或可补偿语义；不能混为一谈。
依据：tests/product_process_recovery.py::exercise_product_process_recovery 的 after_http 分支；app/jobs/results.py。

### 5. 报告为何不会在重下载时变化？

SQLAlchemyProductResultReader 冻结终态 Jobs、attempt 与 accepted metrics；build_durable_report 使用原始数据和快照重建结果，不再次调用目标。发布仓库绑定快照/内容摘要，不可变导出读取已发布的精确字节；身份冲突报错，不悄悄更新。
依据：app/product_experiments/result_snapshot.py；durable_report.py::build_durable_report；report_persistence.py::publish；export_service.py::_read_published。

### 6. 文件 hash 都正确，还可能是假结果吗？

可以。hash 是内容摘要，不是来源认证。local 私有 verifier 检查文件集合、结构和已实现的绑定，未进行完整质量重算；公共包只有投影；durable 私有带真实原始输入才共享聚合器重算。就算复算一致，也不能独立证明目标确实来自声明源码。
依据：scripts/verify_product_experiment.py::main/verify_manifest；app/product_experiments/durable_verification.py::verify_durable_report；tests/unit/scripts/test_verification_scope.py。

### 7. 失败题、未知成本为什么不能补零或删掉？

删题会改变配对样本和门禁分母，补零成本会虚构优势。执行失败保存 case_id、arm、错误码；missing_fields 导致证据不足，不伪造测量。费用是目标报告的观测，平台的请求次数预算不是内部 token/账单硬上限。
依据：app/product_experiments/runner.py::normalize_product_observation/run_experiment；aggregation.py::aggregate_product_observations；measurements.py；app/evaluators/product.py。

### 8. Agent 的粗细两种终态怎么用？

answer 映射 completed；refusal/permission_denied/budget_exhausted 映射 blocked；partial/tool_error/agent_error 映射 failed。两字段同时存在必须一致。只给合法粗终态的旧输入仍有效，不凭空补细原因。预期为粗态就比较粗态，预期为细态就比较细态；缺粗终态为证据不足。
依据：app/product_experiments/observation_contract.py::validate_terminal_pair/terminal_matches_expected；agent_projection.py::project_agent_trace；evaluators.py::AgentTaskCompletionEvaluator。

### 9. local 和 durable 的执行顺序完全一样吗？

不是。local runner 用固定种子生成同题两组顺序并记录执行事件；durable 由队列、任务领取和并发调度决定实际时间顺序。两者共享评分与聚合语义，但不能据此把 durable 延迟当成严格随机对照的因果结论。
依据：app/product_experiments/runner.py::run_experiment；app/jobs/claiming.py；app/product_experiments/aggregation.py。

### 10. 为什么不继续加功能？怎样评价当前范围？

本轮是可信收口，不是模型训练或线上发布。F1/F2 修复避免错误接收/评分；F3 公开真实验证能力；F4/F5 让演示与证据可复查。CI 证明其精确源码下的测试，不证明真人评审、真实质量收益、无限规模或生产资格。历史 NEGATIVE_SCALING 仍成立。
依据：本目录 CLOSEOUT_RESULTS.md；docs/review/PROJECT_SCORECARD.json；.github/workflows/ci.yml；scripts/product_ci_evidence.py。

## 缺陷故事一：超长目标答案

触发：合法输入题的目标响应含 100001 个字符；旧 worker 可记 OBSERVED，直到后段 ProductCaseMeasurement 才拒绝，local CLI 误报 experiment_input_invalid。
根因：接受观测的 ProviderResult 和聚合模型长度约束不一致，fixture 的 Pydantic 异常也没有转成目标执行错误。
修复：共享 MAX_PRODUCT_ANSWER_CHARS=100000，from_target 在接收前做字符约束，安全地转为 target_answer_too_long、不重试；UTF-8 观测字节预算仍独立，合法的 100000 个多字节字符可能因字节预算另行拒绝。
测试：旧环境问题在 Python 3.12 锁定依赖下复现；99999/100000/100001 与多字节、QA/Agent、实际 CLI 和真实本地 HTTP、worker 到持久报告路径均有对应回归。实际执行层以最终回执为准。
局限：不是自动截断，不放宽 gold/输入上限；旧非法已存观测不会被改写，新代码拒绝作为有效证据并给安全错误码。

## 缺陷故事二：矛盾终态错误完成

触发：答案正确但 terminal_state=failed 与 source_terminal_state=answer 并存；旧共享评分优先使用细态，候选仍可得到完成分数和 DEMO_PASS。
根因：粗态、细态的合法性分别存在，没有统一映射一致性检查，artifact 与平铺响应之间也容易漂移。
修复：在共享合同、ProviderResult 和平铺投影前检查配对；artifact 投影复用同一映射，冲突/未知细态为 target_agent_terminal_invalid。完成评分显式按预期粒度比较，缺态不默认为完成。
测试：120 题完整 local gate 从错误 DEMO_PASS 变为保留失败题的 EXECUTION_FAILED；覆盖七种映射、artifact/flat、粗/细预期、旧粗态、缺失态、合法零工具与零预算、持久与私有复算路径。
局限：合同只校验报告语义一致性，不认证 Agent 的真实行为；保持原始历史字节，不能给旧错误通过重新盖章。
