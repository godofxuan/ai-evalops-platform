# 从一次比较到可解释回归

本功能学习 Promptfoo 的声明式入口、DeepEval 的解释性评分接口，以及 Langfuse / Phoenix 的“调用—样本—实验”流程。实现使用现有 Python 3.12 锁定依赖，不需要安装这些完整平台，也不增加模型、数据库或 Agent 框架。

它解决三个问题：新用户怎么开始；一个低分为什么出现；发现的失败怎么变成下一次回归检查。它不宣称取代这些成熟产品，也不宣称从轨迹结构就能判断语义正确性。

## 先运行一次

在本轮功能工作树中，使用项目锁定环境：

```powershell
uv sync --locked --all-groups
uv run --no-sync python -m scripts.evaluation_workflow demo --task agent --output-dir artifacts/my-first-evaluation --include-private
uv run --no-sync python -m scripts.evaluation_workflow verify --bundle artifacts/my-first-evaluation
```

第一个命令执行仓库原有 120 题 Agent 演示，生成逐题对比、原因、盲审输入及回归重点。输入和目标响应为明确标记的 **DEMO fixtures**，没有调用真实模型。`demo --task qa` 可切换为既有 QA 演示。

`--include-private` 是显式选择：包中有题目和答案，不要上传真实业务数据。省略该参数时，只生成原有公开投影，不能把它当成完整诊断或重算证据。输出目录必须是新的；重跑请换目录，不能覆盖旧结果。

也可以生成独立配置后修改自己的目标配置：

```powershell
uv run --no-sync python -m scripts.evaluation_workflow init --task agent --output-dir artifacts/my-config
uv run --no-sync python -m scripts.evaluation_workflow run --spec artifacts/my-config/experiment.json --output-dir artifacts/my-run --include-private
```

`init` 复制原有演示题集和门槛，不降低门槛、不生成 gold。真实 HTTP 目标沿用现有 provider 协议、公网 HTTPS/DNS/peer 校验及凭据环境变量，不能把本地测试注入当作生产网络验证。目标调用可能产生费用，请先用原入口 `--validate-only` 检查配置和计划调用数。

## 如何读结果

| 文件 | 用途与边界 |
|---|---|
| `report.html` | 私有逐题诊断：输入、参考答案、两臂答案、评分原因和关联轨迹；无外部脚本或网络资源 |
| `analysis.json` | 所有原始题目的两臂状态；执行失败、缺失观察和未知成本不会消失 |
| `source/` | 原始私有证据和完整题集；local 使用冻结输入重算，durable 调用既有私有重算验证器 |
| `review-packet.json` | 隐藏 A/B、case ID 和机器分数的独立复核输入 |
| `reviews-template.json` | 未填写的标注行；null 不算完成或一致 |
| `regression-focus.json` | 根据两臂发现生成的重点清单；不是新的总体质量样本 |
| `manifest.json` | 文件哈希和私有边界；验证器还重建诊断/HTML/复核包，不只检查摘要 |

`LOCAL_RECOMPUTED_NOT_PROVENANCE` 表示能够从冻结配置、原题集和保存的观察重算，不表示目标真的来自某台服务器。`PRIVATE_RECOMPUTED` 沿用 durable 已接受 attempt 的重算语义，同样不等于外部来源认证。原质量状态原样保留；新诊断不会把原来 FAIL 或 INSUFFICIENT_EVIDENCE 改成 PASS。

“有发现”表示某个配置检查没有满足，可能是目标问题、数据问题或标准不适用，不等于已经证明根因。Agent 必需观察缺失时，不输出看似完整的工具指标。

## 两种评分怎么选择

- `normalized_exact_v1`：复用原有大小写/空白归一的答案匹配，适合封闭答案；同义改写可能被误拒绝。
- `json_structural_v1`：比较严格 JSON 结构，对象键顺序和排版不影响结果；重复键、非有限数字不被接受，布尔值不能冒充数字。使用 `--profile json_structural_v1` 显式选择。它仍然不理解业务语义。

参考答案不是合法 JSON 时，标为 `INVALID_REFERENCE`，不是候选系统答错。选择 JSON 诊断不会替换已冻结的精确匹配门禁；两者不一致是需要解释的信号，而不是自动改分理由。

接口通过代码注册，不从用户配置动态执行 Python 或加载任意插件。后续若接入语义 judge，必须另行固定模型/提示词/版本、控制费用，并与实际人工标签校准；本轮没有调用或验证语义 judge。

## 人工复核与校准

1. 将 `review-packet.json` 单独交给复核者；不要附上机器评分或盲化对应表。
2. 在模板副本中填写真实 `reviewer_id` 与 PASS / FAIL / UNSURE；没有看过就保留 null。
3. `HUMAN_DECLARED` 只是操作者声明，系统不能认证其身份；程序生成的演示标签必须写 `SYNTHETIC`。
4. 执行 `calibrate`，检查覆盖、误放行、误拒绝及分层一致率，不自动改门槛。

```powershell
uv run --no-sync python -m scripts.evaluation_workflow calibrate --bundle artifacts/my-first-evaluation --reviews artifacts/completed-reviews.json --output-dir artifacts/calibration --include-private
```

每个 item 只接受一条复核；过期 packet_hash、未知或重复 item 会被拒绝。本轮是“评分器与一条人工意见”的一致性，不是两位人工之间的一致性或正式盲审验收。缺失、UNSURE、null、不可评分参考都不计为一致；SYNTHETIC 与 HUMAN_DECLARED 分层显示，不能拿合成标签证明真人认可。

标注身份绑定内容及评分版本，而不是认证某一次执行或某位真人；相同内容可产生相同 item ID。校准包同样必须显式私有导出，使用 `verify --bundle artifacts/calibration` 可离线重算；不提供或不填写真实标签时，不能宣称已经完成评分校准。

诊断包当前最多 1,000 个观察项（完整两臂最多 500 题），单文本 256,000 UTF-8 字节，复核包最多 8,000,000 字节。这是可选诊断的预算，不改变原评测数据集支持范围。私有批量执行前检查可预知的数量限制；响应后才发现超限时保留源证据，不要求重调目标。

## 接入轨迹，不绑定某个 Agent 框架

```powershell
uv run --no-sync python -m scripts.evaluation_workflow analyze --bundle artifacts/existing-private-bundle --dataset path/to/original-cases.json --traces path/to/otlp-traces.json --output-dir artifacts/diagnosis --include-private
```

支持标准 OTLP JSON `resourceSpans/scopeSpans/spans` 的受限输入，识别 OpenInference span kind 和明确列出的 GenAI operation。实际 observation.trace_id 必须与轨迹精确匹配；同一 trace 被多个 case/arm 复用时标为关联歧义，不擅自归属。缺失父 span 保留 PARTIAL，缺轨迹保留 MISSING。

只投影 trace/span/parent ID、步骤类别、耗时和状态；不保存原 span name、prompt、answer、请求头、工具参数、status.message 或 resource 内容。原始轨迹哈希用于标识，原文未保存，因此离线验证只能验证投影和诊断重建，不能证明原轨迹来源。

兼容测试使用锁定的 OpenTelemetry SDK 产生真实 span，再经过 OTLP protobuf 编码器和 JSON 编码规范转换；不是 Phoenix/Langfuse 服务端联调，也不代表所有导出器或所有语义版本均兼容。详细限制见 `docs/reviews/trace-diagnostics-notes.md`。

## 从失败进入回归

```powershell
uv run --no-sync python -m scripts.evaluation_workflow regressions --bundle artifacts/my-first-evaluation --output-dir artifacts/regression-input --include-private
uv run --no-sync python -m scripts.evaluation_workflow run --spec artifacts/regression-input/experiment.json --output-dir artifacts/regression-run --include-private
```

导出完整原始题集（字节不变）和两臂问题重点，不修改答案，不只挑失败题评估，不把结果较好的重跑挑出来。local 导出可直接重跑的配置；durable 保留原注册目标和数据集版本合同，不能转换成臆造的 HTTP 地址。重复执行应使用新 experiment ID/幂等键，避免误读为旧执行重放。

这一步提供“复测入口”，不自动修改目标应用、模型或 prompt。真正证明价值仍需要一个实际应用改动、对应故障、修复和完整复测；本轮演示不能冒充业务 A/B。

## 出错后怎么办

先判断是否已经执行目标。`INPUT_REQUIRED` 是执行前阻止；`EXECUTED_ANALYSIS_BLOCKED` / `EXECUTED_EXPORT_BLOCKED` 表示已有结果但后续导出/诊断失败，应使用保留的源证据做离线恢复，不默认重新调用目标。磁盘完全不可写时无法保证落盘，会如实报告捕获失败。

`EXECUTED_ANALYSIS_BLOCKED` 的输出目录含 `source/`，可直接对它运行 `analyze`。`EXECUTED_EXPORT_BLOCKED` 返回 `recovery_path`；在故障排除后执行：

```powershell
uv run --no-sync python -m scripts.evaluation_workflow recover --bundle <recovery_path> --output-dir artifacts/recovered-source --include-private
uv run --no-sync python -m scripts.evaluation_workflow analyze --bundle artifacts/recovered-source --output-dir artifacts/recovered-analysis --include-private
```

PUBLIC 捕获不含原文，只能恢复公开摘要，不能用 `--include-private` 还原不存在的数据。恢复不会删除旧捕获，也不会请求目标。未完成的 `.evalops-run-*` 是故障现场，先确认恢复结果再由操作者清理。

本轮不更改 main，不自动部署或合并。完整数据库联调和远端 CI 的实际状态，以执行记录与最终交付记录为准；历史绿色 CI 不为未提交代码背书。
