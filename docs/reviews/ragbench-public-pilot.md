# RAGBench 公开评分器校准试点：来源、实现和实际复评

日期：2026-09-12。范围仅 `godofxuan/ai-evalops-platform`。本文件记录公开数据准备和已发布预测的离线复评；本地 Ollama 重新评分由本轮另一执行入口记录，不混为同一件事。

## 1. 为什么选择它

原有 120 题 QA / 120 题 Agent fixtures 检验软件机制，却不能说明评分器在外部数据上是否可靠。RAGBench 提供真实来源的问题、文档、已生成答案和句子级自动标注，适合评估“评测器是否会误判支持性”，而不是再次证明预设响应能通过自定义规则。

- 官方数据集：[galileo-ai/ragbench](https://huggingface.co/datasets/galileo-ai/ragbench/tree/97808f3e5fd16ede40bbff6c2949af8139b2eb7b)。冻结数据版本 `97808f3e5fd16ede40bbff6c2949af8139b2eb7b`。
- 数据卡声明许可 `cc-by-4.0`，保留来源署名；本项目不宣称重新许可各上游第三方原始语料。
- 官方项目：[rungalileo/ragbench](https://github.com/rungalileo/ragbench/tree/c28e6c22fc858086468eabb274250e27b5a8e9d8)。记录源码仓库身份 `c28e6c22fc858086468eabb274250e27b5a8e9d8`，不把其 README 当作已执行评测器代码。
- 方法：[RAGBench 论文 v1](https://arxiv.org/html/2407.11005v1)，尤其 3.2、3.3、5.3 和附录 9.4。本文采用固定阈值的描述性二分类指标；不是论文全量 AUROC 排行的复现。

## 2. 冻结的真实输入

没有使用医疗子集，没有训练、调参或调用付费 API。选择三个领域的官方 `test`：

| 子集 | 官方 test 行数 | 不同问题 ID | 本次问题数 | 作用 |
| --- | ---: | ---: | ---: | --- |
| hotpotqa | 390 | 390 | 100 | 通用知识、多跳信息 |
| finqa | 2294 | 1147 | 100 | 财报文本与数值推导；非投资建议 |
| techqa | 314 | 157 | 100 | 技术支持、长上下文 |

抽样首先在同一问题的不同生成模型响应中，按 `sha256(revision/domain/id/generation_model_name)` 升序固定选一条；然后按 `sha256(revision/domain/id)` 升序每域取 100 题。这样不把同题两种响应当成独立问题。不读取标签或预测决定取舍，不为了补齐预测替换样本。完整文档和答案保留，不静默裁剪。

最终原始问题有 300 个：`cases.json` SHA-256 为 `208141e7adf0b7e9b9e82fb498fe4c5819c46a964f73dd889f6298893948be2f`。正式可用目录是 `artifacts/public-benchmark-20260912/ragbench/pilot-v2/`，其中 `manifest.json`、`source/receipts.json` 和 31 份原始 API 响应记录数据来源。

锁定环境无 parquet/datasets 库，没有新增依赖。通过官方 Dataset Viewer `/rows` 接口下载所有指定 test 行；每页必须返回精确匹配的 `x-revision`，保存原始响应字节、URL、SHA-256、行数。离线读取再次校验版本记录、文件哈希、页码连续性、总行数和 `truncated_cells`。API 响应头是本次实际观察的上游版本声明，不是签名认证，也不是对 parquet 文件独立解码后的等价证明。

## 3. 标注不是人工答案

选中的 100 条 HotpotQA 标注模型字段是 `gpt-4o`，200 条 FinQA / TechQA 是 `gpt-4-turbo-2024-04-09`。保留逐题 `annotating_model_name` 和 `generation_model_name`，统一证据类型 `PUBLIC_AUTOMATED_ANNOTATION`；不把论文中的其他模型版本覆盖到实际数据。

论文附录 9.4 对支持性的定义允许正确的拒答、通用过渡/概括、正确的常识或数学公式以及数值推理，并非要求逐字复述文档。部分支持不能算完全支持。公开自动标注依然可能有错误；评测器与它一致不等于真人确认，也不直接等于“幻觉检测准确率”。

本次标签分布：FinQA 88 支持 / 12 不支持，HotpotQA 90 / 10，TechQA 62 / 38；总共 240 / 60。一个恒定输出“支持”的无用评分器也会得到 80% accuracy，因此必须同时报告平衡准确率、错误放行率和混淆矩阵。不能只挑一个看起来好的数字。

## 4. 已实际执行的官方既有预测离线复评

阈值在评分前固定为 `score >= 0.5`，没有在 test 标签上调阈值。比较的是数据集已经发布的预测列，不是今天重新调用 GPT-3.5、RAGAS 或 TruLens。

| 已发布预测列 | 实际覆盖 | 与自动标签一致率 | 平衡准确率 | 不支持样本被误判支持的比例 |
| --- | ---: | ---: | ---: | ---: |
| gpt3_adherence | 300/300 | 76.67% | 63.54% | 58.33% |
| ragas_faithfulness | 298/300 | 77.18% | 52.06% | 90.00% |
| trulens_groundedness | 298/300 | 51.34% | 62.64% | 18.64% |

这些列覆盖的样本不完全相同，不能据此排一个严格公平的同题排行榜；若要比较模型，需固定共同的样本集合并单列缺失。本报告保留各自全部 300 题分母和缺失量；空值不会被当作零分预测，也不会被宣称已经执行。完整逐域指标在 `published-predictions-report.json`。

解释：降低错误放行可能增加错误拒绝；TruLens 这一列在固定阈值下 false unsupported 为 134，不能仅凭错误放行较低称其全面更好。三列都只体现与公开自动标签的关系，不是评测平台的模型能力提升或生产门槛通过。

## 5. 实现、问题和结果

| 修改 | 原因 | 验证结果 |
| --- | --- | --- |
| `app/public_benchmarks/ragbench.py` | 源问题/生成响应身份、固定抽样、支持性校准 | 顺序或标签变化不影响选题；重复身份拒绝；空值与非法值单列 |
| `scripts/prepare_ragbench_pilot.py` | 可重放公开下载和离线复评 | 实际 31 页下载 / 300 题输出；已有目录拒绝覆盖 |
| `tests/unit/public_benchmarks/test_ragbench.py` | 防止缺值、漏页、篡改和重复问题制造虚假好成绩 | 12 项通过，含真实子进程 CLI，不只是构造内存对象 |

过程记录：

1. 第一条固定抽样测试先因模块不存在失败，再以最小实现通过。
2. 缺失/非法预测校准先因接口不存在失败，随后实现并复用项目已有 Cohen's kappa 计算。
3. Python 3.12 `urllib` 公网连接超时；未改代理、凭据或路由。Windows 系统网络的公开下载正常，因此在 artifacts 提供 `fetch-source.ps1`，下载后使用项目锁定 Python 离线处理。在线 Python 入口保留给网络可达环境。
4. 上游某页返回 502，首次下载不完整，保留 `source-download`；第二次在 `source-download-v2` 下载，最多重试三次并逐页检查版本。只重试获取同一公开输入，不重跑模型挑分。
5. 初始抽样器将问题 ID 误认为行唯一，实际数据检查正确拒绝；调查发现部分领域同题双模型响应。修正为先按模型身份哈希选一个响应，再按题 ID 哈希抽样；未查看模型试验表现才改规则。失败 `pilot` / `pilot-v1` 不作为有效数据包。
6. 数据冻结后才运行官方既有预测复评；固定阈值、空值和类别不平衡都保留。本轮12项回归和2个新增源码文件的 strict mypy / Ruff 通过，日志是 `artifacts/public-benchmark-20260912/ragbench/unit.log` 与 `unit.xml`。

## 6. 重现与本地模型输入边界

```powershell
uv run --no-sync python -m scripts.prepare_ragbench_pilot `
  --source-dir artifacts/public-benchmark-20260912/ragbench/pilot-v2/source `
  --output-dir artifacts/ragbench-replayed
```

该命令不会联系模型。源页/样本不变时重新输出的 `cases.json` 哈希不变。网络下载入口省略 `--source-dir`，但本机 Python 的网络限制需明确保留，不能写成已验证在线 Python 下载。

本地 Ollama 试点可以在每域这100题中再按同一 `sampling_hash` 取前20题，共60题。只把 `question`、`documents`、`response` 放入 judge 输入，不能提供公开标签、标注解释和其他评分器预测。

该60题的原始输入 UTF-8 字节（不含提示词包装）范围：HotpotQA 1002–3515，FinQA 1739–8574，TechQA 7683–30949。字节数不是 token 数；长输入需在模型执行前检测并保留 `CONTEXT_BLOCKED`，不能静默删文档或替换题。实际新模型调用数、结果、上下文限制和来源声明由本地模型试验清单单独记录。

没有改 gold、生产门槛、历史证据、依赖、main 或 RAG 仓库；这里的公开校准试点不等于整套 RAG 端到端效果验收。

## 7. 本轮真实本地模型账本的离线报告入口

后续实现 `app/public_benchmarks/pilot_report.py` 和 `scripts/report_local_public_benchmarks.py`。报告先调用既有 `verify_run` 校验真实 intent/result 账本，逐个计划请求读取结果；正在运行的账本拒绝生成静态报告，生成前后的文件哈希必须一致。导出只允许新目录，包含 `report.json`、`per-case.json`、`manifest.json`；`verify` 从原账本和固定评分器重算所有内容。重哈希篡改也不能通过。

```powershell
uv run --no-sync python -m scripts.report_local_public_benchmarks report `
  --run-dir artifacts/public-benchmark-20260912/bfcl-local-run `
  --bfcl-source-dir artifacts/public-benchmark-20260912/bfcl/upstream `
  --output-dir artifacts/bfcl-reported-again
uv run --no-sync python -m scripts.report_local_public_benchmarks verify `
  --run-dir artifacts/public-benchmark-20260912/bfcl-local-run `
  --bfcl-source-dir artifacts/public-benchmark-20260912/bfcl/upstream `
  --report-dir artifacts/bfcl-reported-again
```

RAGBench 报告省略 `--bfcl-source-dir`，使用实际 RAGBench ledger。只计符合冻结 JSON schema 的 `supported` 布尔预测。未尝试、结果未知、超限、失败和无效 JSON 都保留计划分母且 `correct=0`；另报有预测覆盖范围内的一致率，不能把这两种分母混起来。常数基线和已发布三列均使用该 ledger 固定的同题集合，不能把60题模型结果与300题公共列混比。

报告提供每模型及类别指标、记录到的 wall/load/token p50/p95，配对结果按 case_id 对齐、类别分层、固定种子 20260912 进行2000次bootstrap。三个两两比较为探索性、未多重校正，非总体因果提升。真实运行并未独占机器，字段 `measurement_isolation=OBSERVED_NON_ISOLATED`；不得据此称硬件公平提速、生产SLO或平台性能改善。电费和硬件成本未知，不写成零成本。

### 口径评审纠正：不能把接入格式冒充 BFCL 官方任务正确性

首次报告 `bfcl-report` 已保留为审查记录。它将严格可解析与官方有效两条件合并作为主分，评审指出这会把官方允许的自然语言拒答误称为任务错误。新增真实固定官方检查器回归先重现此偏差，再修正主指标为 `official_valid`；原始模型响应、官方评分函数、gold 和模型调用全部不变。

当前有效 `bfcl-report-final` 在300个已完成真实请求上重算、导出并验证：qwen2.5:3b 官方88/100、qwen3.5:4b 官方82/100、qwen3:8b 官方90/100。严格可解析接入分别68/100、67/100、77/100，明确是输出格式/接入约束，不是另一个官方质量榜。

官方主指标配对区间：4b−3b 为−6个百分点，95%区间[−14,+3]；8b−3b 为+2个百分点，区间[−5.025,+10]；8b−4b 为+8个百分点，区间[+1,+15]。这些是固定100题、同一模型家族的小样本探索，不能声称“8b全面优于3b”，更不能当成平台质量提升。

报告测试覆盖实际 `execute_plan` 持久化后分析、真实BFCL检查器、空/未知调用、无效判断、分层配对统计、实际CLI、禁止覆盖和重哈希篡改。HTTP目标在单元回归中明确使用边界测试桩，不计入真实模型成绩；`bfcl-report-final` 则独立读取本轮已完成真实账本。没有重跑模型来改善报告数字。
