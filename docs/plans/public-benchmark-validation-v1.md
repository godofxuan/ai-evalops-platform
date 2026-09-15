# 公开基准与本地模型实测计划（2026-09-12）

## 目标、基线与范围

用户要求多测不同方案、得到真正能说明效果且适合简历的指标，并明确优先使用自己已有的 Ollama。代码基线为 `89777062654773c737bb47c32d27a3340bbcfc1a`；专用分支 `codex/public-benchmark-validation-v1`。保留原工作区和历史证据，不修改 main、RAG、旧 gold 或质量门槛，不合并、部署、force push。不新增模型或依赖，不使用付费 API；下载新模型只有得到用户进一步指示后才做。

本轮用 zoom-out 梳理了已有模块：`product_experiments.runner` 执行原 QA/Agent 合同；`learning_grading` 提供精确/JSON 诊断；`learning_workflow`、bundle 与 recovery 负责诊断及离线重算。公开 BFCL 需要原官方评分规则，RAGBench 需要参考标注和独立 judge，不能塞成旧 fixture 或冒充原正式门禁。本轮新增明确隔离的本地基准入口，保持生产 HTTP provider 的公网安全约束不变。

## 预先确定的实验矩阵

1. **BFCL Python 单轮 AST 子集。** 固定官方 source SHA、许可证、官方 checker 源字节。simple_python、multiple、parallel、irrelevance 各按固定 hash 选 25 题，共 100。保留原题和全部答案；按官方输出协议生成函数调用表达式，只解析和判分，不执行模型生成代码或真实业务工具。不是完整官方榜单、任务执行成功率或安全认证。
2. **RAGBench 公开预测离线复评。** 固定数据 revision；hotpotqa、finqa、techqa 各固定 hash 选最多 100 个 test 样本。保留官方已有预测列及缺失覆盖率。参考 `adherence_score` 含自动标注，不称真人 gold，已有预测不称本轮新推理。
3. **RAGBench 本地 judge。** 在上述每域固定 hash 前 20 个样本上，对同一公开 question/documents/response 判定 supported，3 个域合计 60 题。目标是验证评分器，而不是让模型生成 RAG 答案。禁止给模型参考标签、来源解释或官方预测分数。
4. **本地同题三模型。** 使用现有 `qwen2.5:3b`、`qwen3.5:4b`、`qwen3:8b`，固定完整 digest、请求模板和执行配置。三者都是 Qwen 家族，不能外推到所有模型。30B 已安装但超出 8GB 显存，不优先用于批量实验；bge-m3 是 embedding，不参加生成任务。新 Gemma/Qwen9B 是可选建议，尚未下载。

## 执行及公平性

- 初始目标 100×3 BFCL 和 60×3 judge，即 480 个预注册样本请求；端到端请求一次，不失败重跑或取最好值。上下文预算最终在查看样本长度、但尚未查看模型结果前锁定，并写入机器可读 plan。
- 单并发、分模型执行以避免频繁换入换出；报告顺序、Ollama版本、加载耗时和真实 wall time。显存、缓存及后台任务可能影响时间，不声称标准硬件吞吐榜单。
- 每次调用前保存 intent；崩溃后不自动重发状态不明的请求。原始响应、错误、开始结束时间和 token/耗时元数据逐条保存，最终统计不删除失败或缺失。
- 不无声裁剪上下文、题目或答案。预检超限保留 BLOCKED 行；输出到达生成上限、结构无效或模型身份不符单列，不能算成功。
- BFCL 主指标是固定样本 AST 正确数/全部计划题；judge 报告有效覆盖、与自动标签一致率、balanced accuracy、误放行/误拒绝，不把缺失当一致。
- 配对比较保留相同 case ID，用固定种子的 case 级 bootstrap 描述 95% 区间；非完整基准且样本小，不作普遍优越或因果结论。区间跨零必须说明不确定；不同模型分数差不是平台代码提升。
- 本机 API 无新增按次服务费；电费、硬件折旧未测量，成本不能写成完全免费。没有真实人评，不伪造人评通过。

## 其他基准和停止条件

τ-bench 与 AgentDojo 包含完整交互/攻击环境，当前先记录适配成本和边界，不安装整套框架后草率跑少数例子就称验收。本轮首先完成上述两种公开基准的可复核链路。

验收：本地真实模型调用日志、公开来源固定身份、逐题结果和离线重算；覆盖执行前/后失败与结果篡改的回归；新增路径和既有非集成检查；写出完整结果说明和允许/禁止的简历表述。未运行范围保持 NOT_RUN。结果不支持提升时报告负面结果，不继续改数据或 prompt 直到刷出好分。完成后冻结本轮范围，不自动继续下载、付费或扩大实验。

## 官方资料

- BFCL：https://gorilla.cs.berkeley.edu/leaderboard.html
- RAGBench：https://huggingface.co/datasets/galileo-ai/ragbench
- Ollama chat：https://docs.ollama.com/api/chat
- Ollama structured outputs：https://docs.ollama.com/capabilities/structured-outputs
