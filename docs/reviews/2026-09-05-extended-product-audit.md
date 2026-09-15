# 第二轮定向审查：原七项以外值得做的改进

日期：2026-09-05。代码基线：`50af0603ff76615f3cf2c54fba3230e1cee7647f`。

性质：只读审查与方案补充；未修复业务代码，未提交、推送或修改其他项目。本报告不代表全仓安全审计、压力测试或真实模型评测。

已合并进唯一主计划：`docs/plans/trustworthy-evaluation-product-execution-plan.md`。原 R1–R7 编号不变；本轮新增 R8–R13，并补充 R5 的具体反例。部分措施在第一版方案中已有方向，本次增加真实证据、明确优先级与验收，避免重复实现。

## 方法和实际验证

检查了 product runner/evaluator/report、HTTP target、failure/retry 分类、dataset 限额、worker 总超时和现有 Agent artifact 模型。使用受限 mock HTTP、合成数据和临时目录进行复现。

本地探针：`artifacts/audit-20260905/extended_probe.py`（忽略目录，非产品实现）。

```powershell
.\.venv\Scripts\python.exe artifacts/audit-20260905/extended_probe.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/unit/product_experiments/test_runner.py tests/unit/product_experiments/test_evaluators.py tests/unit/targets/test_http_rag.py tests/unit/jobs/test_retry_policy.py
```

本轮回归结果：**67 passed in 0.45s**。未重新运行上一轮 108 项集合或全部 CI；两个集合有重叠，不能累加称为 175 项独立测试。

## R8 / P1：基础设施异常和被测质量失败混为一谈

位置：`app/product_experiments/runner.py:297`。

`except Exception` 将 provider 内所有异常转为空答案、tool_error=true、cost=0。没有把错误码、可重试性或失败阶段传递给产品结果。

复现：同一个 candidate case 分别抛出 TimeoutError 和 ValueError。两次都得到 DEMO_FAIL、task_success=0、tool_error_rate=1、cost=0、trace=null，结果中没有 error_code。

影响：用户无法分清网络超时、配置错误、程序 bug 与真实工具错误；后续重试也可能错误地重试质量失败。并非程序完全没有输出，也没有证明异常会被判为 PASS。

修复方向：复用 `app/jobs/retry_policy.py` 已有 failure 分类，为 product observation 保存安全错误码、阶段、是否重试和有效测量状态。不直接发布原始异常全文，不新建另一套重试器。

验收：timeout、HTTP 401/429/5xx、非法 JSON、配置错误、内部异常、有效差答案产生可区别的结果；原始异常中的合成秘密标记不出现在公开报告。

## R9 / P1（条件触发）：metadata 可把评测答案送给被测服务

位置：`app/targets/http_rag.py:144`，以及 product provider 将 case.metadata 原样传入 target 的路径。

复现：设置 include_metadata=true，metadata 中带有 fixture_profiles.baseline.answer 和 evaluation_only.reference_answer。mock HTTP 捕获的请求包含两个合成答案标记。

边界：默认 include_metadata=false，顶层 expected_answer 没被直接发送；本轮没有发生真实外发或证明历史评测被污染。这是开启 metadata 后缺乏输入/标签隔离的条件性问题。

影响：如果从 fixture 数据切到 HTTP，或者把评测标签放在 metadata，服务可能得到本不应看到的答案，评测失去独立性，也可能外发评测专用数据。

修复方向：显式分离 public task context、evaluation-only labels、fixture profiles；仅将经过允许字段/映射配置的任务输入发送。不能仅用字段名黑名单保证无泄漏。允许确实需要的任务上下文，但固定到请求映射版本。

验收：抓取实际构建的请求字节，证明 gold、期望工具调用、fixture profile 均未被发送；public_context 正常发送。对旧 include_metadata=true 配置给出明确迁移提示，不继续默默整包转发。

## R10 / P2：产品路径资源边界不完整

位置：`app/targets/http_rag.py:344`、`app/product_experiments/runner.py:207`、`:317`。

代码事实：HTTP 验证 peer 后使用 response.aread() 整体缓冲，没有显式 body 字节上限；product JSON dataset 一次读入且未复用核心 JSONL 限额；Semaphore 限制执行并发，但 gather 仍为所有 cases 创建待执行任务。

受限探针：一个 1 MiB 的合成流被完整缓冲且正常关闭。该测试不证明 1 MiB 本身过大，更不是内存耗尽试验；无显式上限的结论来自对应实现检查。

边界：核心 dataset 上传已有大小/题数上限，worker 外层已有总超时，不能说全平台没有保护。product local 路径未见同等总 deadline；HTTP 分阶段超时不能代替明确的整个 case deadline。本轮未进行慢速公网请求或压力攻击。

修复方向：增量读取并限制解压后响应大小，限制输入大小/题数/工具轨迹规模，以有界任务窗口执行，明确 case 与实验 deadline。初始限额是产品安全预算，不宣传为测得容量。

验收：阈值内通过、阈值+1 拒绝；无 Content-Length、chunked/压缩响应有界处理；客户端/流关闭；慢流在总 deadline 结束；待执行任务数由窗口限制而不是随输入线性增长。

## R11 / P2：新的执行和重复请求没有清楚区分身份

位置：`app/product_experiments/runner.py:166`。

复现：创建两个 provider，experiment_id 和 case_id 相同，prompt 改为不同内容。生成的 run_id、job_id、attempt_id 全部相同。

边界：这是 product local 的确定性 ID 设计，不能据此声称现有数据库主键或多租户 Run 已经串数据。也没有证明外部服务真的按 X-EvalOps-Job-ID 去重；只是这种使用方式会有混淆风险。

修复方向：区分可读 experiment label、固定内容身份、每次 execution_id、同次请求 idempotency key 与 attempt_id。明确恢复同一次执行和重新运行实验的操作；持久模式复用真实 Run/Job/attempt 身份。

验收：新执行/新输入的 ID 不复用；同次重复提交返回原记录；真正 retry 有新 attempt；按同次 execution 恢复不生成另一实验。

## R12 / P2：工具专项门禁只有绝对阈值，比较设计需更明确

位置：`app/product_experiments/runner.py:435`、`:451`、`:316`。

复现：120 个合成 Agent cases，baseline 工具参数全对，candidate 错 6 个，其余答复/成本/耗时满足现有规则。得到 baseline_mean=1.0、candidate_mean=0.95、paired_delta=-0.05、rule=candidate_mean>=0.95，专项 PASS，整体 DEMO_PASS。

解释：现有“最低质量达标”规则确实允许该结果，并不是违反了已经配置的配对退化阈值；问题是没有可配置的专项不退化约束，用户可能把 PASS 误读为不比 baseline 差。这里是参数匹配指标退步，不是证明模型整体真实质量下降。

另一个代码事实：baseline 全部完成后才执行 candidate。固定顺序可能混入冷启动、缓存、服务负载变化；本轮未测真实偏差大小，不把这一风险写成已证实性能退化。

修复方向：把绝对达标与配对不退化作为不同可选门禁，阈值纳入 policy；报告逐题胜/负/平、类别切片、有效样本数与缺失比例。建立固定 seed 的平衡执行顺序，记录缓存/重试/测量范围；后续有真实随机性研究时再考虑重复与分组统计。

验收：同一组 100%→95% 数据，资格模式可以准确显示“达标但退步”；不退化模式根据预注册容忍度失败/待证据，不能一律总 PASS。切片仅作诊断时明确不是事后挑出的新正式结论。

## R13 / P2：不能表达合法的零工具安全用例

位置：`app/product_experiments/runner.py:248`。

复现：Agent case 使用 allowed_tools=[]、max_tool_calls=0、expected_tool_calls=[]，结果没有工具调用。输入被 `not case.allowed_tools` 拒绝。

影响：“这道题不应调用任何工具”正是有用的权限/安全边界测试，当前入口不能表达。空 allowlist 和未提供 allowlist 不应混为一谈。

修复方向：允许显式空集合与零预算；检查期望工具是否与允许工具/预算一致。按任务预期区分正确拒绝、正确无工具回答和失败，不把所有 refusal 自动当好结果或坏结果。

验收：不调用工具正常通过相应策略检查；调用任一工具产生违规；要求禁止工具的矛盾样本在预检时拒绝。固定一组微型安全回归集，不扩展成完整红队产品。

## R5 补充：参数精确匹配有布尔/数字混淆

位置：`app/product_experiments/evaluators.py:119`–`:129`。

复现：期望参数 n=1，实际参数 n=true，tool_argument_validity=1.0。原因是 Python 对应结构相等比较会把 True 与 1 视为相等。

修复：按 JSON 值类型进行比较，至少严格区分 bool 与 number；数值 1 和 1.0 是否等价由显式规则决定。并区分参数精确匹配、schema 有效性与任务语义正确性，不用一个 validity 名称承诺三者。

## 没有发现的新漏洞与避免重复建设

- HTML 文本输出使用 html.escape；不能仅因报告展示答案就宣称存在 XSS。本轮没发现可执行注入复现。但 status 样式一律为绿色，FAIL 展示值得顺手修正。
- 默认 metadata 转发关闭，HTTP 有 HTTPS/public-IP/DNS pin/peer 检查。新的输入隔离和限额必须保留这些防护。
- 核心已有 failure 分类、dataset 限额、worker 总超时和低基数指标设计，优先复用而非重建。
- `app/agent_eval/schema.py` 已有 versioned AgentRunArtifact。第一版方案中的新 HTTP 合同应作为其受控适配层，或明确理由的精简投影；不要再造一套相互矛盾的终态/轨迹体系。
- `external_evidence.py` 的部分字段校验比 generic aggregate_contract 更严格，可抽取纯校验工具；不能把两个入口一概称为完全没有语义验证。

## 值得做，但不应变成新的阻塞项

1. 在同一 CLI 增加不调用服务的 validate/preflight，预先显示缺输入、题数、指标、请求字段与已知限制。
2. 报告给出“为什么未通过、失败样本、缺什么证据、下一步命令”，而不是主要依赖一大块内部 JSON。公开导出默认脱敏/聚合，详细原始数据留在受控本地模式。
3. 核心阶段之后，仅在有明确需求时增加结构化输出任务 pack、性能归因或生产运维验证。无须同时接满流行框架、搭建前端大屏或购买 LLM judge。

上述细节、排序、测试与停止条件已经纳入主执行方案。当前交付是补充审查和统一方案，不是实现完成。
