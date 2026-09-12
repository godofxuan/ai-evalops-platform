# 公开基准实测：修改原因、问题、效果与验证记录

日期：2026-09-12。分支：`codex/public-benchmark-validation-v1`。代码基线：`89777062654773c737bb47c32d27a3340bbcfc1a`。

## 为什么做这一轮

用户希望得到真正能说明效果、可以解释给面试官听的指标，并要求优先使用自己的 Ollama。因此本轮没有购买 API、没有拉取新模型，也没有为了流行名词引入 Agent 框架。首先用 zoom-out 梳理既有业务执行、判分、bundle/离线重算模块，判断直接把 BFCL/RAGBench 塞进旧 gold 会混淆质量口径，最终新增隔离的 `app/public_benchmarks/` 与 CLI。本轮是学习并验证公开基准方法，不是修改原正式门槛。

## 逐阶段记录

| 阶段 | 做了什么，为什么 | 遇到的问题及处理 | 可见效果/边界 |
| --- | --- | --- | --- |
| 环境检查 | 读取本机 tags/show/version 与 GPU；复用 Python 3.12.13 锁定环境 | 30B 包约 18GB，8GB 显存不适合快速批量；同家族模型不能代表所有生态 | 选择现有 3B/4B/8B 三模型，完整 digest 进入 plan；未下载 |
| BFCL 来源 | 固定上游 SHA，保留原题、gold、checker 和 Apache 许可证；按类别固定哈希抽样 | 初稿 first-N 不符合预先计划，推理前改成固定 hash；旧预检文件保留 | 4 类各 25，共 100，不是完整官方榜单 |
| 官方 checker | 复用固定源码中实际 parser/checker 函数，并验证源字节 | 上游解析器的 BinOp/Lambda 路径包含 eval；先阻断可执行表达式，再在受限命名空间调用 | 真实上游案例和恶意表达式负例均测；不执行模型生成代码 |
| RAG 数据 | 固定 HF revision、保存 31 页原始公开 API JSON 与 receipt；每域 100 个不同问题 | 下载曾失败；FinQA/TechQA 同题有两种生成答案，简单去重会丢失来源 | 保留失败下载目录；先按独立于标签的 hash 固定一条答案，再按问题 hash 抽样，不按得分选题 |
| 判分准则 | 读官方 adherence rubric，输入只有 question/documents/answer | “有支撑”并非要求每个过渡句/常识都逐字出现在资料；错误准则会系统误判 | 推理前锁定允许正确常识、公式/数值推导、合适拒答的 prompt；不泄漏参考标签 |
| 请求冻结 | 固定完整模型 digest、seed、参数、顺序、单并发、模型模板、源哈希 | 长文本可能被运行时裁剪；无限扩大 context 会产生资源压力 | 预设保守 UTF-8 字节预算，超限不调用且保留分母；没有静默截断 |
| 实际调用 | 每次先写 intent，再访问固定 localhost Ollama，保存原始响应 | 调用中断时不能知道服务端是否已经完成 | 已有 intent 永不自动重发；保存 unknown/timeout/error 状态，不刷分 |
| 账本审计 | 用 TDD 针对重签名后的语义矛盾建立红→绿回归 | 仅有 SHA 校验不能拒绝“重新计算摘要的假成功” | 新增 called/response/status、context 数值、恢复前校验、remote inventory、HTTP status 合同约束 |
| 离线报告 | 从同一冻结计划、全部 intent/result 生成逐题和聚合，固定 seed 配对 bootstrap | 初版把严格可解析格式当成 BFCL 官方主分，错误惩罚合法不调用回答 | 保留旧报告，仅重算修正口径；最终主分为 88/82/90，不改模型回答或重跑 |
| 交付 | 新增入口、详细记录、简历稿、演示命令、源码+公开证据 ZIP | 历史 README/评分卡有冻结摘要，直接覆盖会破坏旧证据身份 | 新入口独立命名，原历史证据只读核验；新 CI、durable 集成未执行即 NOT_RUN |

## 冻结身份和参数

- BFCL selected cases SHA-256：`e95152b4eb86a2bc7b14b582af439a64b89e323a99ed85f1cf57b59b8f9f6446`。
- BFCL 实测 plan SHA-256：`b51515c92ad4a3cbe2f55917815a0d8f8b2a5121c37aee39442dfab42bccdceb`。
- RAG 300 cases SHA-256：`208141e7adf0b7e9b9e82fb498fe4c5819c46a964f73dd889f6298893948be2f`。
- RAG 实测 plan SHA-256：`6f37e937c6ee2240dd3298567fb8eab06448966d93432babd3a5fac3f0861108`。
- Ollama 0.34.0；temperature=0，seed=20260912，top_k=1，top_p=1，repeat_penalty=1，presence_penalty=0，num_predict=512；3.5/3 关闭 thinking，2.5 不传不支持的参数。
- BFCL num_ctx=8192、消息字节预算6144；RAG num_ctx=32768、消息字节预算30720。这是保守字节预检，不声称等于 tokenizer 的实际 token 数。
- 固定顺序 qwen2.5:3b → qwen3.5:4b → qwen3:8b；同题同输入、单并发。它是共同低随机配置，未分别调成各厂商最佳配置，不是最高能力榜单。

BFCL 共 300 次响应。RAG 共 174 次响应；每模型 TechQA DEV_Q096（31758 bytes）和 DEV_Q182（32612 bytes）预检超限，各保留 2 项，共 6 项。真实推理合计 474；计划合计 480。实际完成调用的响应都进入结果，未重新采样。RAG 174 条严格 JSON 均有效，但“格式全对”不意味着判断内容正确。

BFCL 原始请求前保留了当时实现文件哈希，RAG 进一步保存 implementation/ 字节快照。BFCL 此后发生输出统计修正和 runner 合同加固，不倒写原始 plan，不声称最终源码就是先前执行字节。最终 ZIP 的源码摘要负责标識交付代码，plan 摘要负责标识当时实验，两者分工不同。

## 实测结果及不确定性

BFCL 固定子集官方正确数：3B=88，4B=82，8B=90。各类（simple/multiple/parallel/irrelevance）分别为 23/23/22/20、24/23/20/15、24/24/21/21，每类分母 25。

官方 irrelevance 允许自然语言不调用；其 Python parse_failed 不能自动算任务错误。最终共 1/225 个需要调用的回答解析失败；非调用类另行按官方规则评分。严格格式接入统计 68/67/77 只用于诊断下游接入约束，不作为官方主分。安全预检拒绝数和 checker 异常数本轮均为 0，这也不是通用安全认证。

8B−4B 的子集差值 +8pp、探索性95%配对 bootstrap区间 [1,15]pp；8B−3B +2pp、区间 [-5.025,10]pp。4B−3B −6pp、区间 [-14,3]pp。固定 seed=20260912，按 case 配对、类别分层、重采样2000次，没有多重比较校正。不能写成“平台准确率提高8%”或普遍领先。

RAG 本地判分：与自动标签一致且分母包括未执行项，3B47/60、4B44/60、8B49/60；有效58项的一致率81.03%/75.86%/84.48%，balanced accuracy52.49%/76.64%/59.07%。3款都是49个正例、9个负例的相同有效集合。4B少误放行但多误拒绝。所有总计划一致率差的探索性配对区间跨零。负例只有9个，不能当作稳定人评校准。

公开既有预测的300题复评只是历史列重算，不是本轮运行 GPT、RAGAS 或 TruLens。各列原始覆盖300/300、298/300、298/300；总准确率要同时看类别平衡和覆盖，不能混分母选赢家。本地60题的既有列对照及每域结果另见 RAG 结果文档。

## 回归和问题留痕位置

证据根：`artifacts/public-benchmark-20260912/`。

- 六轮 TDD：`runner-regression/red-*.xml`、`green-*.xml`；红灯是期望暴露的问题，不是删除掉的失败。
- runner + 官方BFCL真实checker回归50项：`runner-regression/final-combined-50.xml`。
- 运行前 CLI/runner26项：`local-preflight-regression.xml`；来源和标签隔离 CLI3项：`cli-source-snapshot-regression.xml`。
- RAG及离线报告18项：`ragbench/report-unit-final-v2.log` 和 XML。
- 完整项目非集成回归：`full-unit.log`、`full-unit.xml`；最终准确数量见 `validation-summary.json`，不能把本节各组重叠测试相加。
- 静态检查与历史证据核验记录：`validation-summary.json` 和 `historical-*-verification.log`。
- 两份最终报告及离线核验：`bfcl-report-final/`、`ragbench-report-final/`。

MockTransport 单元测试覆盖真实 runner→文件→report→verify 控制流，但 transport 是测试替身；474条模型响应是另外的本地实测证据。两者不冒充 durable API/数据库验收。BFCL 部分测试依赖缓存的固定上游源，缺缓存的环境会明确 skip，不伪称正式 checker 已验收。

## 有价值的改进和停止边界

### 实际解压发现并修复的交付问题

首个ZIP完成CRC和逐文件SHA核验后，仍在新目录实际演示中失败。原因不是模型结果变化：根代理用Tee-Object把两份verify.log写到了严格报告目录内部。校验器只允许manifest列出的三个报告文件，所以它正确地报 `unexpected_report_files`。这说明“压缩包字节完整”不等于“交付流程可以执行”。

处理：不放宽校验器、不修改模型回答、不改报告摘要；只把本轮生成的两份日志移至证据根目录，保留首包及首轮解压失败日志 `delivery-v1-unexpected-report-files.log`。重新离线重算两份报告均通过，再生成独立 `_v2.zip` 并在另一个新目录重走解压演示。首包不是最终可用交付，最终包身份与解压结果以包旁 `DELIVERY_RECEIPT.json` 为准。此修复只改变日志布局和说明，没有改源码，因此完整代码回归的版本未发生变化。

项目新增了公开数据来源固定、官方评分接入、同题多模型真实运行、含失败分母的比较、判分器校准与离线复核。最有价值的发现是：新版本并不在所有任务领先，而只看准确率会掩盖偏向正类的判分器。这能展示实验设计、指标解释和工程证据能力。

这一轮不能证明服务吞吐/调度性能提升，也没有完成真实人类标注、正式业务A/B、完整Agent任务、原生tools协议、数据库持久化链路的新验收。τ-bench/AgentDojo未执行；新模型未下载；不部署、不推main、不修改RAG，不自动扩实验。

完成本轮本地回归、离线重算与交付后冻结功能。新提交和GitHub CI未发生，旧SHA的绿灯不覆盖这些新增代码；交付以源码和逐文件摘要为准。外部缺口明确保留，不为了“项目晋级”改写历史评分卡。
