# 公开基准 × 本地 Ollama：2026-09-12 实测入口

> 本文保留首轮三款Qwen的历史结果和v2包说明。最新Gemma跨家族续测、四模型结果、新包恢复方法与版本边界见 [GEMMA_CROSS_FAMILY.md](GEMMA_CROSS_FAMILY.md)。下文“未下载、未提交、CI未运行”均指首轮v2交付时的状态，不代表后续状态。

本轮把“能运行评测”推进到“可以对公开题目产生逐题、可离线重算的模型比较”。它仍是**本地研究试验**，不是完整官方榜单、正式业务 A/B、人工验收或生产上线证明。

## 本轮结论

全部使用已安装的 Ollama 模型，没有下载新模型或调用付费 API。480 个计划请求中，474 次真实推理取得响应；6 项因同一预设长度规则未调用，完整保留。没有失败重试、选最好成绩、改 gold 或删样本。

| 模型 | BFCL 固定 100 题官方 AST 判分 | RAGBench 有效判分覆盖 | RAG 判分 balanced accuracy | 负例误放行 |
| --- | ---: | ---: | ---: | ---: |
| qwen2.5:3b | 88/100 | 58/60 | 52.49% | 8/9 |
| qwen3.5:4b | 82/100 | 58/60 | 76.64% | 2/9 |
| qwen3:8b | 90/100 | 58/60 | 59.07% | 7/9 |

两列“质量”测的是不同对象：BFCL 是模型生成函数调用表达式的正确性；RAGBench 是模型判断别人答案是否有资料支撑，与公开**自动标注**的一致性，不是新生成 RAG 答案的准确率。后者所有模型各有相同 2 个超长正例未执行，balanced accuracy 仅在 58 个有效预测上计算，并不抹除总计划分母。

RAG 本地 60 题中有 51 个正例、9 个负例。“永远回答有支撑”也能取得 85% 总准确率；3 款模型总计划一致率分别为 78.33%、73.33%、81.67%。因此不能凭看起来不低的准确率声称 judge 可靠。4B 误放行较少，但误拒绝为 12/49，高于另两款的 3/49、2/49；也不是全面胜出。

详细结果：[执行记录](docs/reviews/public-benchmark-execution-20260912.md)、[RAG 判分结果](docs/reviews/ragbench-local-results-20260912.md)、[简历及答辩稿](docs/public-benchmark-resume-notes.md)、[模型选择](docs/reviews/local-model-selection-20260912.md)。

## 数据、代码与交付身份

- 代码基线：`89777062654773c737bb47c32d27a3340bbcfc1a`。
- 本地新增分支：`codex/public-benchmark-validation-v1`。本轮没有新提交或推送，因此没有“新代码 SHA 的 CI 通过”；状态为 **NOT_RUN**。
- 新增代码和文档以交付 ZIP 的 `DELIVERY_MANIFEST.json` 逐文件 SHA-256 标识；基线提交号不能冒充新增代码身份。
- BFCL 上游：`f7cf7359b7ac615a0b294831c5ba2bc95ee4a000`；Python 单轮 simple/multiple/parallel/irrelevance 各固定哈希选 25 题。
- RAGBench 数据 revision：`97808f3e5fd16ede40bbff6c2949af8139b2eb7b`；3 个域各 100 个不同问题进行公开既有预测复评，其中各 20 题参加本地 judge。
- 权重完整 digest、Ollama 版本、请求、原始输出、全部计划及失败状态均在证据目录。BFCL 实测计划保存了执行源码哈希；RAG 实测计划进一步保存执行源码快照。最终报告器/验收加固版本可能晚于 BFCL 原始调用，不能将最终代码反标为当时的推理实现。
- 本轮不改 main、原工作区未提交修改、RAG 仓库或旧证据清单。旧评分卡保留原判定，不因本地试验自动晋级。

## 5 分钟离线演示（不会调用模型）

最终交付选用 `AI_EvalOps_Public_Benchmark_Pilot_20260912_v2.zip`。无 `_v2` 后缀的首包保留为失败记录，不是合格交付：校验日志曾误放进严格报告目录，触发 `unexpected_report_files`。现已将日志移到证据根目录；报告器的完整性约束未放宽。最终解压复核结果记录在 ZIP 旁的 `DELIVERY_RECEIPT.json`。

解压交付 ZIP 到**新目录**。在解压根目录恢复证据布局：

```powershell
New-Item -ItemType Directory -Path './source/artifacts/public-benchmark-20260912'
Get-ChildItem -LiteralPath './evidence' -Force | Copy-Item -Destination './source/artifacts/public-benchmark-20260912' -Recurse
Set-Location -LiteralPath './source'
```

先准备项目锁定的 Python 3.12 依赖（`uv sync --frozen`）；以下命令使用已经准备好的环境，验证本身不需要 Ollama、API key 或网络：

```powershell
.venv/Scripts/python.exe -m scripts.run_local_public_benchmarks verify --run-dir artifacts/public-benchmark-20260912/bfcl-local-run
.venv/Scripts/python.exe -m scripts.run_local_public_benchmarks verify --run-dir artifacts/public-benchmark-20260912/ragbench-local-run
.venv/Scripts/python.exe -m scripts.report_local_public_benchmarks verify --run-dir artifacts/public-benchmark-20260912/bfcl-local-run --report-dir artifacts/public-benchmark-20260912/bfcl-report-final --bfcl-source-dir artifacts/public-benchmark-20260912/bfcl/upstream
.venv/Scripts/python.exe -m scripts.report_local_public_benchmarks verify --run-dir artifacts/public-benchmark-20260912/ragbench-local-run --report-dir artifacts/public-benchmark-20260912/ragbench-report-final
```

看报告：两个 `*-report-final/report.json` 是聚合，`per-case.json` 是逐题评分。查看一题的 request ID，再到 `*-local-run/attempts/` 查 intent/result，可以追到输入、参考、原始模型回答及判分。离线重算会验证计划/结果一致性和官方 checker 源字节，不会重新生成模型答案。

每个 `*-report-final/` 目录严格只包含 `report.json`、`per-case.json` 和 `manifest.json`。若把终端输出重定向为日志，请存放在该目录之外，否则校验会按设计拒绝额外文件。

旧 `bfcl-report/` 是审查前的格式指标口径，特意保留历史；**最终比较只引用 `bfcl-report-final/`**。详见执行记录中的纠正原因。

## 如需另开一轮真实实验

本轮已经结束。下面是可运行入口，不代表已额外执行；必须使用新的输出目录，且本机已有同名模型。新一轮结果必须单独报告，不能覆盖或择优替换本轮结果：

```powershell
.venv/Scripts/python.exe -m scripts.run_local_public_benchmarks plan --benchmark bfcl --source-dir artifacts/public-benchmark-20260912/bfcl --output-dir artifacts/my-new-bfcl-plan
.venv/Scripts/python.exe -m scripts.run_local_public_benchmarks run --plan artifacts/my-new-bfcl-plan/plan.json --output-dir artifacts/my-new-bfcl-run --max-new-calls 3
.venv/Scripts/python.exe -m scripts.report_local_public_benchmarks report --run-dir artifacts/my-new-bfcl-run --output-dir artifacts/my-new-bfcl-report --bfcl-source-dir artifacts/public-benchmark-20260912/bfcl/upstream
```

第三步即使只执行 3 次，也会保留尚未执行请求的分母。恢复第二步不会重发已有 intent；状态不明的请求需保留为未知，而不是自动重试。

## 范围与来源

本轮入口没有贯穿 PostgreSQL/Redis/MinIO 的 durable worker，也没有进行实际工具执行、原生 Ollama tools 协议或完整多轮 Agent 环境验收。单元/CLI 模拟 transport 测试与 474 次本地真实模型推理是两类证据，不能混计。跨机器推理的再现性、真人标注、服务端来源认证与生产延迟均未验收。

本轮全仓库非集成回归 **1473 passed / 3 skipped / 40 deselected**；3项跳过是Windows符号链接权限，40项是未执行的integration标记测试。最终Ruff格式711文件、Ruff规则、mypy247源码通过；两份最终报告离线重算通过。详见证据包 `validation-summary.json` 与原始日志，不累加重叠子集测试数量。

本机 RTX 5060 为 8GB 显存，后台并不独占。Qwen3:8b 在 32k 上下文中观察到 CPU/GPU 混合运行；记录的耗时只是该次观测，不能作为受控硬件速度排名。

来源与许可证保留：[BFCL 官方](https://gorilla.cs.berkeley.edu/leaderboard.html) / [Gorilla 源码](https://github.com/ShishirPatil/gorilla)（Apache-2.0）；[RAGBench 数据卡](https://huggingface.co/datasets/galileo-ai/ragbench)（数据卡 CC-BY-4.0，原语料权利以其声明为准）。公开原题保留原作者归属，不重新宣称拥有其内容。
