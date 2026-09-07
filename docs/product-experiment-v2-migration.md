# 产品实验 v2：当前实现与迁移说明

这是 `codex/trustworthy-evaluation-product-v2` 的阶段说明，不是完整方案的发布公告。主方案仍以 `docs/plans/trustworthy-evaluation-product-execution-plan.md` 为准；持久实验接入、完整指标升级和严格证据包收口尚未完成。

## 先检查输入

新实验的共享领取窗口通过 0031 迁移接入既有调度器：max_active_jobs（默认 4，1–64）统计两组的 RUNNING/CANCELLING Jobs，重试不另领一份额度。旧 Run 不回填；满额时不生成 attempt。它是数据库 active-claim 上限，不是失联外部调用的物理并发保证。该改动须等待本检查点精确 CI，公开持久提交入口仍未开放。

持久结果新增 0030 迁移：新成功结果直接关联 accepted_attempt_id，并通过复合外键绑定同一个 Job；旧结果保持 null，不猜测回填。提交同时检查 claim/Job/attempt 的尝试序号一致。它为后续只导出有效结果提供身份依据，但尚不代表完整 durable 导出已经开放。

```console
python -m scripts.run_product_experiment --spec benchmarks/product_demo_v1/experiment.json --validate-only
```

该命令共享运行入口的本地输入校验，不执行目标、不创建 Run 或输出目录。READY 只表示目前已实施的本地预检通过，不代表远端可连接、正式资格或生产资格通过。当前 v1 spec 没有独立验证来源材料的输入合同，因此 FORMAL 返回 INPUT_REQUIRED；fixture 返回 FORMAL_FIXTURE_NOT_ELIGIBLE，HTTP 返回 FORMAL_PROVENANCE_CONTRACT_REQUIRED。仅换标签或传输方式不能解除限制。

## 执行与退出码

```console
python -m scripts.run_product_experiment --spec benchmarks/product_demo_v1/experiment.json --output-dir artifacts/product-experiment-v2
```

| 自动门禁结果 | 退出码 |
| --- | --- |
| DEMO_PASS 或自动通过 | 0 |
| DEMO_FAIL / AUTOMATED_FAIL | 1 |
| 输入错误、缺输入、测量不足 | 2 |
| 执行失败、内部或导出异常 | 3 |

`--gate formal` 对演示/待人审结果返回 2，对已确定的质量失败仍返回 1。CLI 不打印 Pydantic 输入值或原始异常全文；库调用方仍应在受控环境处理异常。KeyboardInterrupt 在命令边界返回 130；该回归不等于真实 worker 崩溃恢复验证。

## HTTP 输入隔离

默认 `include_metadata=false`，只发送题目。若开启，必须将明确允许目标读取的上下文放在 `metadata.public_context` 对象中：

```json
{
  "public_context": {"locale": "zh-CN"},
  "fixture_profiles": {"candidate": {"answer": "仅评测端使用"}}
}
```

发给目标的 metadata 只有 public_context 内的内容。没有这个显式对象的旧整包转发配置会被拒绝；请迁移，不要把参考答案、标签或凭据放入 public_context。此机制是允许列表分区，不是任意秘密检测器。

## Agent 响应与缺测

支持旧平铺观测字段，以及已有 `agent-run-artifact/v1` 的受限投影。平铺 Agent 观测需要显式给出 `tool_calls`（可为空）、`tool_error`、`terminal_state` 和 `budget_exhausted`。工具调用状态缺失不是成功。

既有 artifact 投影保留原始终态和 artifact hash；调用/结果需要明确 step ID、工具名和唯一对应结果。参数缺失或结果配对歧义会产生证据不足，不补造参数。目标自报 artifact/hash 不等于独立来源认证。

HTTP 错误、超时、无效响应进入 execution_errors，不转换成差答案或工具质量分。有效的工具错误仍是可评分观测。原始观测保存在执行结果的 observations 中；只有显式 private 导出才写入完整材料，该模式禁止直接公开真实业务内容。

## 费用与版本

新结果为 `evalops.experiment-result/2.0`，manifest 为 2.0。现有 v1 文件不改写，也不因为能读取而获得新语义认证。严格包完整性校验仍待后续完成，当前 verifier 通过不代表完整新合同通过。

目标未报告费用时为 null，不是零；仅有 token 数且没有固定适用价格表，也仍是未知。当前完整成本门禁在缺测时返回 INSUFFICIENT_EVIDENCE，不将缺失补成 0 送入旧统计。显式非负有限数值才可作为报告费用；bool、字符串、负数、NaN 和 Infinity 为响应错误。自报美元费用仍不是独立账单核验。

## 安全预算与身份

| 边界 | 当前值/行为 |
| --- | --- |
| spec / policy 文件 | 各最多 1 MiB，限量读取 |
| dataset | 最多 10 MiB，2–10,000 题 |
| bootstrap | 最多 10,000 resamples，题数 × resamples 不超过 2,000,000 |
| HTTP 响应 | 默认 2 MiB，可设 max_response_bytes，最大 16 MiB |
| 压缩响应 | 请求 identity；拒绝压缩响应，不支持自动解压 |
| 单 HTTP 调用 | timeout_seconds 覆盖 DNS、连接和流读取 |
| 实验目标执行阶段 | execution_timeout_seconds 默认 3,600 秒，最大 86,400 秒 |
| 待执行任务 | 固定消费者窗口，最多 max_concurrency（1–64） |

这些是安全预算，不是实测容量或硬美元预算。实验执行超时会取消等待任务、保留已收到的观测，并为未完成题记录原因；它不表示外部服务已经撤销产生的副作用。同步解析/统计依赖输入和计算预算限制，不宣称拥有可抢占的 CPU 硬 deadline。

每次 local 运行都有新 execution UUID；run/job/attempt 标识由本次执行派生。相同名称重新运行不会复用旧身份。local 尚无持久恢复/重试；HTTP 头部标识本身也不保证目标服务实现幂等。

## 尚未完成的内容

持久提交准备函数 prepare_durable_experiment 已接好原始 JSON→规范化 dataset 的身份核对、两组 registry 配置、同 policy、共同绝对 deadline 和总 attempt 预留。它只读准备两组 NewRun，不持久写入，不是新公开 POST API。请求合同仅支持 DEMO，source SHA 标为 CLIENT_DECLARED。原始 JSON 字节不会因准备过程自动永久留存。

总预算按 sum(每组题数 × 每 Job max_attempts) 保守预分配，默认最大 20000 次，可声明 1–200000 次；并非两组各得到一份。它约束既有平台 target attempt 上限，不计费、不控制目标内部模型调用，也尚未完成共享并发和观测体积限制。

持久化基础已增加 product_experiments 表及 0028 迁移，两组现有 Run/Job 与父记录原子创建。阶段性控制接口为鉴权 GET /api/v1/experiments/{id} 和 POST /api/v1/experiments/{id}/cancel；跨租户对象按不存在处理。取消共用旧 Run 状态机，不保证撤销目标服务副作用。两组执行成功仅为 READY_FOR_ASSESSMENT，不能解释为质量通过。目前还没有公开实验提交/结果导出入口，不建议绕过服务手工组装数据库对象。

worker 新插件 product_qa_v2 / product_agent_v2 要求 evaluator_version=product-v2；数据须由 map_product_dataset 映射并保留私有 evalops_product_case。原始 JSON SHA 与规范化 JSONL SHA 含义不同，不能互换。缺少评分标签或映射不一致时在创建任务前拒绝。旧插件版本语义不变。

私有报告新增 metric_diagnostics：按指标展示有效配对与缺失数量、胜负/持平、平均 candidate-minus-baseline 差；该区只有 DESCRIPTIVE_ONLY 保证。缺失费用时其他已测指标仍可查看，但完整门禁不会获得 PASS。公开 v1 HTML 渲染冻结维持历史复核兼容，暂不包含新诊断区。

category_diagnostics 按类别给出同样的诊断，显式列出必需但缺失的类别、小样本类别和逐指标有效配对不足。描述性最低题数来自固定 policy，不等于统计显著性；类别文字只进受控私有报告。

0029 迁移为 Run 增加可选绝对 execution_deadline_at，原 worker 从 claim 读取它，两组必须相同，重试不延长期限。null 保留旧行为。总期限耗尽为不可重试执行失败，和可重试的目标单次超时区分。仍没有完成持久入口的共享并发/调用量/观测量预算，不应把本阶段字段当成完整预算产品 API。

严格快照绑定、持久 Run/Job 接入、真实故障恢复验收、最终精确 SHA/CI 和教学/简历任务同步仍未完成。公开/私有导出的基本分离已实现，真实进程中断恢复等验收仍待完成。

快照校验已推进：完成的 v2 私有包须有已知版本输入快照，规范化配置与 policy 的内容摘要必须匹配，并与主结果的 dataset、两组来源、scope 和 task_type 交叉一致。它不证明原 spec/policy 字节已公开，也不证明服务端运行代码已独立认证。旧 v1 不自动升级保证。

聚合证据读取现在要求无重复字段、无 NaN/Infinity 常量、JSON 深度不超过 64；reference 最大 1 MiB、聚合 artifact 最大 16 MiB。超限时应减小聚合合同，而不是塞入逐题私有内容。聚合校验仍保留离线 NOT_RUN 在线核验状态。

## 新增的比较与证据行为

QA 分别报告来源 ID recall 与 precision；不能把它们解释为答案语义忠实度。Agent 的引用指标为不适用。工具参数使用类型敏感结构匹配（true 不等于 1，1 与 1.0 数值等价）；显式空 allowlist 和零预算合法。expected_terminal_state 可指定正确拒绝，耗尽预算不自动算超限。

agent_comparison_policy 支持 qualification、non_regression 或 both，分别记录绝对达标和退化结论。order_seed 固定逐题平衡的两组先后顺序，execution_schedule 与 execution_events 保存安排和实际时间；不声称控制了服务端缓存。每个 case 最大 1 MiB；max_observation_bytes 默认 64 MiB，最大 256 MiB，超过后停止新增调用并保留已有观测，不伪造质量评分。

证据导出使用临时 staging，先验证再发布，不覆盖已有非空目录。manifest 拒绝重复 JSON 字段、额外未知文件和符号链接，并限制读取大小。强杀留下的锁及完整快照合同仍待收口，因此当前 verifier 通过不是最终发布资格。

## 默认公开摘要与受控私有导出

CLI 和 write_product_artifacts 默认 export_mode=public。公开产物采用独立的 evalops.public-experiment-summary/1.0 合同，只包含受限状态、计数、执行 UUID 与摘要身份，不包含逐题题目、答案、工具参数、内部 URL、原始命令或原实验名称。名称转为 SHA-256 标识；这不是数学意义的匿名化，已知值的 hash 仍可被猜测关联。

```console
python -m scripts.run_product_experiment --spec benchmarks/product_demo_v1/experiment.json --output-dir artifacts/private-debug --export-mode private
```

private 显式保留原完整 result、两组逐题材料和报告。公开摘要保存 private_result_sha256，但不会把私有材料自动永久存储；需要复核时应在受控环境保存同次执行的 private 导出，不可重新运行冒充同一次材料。当前公开摘要校验范围为 PUBLIC_PROJECTION_ONLY，不证明审核者已访问原始证据，也不证明质量提升。公开 HTML 必须由受限摘要确定性生成，重算文件 hash 也不能夹带额外文字。
