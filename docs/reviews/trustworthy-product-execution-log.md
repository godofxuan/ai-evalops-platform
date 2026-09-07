# 可信评测产品执行记录

## 2026-09-07 第六检查点：持久提交准备、总尝试预留与输入一致性

提交前重新执行产品、Run、evaluator 与 CLI 回归：180 passed / 1 Windows symlink skipped，59.60 秒。上一轮完整输出未留存，所以重新运行而非推测结果。全仓 lint、605 文件格式检查、211 文件 mypy 与 git diff --check 通过。真实数据库预算断言仍待本检查点精确 CI。

第五检查点 `52ab9c7d3eee524fce590fa11e6d327efb8bbeb1` 已推送，精确 [CI 34092870938](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34092870938) 的 quality-and-integration 与 compose-smoke 均 completed/success，包含新 deadline 数据库往返与迁移验证。本节是此后的新修改。

- 持久提交准备：新增严格 DurableExperimentRequest 和 prepare_durable_experiment，只准备、不写 Run/Job、不调用目标。接收同租户不可变 dataset version、原始 product JSON 的 SHA、两组 registry target_id/版本、policy 与尝试/时间额度。逐项复用原 mapper、LocalArtifactStore/RunService、产品评分标签预检与目标输入投影，在数据库写事务外完成。测试通过真实 mapper、文件存储与 RunService，仅替换数据库边界。
- 原始与规范化身份：原始 JSON 字节先验 SHA 校验，再映射 JSONL；两组准备的已授权 dataset hash 必须等于映射产物。篡改 prompt 并重算原始 SHA 仍因存量版本不匹配拒绝，未知 registry version 拒绝。来源 SHA 明确 CLIENT_DECLARED，server evalops SHA 是配置身份而非独立运行认证。原始字节不自动永久保留，这仍不是独立原始数据公开复核。
- 固定配置：使用独立 durable-experiment-input/1.0 快照，保留规范化 request、mapping 版本、两种数据摘要、组件配置摘要/版本与共同绝对 deadline，不伪装成 local snapshot。来源字段不允许 URL 用户信息、query 或 fragment。接口初版只允许 DEMO，不能通过 FORMAL 标签绕开来源资格。
- 总尝试预算：默认 max_total_attempts=20000，可声明 1–200000；每 Job 的最大尝试保持 1–10。两组所有 Jobs 的最大尝试数一次性求和，超总额拒绝。用既有每 Job 的 retry/reaper 上限执行，不新增第二计数/调度循环，不允许两组各领取一份总额度。保守预留不回收未使用额度，不代表实际消费、模型内部调用数或硬美元预算。
- 检查中纠正一个断言：集成用例有 4 Jobs，但 Run 默认 max_attempts=3，所以应预留 12 次而非 4 次；单元夹具 max_attempts=1 时才是 4。没有修改既有策略去迎合错误计数。数据库预算与完整快照 hash 断言待本检查点 CI。
- 嵌套可变性：frozen dataclass 不会冻结内部字典。构造后改单组 case 的反例原会先访问数据库；repository 现在在首次 await 前复制两组与 snapshot，并再次触发合同验证。预算注入与完整 snapshot hash 统一由同一函数生成，避免新增字段后沿用旧 hash。
- 解析一致性：spec、policy 和原始 dataset 原会接受重复 scope/bootstrap_seed/prompt 的最后一个值。3 个反例先失败，输入端复用严格 JSON 后通过；原始字节 hash 算法不变。聚合数字 1e999 原会解析为 Infinity 绕过常量检查，现也拒绝解析后非有限值。
- 定向验证：上述新准备入口 4 passed，连同持久合同 5 passed；此前产品/Run/evaluator/CLI 集合 176 passed / 1 symlink skipped。集合有重叠，不相加。当前 mypy 211 文件通过。测试函数一行过长导致 lint/格式检查失败，已使用格式器修复，未降低检查规则。

仍未开放公开实验提交入口：共享并发窗口、观测总量和最终 accepted-attempt 导出必须接好并验证后再开放。本准备函数是 S4 内部前置能力，不能当作 API→worker→报告 E2E 已完成。继续保留原计划的故障矩阵、最终双 SHA 与跨任务最终同步要求。

## 2026-09-07 第五检查点：类别诊断与持久截止时间

提交前受影响集合：281 passed / 1 Windows symlink skipped（51.67 秒），210 文件类型检查、603 文件格式与 lint 通过。测试覆盖产品/CLI、Run、worker、Job 与迁移。真实 PostgreSQL 新断言仍等待本检查点精确 CI，不能用定向单元测试替代。

第四检查点 `f5af8cfa88a3a44e5ecc6824d112ba98337435cb` 已推送，精确 [CI 34090774472](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34090774472) completed/success。以下是后续新改动，不由第四检查点 CI 代替验证。

- 类别诊断：按同一固定 category 分组，复用 build_metric_diagnostics，不复制评分公式。保留 policy 要求但没有题目的类别；样本不足标 SMALL_SAMPLE，无题标 MISSING_CATEGORY，逐指标有效配对不足列 undersampled_metrics。构造两类一升一降与缺费用反例，证明局部退化不会因总体混合而不可见。实际超时运行也保存全部类别分母和缺测提示。私有报告增加该区，公开 v1 golden 字节回归保持通过。该区 DESCRIPTIVE_ONLY，不增加新的显著性检验或 PASS。
- 持久时间预算决策：为原 Run 增加 nullable execution_deadline_at，用 0029 增量迁移，不回填旧 Run，不在 retry/claim 时重新计算期限。NewRun → ORM → ClaimedJob → 原 worker 传递同一时刻，双组 DTO 拒绝不同截止时间。不新增调度循环，尚未开放提交 API。
- 反例与效果：首次/第二次 attempt 在期限已过时原无此合同；加入检查后，在创建目标前产生不可重试 experiment_deadline_exceeded。慢调用跨越总期限原最终记录可重试 HTTP500；改为将单次 timeout 与总剩余时间取最小值，明确区分总预算耗尽与目标自身超时。调用返回后再检查期限，不接受已过期的返回值。采用 UTC 墙钟/合作式异步取消，不承诺撤销远端副作用、CPU 抢占或无时钟漂移。
- 兼容性：旧 Run 截止时间为 null，保持原 per-case timeout 与重试路径。未给全部既有任务强行添加截止时间。过期的排队任务仍需原 worker 领取后结束，不宣称在 worker 停机时自动即时终止。
- 验证：类别/runner/report 55 passed；worker/jobs/迁移/双组合同 72 passed；此前相关 runs/ORM 47 passed。集合重叠不相加。mypy 210 文件通过。新增真实 PostgreSQL 双组 deadline roundtrip 断言须等待第五检查点 CI；离线迁移 SQL 只证明生成的升级/回退语句，不是本机数据库演练。
- 外部只读核验：RAG 精确公开交付已完成摘要、775 服务行/87 CSV 聚合/2 组配对/800 检索行重算，详见 rag-runtime-delivery-readonly-verification-20260907.md。CSV 核验采用表格技能的只读源数据/分母/缺失值原则，不创建或改写表格。该结果不升级 EvalOps 的正式质量资格，也不冒充私有重放。

剩余共享预算：并发窗口、跨两组及重试的总调用额度和观测体积仍须实施/验收；只有共享截止时间基础不代表 R10/S4 已完成。继续推进持久提交、accepted-attempt 导出、真实 worker 故障 E2E 与最终双 SHA。

## 2026-09-07 第四检查点：固定输入与聚合解析边界

提交前验证：product_experiments 与产品 CLI/证据集合 132 passed、1 Windows symlink skipped（51.65 秒）；mypy 210 个文件、ruff check 和 600 文件格式检查通过。已把第三检查点精确 CI 和本节待推送内容、未完成项发给简历/教学/投递三个任务，请其思考资料改进，不改已投简历及链接；发送成功不等于对方已完成材料调整。

第三检查点 `28a2b9da9b97bdc0a1e5955069e6cf1b7230ccf5` 已推送，精确 [CI 34089484214](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34089484214) 的 quality-and-integration 和 compose-smoke 均 completed/success。本地提交前 161 passed / 1 Windows symlink skipped，598 文件格式与 208 文件类型检查通过；不与以前计数相加。

- 提交合同：同一 dataset ID/hash 不保证内部 DTO 携带同样题目。复现后增加同 actor、规范化 JSON 摘要相同的有序 cases、相同 evaluator 类型/版本/配置约束。不比较 Python 的宽松 bool/number 相等性。此合同仍不是已开放的提交 API。
- 快照反例：修改 policy 而不改摘要、重算摘要后换 dataset、未知 schema/字段、改 source/scope、直接删除完成结果快照，原导出均接受。逐步增加内容摘要、严格已知模型、数据集/来源/任务/范围交叉绑定；完成的 v2 必须有快照。v1 和尚未开始的 INPUT_REQUIRED 包不被误称具有此保证。
- 兼容修复：原公开隐私测试用任意 internal_url 字典替代快照，现在被正确拒绝。改为在合法 source_repository 中植入相同秘密标记，并同步模拟身份/摘要，保留原有答案、命令、内部 URL 不出现在公开包的断言；不是放宽验证器让错误夹具通过。
- 保证范围：原 spec/policy 字节未包含在本快照中，无法独立重算它们的原始字节 hash；配置内容 hash 可复核但不是签名或独立来源认证。没有伪造原文件，也没有用新代码重写旧证据。
- 聚合读取：重复 decision 字段即使 hash 正确也必须拒绝，反例先失败后通过。抽出共用 decode_evidence_json，拒绝重复字段、非有限常量和超过 64 层嵌套，产品 verifier 复用同一规则。聚合 reference 限 1 MiB、artifact 限 16 MiB，均最多读上限加一字节；1 MiB 空白填充反例已复现/修复。不是内存 RSS 或恶意文件系统并发替换的完整保证。
- RAG 通知其真实模型测量结束，本轮仅确认协调解除。其 runtime-service-contracts/1 和 runtime-delivery-evidence/1 不冒充 enterprise.agent-run/1.0，不把聚合数字拆成虚构逐题结果。仍不修改 RAG 仓库。

本节改动尚需独立提交/精确 CI，第三检查点 CI 不覆盖它们。剩余重点仍为持久提交/共享预算/结果导出与 worker 故障验收；不能因证据验证加固而宣布整个计划完成。

## 2026-09-07 第三检查点：控制接口、缺测诊断与兼容性

第二检查点 `90ff44a9562191e9f55024d73e395c278eb8be10` 已推送，其精确 [CI 34086968459](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34086968459) completed/success，包含真实 PostgreSQL 原子双 Run 幂等/回滚集成及 Compose smoke。这不能作为本节新修改的 CI 证明。

- 取消：在 GREEN 状态提取现有 cancel_run_in_session，不复制取消状态机；父实验取消按 Tenant → Experiment → 排序后的 Runs → Jobs 加锁，在同一事务取消两组，重复取消不增加父版本。它不会撤销已经发生的外部服务副作用。
- 控制入口：增加鉴权 GET /api/v1/experiments/{id} 与 POST /{id}/cancel。状态从两组 Run 派生，全部执行成功也只叫 READY_FOR_ASSESSMENT，不叫质量 PASS。未认证请求从原来的 404 复现到正确的 401；授权查询、跨租户 404 和双组取消验收已追加到真实数据库集成，待本检查点 CI。
- 早期拒绝：产品 evaluator 要求 product-v2 版本、规范化映射题目和显式评分标签。原本会创建 Jobs 的不合法数据集，以及会先访问数据的错误 evaluator 版本，均先写失败测试再修复。拒绝信息不回显私有题目。
- 证据配对：拒绝 arm 角色错误或两组同 case_id 却 prompt/category 不同的包，不能仅凭 hash 自洽认定配对有效。
- 缺测诊断：即使费用缺失阻止完整门禁，仍展示可用质量/延迟的配对覆盖、胜负/持平和平均差。全部标记 DESCRIPTIVE_ONLY，无显著性或正式结论。极大但有限费用的求和溢出先复现，再使用缩放后求和；未知费用仍不是零。
- 兼容性问题：给 HTML 增加诊断区会改变公开 v1 的确定性字节。提取已推送检查点的固定合成样本摘要并编写 golden 回归，先失败，再仅为私有报告增加诊断区。公开 v1 原渲染保留，不重写历史证据。
- 定向结果：产品/runs/evaluators/CLI 160 passed、1 Windows symlink skipped；随后公开渲染兼容性集合 10 passed；mypy 208 个文件通过。集合重叠，不相加。真实取消/隔离尚待精确 CI，Windows 无权限创建真实符号链接不记为通过。
- 资源协调：RAG 任务正在做真实服务配对性能测试，本轮不操作其仓库、不启动 GPU/Ollama 负载，完整数据库和并发验证使用远端 CI，本地只做定向回归。

尚未打通：鉴权实验提交与 CLI、共享实验预算、固定快照、从已接纳 attempt 导出结果、真实 worker/故障 E2E、最终双 SHA 收口。上述控制接口是中间能力，不是 S4/S5 完成声明。

## 2026-09-07 后续切片：精确 CI 与持久实验基础

第二检查点提交前：受影响集合 **252 passed, 1 symlink skipped in 33.81s**；随后补“产品 worker 不静默忽略评分覆盖参数”，反例先失败，限制配置为现有 max_attempts 后 evaluator/runs **37 passed**。全仓 lint、格式与 205 文件类型检查通过；0027→0028 的离线 SQL 成功生成并人工核对复合外键/幂等/RLS，未在本机执行 DDL。上述集合重叠，不相加。新数据库集成仍须等第二检查点精确 CI。

- 工作分支检查点已提交并推送：`8cbad06f32f9a0e010c35da7aa97e68b08007e2f`。精确 [CI 34085325610](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34085325610) 已 completed/success，包含完整 quality-and-integration 与 Compose smoke。该结果只覆盖该提交，不覆盖下面的未提交修改。main 仍为 `50af0603ff76615f3cf2c54fba3230e1cee7647f`。
- 证据继续收口：新增 64 层 JSON 解析前深度限制；新增 arm 与主结果的 dataset/source SHA 交叉验证。反例分别是深层 JSON 原本仅报未知 schema、两份文件彼此一致却与主身份冲突；修复后定向测试通过。
- 数据映射：map_product_dataset 复用 local 的 parse_product_dataset，原始 JSON 字节摘要与规范化 JSONL 摘要分别记录，mapping_version 固定。目标可读上下文只从 public_context 复制；原 case/标签保存在 evalops_product_case 私有评测元数据中。显式零工具字段保留，不把缺字段补成已提供。mapper 与 runner 44 项通过。
- 共用评分：从 HTTP provider 提取 normalize_product_observation，把 local 的评分入口命名为 score_product_case。worker 注册 product_qa_v2 / product_agent_v2 薄适配器调用同一实现，旧三个插件的 builtin-v1 不变。QA 来源 ID recall/precision、Agent 正确零工具拒绝得到回归；缺费用/缺观测不填零分或成功分。相关 evaluator/product 集合 90 项通过。它还不是从鉴权实验 API 到 worker 的 E2E 证明。
- 事务基础：GREEN 状态机械提取 insert_run_and_jobs，保留旧 create_or_replay 的事务所有权和冲突处理，runs 26 项通过。新增 NewProductExperiment 的同租户/同数据集前置合同，以及 product_experiments 控制表、租户复合外键、幂等唯一约束、RLS 和 0028 增量迁移，不回填旧 Run。新 repository 在一个 begin 中插入两组及父记录，只有指定幂等唯一冲突允许查询重放。
- 真实验收已编写并加入 CI：8 个并发重复提交只保留一对 Run/4 Jobs；不同请求冲突、跨租户查询隐藏；在第二组 ORM 插入边界注入错误，确认已处理过第一组后整体回滚，无新父记录或孤立 Run/Jobs。成功后仅删除测试专属租户对象；共享 blob 不盲删。当前本地仅 collection/类型检查与跳过，尚未获得这项新数据库测试的成功证据。
- 本地模型/既有迁移/输入合同集合为 50 passed / 1 integration skipped；类型检查随新模块为 205 source files。一次测试遗漏独立 basetemp，触发既有 pytest 临时垃圾目录 77 条权限清理警告；未手工删除那些目录，后续恢复独立 basetemp。

仍未完成：持久实验鉴权 API/CLI、共享全实验限额、取消/导出与固定快照、真正 worker E2E/进程故障、完整缺测与切片报告、最终双 SHA/两次精确 CI 收口。当前新增 repository 不能单独作为已发布产品入口宣传。

## 2026-09-07：恢复执行、证据读取与发布边界

提交前受影响集合复测：product_experiments、CLI/证据、runs、HTTP target 共 **188 passed, 1 skipped in 28.34s**；全仓 ruff check、585 文件格式检查通过；mypy app/scripts/integration/concurrency 的 201 文件通过。历史 scorecard 与 final evidence manifest 只读校验通过。下一步为工作分支阶段提交/推送与精确 CI；不是 S7 最终代码/文档双提交收口。

本地全量非集成检查点：**1020 passed, 1 skipped, 39 deselected in 367.17s**，JUnit 位于忽略目录 artifacts/trustworthy-v2-checkpoints/nonintegration-20260907.xml。运行期间另补报告状态颜色和 Run 准备入口，因此最终提交仍需受影响集合复测与精确远端 CI，不能把此数直接贴作最终 SHA 验收。

S4 前置切片：新增 SQLAlchemyRunService.prepare_run，复用现有租户 dataset 授权、registry target 限制、内容校验及快照构造，但不提交 Run/Job；create_run 继续拥有原有幂等检查、遥测和提交逻辑。先以数据库边界记录器验证“准备不持久写入”失败，再提取实现；runs 集合 26 passed，CI 范围 mypy 201 source files 通过。这只是双组共享事务的前置接口，不是持久实验已经落地。

报告状态切片：原 HTML 所有状态都使用成功色；5 个状态矩阵反例失败后，明确成功/失败/待定样式，未知状态按待定，报告集合 8 passed。不改变任何质量决策。

跨任务同步已发送至“优化简历内容与结构”“两个项目学习与面试答辩｜RAG + EvalOps”“秋招投递总控（找岗位+定制简历+台账）”，附完整本地记录路径与本轮能力/限制，明确未发布不能替换已投材料。简历任务已回复并记录到 FUTURE_RESUME_EVALOPS_RULES_20260902.md 第 10 节，保持 R11 不动，待精确代码/证据 SHA 与 CI 后再考虑 R12。

追加公开导出切片：秘密标记同时放入实验名称、答案、快照内部 URL 和命令文本，旧默认导出泄漏而失败。新默认 public 使用独立严格摘要模型，不透传自由文本或原始比较对象；private 显式保留完整包，旧完整性测试通过明确 private 模式继续验证，并未删除。公开材料绑定同次私有 result 字节 hash，但只获得 PUBLIC_PROJECTION_ONLY 保证。另一个反例在 HTML 追加秘密并更新 manifest 的 hash/size，原验证仍接受；现在要求 HTML 与受限摘要渲染完全一致。该公开报告版本的渲染需要随合同冻结维护，未来不能无版本地改变后声称旧包仍确定性一致。

检查点：发布前自校验后 CLI 为 28 passed / 1 skipped；首次公开分离后为 29 passed / 1 skipped；公开 HTML 反例修复后定向 3 passed。mypy app scripts 随新增模型为 182 source files。当前全量非集成测试正在运行，尚不能写通过。

本节更新前文阶段记录；旧记录中的“尚未完成”是当时状态，不作为当前进度判断。仍未提交或推送本轮实现，不将本地检查冒充远端 CI。

- 恢复原因：上次审批系统返回 refresh token revoked，命令未执行。此次普通沙箱仍初始化失败，但只读审批命令成功；随后按原授权恢复工作，没有绕过审批或改动凭据。
- JSON 歧义：构造重复 production_ready 字段，旧验证器按最后一个值覆盖并接受；使用 object_pairs_hook 拒绝重复字段后通过。此规则也应用于 result 和 arm JSON。
- 文件种类：原验证器接受任意额外文件。现在只接受本合同的 result.json、report.html、baseline.json、candidate.json；未来增加快照文件必须显式升级允许列表及测试。
- 读取限制：1 MiB + 1 的 manifest 原本在完整读入后才报告 JSON 不可读；改为最多读取上限 + 1 字节，准确报告尺寸超限。manifest 上限 1 MiB，单产物上限 256 MiB；这不是进程 RSS 的硬上限。
- 链接：实际 Windows 链接创建返回 1314，真实链接测试保留并跳过，不能计为通过。文件系统边界注入链接状态的反例先失败，增加链接/解析父路径检查后通过。此检查不声称抵抗同一目录恶意并发替换的所有 TOCTOU 攻击。
- 发布：磁盘边界模拟 report.html 写入失败，旧实现残留已发布 result.json。现在使用同文件系统临时 staging、独占导出锁、验证后 rename；失败时清理本次临时目录，不发布半包。已有非空输出不覆盖。仅允许移除空目标目录，非递归。进程被强杀可能留下锁或临时目录，尚需恢复流程与真实进程测试。
- 自校验：构造完成结果题数不一致，旧 writer 仍发布。新 writer 发布前调用 verifier。旧篡改测试使用“0 题 DEMO_PASS”假夹具，现改为合法 INPUT_REQUIRED，保留篡改 hash/size 拒绝断言。
- 检查点：在 staging 修改之前，产品与 CLI 集合为 **100 passed, 1 skipped in 18.11s**；mypy app scripts 为 **181 source files passed**。这些不是最终全量结果，后续检查另记，重叠测试不相加。

此前连续实施还已落地：QA 来源 ID recall/precision（不等于语义忠实度）；Agent 引用不适用而非补 1；qualification 与 non-regression 可配置且分别报告；类型敏感工具参数精确匹配；预期拒绝终态；固定 seed 的逐题平衡执行与事件时间记录；单 case 1 MiB、观测总量默认 64 MiB/最大 256 MiB；严格 aggregate v2 与有限保证的 legacy 分开，离线校验明确 NOT_RUN 在线核实。旧全量检查点 1008 passed / 39 deselected 不是这些最新修改后的最终证据。

剩余重点仍包括公开脱敏导出、严格输入快照绑定、切片与缺测覆盖率、持久实验接入 Run/Job、真实进程故障/租户集成、最终代码与证据双 SHA/CI，以及教学和简历任务同步。没有宣称全计划完成或 production-ready。

## 继续实施批次：退出合同、输入身份、Agent 边界与证据关联

本批沿用已批准方案与 tdd 技能，不创建新目标、不修改 main。由于输入快照与证据包直接关联，把相关完整性反例一并修复；这不代表跨过未完成的阶段验收，也不宣称 S2/S3 整体完成。

1. CLI 退出合同：新增公开 experiment_exit_code 的完整状态矩阵，初次因接口不存在失败；实现后所有已知状态按约定映射，未知状态/门禁返回 3。文件系统边界注入 KeyboardInterrupt 时，原 main 把中断传播出边界；补处理后安全返回 130。CLI 当时 16 项通过。中断测试证明的是命令边界合同，不冒充真实 worker 进程恢复。
2. 输入快照：反例要求同输入两次运行的快照相同、execution ID 不同，修改 policy seed 后内容身份不同；初次缺 input_snapshot 字段而失败。现在从实际读取的一份 spec/policy 字节计算摘要，并保存规范化配置和规则；dataset 使用已校验的精确 hash。没有在导出时重新读取文件。名称与本机文件路径不进入规范化内容身份；原文件摘要另存。相关 product/CLI 当时 65 项通过。
3. 零工具：原预检用空元组判断缺 allowlist，导致合法零预算/零调用输入失败。改为检查是否显式提供字段，零工具可执行；再加入缺 allowlist、预期越权工具、预期超预算的反例，后两项原本漏检，补一致性校验后通过。
4. 参数结构比较：两个反例显示 Python 把 True 与 1、嵌套 False 与 0 评为完全匹配。新规则显式区分 bool/number；1 和 1.0 按 JSON 数值等价处理；对象键顺序不影响结果，数组顺序影响结果。不是工具 JSON Schema 有效性验证，只是类型敏感的精确结构匹配。
5. 预算：恰好使用 1 次/限额 1 且报告 budget_exhausted=true，原本算违规。改成实际调用数超过上限才算违规，耗尽字段继续保留在原始观测。同步调整之前把“耗尽”当“超限”的断言，没有删除工具错误/终态保留断言。product 当时 59 项通过。
6. 证据包：先后复现完成包省略两组条目、重算 candidate 文件 hash 后来源 SHA 与 result 矛盾、重算 result hash 后题数谎报、结果自称 formal allowed、未知结果 schema。原校验都没有拒绝对应反例。现在按完成状态要求两组文件，逐内容比对 arm/result，核对题集/唯一性/计数/对比集合，并做严格结果模型与 manifest 版本校验。CLI/证据测试当时 21 项通过。

本批仍在实施和验证。上述测试集合重叠、不相加。快照尚需严格 schema/版本实现绑定与导出配套；尚未完成引用适用性、完整比较 policy、持久执行和真实集成。后续检查结果继续追加，不使用前批 914 单测数充当本批全量结果。

## 总状态

- 方案：`docs/plans/trustworthy-evaluation-product-execution-plan.md`（v2）。
- 用户已批准按方案实施；工作分支 `codex/trustworthy-evaluation-product-v2`。
- 起始代码/远端 main：`50af0603ff76615f3cf2c54fba3230e1cee7647f`。
- S0 已完成基线与合同选择；S1 核心修复已落地，仍有验收缺口；与预检/归一化直接相关的 R1/R5 前置防护已加入。S2–S7 未完成。T1–T4 不默认实施。
- 未修改 main、RAG、历史证据，未宣称正式质量或生产资格通过。

## S0 / 2026-09-05：基线与执行判断

修改前状态：只有本任务生成的方案与补充审查文档未跟踪，没有用户业务源码修改。远端 main 与审查 SHA 相同，目标实现分支不存在，因此从当前基线创建独立分支。

实际检查：Python 3.12.13；定向基线 `tests/unit/product_experiments tests/unit/scripts/test_product_experiment.py tests/unit/targets/test_http_rag.py tests/unit/jobs tests/unit/workers` 为 **139 passed in 1.72s**。证据校验命令执行，scorecard 返回 PROJECT_SCORECARD_VERIFIED，仍为 READY_WITH_EXPLICIT_LIMITS / NOT_VERIFIED / NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED。

环境问题：Docker 不在 PATH，常规 Docker Desktop CLI 路径也不存在。集成环境尚未就绪，不安装新软件、不借用其他项目数据库；先推进可独立验证的修复，再检查安全可用的隔离环境/分支 CI。此限制不能写成集成通过。

实施原则：使用 tdd 技能，一次只为一个公开行为写失败回归，再最小修复。接口和验收采用用户批准的方案，不重新发明模型、调度器或重试系统。

S0 合同决定：CLI 默认 automated，新增 formal 门禁；质量 FAIL=1，缺输入/正式待定=2，内部错误/导出失败=3，中断=130。新结果语义另有版本，不改写历史文件。HTTP 输入与评测标签隔离；执行 label/content/execution/attempt 身份分开。详细 R1–R13 行为清单与兼容/数据/故障约束见主方案第 2–8 节。

教学要点：基线测试通过只能说明既有断言满足；缺陷需要新的反例证明。独立分支保护发布入口，但不会自动证明新改动正确。

## S1-01：CLI 质量失败必须传递给调用方（定向通过）

原因：旧 CLI 对 DEMO_FAIL/AUTOMATED_FAIL 返回 0，自动化调用方无法正确阻断。

测试设计：复制公开 demo 到临时输入，将 candidate 答案全部改错并更新合法数据 hash；运行实际 Python 子进程，不 mock runner。期待 DEMO_FAIL、非零退出码，同时仍生成可读失败产物。

RED：真实子进程返回 0；GREEN：失败报告保留，退出 1。新增 formal 门禁后，demo 即使通过也退出 2。执行失败退出 3。随后补了顶层输入和导出异常回归，详见 S1-04；中断和穷尽状态映射尚未完成，不能把这条记录当成全部 CLI 合同完成。

## S1-02：网络输入、轨迹与失败分类（定向通过）

为什么修改：旧 metadata 选项会把参考答案等评测信息发给目标；HTTP Agent 丢失工具结果；网络失败被转换成质量错误。这些问题会污染分数而不一定让旧测试失败。

实际修改：只投影显式 public_context；通过公开 runner 的 HTTP client/resolver 边界注入做测试。保留平铺 Agent 字段，并新增既有 AgentRunArtifact/v1 的显式投影，校验题目/答案、事件标识、调用和结果配对，记录原始终态和内容 hash。缺少可评分轨迹返回 INSUFFICIENT_EVIDENCE；401/429/503 等基础设施错误记录安全原因码并返回 EXECUTION_FAILED，不制造空答案和工具质量分。

RED/GREEN：标签泄漏断言先失败后通过；映射测试先因缺少公开注入接口失败，补实现时误将参数插入结果构造，导致 Pydantic 多余字段错误，检查实际调用位置后修复；错误分类反例从 DEMO_FAIL 改为 EXECUTION_FAILED；缺轨迹从错误评分改为证据不足。日志不保留真实令牌或上游正文。

效果与限制：新结果/manifest 使用 2.0，旧版本仍可读取；只对明确公开上下文做投影，不声称能检测使用者主动放入 public_context 的秘密。没有伪造缺失参数；旧轨迹缺工具参数时仍不足以支持参数精确匹配。正式资格、费用缺失和严格证据包验证尚待后续阶段。

## S1-03：有界读取、执行窗口与身份（定向通过）

实际修改：HTTP 默认响应上限 2 MiB，可配置至 16 MiB；读取时限制字节数并保证关闭响应；请求 identity 编码并拒绝压缩响应，避免解压绕过限制；总 HTTP timeout 包含 DNS 和流读取。数据文件最多 10 MiB、2 至 10,000 题；执行采用固定消费者窗口而非一次创建全部题目任务。

RED/GREEN：流读取超限测试先被未支持配置拒绝，实现后稳定返回大小限制错误并关闭流；慢流测试原来触发测试外层 timeout，修复后触发目标 deadline；空/超大数据原来被接受或进入解析，修复后在校验边界拒绝。任务窗口测试原来观测到 121 个活跃任务，修复后满足测试上限，runner 定向 14 passed。这是资源边界证据，不是吞吐量或生产容量证明；仍保留 O(N) 的有界输入/结果存储。

身份：每次运行生成 execution UUID，再派生 arm/run/job/attempt 标识。同配置运行两次的 job ID 原来相同，新回归证明不同。尚未实现持久恢复，因此不宣称 local 路径具备恢复语义。

预检：新增 --validate-only；实际 CLI 验证 120 题/240 计划执行，不调用目标、不创建输出目录。随后统一预检与执行的输入准备，详见 S1-04；不能只凭 READY 推断正式试验可开始。

## S1-04：错误边界、共享预检和计算预算

逐步执行：

1. 写真实 CLI 非法 scope 反例。原行为退出 1，stderr 包含合成私有输入值及 traceback；改为固定 experiment_input_invalid、退出 2，反例通过。
2. 写真实导出路径冲突反例，输出位置是已有文件。原行为打印路径并退出 1；改为安全执行/导出原因码、退出 3，同时确认原文件内容未变。CLI 七项定向通过，不以此代替未测试的中断语义。
3. 在绿灯回归基础上抽取 `_prepare_experiment`，预检与实际运行共享 spec/dataset/policy 和 Agent 输入校验。相关 43 项通过。这样修改是为了避免“预检接受、执行拒绝”的双重校验漂移，不是另造框架。
4. 增加实验目标执行阶段 deadline。旧 spec 不支持该字段；实现后等待中的调用被取消，已完成 baseline 的 120 个观测保留，未完成题记录 experiment_deadline_exceeded，没有虚假对比。默认 3,600 秒，最大 86,400 秒。同步解析和统计仍依靠大小/工作量预算，不宣称 CPU 可被硬抢占。
5. 三个预检反例：spec 超过 1 MiB、policy 超过 1 MiB、bootstrap_resamples=1,000,000。原行为均接受；增加限量读取和题数×resamples 预算后全部拒绝，未实际执行巨量采样。上限是保守安全预算，不是性能测试得出的容量结论。

遇到的问题：总 deadline 回归最初设 20 ms，在并行完整回归期间，可能尚未进入目标就到期，导致“流已关闭”断言不成立。这不是取消代码失效。调整测试为 500 ms 启动裕量、外层 5 秒保险，目标仍永久等待，不放松取消、部分观测和失败原因断言，runner 27 项通过。

## 与 S1 共用边界的 R1/R5 防护（不代表 S2 已完成）

正式资格：新反例证明旧预检把 FORMAL fixture 标为 READY。当前 v1 spec 不含独立来源/协议材料合同，因此在执行前 fail closed：fixture 返回 FORMAL_FIXTURE_NOT_ELIGIBLE，HTTP 返回 FORMAL_PROVENANCE_CONTRACT_REQUIRED。缺凭据原因仍独立保留。尚未完成整个正式证据合同和执行后资格计算；不是把 FORMAL 功能改成已验收。

未知成本：最初构造的 usage 少了 output_tokens，被核心响应合同先拒绝；修正为有效 usage 后，确认旧实现确实把未知费用变成 0。v2 ProviderResult 改为可空成本，缺失返回 MISSING_COST_MEASUREMENT；旧数字统计适配器显式拒绝 None，不补零。原始观测保留，完整门禁证据不足。尚未完成部分指标单独展示、配对覆盖率、来源模型和 HTML 缺测展示，故 R5 仅部分完成。

非法成本：bool、负值、字符串、NaN 原先被当缺失；Infinity 导致笼统内部错误。五个反例先失败，加入有限、非负、非 bool 数值检查后，均返回 target_cost_invalid。非法 Agent 终态另有反例，原先 worker_internal_error，现为 target_agent_observation_invalid，产物不包含合成私有原值。

兼容性发现：初版投影把 QA 自定义 trace schema 误当 Agent schema，回归产生 120 个 schema 错误。现在把 task_type 显式传到 provider，仅 Agent 走 Agent artifact 投影；普通 QA 保留原有轨迹解释，定向通过。

安全补充验收：HTTP 字节阈值恰好等于限制时接受，多一个字节拒绝；压缩响应在读取/解压前拒绝并关闭；缺 public_context 的旧 metadata 配置在 DNS 前阻断。target 53 项通过，包含原有 SSRF/peer/redirect 回归。

## 当前验证与剩余工作

第一轮全量单元测试为 **900 passed in 296.97s**，第二轮为 **914 passed in 240.95s**，分别对应当时启动的检查点。第二轮启动后又补了 QA 兼容性与 HTTP 边界测试，因此最后额外运行整个相关集合：`tests/unit/product_experiments tests/unit/scripts/test_product_experiment.py tests/unit/targets/test_http_rag.py`，**108 passed in 13.09s**。各集合重叠，不相加；不能把 914 写成最后补丁后再次完成的全量结果。

最后静态检查：mypy 198 个文件通过；ruff check 通过；ruff format --check 显示 582 files already formatted；git diff --check 通过。新增投影模块最初的同名变量类型冲突已经修复。没有运行本轮真实数据库/worker 故障集成，也没有远端 CI 结果。

迁移与使用说明：`docs/product-experiment-v2-migration.md`，列出新参数、退出码、metadata 迁移、费用语义、资源限制和未完成功能。当前结果 JSON/HTML 仍当私有调试产物，不直接公开真实业务内容。

S1 尚在收口；S2–S7 未完成。未提交、未推送，未同步教学/简历任务。后续必须完成费用/指标/正式资格、严格证据、持久执行、真实集成与精确 CI，不能把本阶段结果替代最终验收。

下一实施切片：先补 S1 退出码穷尽/中断、输入快照/单题预算和响应来源/耗时合同；再按 S2 升级版本化指标与任务适用性，清除仍存在的 legacy 默认值和硬编码资格信息。不要先把当前分支标成发布完成。S3–S7 仍按主方案顺序执行，教学/简历同步在实际证据收口后进行。
