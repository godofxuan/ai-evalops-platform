# 评测使用闭环：实施与验收计划（2026-09-12）

## 基线与边界

从已交付 DOC `6be5f971cc6b6d53d02bd026cf27473bc77785cc` 的独立工作树继续，分支为 `codex/evaluation-workflow-v1`。完整保留此前 reliability-panels 的 12 个未提交文件；主工作区、历史证据文件、RAG、main 均不修改。不新增模型、数据库、Agent 框架或前端服务，不执行付费调用，不自动推送或合并。

用户要求实际实现上一轮建议，同时检查操作和逻辑问题。本轮不是把五个开源平台全部安装或重写，而是实现它们最值得借鉴的三个可验证流程。

## 顺序与验收

1. **复用已有声明式执行器，提供统一入口。** 一个命令运行现有 DEMO 并生成可解释结果；真实目标沿用 HTTP 安全配置与固定输入。输出路径先检查，不能调用完目标才发现证据无法保存。默认公开输出不含题目、答案或工具载荷；私有分析显式选择。
2. **诊断评分与校准。** 版本化 code-registered grader，返回分数、理由、适用范围；精确答案与 JSON 结构答案分开。生成盲化的人工标注模板，对缺失、UNSURE、重复、过期及合成标签明确处理，报告误放行/误拒绝与覆盖率。不改变原 gold、旧 evaluator 合同或正式门槛，不生成假人评。
3. **轨迹—问题—回归。** 接受受限 OTLP JSON / OpenInference 结构投影，与具体 observation.trace_id 关联。只保留白名单结构信息，未知与缺失不当成功。失败题导出为新回归数据集，原题及原参考答案不改；保留来源哈希、选择原因和样本选择偏差。不能用选出的失败子集证明总体质量提升。
4. **证据与验证。** 新工作流支持离线重建诊断，私有 durable 来源必须通过现有原始题集重算。公开输出只能验证投影。新增路径的真实服务集成尽可能复用现有环境，缺环境明确未运行；SDK 序列化兼容测试不冒充 Phoenix/Langfuse 服务端联调。
5. **审查与交付。** 独立审查、针对回归、全量非集成、静态检查、历史证据复验；执行记录包含初始失败和修复原因。提供源码差异、日志、可运行命令与教程，不把本地修改引用为已推送的新 CODE SHA。

## 参考与独立实现

- Promptfoo 配置与断言工作流：https://www.promptfoo.dev/docs/configuration/expected-outputs/
- DeepEval 指标及解释接口：https://deepeval.com/docs/metrics-introduction
- Langfuse 线上样本到离线实验：https://langfuse.com/docs/evaluation/overview
- OTLP JSON 编码：https://opentelemetry.io/docs/specs/otlp/
- OpenInference 语义约定：https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md

学习公开接口和设计，不复制外部项目代码；兼容范围由实际测试决定。新增评分、来源哈希和报表不是来源认证、统计独立性证明或 production-ready。

## 停止条件

完成上述本地功能和可运行验证后冻结本轮范围。真实人工标注、付费模型实验、外部服务联调及专用分支远端 CI 属于单独核验事项；没有对应证据时明确 PENDING / NOT_RUN，不反复挑选成绩或默认扩展功能。
