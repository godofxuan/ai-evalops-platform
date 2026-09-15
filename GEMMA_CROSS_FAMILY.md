# Gemma 跨家族续测：结论与验收入口

执行日期：2026-09-12；暂停后收口：2026-09-13。分支：`codex/public-benchmark-validation-v1`。

## 结论

**现有 Qwen3.5:4b 仍值得保留，没有证据支持用新下载的 Gemma 全面替换它。** Gemma 的价值是增加不同家族对照，暴露了格式遵循和领域判分的弱项，而不是让项目分数自动提高。

| 模型 | BFCL固定100题 | RAG有预测覆盖 | RAG平衡准确率（58题） | 负例误放行 | 正例误拒绝 |
| --- | ---: | ---: | ---: | ---: | ---: |
| qwen2.5:3b | 88/100 | 58/60 | 52.49% | 8/9 | 3/49 |
| qwen3.5:4b | 82/100 | 58/60 | 76.64% | 2/9 | 12/49 |
| qwen3:8b | 90/100 | 58/60 | 59.07% | 7/9 | 2/49 |
| gemma4:e2b-it-qat | 69/100 | 58/60 | 58.50% | 6/9 | 8/49 |

这是固定公开小样本、相同低随机配置下的观测。BFCL测的是输出函数调用表达式的官方AST有效性，不是实际工具副作用或完整Agent成功率；RAG测的是judge与公开自动标注的一致性，不是新生成RAG答案准确率或真人认可。

本地RAG计划60题为51正9负，永远预测“有支撑”就有85%总准确率。Gemma与Qwen3.5总计划都为44/60=73.33%，但错误类型不同；不得因为总分一样就认为两种judge可以互换。

## 真实执行和规模

- 原三模型实测没有重跑：480计划、474真实基准调用、6项上下文阻塞。
- 新增Gemma：160计划、158真实基准调用、2项同样的超长TechQA阻塞。100个BFCL响应、58个RAG响应全部保留，无失败重试或挑最好成绩。
- 两轮合计：**4款模型、2个模型家族、160个不同计划题目、640个题目×模型计划项、632次真实基准调用、8项上下文阻塞**。另有2次合成兼容性预检调用，不计入632。
- 300个RAGBench问题的已有GPT/RAGAS/TruLens预测列离线复评，仍是历史公开数据复评，不是本轮新调用这些服务。
- 没有付费API，没有新增人工标注；不把本地模型耗电/硬件成本说成零。

Gemma下载成功耗时128.20秒，包4336358185 bytes，完整digest：

`07ea59a474013479c8b6b802bef095c40e964a1d776ba02f264c0e30e1aede0c`。

参数量显示4.6B，量化Q4_0。“E2B”不是全部权重只有2B的承诺。Ollama0.34.0实际文本与JSON预检成功；思考模式显式关闭。权重保留，本任务暂停时已从显存卸载；本次恢复只做离线工作，不重载模型。

## 错误分析与不确定性

Gemma各BFCL类别（每类25）：simple23、multiple21、parallel9、irrelevance16。并行题中14项无法被固定官方协议解析：例如它输出多行独立单元素列表，而不是一个包含多个调用的列表。保留原输出和官方判分，不在看到结果后增加修复适配器来重写这一轮成绩。

Gemma的30个parse_failed中，16个属于官方接受的irrelevance不调用回答，不应当扣除；真正需调用类别的解析失败为14/75。因此“parse_failed=30”不是“30个任务错误”的同义词。

同题、类别分层、固定seed20260912、2000次配对bootstrap，Gemma减去三款Qwen的BFCL差值分别为-19pp[-28,-10]、-13pp[-22,-4]、-21pp[-29,-13]。RAG总计划一致率差值为-5pp[-15,3.33]、0pp[-13.33,13.33]、-8.33pp[-18.33,0]。RAG差值区间均包含零；比较未作多重校正，只能称探索性结果。

Gemma在HotpotQA的20题判分全部与自动标签一致，但该子集仅1个负例；TechQA只9/20（18实际预测），负例误放行6/8。不应只摘录100%的单域分数做简历宣传。

Gemma观测BFCL wall p50/p95约373/823ms，RAG约1158/2625ms。两轮非同时执行、硬件非独占；Ollama曾显示Gemma在32k上下文100%GPU，但这不是隔离硬件测量或权重总显存计量，不能算出公平速度提升倍数。

官方建议Gemma使用不同采样参数。本轮沿用上一轮已冻结的temperature=0/top_k=1等共同配置，因此结论限定在共同配置，不宣称Gemma最优能力或官方榜单排名。[模型与参数来源](https://ollama.com/library/gemma4:e2b-it-qat)

## 工程改进：为什么做、遇到什么、达成什么

1. **精确标签接入**：只增加批准的Gemma本地标签，默认模型仍是原三款，避免用户旧命令突然增加调用量。文本/JSON两项合成探针真实通过；28项runner/CLI回归通过。云端路由和未知模型仍禁止。
2. **跨轮比较**：旧三模型和Gemma各有独立计划/intent，不伪造合并计划。新增compare/verify CLI先重算原报告，检查源码仓库/数据revision/源case哈希、模型身份唯一、完整case集合及参考答案一致，再核对messages/options/format/类别/长度预算。显式非思考，只有不支持thinking的qwen2.5可省略参数。
3. **暂停点补齐**：恢复后发现“同ID换参考答案也可比较”以及“重复evidence-dir只取末项”，先运行现有用例得到2 failed / 5 passed，再分别最小修复；没有把未完代码当作已验收。
4. **新的负例**：不同提示词/seed/格式/thinking会被拒绝；导出比较不能覆盖旧目录；即使篡改分数后重算摘要，也会被原始账本重算拦截。
5. **交付可靠性**：新包能包含两个显式证据目录并给出恢复映射。打包前拒绝报告目录中的额外verify.log，复现并修复Windows祖先junction绕过；拒绝artifacts整根、重复/重叠输入、私有.env和活动.run.lock，避免首轮“ZIP校验通过但实际演示失败”再次发生。
6. **范围冻结**：没有改prompt、gold、阈值或模型结果，没有新框架、数据库、前端或付费服务。TDD红绿XML和全部原响应都保留。测试替身只用于工程控制流回归，真实推理数量单独统计。

详细脚本：`scripts/compare_local_public_benchmarks.py`、`scripts/package_public_pilot.py`。源码测试、模型输出、CLI离线结果是不同证据，不能相加成“模型正确率”。

## 新交付包的离线演示

使用 **AI_EvalOps_Cross_Family_20260913.zip**，解压到新目录。本包包含两个证据根，布局与首轮单目录包不同。先按manifest映射恢复：

```powershell
$deliveryManifest = Get-Content -LiteralPath './DELIVERY_MANIFEST.json' -Raw | ConvertFrom-Json
foreach ($evidenceRoot in $deliveryManifest.evidence_roots) {
    New-Item -ItemType Directory -Path $evidenceRoot.restore_to
    Get-ChildItem -LiteralPath $evidenceRoot.archive_prefix -Force | Copy-Item -Destination $evidenceRoot.restore_to -Recurse
}
Set-Location -LiteralPath './source'
```

只对新解压目录操作；不要把包覆盖进已有仓库。依赖预先按Python3.12和uv.lock准备（`uv sync --frozen`）。然后在已安装依赖的环境执行下面两条，**不需要Ollama、GPU、Git或网络**：

```powershell
python -m scripts.compare_local_public_benchmarks verify --run-dir artifacts/public-benchmark-20260912/bfcl-local-run --report-dir artifacts/public-benchmark-20260912/bfcl-report-final --run-dir artifacts/gemma-cross-family-20260912/bfcl-run --report-dir artifacts/gemma-cross-family-20260912/bfcl-report-final --output-dir artifacts/gemma-cross-family-20260912/bfcl-cross-comparison --bfcl-source-dir artifacts/public-benchmark-20260912/bfcl/upstream
python -m scripts.compare_local_public_benchmarks verify --run-dir artifacts/public-benchmark-20260912/ragbench-local-run --report-dir artifacts/public-benchmark-20260912/ragbench-report-final --run-dir artifacts/gemma-cross-family-20260912/ragbench-run --report-dir artifacts/gemma-cross-family-20260912/ragbench-report-final --output-dir artifacts/gemma-cross-family-20260912/ragbench-cross-comparison
```

期望为COMPARISON_RECOMPUTED，分别每模型100/60题。每条都会重算两份来源报告，来源报告再校验原始账本；这不是只检查一串摘要。比较输出目录严格只含comparison.json/manifest.json，日志写在目录外。

基准运行计划SHA：BFCL `a3b5fbc087b2a78d5cbf917575e440f07a24f7cfd0ffb39b896350d4b0955d87`；RAG `1eea984ec4334620fc5169ff45d8e08486dcb8025af93a71f57a27ca83f811ef`。执行实现身份仍为原基线`89777062654773c737bb47c32d27a3340bbcfc1a`加计划目录implementation源码快照；后续交付提交不能倒写成当时推理的代码身份。

## GitHub、CI与未完成范围

2026-09-13本地全量回归：**1495 passed / 3 skipped / 40 deselected**；3项是既有Windows符号链接权限限制，40项为本地未执行的集成测试。新增公开基准相关用例共93项，包含在1495内，不额外累加。Ruff格式715文件、Ruff规则与mypy248源码检查均通过。原始日志位于Gemma证据根。

源码和文档在专用分支同步，不推main、不自动合并。准确交付提交、实际CI状态、ZIP摘要和解压验证日志位于包旁的`CROSS_FAMILY_DELIVERY_RECEIPT.json`及随包验证记录；不能用旧提交的CI覆盖新代码。首轮v2包及其收据仍保留为历史快照。

本轮本地全量检查不包含真实数据库/Redis/MinIO集成；GitHub已有流水线若执行它们，按具体job日志另记。无论CI是否绿灯，都不把它等同于本轮公开基准贯穿durable worker：新入口仍是本地文件账本。正式业务A/B、真人标注、完整多轮Agent、生产可用性均未验收。哈希完整性与离线重算也不是服务端签名真实性证明。

## 可用的简历增量

> 接入BFCL与RAGBench固定版本公开基准，对Qwen/Gemma两个家族4款本地模型完成632次真实基准推理；保留8项上下文阻塞和逐题原始证据，建立严格同题同配置的跨轮配对比较及离线重算，使用平衡准确率和误放行/误拒绝识别判分器偏置与输出格式问题。

不写“632道独立题”“平台准确率提升”“Gemma全面领先”“真实人评通过”或“生产级”。此轮增加的是可验证的跨家族实验与可靠性约束，并非已证明模型或平台质量全面提升。
